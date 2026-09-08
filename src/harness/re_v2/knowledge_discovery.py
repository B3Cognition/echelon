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
    EvidenceSelectorV1, SafeEvidenceBoundary,
    screen_provider_output, security_policy_id,
)
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError
from harness.re_v2.protocol_22.partition import WorkspacePartitionCatalogV1
from harness.re_v2.protocol_22.schema import digest_value, safe_id
from harness.re_v2.protocol_28.policies import DOMAIN_CATEGORIES, SOURCE_CATEGORIES
from harness.re_v2.snapshot import CapturedSnapshot


class DiscoveryError(ValueError):
    """Closed diagnostic code; never include model or source values."""


def _closed_errors(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except DiscoveryError:
            raise
        except (ValueError, TypeError, KeyError, OSError, ReV2LedgerError, RecursionError):
            raise DiscoveryError("invalid-discovery-input") from None
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


class DiscoveryBoundary:
    """Build safe input and validate one result; owns no execution loop or budget."""

    @_closed_errors
    def __init__(
        self, snapshot: CapturedSnapshot, partition: WorkspacePartitionCatalogV1,
        source_id: str, depth: str, origin_obligation_id: str,
        objects: ObjectStore, quarantine: ObjectStore,
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

    def _context(self, selectors):
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
            projection = self._evidence.project(_selector(row))
            evidence.append({"projection_id": projection.projection_id,
                             "projection": _load(projection.provider_bytes())})
            mappings.append(projection.mapping_receipt_id)
        context = canonical_json_bytes({
            "schema_version": 1, "kind": "untrusted_discovery_context", "source_id": self._source_id,
            "depth": self._depth, "origin_obligation_id": self._origin,
            "security_policy_id": security_policy_id(),
            "inventory": sorted(inventory, key=lambda r: r["path"]), "evidence": evidence,
            "required_categories": {"source": list(SOURCE_CATEGORIES), "domain": list(DOMAIN_CATEGORIES)},
        })
        if len(context) > 262_144:
            raise DiscoveryError("discovery-context-bound")
        binding = canonical_json_bytes({
            "schema_version": 1, "kind": "private_discovery_binding", "context_id": content_digest(context),
            "snapshot_id": self._snapshot_id, "partition_id": self._partition_id,
            "source_id": self._source_id, "depth": self._depth, "origin_obligation_id": self._origin,
            "security_policy_id": security_policy_id(), "selectors": normalized, "mapping_ids": mappings,
        })
        return context, binding

    @_closed_errors
    def prepare(self, selectors: tuple[EvidenceSelectorV1, ...]) -> str:
        context, binding = self._context(selectors)
        self._objects.put_blob(context)
        return self._objects.put_blob(binding)

    @_closed_errors
    def provider_bytes(self, binding_id: str) -> bytes:
        binding_bytes = self._objects.read_blob(binding_id)
        binding = _load(binding_bytes)
        # Replay from the real pinned reader, not caller-constructed projection
        # handles or a content-addressed but unauthenticated replacement context.
        expected_context, expected_binding = self._context(tuple(_selector(row) for row in _rows(binding["selectors"], 64)))
        if expected_binding != binding_bytes:
            raise DiscoveryError("discovery-binding-mismatch")
        context = self._objects.read_blob(binding["context_id"])
        if context != expected_context:
            raise DiscoveryError("discovery-context-mismatch")
        return context

    @_closed_errors
    def admit(self, binding_id: str, output: bytes) -> str:
        # This gate must precede any ordinary response retention or diagnostics.
        safe_output = screen_provider_output(output, self._quarantine)
        context = _load(self.provider_bytes(binding_id))
        proposal = _load(safe_output)
        if isinstance(proposal, dict) and proposal.get("kind") == "evidence_requests":
            return self._admit_requests(binding_id, proposal, context)
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
        proposal_bytes = canonical_json_bytes(normalized)
        proposal_id = content_digest(proposal_bytes)
        result = canonical_json_bytes({
            "schema_version": 1, "state": "proposal_validated", "binding_id": binding_id,
            "proposal_id": proposal_id, "review_required": True,
            "unassigned_paths": sorted(path for path, row in inventory.items() if row["owner"] is None),
            "subject_ids": {key: content_digest({"binding_id": binding_id, "proposal_id": proposal_id,
                                                  "subject_key": key}) for key in sorted(subjects)},
        })
        self._objects.put_blob(proposal_bytes)
        return self._objects.put_blob(result)

    def _admit_requests(self, binding_id, response, context):
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
        return self._objects.put_blob(canonical_json_bytes({
            "schema_version": 1, "state": "evidence_requested", "binding_id": binding_id,
            "requests": sorted(normalized, key=lambda row: row["request_id"]),
        }))
