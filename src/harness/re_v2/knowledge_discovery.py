"""Passive admission of discovery proposals against screened snapshot evidence.

Records from this boundary are staged inputs, not certifications or active plans.
Only the existing controller may account for dispatch, resolve expansion requests,
commit revisions and accept independently reviewed knowledge.
"""

from __future__ import annotations

from functools import wraps
import json

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_evidence import (
    EvidenceSelectorV1, KnowledgeEvidenceError, SafeEvidenceBoundary,
    screen_provider_output, security_policy_id,
    validate_provider_output,
)
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError
from harness.re_v2.protocol_22.partition import WorkspacePartitionCatalogV1
from harness.re_v2.protocol_22.schema import digest_value, safe_id
from harness.re_v2.protocol_28.policies import (
    DOMAIN_CATEGORIES,
    SOURCE_CATEGORIES,
    Protocol28PolicyError,
    categories_for_depth as _protocol_28_categories_for_depth,
    category_depth_applicability,
)
from harness.re_v2.snapshot import CapturedSnapshot


_AUTHORIAL_BYTE_LIMIT = 262_144

# Only admission failures caused by screened authorial bytes may be reflected
# back to a producer. Storage, binding and replay failures remain terminal and
# never become model-visible diagnostics.
DISCOVERY_REPAIRABLE_REASONS = frozenset({
    "discovery-context-bound",
    "discovery-normalized-bound",
    "discovery-receipt-bound",
    "discovery-row-bound",
    "discovery-source-mismatch",
    "duplicate-discovery-domain",
    "duplicate-discovery-field",
    "duplicate-discovery-obligation",
    "duplicate-evidence-request",
    "empty-evidence-request-batch",
    "incomplete-discovery-inventory",
    "incomplete-discovery-obligations",
    "invalid-discovery-disposition",
    "invalid-discovery-evidence",
    "invalid-discovery-fields",
    "invalid-discovery-input",
    "invalid-discovery-obligation",
    "invalid-discovery-obligation-membership",
    "invalid-discovery-obligation-subject",
    "invalid-discovery-ownership",
    "invalid-discovery-question",
    "invalid-discovery-response",
    "invalid-discovery-domain-target-closure",
    "invalid-discovery-domain-target-evidence",
    "invalid-discovery-target-ownership",
    "invalid-discovery-subject",
    "invalid-discovery-subject-category",
    "invalid-discovery-text",
    "invalid-evidence-request-authority",
    "invalid-outside-depth-obligation",
    "nonfinite-discovery-value",
    "subjectless-discovery-domain",
    "unattempted-discovery-obligation",
    "unsupported-discovery-obligation",
    "unsupported-discovery-inventory-ownership",
    "unsupported-not-applicable-obligation",
})


def categories_for_depth(depth: str, target_kind: str) -> frozenset[str]:
    """Canonical protocol-2.8 depth/category applicability for discovery.

    Task 3 activation consumes this same policy rather than deriving a second
    interpretation from model-authored dispositions.
    """
    try:
        return _protocol_28_categories_for_depth(depth, target_kind)
    except Protocol28PolicyError:
        raise DiscoveryError("invalid-discovery-depth-category") from None


class DiscoveryError(ValueError):
    """Closed diagnostic code; never include model or source values."""


class DiscoveryStorageError(DiscoveryError):
    """Local authority could not be read/persisted; not a model rejection."""


class DiscoveryAdmissionError(DiscoveryError):
    """A screened response violates the authorial contract."""


