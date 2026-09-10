"""Run-wide execution receipts for the new knowledge controller (not a scheduler).

Legacy runs cannot acquire this account alongside their existing budget. Every
knowledge phase must use this same account; source/context changes never allocate
resources. Mutations are private controller operations under the RE ownership lock.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_discovery import DiscoveryError, _closed_errors, _load, _obj
from harness.re_v2.knowledge_discovery_review import _overlap_pairs
from harness.re_v2.ledger import DurableLedger, ObjectStore
from harness.re_v2.protocol_22.budget import conservative_charge
from harness.re_v2.protocol_22.provider import DispatchReservationV1, decode_normalized_usage_bytes
from harness.re_v2.protocol_22.recovery import protocol_22_run_lock
from harness.re_v2.protocol_22.schema import digest_value, safe_id
from harness.re_v2.run_store import ReV2Paths


def _positive(value):
    if type(value) is not int or not 0 < value < 2**63:
        raise DiscoveryError("invalid-discovery-resource-limit")
    return value


@dataclass(frozen=True, slots=True)
class KnowledgeDispatchPolicy:
    token_limit: int
    active_ms_limit: int
    max_source_turns: int

    def __post_init__(self):
        for value in asdict(self).values():
            _positive(value)


@dataclass(frozen=True, slots=True)
class KnowledgeProviderContract:
    """Stored adapter/accounting authority, not a native isolation claim."""
    provider_id: str
    model_id: str
    adapter_digest: str
    execution_mode: str = "offline-scripted"
    input_accounting: str = "utf8-byte-upper-bound"

    def __post_init__(self):
        safe_id(self.provider_id, "provider")
        safe_id(self.model_id, "model")
        digest_value(self.adapter_digest, "adapter")
        allowed = {
            "offline-scripted": "utf8-byte-upper-bound",
            "configured-provider-accounted": "rendered-prompt-utf8-bytes",
        }
        if self.execution_mode not in allowed:
            raise DiscoveryError("production-discovery-backend-not-enabled")
        if self.input_accounting != allowed[self.execution_mode]:
            raise DiscoveryError("unsupported-discovery-input-accounting")

    @property
    def identity(self):
        return content_digest(asdict(self))


def _run_authority(value):
    _obj(value, ("snapshot_id", "partition_id", "security_policy_id", "source_ids"))
    for key in ("snapshot_id", "partition_id", "security_policy_id"):
        digest_value(value[key], key)
    sources = value["source_ids"]
    if not isinstance(sources, list) or not sources or sources != sorted(set(sources)):
        raise DiscoveryError("invalid-knowledge-source-selection")
    for source in sources:
        safe_id(source, "source")
    return value


@dataclass(frozen=True, slots=True)
class KnowledgeUsage:
    charged_tokens: int
    charged_active_ms: int
    open_tokens: int
    open_active_ms: int
    reservation_breached: bool


class _DispatchProtocol:
    def __init__(self, opening):
        self.opening = opening

    def canonical_payload(self, kind, payload):
        if kind not in {"account_opened", "dispatch_reserved", "review_reserved",
                        "dispatch_captured", "discovery_applied", "review_applied", "account_transferred"}:
            raise DiscoveryError("invalid-knowledge-dispatch-event")
        _obj(payload, ("receipt_id",))
        digest_value(payload["receipt_id"], "receipt")
        return dict(payload)

    def new_state(self):
        return _DispatchState(self.opening)


class _DispatchState:
    def __init__(self, opening):
        self.opening, self.opened = opening, False
        self.dispatches, self.captures, self.applied, self.sources = {}, {}, {}, {}
        self.dispatch_kinds, self.discovery_sources, self.review_sources = {}, {}, {}
        self.transfer_id = None

    def view(self):
        return self

    def idempotent_record(self, history, kind, payload):
        return next((r for r in history if r.type == kind and r.payload == payload), None)

    def usage(self):
        tokens = active = open_tokens = open_active = 0
        breached = False
        for key, request in self.dispatches.items():
            reserve = request["reservation"]
            capture = self.captures.get(key)
            if capture is None:
                open_tokens += reserve["billable_tokens"]
                open_active += reserve["active_ms"]
            else:
                usage = decode_normalized_usage_bytes(canonical_json_bytes(capture["usage"]))
                charged = conservative_charge(usage.billable_tokens, usage.status, reserve["billable_tokens"])
                elapsed = conservative_charge(capture["active_ms"], capture["active_status"], reserve["active_ms"])
                tokens += charged
                active += elapsed
                breached |= charged > reserve["billable_tokens"] or elapsed > reserve["active_ms"]
        return KnowledgeUsage(tokens, active, open_tokens, open_active, breached)

    def dispatch_breached(self, dispatch_id):
        capture = self.captures[dispatch_id]
        reserve = self.dispatches[dispatch_id]["reservation"]
        usage = decode_normalized_usage_bytes(canonical_json_bytes(capture["usage"]))
        return (conservative_charge(usage.billable_tokens, usage.status, reserve["billable_tokens"]) > reserve["billable_tokens"]
                or conservative_charge(capture["active_ms"], capture["active_status"], reserve["active_ms"]) > reserve["active_ms"])

    def _resource_refusal(self, request):
        if self.transfer_id is not None:
            return 'knowledge-account-transferred'
        usage, policy = self.usage(), self.opening["policy"]
        if usage.reservation_breached:
            return "reservation-exceeded"
        reserved = request["reservation"]
        if (usage.charged_tokens + usage.open_tokens + reserved["billable_tokens"] > policy["token_limit"]
                or usage.charged_active_ms + usage.open_active_ms + reserved["active_ms"] > policy["active_ms_limit"]):
            return "budget-exhausted"
        previous = self.sources.get(request["source_id"], [])
        if len(previous) >= policy["max_source_turns"]:
            return "discovery-turn-limit"
        return None

    def refusal(self, request):
        refusal = self._resource_refusal(request)
        if refusal:
            return refusal
        previous = self.discovery_sources.get(request["source_id"], [])
        if previous:
            first, last = self.dispatches[previous[0]], self.applied.get(previous[-1])
            if any(request[key] != first[key] for key in ("scope_id", "agent_id", "reservation")):
                return "discovery-dispatch-authority-mismatch"
            if last is None or last["state"] != "evidence_ready":
                return "discovery-dispatch-not-ready"
            if request["revision_id"] != last["revision_id"]:
                return "stale-discovery-revision"
        return None

    def review_refusal(self, request):
        refusal = self._resource_refusal(request)
        if refusal:
            return refusal
        source = request["source_id"]
        producer_id = request["producer_dispatch_id"]
        producer_history = self.discovery_sources.get(source, [])
        if (not producer_history or producer_id != producer_history[-1]
                or self.sources.get(source, [])[-1] != producer_id):
            return "discovery-review-proposal-required"
        producer = self.dispatches[producer_id]
        application = self.applied.get(producer_id)
        if (application is None or application["state"] != "proposal_ready"
                or application["receipt_id"] != request["proposal_receipt_id"]):
            return "discovery-review-proposal-required"
        if any(request[key] != producer[key]
               for key in ("source_id", "scope_id", "binding_id", "revision_id")):
            return "discovery-review-authority-mismatch"
        if request["agent_id"] == producer["agent_id"]:
            return "discovery-review-agent-not-distinct"
        return None

    def consume(self, record, objects):
        row = _load(objects.read_blob(record.payload["receipt_id"]))
        if record.type == 'account_transferred':
            from harness.re_v2.protocol_28.model import KnowledgeAccountTransferV1
            transfer = KnowledgeAccountTransferV1.from_json_dict(row)
            usage = self.usage()
            if (not self.opened or self.transfer_id is not None
                    or transfer.account_id != content_digest(self.opening)
                    or transfer.logical_run_id != self.opening['logical_run_id']
                    or transfer.account_tail_id != record.previous_record_hash
                    or transfer.settled_dispatch_ids != tuple(sorted(self.dispatches))
                    or set(self.dispatches) != set(self.captures)
                    or usage.open_tokens or usage.open_active_ms or usage.reservation_breached
                    or (transfer.charged_tokens, transfer.charged_active_ms) != (usage.charged_tokens, usage.charged_active_ms)
                    or (transfer.token_limit, transfer.active_ms_limit) != (
                        self.opening['policy']['token_limit'], self.opening['policy']['active_ms_limit'])):
                raise DiscoveryError('invalid-knowledge-account-transfer')
            self.transfer_id = transfer.identity
            return
        if self.transfer_id is not None:
            raise DiscoveryError('knowledge-account-transferred')
        if record.type == "account_opened":
            if self.opened or row != self.opening:
                raise DiscoveryError("knowledge-account-mismatch")
            contract = KnowledgeProviderContract(**_load(objects.read_blob(row["provider_contract_id"])))
            if contract.identity != row["provider_contract_id"]:
                raise DiscoveryError("knowledge-provider-contract-mismatch")
            self.opened = True
            return
        if not self.opened:
            raise DiscoveryError("missing-knowledge-account")
        if record.type in {"dispatch_reserved", "review_reserved"}:
            fields = ("source_id", "scope_id", "agent_id", "binding_id", "revision_id", "context_id",
                      "reservation", "turn")
            if record.type == "review_reserved":
                fields += ("producer_dispatch_id", "proposal_receipt_id")
            _obj(row, fields)
            safe_id(row["source_id"], "source")
            for key in ("scope_id", "agent_id", "binding_id", "revision_id", "context_id"):
                digest_value(row[key], key)
                objects.read_blob(row[key])
            scope = _load(objects.read_blob(row["scope_id"]))
            run = self.opening["run_authority"]
            if (scope.get("logical_run_id") != self.opening["logical_run_id"]
                    or scope.get("budget_run_id") != self.opening["logical_run_id"]
                    or scope["evidence_scope"]["source_id"] != row["source_id"]
                    or row["source_id"] not in run["source_ids"]
                    or any(scope["evidence_scope"][key] != run[key]
                           for key in ("snapshot_id", "partition_id", "security_policy_id"))):
                raise DiscoveryError("knowledge-run-authority-mismatch")
            DispatchReservationV1(**_obj(row["reservation"], ("initial_input_tokens", "billable_tokens", "active_ms")))
            if (type(row["turn"]) is not int
                    or row["turn"] != len(self.sources.get(row["source_id"], [])) + 1):
                raise DiscoveryError("invalid-discovery-turn")
            refusal = self.review_refusal(row) if record.type == "review_reserved" else self.refusal(row)
            if refusal:
                raise DiscoveryError(refusal)
            if record.type == "review_reserved":
                self._validate_review_request(row, objects)
            key = record.payload["receipt_id"]
            self.dispatches[key] = row
            self.dispatch_kinds[key] = "review" if record.type == "review_reserved" else "discovery"
            self.sources.setdefault(row["source_id"], []).append(key)
            selected = self.review_sources if record.type == "review_reserved" else self.discovery_sources
            selected.setdefault(row["source_id"], []).append(key)
        elif record.type == "dispatch_captured":
            _obj(row, ("dispatch_id", "output_id", "reason_code", "usage", "active_ms", "active_status"))
            key = row["dispatch_id"]
            if key not in self.dispatches or key in self.captures:
                raise DiscoveryError("invalid-discovery-capture")
            if row["reason_code"] not in {None, "provider-failed", "unsafe-provider-output", "invalid-provider-result"}:
                raise DiscoveryError("invalid-discovery-capture")
            if (row["output_id"] is None) != (row["reason_code"] is not None):
                raise DiscoveryError("invalid-discovery-capture")
            if row["output_id"] is not None:
                digest_value(row["output_id"], "output")
                objects.read_blob(row["output_id"])
            decode_normalized_usage_bytes(canonical_json_bytes(row["usage"]))
            conservative_charge(row["active_ms"], row["active_status"], self.dispatches[key]["reservation"]["active_ms"])
            self.captures[key] = row
        else:
            _obj(row, ("dispatch_id", "state", "receipt_id", "reason_code", "revision_id"))
            key = row["dispatch_id"]
            if key not in self.captures or key in self.applied:
                raise DiscoveryError("invalid-discovery-application")
            expected_kind = "review" if record.type == "review_applied" else "discovery"
            if self.dispatch_kinds.get(key) != expected_kind:
                raise DiscoveryError("invalid-discovery-application")
            allowed = ({"review_ready", "revision_required", "blocked"}
                       if expected_kind == "review" else {"proposal_ready", "evidence_ready", "blocked"})
            if row["state"] not in allowed:
                raise DiscoveryError("invalid-discovery-application")
            if expected_kind == "review":
                self._validate_review_application(row, objects)
            else:
                self._validate_application(row, objects)
            if row["receipt_id"] is not None:
                objects.read_blob(row["receipt_id"])
            digest_value(row["revision_id"], "revision")
            objects.read_blob(row["revision_id"])
            self.applied[key] = row

    def _validate_review_request(self, row, objects):
        producer = self.dispatches[row["producer_dispatch_id"]]
        application = self.applied[row["producer_dispatch_id"]]
        proposal_receipt = _load(objects.read_blob(application["receipt_id"]))
        proposal = _load(objects.read_blob(proposal_receipt["proposal_id"]))
        context_bytes = objects.read_blob(row["context_id"])
        context = _load(context_bytes)
        _obj(context, ("schema_version", "kind", "candidate_id", "candidate",
                       "safe_discovery_context", "overlap_pairs", "review_obligations"))
        obligations = {
            "independence": "fresh-independent-execution-certification-required",
            "candidate_integrity": "review-without-editing-candidate-ownership",
            "domains": "cover-every-candidate-domain-key-exactly-once",
            "subjects": "cover-every-candidate-subject-key-exactly-once",
            "inventory": "reconcile-every-candidate-inventory-path-exactly-once",
            "overlaps": "reconcile-every-common-path-subject-pair-exactly-once",
            "questions": "preserve-all-candidate-questions",
            "categories": "preserve-all-candidate-category-obligations-without-completeness-claim",
            "execution": "passive-review-does-not-certify-execution-or-analysis",
        }
        binding = _load(objects.read_blob(producer["binding_id"]))
        safe_context = canonical_json_bytes(context["safe_discovery_context"])
        expected_pairs = [
            list(pair) for pair in _overlap_pairs(proposal, context["safe_discovery_context"])
        ]
        if (context_bytes != canonical_json_bytes(context)
                or context["schema_version"] != 1
                or context["kind"] != "untrusted_discovery_review_context"
                or context["candidate"] != proposal
                or context["candidate_id"] != content_digest(canonical_json_bytes(proposal))
                or context["review_obligations"] != obligations
                or context["overlap_pairs"] != expected_pairs
                or content_digest(safe_context) != binding.get("context_id")
                or objects.read_blob(binding["context_id"]) != safe_context):
            raise DiscoveryError("discovery-review-context-mismatch")

    def _validate_review_application(self, row, objects):
        key = row["dispatch_id"]
        request, capture = self.dispatches[key], self.captures[key]
        reasons = {"provider-failed", "unsafe-provider-output", "invalid-provider-result",
                   "reservation-exceeded", "review-result-invalid"}
        if ((row["state"] == "blocked" and row["reason_code"] not in reasons)
                or (row["state"] != "blocked" and row["reason_code"] is not None)
                or row["revision_id"] != request["revision_id"]):
            raise DiscoveryError("invalid-discovery-application")
        if self.dispatch_breached(key):
            if row["reason_code"] != "reservation-exceeded":
                raise DiscoveryError("invalid-discovery-application")
        elif row["reason_code"] == "reservation-exceeded":
            raise DiscoveryError("invalid-discovery-application")
        transport_reasons = {"provider-failed", "unsafe-provider-output", "invalid-provider-result"}
        if row["reason_code"] in transport_reasons and row["reason_code"] != capture["reason_code"]:
            raise DiscoveryError("invalid-discovery-application")
        if capture["reason_code"] is not None and row["reason_code"] not in {
                capture["reason_code"], "reservation-exceeded"}:
            raise DiscoveryError("invalid-discovery-application")
        receipt = _load(objects.read_blob(row["receipt_id"])) if row["receipt_id"] is not None else None
        if row["state"] == "blocked":
            if receipt is not None:
                raise DiscoveryError("invalid-discovery-application")
            return
        if receipt is None:
            raise DiscoveryError("invalid-discovery-application")
        _obj(receipt, ("schema_version", "state", "binding_id", "proposal_receipt_id",
                       "proposal_id", "review_id", "authorial_response_id", "reviewer_context_id",
                       "outcome", "execution_certification_required", "analysis_certified", "findings"))
        outcomes = {"ready_for_planning": "review_ready", "revision_required": "revision_required"}
        expected_state = outcomes.get(receipt["outcome"])
        if (receipt["schema_version"] != 1 or receipt["state"] != "review_validated"
                or expected_state is None or row["state"] != expected_state
                or receipt["binding_id"] != request["binding_id"]
                or receipt["proposal_receipt_id"] != request["proposal_receipt_id"]
                or receipt["authorial_response_id"] != capture["output_id"]
                or receipt["reviewer_context_id"] != request["context_id"]
                or receipt["execution_certification_required"] is not True
                or receipt["analysis_certified"] is not False):
            raise DiscoveryError("invalid-discovery-application")
        review = objects.read_blob(receipt["review_id"])
        if content_digest(review) != receipt["review_id"]:
            raise DiscoveryError("invalid-discovery-application")
        producer_receipt = _load(objects.read_blob(request["proposal_receipt_id"]))
        if receipt["proposal_id"] != producer_receipt.get("proposal_id"):
            raise DiscoveryError("invalid-discovery-application")

    def _validate_application(self, row, objects):
        key = row["dispatch_id"]
        request, capture = self.dispatches[key], self.captures[key]
        reasons = {"provider-failed", "unsafe-provider-output", "invalid-provider-result", "reservation-exceeded",
                   "discovery-result-invalid", "discovery-no-new-evidence", "evidence-expansion-limit", "discovery-context-bound"}
        if ((row["state"] == "blocked" and row["reason_code"] not in reasons)
                or (row["state"] != "blocked" and row["reason_code"] is not None)):
            raise DiscoveryError("invalid-discovery-application")
        if self.dispatch_breached(key):
            if row["reason_code"] != "reservation-exceeded":
                raise DiscoveryError("invalid-discovery-application")
        elif row["reason_code"] == "reservation-exceeded":
            raise DiscoveryError("invalid-discovery-application")
        if capture["reason_code"] is not None and row["reason_code"] not in {capture["reason_code"], "reservation-exceeded"}:
            raise DiscoveryError("invalid-discovery-application")
        if row["state"] != "evidence_ready" and row["revision_id"] != request["revision_id"]:
            raise DiscoveryError("invalid-discovery-application")
        receipt = _load(objects.read_blob(row["receipt_id"])) if row["receipt_id"] is not None else None
        if row["state"] == "blocked":
            reason = row["reason_code"]
            if reason == "reservation-exceeded" or capture["reason_code"] is not None:
                if receipt is not None:
                    raise DiscoveryError("invalid-discovery-application")
            elif reason == "discovery-result-invalid":
                if receipt is not None:
                    raise DiscoveryError("invalid-discovery-application")
            elif reason in {"discovery-no-new-evidence", "evidence-expansion-limit", "discovery-context-bound"}:
                if receipt is None or receipt.get("state") != "evidence_requested":
                    raise DiscoveryError("invalid-discovery-application")
            else:
                raise DiscoveryError("invalid-discovery-application")
        if row["state"] != "blocked" and receipt is None:
            raise DiscoveryError("invalid-discovery-application")
        if receipt is not None and receipt.get("binding_id") != request["binding_id"]:
            raise DiscoveryError("invalid-discovery-application")
        if receipt is not None and receipt.get("authorial_response_id") != capture["output_id"]:
            raise DiscoveryError("discovery-capture-admission-mismatch")
        if row["state"] == "proposal_ready":
            if receipt.get("state") != "proposal_validated" or receipt.get("review_required") is not True:
                raise DiscoveryError("invalid-discovery-application")
            proposal = _load(objects.read_blob(receipt["proposal_id"]))
            if proposal.get("kind") != "discovery_proposal":
                raise DiscoveryError("invalid-discovery-application")
        elif row["state"] == "evidence_ready":
            revision = _load(objects.read_blob(row["revision_id"]))
            if (receipt.get("state") != "evidence_requested"
                    or revision.get("kind") != "discovery_context_revision"
                    or revision.get("scope_id") != request["scope_id"]
                    or revision.get("previous_revision_id") != request["revision_id"]):
                raise DiscoveryError("invalid-discovery-application")
            intent = _load(objects.read_blob(revision["intent_id"]))
            if intent.get("batch_id") != row["receipt_id"]:
                raise DiscoveryError("invalid-discovery-application")


class KnowledgeDispatchAccount:
    @_closed_errors
    def __init__(self, paths: ReV2Paths, policy: KnowledgeDispatchPolicy,
                 provider_contract: KnowledgeProviderContract, run_authority: dict):
        if not isinstance(policy, KnowledgeDispatchPolicy):
            raise DiscoveryError("invalid-discovery-policy")
        if not isinstance(provider_contract, KnowledgeProviderContract):
            raise DiscoveryError("invalid-knowledge-provider-contract")
        if paths != ReV2Paths.for_run(paths.root.parent):
            raise DiscoveryError("noncanonical-knowledge-run-paths")
        self.contract = provider_contract
        self.paths = paths
        self.opening = {"schema_version": 1, "kind": "knowledge_execution_account",
                        "logical_run_id": paths.root.parent.name, "policy": asdict(policy),
                        "provider_contract_id": provider_contract.identity,
                        "run_authority": _run_authority(_load(canonical_json_bytes(run_authority)))}
        with protocol_22_run_lock(paths):
            self._require_new_knowledge_store()
            self.objects = ObjectStore(paths.objects)
            self.ledger = DurableLedger(paths.root / "knowledge-dispatch.jsonl", self.objects,
                                       _DispatchProtocol(self.opening))
            if self.ledger.path.exists() or self.ledger.lock_path.exists():
                self._state()
            else:
                self.objects.put_blob(canonical_json_bytes(asdict(provider_contract)))
            self._record("account_opened", self.opening)

    def _require_new_knowledge_store(self):
        # No fresh account may shadow a legacy manifest, event or artifact ledger.
        if any(path.exists() or path.is_symlink() for path in (
                self.paths.manifest, self.paths.events, self.paths.ledger, self.paths.root / "captures")):
            raise DiscoveryError("legacy-run-requires-accounting-migration")

    def _record(self, kind, receipt):
        receipt_id = self.objects.put_blob(canonical_json_bytes(receipt))
        self.ledger._append(kind, {"receipt_id": receipt_id})
        return receipt_id

    def _state(self):
        state = self.ledger.replay()
        if not state.opened:
            raise DiscoveryError("missing-knowledge-account")
        return state

    @_closed_errors
    def status(self):
        self._require_new_knowledge_store()
        return self._state().usage()