def _closed_errors(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except DiscoveryError:
            raise
        except (OSError, ReV2LedgerError):
            raise DiscoveryStorageError("discovery-storage-unavailable") from None
        except (ValueError, TypeError, KeyError, RecursionError):
            raise DiscoveryError("invalid-discovery-input") from None
    return call


def _admission_errors(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (DiscoveryStorageError, OSError, ReV2LedgerError):
            raise DiscoveryStorageError("discovery-storage-unavailable") from None
        except DiscoveryError as exc:
            raise DiscoveryAdmissionError(str(exc)) from None
        except (ValueError, TypeError, KeyError, RecursionError):
            raise DiscoveryAdmissionError("invalid-discovery-input") from None
    return call


def _obj(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise DiscoveryError("invalid-discovery-fields")
    return value


def _rows(value, limit=4096):
    if not isinstance(value, list) or len(value) > limit:
        raise DiscoveryError("discovery-row-bound")
    return value


def _text(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 4096
            or any(ord(c) < 32 and c not in "\n\t" for c in value)):
        raise DiscoveryError("invalid-discovery-text")
    return value


def _load(payload):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise DiscoveryError("duplicate-discovery-field")
            result[key] = value
        return result

    def reject_constant(_):
        raise DiscoveryError("nonfinite-discovery-value")

    if not isinstance(payload, bytes) or len(payload) > 262_144:
        raise DiscoveryError("discovery-context-bound")
    return json.loads(payload, object_pairs_hook=pairs, parse_constant=reject_constant)


def _selector(value):
    return EvidenceSelectorV1(**_obj(value, ("source_id", "path", "byte_start", "byte_end")))


def _validate_replay_bytes(payload):
    try:
        return validate_provider_output(payload)
    except KnowledgeEvidenceError as exc:
        raise DiscoveryError(str(exc)) from None


class DiscoveryBoundary:
    """Build safe input and validate one result; owns no execution loop or budget."""

    @_closed_errors
    def __init__(
        self, snapshot: CapturedSnapshot, partition: WorkspacePartitionCatalogV1,
        source_id: str, depth: str, origin_obligation_id: str,
        objects: ObjectStore, quarantine: ObjectStore,
        selected_domain_keys: tuple[str, ...] | None = None,
    ) -> None:
        safe_id(source_id, "source")
        digest_value(origin_obligation_id, "origin")
        if depth not in {"quick", "standard", "deep"}:
            raise DiscoveryError("invalid-discovery-depth")
        ordinary_root, quarantine_root = objects.root.resolve(), quarantine.root.resolve()
        if (ordinary_root == quarantine_root or ordinary_root in quarantine_root.parents
                or quarantine_root in ordinary_root.parents):
            raise DiscoveryError("discovery-quarantine-not-separate")
        self._evidence = SafeEvidenceBoundary(snapshot, partition, (source_id,), objects)
        self._snapshot_id, self._partition_id = snapshot.snapshot_id, partition.identity
        self._source_id, self._depth, self._origin = source_id, depth, origin_obligation_id
        self._objects, self._quarantine = objects, quarantine
        self._files = next(source.files for source in partition.sources if source.source_id == source_id)
        self._source_ids = tuple(source.source_id for source in partition.sources)
        self._partition = partition
        self._selected_domain_keys = selected_domain_keys

    def run_authority(self):
        """Frozen snapshot/partition and declared sources; account may select a subset."""
        return {"snapshot_id": self._snapshot_id, "partition_id": self._partition_id,
                "security_policy_id": security_policy_id(), "source_ids": list(self._source_ids)}

    def _analysis_domain_contract(self):
        source = next(
            source for source in self._partition.sources
            if source.source_id == self._source_id
        )
        selected = (
            set(self._selected_domain_keys)
            if self._selected_domain_keys is not None else None
        )
        return {
            domain.domain_key: domain
            for domain in source.domains
            if selected is None or domain.domain_key in selected
        }

    @classmethod
    def from_catalog(cls, catalog, partition, selection, source_id, depth, origin, objects):
        """Reconstruct the public admission boundary for read-only L4 replay."""
        safe_id(source_id, "source")
        digest_value(origin, "origin")
        if depth not in {"quick", "standard", "deep"}:
            raise DiscoveryError("invalid-discovery-depth")
        result = cls.__new__(cls)
        result._evidence = SafeEvidenceBoundary.from_catalog(
            catalog, partition, selection, (source_id,), objects)
        result._snapshot_id, result._partition_id = catalog.source_snapshot_id, partition.identity
        result._source_id, result._depth, result._origin = source_id, depth, origin
        result._objects, result._quarantine = objects, None
        result._files = next(source.files for source in partition.sources if source.source_id == source_id)
        result._source_ids = tuple(source.source_id for source in partition.sources)
        result._partition = partition
        result._selected_domain_keys = selection.domain_keys or None
        return result

    @property
    def partition_authority(self):
        """Frozen local inventory authority; never serialize into provider input."""
        return self._partition

    def _context(self, selectors, *, persist=True, schema_version=2):
        if type(schema_version) is not int or schema_version not in {1, 2, 3}:
            raise DiscoveryError("invalid-discovery-context-version")
        if not isinstance(selectors, tuple) or len(selectors) > 64:
            raise DiscoveryError("discovery-evidence-bound")
        normalized = []
        for selector in selectors:
            if not isinstance(selector, EvidenceSelectorV1) or selector.source_id != self._source_id:
                raise DiscoveryError("discovery-source-mismatch")
            normalized.append(selector.to_json_dict())
        normalized.sort(key=canonical_json_bytes)
        if len({canonical_json_bytes(row) for row in normalized}) != len(normalized):
            raise DiscoveryError("duplicate-discovery-selector")
        inventory = []
        for record in self._files:
            # Validate metadata too: a source-controlled filename is not trusted.
            EvidenceSelectorV1(self._source_id, record.source_relative_path, 0, 0)
            inventory.append({"path": record.source_relative_path, "byte_count": record.byte_count,
                              "object_kind": record.object_kind, "text_status": record.text_status})
        evidence, mappings = [], []
        for row in normalized:
            project = self._evidence.project if persist else self._evidence.read_projection
            projection = project(_selector(row))
            evidence.append({"projection_id": projection.projection_id,
                             "projection": _load(projection.provider_bytes())})
            mappings.append(projection.mapping_receipt_id)
        context_value = {
            "schema_version": schema_version, "kind": "untrusted_discovery_context", "source_id": self._source_id,
            "depth": self._depth, "origin_obligation_id": self._origin,
            "security_policy_id": security_policy_id(),
            "inventory": sorted(inventory, key=lambda r: r["path"]), "evidence": evidence,
            "required_categories": {"source": list(SOURCE_CATEGORIES), "domain": list(DOMAIN_CATEGORIES)},
        }
        if schema_version in {2, 3}:
            context_value["category_depth_applicability"] = category_depth_applicability()
        if schema_version == 3:
            context_value["analysis_domain_targets"] = [
                {
                    "key": domain.domain_key,
                    "source_relative_root": domain.source_relative_root,
                }
                for domain in self._analysis_domain_contract().values()
            ]
        context = canonical_json_bytes(context_value)
        if len(context) > 262_144:
            raise DiscoveryError("discovery-context-bound")
        binding = canonical_json_bytes({
            "schema_version": schema_version, "kind": "private_discovery_binding", "context_id": content_digest(context),
            "snapshot_id": self._snapshot_id, "partition_id": self._partition_id,
            "source_id": self._source_id, "depth": self._depth, "origin_obligation_id": self._origin,
            "security_policy_id": security_policy_id(), "selectors": normalized, "mapping_ids": mappings,
        })
        return context, binding

    @_closed_errors
    def prepare(
        self, selectors: tuple[EvidenceSelectorV1, ...], *, schema_version: int = 2
    ) -> str:
        context, binding = self._context(selectors, schema_version=schema_version)
        self._objects.put_blob(context)
        return self._objects.put_blob(binding)

    @_closed_errors
    def verify_selection(
        self, selectors: tuple[EvidenceSelectorV1, ...], *, schema_version: int = 2
    ) -> str:
        context, binding = self._context(
            selectors, persist=False, schema_version=schema_version
        )
        if (self._objects.read_blob(content_digest(context)) != context
                or self._objects.read_blob(content_digest(binding)) != binding):
            raise DiscoveryError("discovery-context-mismatch")
        return content_digest(binding)

    @_closed_errors
    def provider_bytes(self, binding_id: str) -> bytes:
        binding_bytes = self._objects.read_blob(binding_id)
        binding = _load(binding_bytes)
        # Replay from the real pinned reader, not caller-constructed projection
        # handles or a content-addressed but unauthenticated replacement context.
        expected_context, expected_binding = self._context(
            tuple(_selector(row) for row in _rows(binding["selectors"], 64)),
            persist=False,
            schema_version=binding.get("schema_version"),
        )
        if expected_binding != binding_bytes:
            raise DiscoveryError("discovery-binding-mismatch")
        context = self._objects.read_blob(binding["context_id"])
        if context != expected_context:
            raise DiscoveryError("discovery-context-mismatch")
        return context

    @property
    def object_store(self) -> ObjectStore:
        """Private controller storage; never include its location in model input."""
        return self._objects

    def screen_output(self, payload: bytes) -> bytes:
        """Screen before the controller retains even a failed provider capture."""
        return screen_provider_output(payload, self._quarantine)

    @_closed_errors
    def binding_details(self, binding_id: str) -> dict:
        """Authenticate before exposing private scope metadata to the controller."""
        self.provider_bytes(binding_id)
        return _load(self._objects.read_blob(binding_id))

    @_closed_errors
    def read_requests(self, binding_id: str, batch_id: str) -> list[dict]:
        """Reconstruct admission: a content address alone is not request authority."""
        context = _load(self.provider_bytes(binding_id))
        receipt = _load(self._objects.read_blob(batch_id))
        response_id = None
        if receipt.get("schema_version") == 1:
            _obj(receipt, ("schema_version", "state", "binding_id", "requests"))
            rows = _rows(receipt["requests"], 16)
            response = {"schema_version": 1, "kind": "evidence_requests", "source_id": self._source_id,
                        "requests": [{key: row[key] for key in ("obligation_id", "reason_class", "selector")} for row in rows]}
        elif receipt.get("schema_version") == 2:
            _obj(receipt, ("schema_version", "state", "binding_id", "requests", "authorial_response_id"))
            rows = _rows(receipt["requests"], 16)
            response_id = receipt["authorial_response_id"]
            response = _load(self._objects.read_blob(response_id))
        else:
            raise DiscoveryError("invalid-discovery-receipt-version")
        expected_id = content_digest(self._request_receipt(binding_id, response, context, response_id))
        if expected_id != batch_id:
            raise DiscoveryError("request-receipt-mismatch")
        return rows

    @_closed_errors
    def read_proposal(self, binding_id: str, receipt_id: str) -> dict:
        """Authenticate and reconstruct a staged proposal without repairing it."""
        context = _load(self.provider_bytes(binding_id))
        receipt_bytes = self._objects.read_blob(receipt_id)
        receipt = _load(receipt_bytes)
        response_id = None
        if receipt.get("schema_version") == 1:
            _obj(receipt, (
                "schema_version", "state", "binding_id", "proposal_id",
                "review_required", "unassigned_paths", "subject_ids",
            ))
            proposal_source = self._objects.read_blob(receipt["proposal_id"])
        elif receipt.get("schema_version") == 2:
            _obj(receipt, (
                "schema_version", "state", "binding_id", "authorial_response_id",
                "proposal_id", "review_required", "unassigned_paths", "subject_ids",
            ))
            response_id = receipt["authorial_response_id"]
            proposal_source = self._objects.read_blob(response_id)
        else:
            raise DiscoveryError("invalid-discovery-receipt-version")
        _validate_replay_bytes(proposal_source)
        proposal = _load(proposal_source)
        if receipt["binding_id"] != binding_id:
            raise DiscoveryError("proposal-receipt-mismatch")
        proposal_for_normalization = proposal
        if (receipt.get("schema_version") == 1
                and proposal.get("schema_version") == 2):
            proposal_for_normalization = {
                **proposal,
                "obligations": [
                    {key: value for key, value in row.items() if key != "obligation_id"}
                    for row in _rows(proposal["obligations"])
                ],
            }
        normalized = self._normalize_proposal(proposal_for_normalization, context)
        proposal_bytes = canonical_json_bytes(normalized)
        stored_proposal = self._objects.read_blob(receipt["proposal_id"])
        _validate_replay_bytes(stored_proposal)
        if (content_digest(proposal_bytes) != receipt["proposal_id"]
                or stored_proposal != proposal_bytes):
            raise DiscoveryError("proposal-object-mismatch")
        expected = self._proposal_receipt(binding_id, normalized, response_id)
        if content_digest(expected) != receipt_id or expected != receipt_bytes:
            raise DiscoveryError("proposal-receipt-mismatch")
        return normalized

    def _request_outcome(self, binding_id, batch_id, request, *, persist=True):
        projection = None
        reason = request["reason_code"]
        if request["state"] == "pending":
            project = self._evidence.project if persist else self._evidence.read_projection
            projection = project(_selector(request["selector"]))
            reason = _load(projection.provider_bytes())["reason_code"]
        return {
            "schema_version": 1, "kind": "discovery_evidence_outcome",
            "binding_id": binding_id, "batch_id": batch_id, "request_id": request["request_id"],
            "selector": request["selector"], "reason_class": request["reason_class"],
            "obligation_id": request["obligation_id"],
            "disposition": "unknown" if reason else "resolved", "reason_code": reason,
            "projection_id": projection.projection_id if projection else None,
            "mapping_id": projection.mapping_receipt_id if projection else None,
        }

    @_closed_errors
    def resolve_request(self, binding_id: str, batch_id: str, request_id: str) -> str:
        requests = self.read_requests(binding_id, batch_id)
        request = next((row for row in requests if row["request_id"] == request_id), None)
        if request is None:
            raise DiscoveryError("unknown-evidence-request")
        return self._objects.put_blob(canonical_json_bytes(self._request_outcome(binding_id, batch_id, request)))

    @_closed_errors
    def validate_outcome(self, outcome_id: str) -> dict:
        """Authenticate stored evidence against the pinned reader before dispatch.

        This is verification, not a new acquisition attempt or a new reservation.
        No model work runs here and the controller's request receipt is unchanged.
        """
        outcome = _load(self._objects.read_blob(outcome_id))
        requests = self.read_requests(outcome["binding_id"], outcome["batch_id"])
        request = next((row for row in requests if row["request_id"] == outcome["request_id"]), None)
        return self._validate_admitted_outcome(outcome_id, outcome["binding_id"], outcome["batch_id"], request)

    def _validate_admitted_outcome(self, outcome_id, binding_id, batch_id, request):
        """Internal replay fast path: request already authenticated in this replay.

        Only the admission boundary and acquisition replay call this helper. The
        selected evidence is still authenticated afresh; we do not re-screen the
        entire old context for each individual request in the same batch.
        """
        outcome = _load(self._objects.read_blob(outcome_id))
        if request is None or self._request_outcome(binding_id, batch_id, request, persist=False) != outcome:
            raise DiscoveryError("evidence-outcome-mismatch")
        return outcome

    @_closed_errors
    def admit(self, binding_id: str, output: bytes, *, capture_bound: bool = False) -> str:
        # This gate must precede any ordinary response retention or diagnostics.
        safe_output = screen_provider_output(output, self._quarantine)
        context = _load(self.provider_bytes(binding_id))
        if type(capture_bound) is not bool:
            raise DiscoveryError("invalid-discovery-admission-mode")
        return self._admit_payload(binding_id, safe_output, context, capture_bound)

    @_admission_errors
    def _admit_payload(self, binding_id, safe_output, context, capture_bound):
        proposal = _load(safe_output)
        # Passive normalized identity stays stable under row/key reordering.
        # Execution capture receipts additionally bind the exact response bytes.
        response_id = content_digest(safe_output) if capture_bound else None
        if isinstance(proposal, dict) and proposal.get("kind") == "evidence_requests":
            receipt = self._request_receipt(binding_id, proposal, context, response_id)
            if capture_bound:
                self._objects.put_blob(safe_output)
            return self._objects.put_blob(receipt)
        normalized = self._normalize_proposal(proposal, context)
        proposal_bytes = canonical_json_bytes(normalized)
        result = self._proposal_receipt(binding_id, normalized, response_id)
        if len(proposal_bytes) > _AUTHORIAL_BYTE_LIMIT:
            raise DiscoveryError("discovery-normalized-bound")
        if len(result) > _AUTHORIAL_BYTE_LIMIT:
            raise DiscoveryError("discovery-receipt-bound")
        if capture_bound:
            self._objects.put_blob(safe_output)
        self._objects.put_blob(proposal_bytes)
        return self._objects.put_blob(result)

    def _normalize_proposal(self, proposal, context):
        if not isinstance(proposal, dict) or type(proposal.get("schema_version")) is not int:
            raise DiscoveryError("invalid-discovery-response")
        if proposal["schema_version"] == 1:
            return self._normalize_proposal_v1(proposal, context)
        if proposal["schema_version"] == 2:
            return self._normalize_proposal_v2(proposal, context)
        raise DiscoveryError("invalid-discovery-response")

    def _normalize_proposal_v1(self, proposal, context):
        _obj(proposal, ("schema_version", "kind", "source_id", "domains", "subjects", "inventory", "obligations", "questions"))
        if (type(proposal["schema_version"]) is not int or proposal["schema_version"] != 1
                or proposal["kind"] != "discovery_proposal" or proposal["source_id"] != self._source_id):
            raise DiscoveryError("invalid-discovery-response")
        usable = {row["projection_id"] for row in context["evidence"]
                  if row["projection"]["disposition"] != "withheld" and row["projection"]["text"].strip("*\n\r\t ")}
        supplied = {row["projection_id"] for row in context["evidence"]}

        def refs(value, required=True):
            rows = _rows(value, 64)
            # Questions may cite a withheld projection to explain an unknown;
            # proposed domains/subjects need actual visible evidence instead.
            allowed = usable if required else supplied
            if ((required and not rows) or any(not isinstance(x, str) or x not in allowed for x in rows)
                    or len(set(rows)) != len(rows)):
                raise DiscoveryError("invalid-discovery-evidence")
            return sorted(rows)

        domains, subjects = {}, {}
        for row in _rows(proposal["domains"], 256):
            _obj(row, ("key", "description", "evidence_ids"))
            key = safe_id(row["key"], "key")
            if key == "source" or key in domains:
                raise DiscoveryError("duplicate-discovery-domain")
            domains[key] = {**row, "description": _text(row["description"]), "evidence_ids": refs(row["evidence_ids"])}
        targets = {"source", *domains}
        for row in _rows(proposal["subjects"], 1024):
            _obj(row, ("key", "target", "description", "evidence_ids"))
            key = safe_id(row["key"], "key")
            if key in subjects or row["target"] not in targets:
                raise DiscoveryError("invalid-discovery-subject")
            subjects[key] = {**row, "description": _text(row["description"]), "evidence_ids": refs(row["evidence_ids"])}
        if any(not any(s["target"] == key for s in subjects.values()) for key in domains):
            raise DiscoveryError("subjectless-discovery-domain")
        inventory = {}
        expected_paths = {row["path"] for row in context["inventory"]}
        for row in _rows(proposal["inventory"]):
            _obj(row, ("path", "owner", "reason"))
            path = row["path"]
            if (path not in expected_paths or path in inventory
                    or (row["owner"] is not None and row["owner"] not in subjects)):
                raise DiscoveryError("invalid-discovery-ownership")
            inventory[path] = {**row, "reason": _text(row["reason"])}
        if set(inventory) != expected_paths:
            raise DiscoveryError("incomplete-discovery-inventory")
        obligations = set()
        for row in _rows(proposal["obligations"]):
            _obj(row, ("target", "category"))
            pair = (row["target"], row["category"])
            if pair in obligations:
                raise DiscoveryError("duplicate-discovery-obligation")
            obligations.add(pair)
        expected = {("source", category) for category in SOURCE_CATEGORIES}
        expected.update((key, category) for key in domains for category in DOMAIN_CATEGORIES)
        if obligations != expected:
            raise DiscoveryError("incomplete-discovery-obligations")
        questions = []
        for row in _rows(proposal["questions"], 256):
            _obj(row, ("target", "question", "evidence_ids"))
            if row["target"] not in targets:
                raise DiscoveryError("invalid-discovery-question")
            questions.append({**row, "question": _text(row["question"]), "evidence_ids": refs(row["evidence_ids"], False)})
        normalized = {**proposal, "domains": [domains[key] for key in sorted(domains)],
                      "subjects": [subjects[key] for key in sorted(subjects)],
                      "inventory": [inventory[key] for key in sorted(inventory)],
                      "obligations": [{"target": target, "category": category} for target, category in sorted(obligations)],
                      "questions": sorted(questions, key=canonical_json_bytes)}
        return normalized

    def _normalize_proposal_v2(self, proposal, context):
        _obj(proposal, (
            "schema_version", "kind", "source_id", "domains", "subjects",
            "inventory", "obligations", "questions",
        ))
        if (proposal["schema_version"] != 2
                or proposal["kind"] != "discovery_proposal"
                or proposal["source_id"] != self._source_id):
            raise DiscoveryError("invalid-discovery-response")

        projections = {
            row["projection_id"]: row["projection"] for row in context["evidence"]
        }
        supplied = set(projections)
        visible = {
            projection_id for projection_id, projection in projections.items()
            if projection["disposition"] != "withheld"
            and projection["text"].strip("*\n\r\t ")
        }

        def refs(value, *, visible_only=False, required=False):
            rows = _rows(value, 64)
            allowed = visible if visible_only else supplied
            if ((required and not rows)
                    or any(not isinstance(item, str) or item not in allowed for item in rows)
                    or len(set(rows)) != len(rows)):
                raise DiscoveryError("invalid-discovery-evidence")
            return sorted(rows)

        domains = {}
        for raw in _rows(proposal["domains"], 256):
            row = _obj(raw, ("key", "description", "evidence_ids"))
            key = safe_id(row["key"], "key")
            if key == "source" or key in domains:
                raise DiscoveryError("duplicate-discovery-domain")
            domains[key] = {
                "key": key,
                "description": _text(row["description"]),
                "evidence_ids": refs(row["evidence_ids"], visible_only=True, required=True),
            }

        if context.get("schema_version") == 3:
            expected_domain_keys = {
                row["key"] for row in context["analysis_domain_targets"]
            }
            if set(domains) != expected_domain_keys:
                raise DiscoveryError("invalid-discovery-domain-target-closure")
            contract = self._analysis_domain_contract()
            for key, row in domains.items():
                domain = contract[key]
                root = domain.source_relative_root
                primary_paths = {
                    relative if root == "." else f"{root}/{relative}"
                    for relative in domain.owned_domain_relative_paths
                }
                member_paths = primary_paths | set(
                    domain.supporting_source_relative_paths
                )
                evidence_paths = {
                    projections[item]["path"] for item in row["evidence_ids"]
                }
                if (not evidence_paths.issubset(member_paths)
                        or not evidence_paths.intersection(primary_paths)):
                    raise DiscoveryError("invalid-discovery-domain-target-evidence")

        targets = {"source", *domains}
        subjects = {}
        for raw in _rows(proposal["subjects"], 1024):
            row = _obj(raw, (
                "key", "target", "description", "category_ids", "evidence_ids",
            ))
            key = safe_id(row["key"], "key")
            target = row["target"]
            if key in subjects or target not in targets:
                raise DiscoveryError("invalid-discovery-subject")
            target_kind = "source" if target == "source" else "domain"
            allowed_categories = (
                frozenset(SOURCE_CATEGORIES)
                if target_kind == "source" else frozenset(DOMAIN_CATEGORIES)
            )
            category_ids = _rows(row["category_ids"], 16)
            if (not category_ids
                    or any(not isinstance(category, str) or category not in allowed_categories
                           for category in category_ids)
                    or len(set(category_ids)) != len(category_ids)
                    or not set(category_ids).issubset(
                        categories_for_depth(self._depth, target_kind)
                    )):
                raise DiscoveryError("invalid-discovery-subject-category")
            subjects[key] = {
                "key": key,
                "target": target,
                "description": _text(row["description"]),
                "category_ids": sorted(category_ids),
                "evidence_ids": refs(row["evidence_ids"], visible_only=True, required=True),
            }
        if any(not any(subject["target"] == key for subject in subjects.values())
               for key in domains):
            raise DiscoveryError("subjectless-discovery-domain")

        if context.get("schema_version") == 3:
            contract = self._analysis_domain_contract()
            for subject in subjects.values():
                if subject["target"] == "source":
                    continue
                domain = contract[subject["target"]]
                root = domain.source_relative_root
                member_paths = {
                    relative if root == "." else f"{root}/{relative}"
                    for relative in domain.owned_domain_relative_paths
                } | set(domain.supporting_source_relative_paths)
                if any(
                    projections[item]["path"] not in member_paths
                    for item in subject["evidence_ids"]
                ):
                    raise DiscoveryError("invalid-discovery-domain-target-evidence")

        inventory = {}
        inventory_context = {row["path"]: row for row in context["inventory"]}
        for raw in _rows(proposal["inventory"]):
            row = _obj(raw, ("path", "owner", "reason"))
            path = row["path"]
            if (path not in inventory_context or path in inventory
                    or (row["owner"] is not None and row["owner"] not in subjects)):
                raise DiscoveryError("invalid-discovery-ownership")
            inventory[path] = {
                "path": path,
                "owner": row["owner"],
                "reason": _text(row["reason"]),
            }
        if set(inventory) != set(inventory_context):
            raise DiscoveryError("incomplete-discovery-inventory")

        if context.get("schema_version") == 3:
            primary_target_by_path = {}
            for key, domain in self._analysis_domain_contract().items():
                root = domain.source_relative_root
                for relative in domain.owned_domain_relative_paths:
                    path = relative if root == "." else f"{root}/{relative}"
                    primary_target_by_path[path] = key
            for path, row in inventory.items():
                if row["owner"] is None:
                    continue
                expected_target = primary_target_by_path.get(path, "source")
                if subjects[row["owner"]]["target"] != expected_target:
                    raise DiscoveryError("invalid-discovery-target-ownership")
                if not any(
                    projections[item]["path"] == path
                    for item in subjects[row["owner"]]["evidence_ids"]
                ):
                    raise DiscoveryError(
                        "unsupported-discovery-inventory-ownership"
                    )

        subject_membership = {}
        for target in targets:
            categories = SOURCE_CATEGORIES if target == "source" else DOMAIN_CATEGORIES
            for category in categories:
                subject_membership[(target, category)] = sorted(
                    key for key, subject in subjects.items()
                    if subject["target"] == target
                    and category in subject["category_ids"]
                )

        obligations = {}
        dispositions = {
            "analyze", "not-applicable", "unknown", "outside-requested-depth",
        }
        empty_source = bool(inventory_context) and all(
            record["byte_count"] == 0 for record in inventory_context.values()
        )
        empty_source = empty_source or not inventory_context

        def scoped_evidence(target, *, visible_only=False):
            if target == "source":
                return set(visible if visible_only else supplied)
            target_paths = {
                projections[item]["path"]
                for item in (
                    set(domains[target]["evidence_ids"])
                    | set().union(*(
                        set(subject["evidence_ids"])
                        for subject in subjects.values() if subject["target"] == target
                    ))
                )
            }
            allowed = visible if visible_only else supplied
            return {
                item for item in allowed if projections[item]["path"] in target_paths
            }

        for raw in _rows(proposal["obligations"]):
            row = _obj(raw, (
                "target", "category", "disposition", "subject_keys",
                "rationale", "evidence_ids",
            ))
            target, category = row["target"], row["category"]
            pair = (target, category)
            categories = (
                SOURCE_CATEGORIES if target == "source"
                else DOMAIN_CATEGORIES if target in domains else ()
            )
            if category not in categories or pair in obligations:
                raise DiscoveryError("invalid-discovery-obligation")
            disposition = row["disposition"]
            if disposition not in dispositions:
                raise DiscoveryError("invalid-discovery-disposition")
            target_kind = "source" if target == "source" else "domain"
            applicable = category in categories_for_depth(self._depth, target_kind)
            if (disposition == "outside-requested-depth") == applicable:
                raise DiscoveryError("invalid-outside-depth-obligation")
            subject_keys = _rows(row["subject_keys"], 1024)
            if (any(not isinstance(key, str) or key not in subjects for key in subject_keys)
                    or len(set(subject_keys)) != len(subject_keys)):
                raise DiscoveryError("invalid-discovery-obligation-subject")
            subject_keys = sorted(subject_keys)
            if subject_keys != subject_membership[pair]:
                raise DiscoveryError("invalid-discovery-obligation-membership")
            evidence_ids = refs(row["evidence_ids"])
            if disposition == "analyze":
                subject_evidence = set().union(*(
                    set(subjects[key]["evidence_ids"]) for key in subject_keys
                ))
                if (not subject_keys or not evidence_ids
                        or any(item not in visible for item in evidence_ids)
                        or not set(evidence_ids).issubset(subject_evidence)
                        or any(not set(evidence_ids).intersection(subjects[key]["evidence_ids"])
                               for key in subject_keys)):
                    raise DiscoveryError("unsupported-discovery-obligation")
            elif subject_keys:
                raise DiscoveryError("invalid-discovery-obligation-membership")
            elif disposition == "not-applicable":
                target_evidence = scoped_evidence(target, visible_only=True)
                supported = (
                    set(evidence_ids).issubset(target_evidence)
                    and bool(set(evidence_ids).intersection(target_evidence).intersection(visible))
                )
                if not supported and not (target == "source" and empty_source):
                    raise DiscoveryError("unsupported-not-applicable-obligation")
            elif disposition == "unknown":
                target_evidence = scoped_evidence(target)
                supported = (
                    bool(evidence_ids)
                    and set(evidence_ids).issubset(target_evidence)
                ) or (
                    target == "source" and empty_source and not evidence_ids
                )
                if not supported:
                    raise DiscoveryError("unattempted-discovery-obligation")
            else:
                target_evidence = scoped_evidence(target, visible_only=True)
                if (target == "source" and empty_source and not evidence_ids):
                    pass
                elif (not evidence_ids
                        or not set(evidence_ids).issubset(target_evidence)
                        or any(item not in visible for item in evidence_ids)):
                    raise DiscoveryError("invalid-discovery-evidence")

            base = {
                "target": target,
                "category": category,
                "disposition": disposition,
                "subject_keys": subject_keys,
                "rationale": _text(row["rationale"]),
                "evidence_ids": sorted(evidence_ids),
            }
            obligations[pair] = {
                **base,
                "obligation_id": content_digest({
                    "schema_version": 2,
                    "kind": "discovery_category_obligation",
                    "source_id": self._source_id,
                    **base,
                }),
            }

        expected = {("source", category) for category in SOURCE_CATEGORIES}
        expected.update((key, category) for key in domains for category in DOMAIN_CATEGORIES)
        if set(obligations) != expected:
            raise DiscoveryError("incomplete-discovery-obligations")

        questions = []
        for raw in _rows(proposal["questions"], 256):
            row = _obj(raw, ("target", "question", "evidence_ids"))
            if row["target"] not in targets:
                raise DiscoveryError("invalid-discovery-question")
            questions.append({
                "target": row["target"],
                "question": _text(row["question"]),
                "evidence_ids": refs(row["evidence_ids"]),
            })

        return {
            "schema_version": 2,
            "kind": "discovery_proposal",
            "source_id": self._source_id,
            "domains": [domains[key] for key in sorted(domains)],
            "subjects": [subjects[key] for key in sorted(subjects)],
            "inventory": [inventory[key] for key in sorted(inventory)],
            "obligations": [obligations[key] for key in sorted(obligations)],
            "questions": sorted(questions, key=canonical_json_bytes),
        }

    def _proposal_receipt(self, binding_id, normalized, response_id):
        proposal_bytes = canonical_json_bytes(normalized)
        proposal_id = content_digest(proposal_bytes)
        inventory = {row["path"]: row for row in normalized["inventory"]}
        subjects = {row["key"]: row for row in normalized["subjects"]}
        return canonical_json_bytes({
            "schema_version": 2 if response_id is not None else 1,
            "state": "proposal_validated", "binding_id": binding_id,
            **({"authorial_response_id": response_id} if response_id is not None else {}),
            "proposal_id": proposal_id, "review_required": True,
            "unassigned_paths": sorted(path for path, row in inventory.items() if row["owner"] is None),
            "subject_ids": {key: content_digest({"binding_id": binding_id, "proposal_id": proposal_id,
                                                  "subject_key": key}) for key in sorted(subjects)},
        })

    def _request_receipt(self, binding_id, response, context, response_id):
        _obj(response, ("schema_version", "kind", "source_id", "requests"))
        if (type(response["schema_version"]) is not int or response["schema_version"] != 1
                or response["source_id"] != self._source_id):
            raise DiscoveryError("invalid-discovery-response")
        requests = _rows(response["requests"], 16)
        if not requests:
            raise DiscoveryError("empty-evidence-request-batch")
        inventory = {row["path"]: row for row in context["inventory"]}
        normalized, seen = [], set()
        for row in requests:
            _obj(row, ("obligation_id", "reason_class", "selector"))
            if (row["obligation_id"] != self._origin
                    or row["reason_class"] not in {"missing-behavior", "ownership", "relationship"}):
                raise DiscoveryError("invalid-evidence-request-authority")
            selector = _selector(row["selector"])
            if selector.source_id != self._source_id:
                raise DiscoveryError("discovery-source-mismatch")
            request = {"obligation_id": self._origin, "reason_class": row["reason_class"],
                       "selector": selector.to_json_dict()}
            request_bytes = canonical_json_bytes(request)
            if request_bytes in seen:
                raise DiscoveryError("duplicate-evidence-request")
            seen.add(request_bytes)
            record = inventory.get(selector.path)
            available = record is not None and record["object_kind"] == "regular" and selector.byte_end <= record["byte_count"]
            normalized.append({**request, "request_id": content_digest({"binding_id": binding_id, **request}),
                               "state": "pending" if available else "unavailable",
                               "reason_code": None if available else "unavailable-evidence"})
        return canonical_json_bytes({
            "schema_version": 1 if response_id is None else 2, "state": "evidence_requested", "binding_id": binding_id,
            **({"authorial_response_id": response_id} if response_id is not None else {}),
            "requests": sorted(normalized, key=lambda row: row["request_id"]),
        })
