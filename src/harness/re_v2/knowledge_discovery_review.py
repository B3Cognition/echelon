"""Passive admission of independent discovery review feedback.

This boundary validates and retains screened feedback.  It does not invoke a
provider, certify that an independent invocation occurred, or activate a plan.
"""

from __future__ import annotations

from functools import wraps

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_discovery import (
    DiscoveryAdmissionError,
    DiscoveryBoundary,
    DiscoveryError,
    DiscoveryStorageError,
    category_depth_applicability,
    _load,
    _obj,
    _rows,
    _text,
)
from harness.re_v2.knowledge_evidence import (
    KnowledgeEvidenceError,
    validate_provider_output,
)
from harness.re_v2.ledger import ReV2LedgerError


_CONTEXT_BYTE_LIMIT = 262_144
_ROW_LIMIT = 4096
_OVERLAP_PAIR_LIMIT = 4096
_REVIEW_FIELDS = (
    "schema_version", "kind", "proposal_id", "verdict", "domains",
    "subjects", "inventory", "overlaps", "findings",
)
_REVIEW_V2_FIELDS = (*_REVIEW_FIELDS[:-1], "obligations", "findings")
_RECEIPT_FIELDS = (
    "schema_version", "state", "binding_id", "proposal_receipt_id",
    "proposal_id", "review_id", "authorial_response_id", "reviewer_context_id",
    "outcome", "execution_certification_required", "analysis_certified",
    "findings",
)
_FINDING_REASONS = frozenset({
    "missing-behavior", "unsupported-domain", "ownership", "overlap",
    "evidence-gap",
})

# Only closed failures derived from already-screened reviewer bytes may be sent
# back to the same reviewer. Authority, storage and transport failures are never
# model-visible and remain terminal.
DISCOVERY_REVIEW_REPAIRABLE_REASONS = frozenset({
    "altered-discovery-review-obligation",
    "discovery-review-finding-required",
    "discovery-review-normalized-bound",
    "discovery-review-receipt-bound",
    "discovery-review-row-bound",
    "discovery-review-schema-mismatch",
    "duplicate-discovery-field",
    "duplicate-discovery-review-finding",
    "false-ready-discovery-review",
    "incomplete-discovery-review-coverage",
    "incomplete-discovery-review-inventory",
    "incomplete-discovery-review-obligations",
    "incomplete-discovery-review-overlap",
    "invalid-discovery-fields",
    "invalid-discovery-input",
    "invalid-discovery-review-coverage",
    "invalid-discovery-review-depth-authority",
    "invalid-discovery-review-disposition",
    "invalid-discovery-review-evidence",
    "invalid-discovery-review-finding",
    "invalid-discovery-review-inventory",
    "invalid-discovery-review-obligation",
    "invalid-discovery-review-overlap",
    "invalid-discovery-review-overlap-context",
    "invalid-discovery-review-response",
    "invalid-discovery-review-verdict",
    "invalid-discovery-text",
    "unsupported-discovery-review-obligation",
    "unsupported-discovery-review-overlap",
    "unsupported-discovery-review-ownership",
    "unsupported-discovery-review-row",
    "unsupported-excluded-disposition",
    "unsupported-nonbehavioral-disposition",
})


def review_repair_requirement(reason_code: str) -> str:
    if reason_code == "invalid-discovery-review-evidence":
        return (
            "Every evidence_ids entry must be copied exactly from the supplied "
            "safe review context. Do not invent, reconstruct, shorten, or cite "
            "any other identifier. A supported row must cite applicable visible "
            "evidence under the review contract."
        )
    return (
        "Return one complete replacement review satisfying the exact review "
        "response contract and deterministic feedback. Do not return a patch, "
        "commentary, or a partial set of rows."
    )


def build_review_repair_context(
    safe_review_context: dict, previous_review_text: str, reason_code: str
) -> bytes:
    if reason_code not in DISCOVERY_REVIEW_REPAIRABLE_REASONS:
        raise DiscoveryReviewError("invalid-discovery-review-repair-feedback")
    if (
        not isinstance(previous_review_text, str)
        or not previous_review_text
        or not isinstance(safe_review_context, dict)
        or safe_review_context.get("kind") != "untrusted_discovery_review_context"
    ):
        raise DiscoveryReviewError("invalid-discovery-review-repair-feedback")
    return canonical_json_bytes({
        "schema_version": 1,
        "kind": "untrusted_discovery_review_repair_context",
        "safe_review_context": safe_review_context,
        "previous_review_text": previous_review_text,
        "deterministic_feedback": {
            "reason_code": reason_code,
            "requirement": review_repair_requirement(reason_code),
        },
    })


class DiscoveryReviewError(ValueError):
    """Closed diagnostic code; never includes provider or source values."""


class DiscoveryReviewStorageError(DiscoveryReviewError):
    """Local review authority is unavailable; this is not model rejection."""


class DiscoveryReviewAdmissionError(DiscoveryReviewError):
    """The complete screened reviewer response violates the review contract."""


def _closed_errors(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except DiscoveryReviewError:
            raise
        except (DiscoveryStorageError, OSError, ReV2LedgerError):
            raise DiscoveryReviewStorageError("discovery-review-storage-unavailable") from None
        except (DiscoveryError, DiscoveryAdmissionError):
            raise DiscoveryReviewError("invalid-discovery-review-authority") from None
        except (ValueError, TypeError, KeyError, RecursionError):
            raise DiscoveryReviewError("invalid-discovery-review-input") from None
    return call


def _admission_errors(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except DiscoveryReviewAdmissionError:
            raise
        except DiscoveryReviewStorageError:
            raise
        except (DiscoveryError, DiscoveryAdmissionError) as exc:
            raise DiscoveryReviewAdmissionError(str(exc)) from None
        except (ValueError, TypeError, KeyError, RecursionError):
            raise DiscoveryReviewAdmissionError("invalid-discovery-review-response") from None
    return call


def _review_obj(value, fields):
    try:
        return _obj(value, fields)
    except DiscoveryError as exc:
        raise DiscoveryReviewAdmissionError(str(exc)) from None


def _review_rows(value, limit=_ROW_LIMIT):
    try:
        return _rows(value, limit)
    except DiscoveryError as exc:
        raise DiscoveryReviewAdmissionError(str(exc)) from None


def _review_text(value):
    try:
        return _text(value)
    except DiscoveryError as exc:
        raise DiscoveryReviewAdmissionError(str(exc)) from None


def _row_identity(proposal_id: str, kind: str, row: dict) -> str:
    return content_digest({"proposal_id": proposal_id, "review_row_kind": kind, "row": row})


def _validate_replay_bytes(payload: bytes) -> bytes:
    try:
        return validate_provider_output(payload)
    except KnowledgeEvidenceError as exc:
        raise DiscoveryReviewError(str(exc)) from None


def _overlap_pairs(candidate: dict, safe_context: dict) -> tuple[tuple[str, str], ...]:
    """Enumerate common-path subject pairs once, stopping at the finite cap."""
    projections = {
        row["projection_id"]: row["projection"]
        for row in safe_context["evidence"]
    }
    subjects_by_path: dict[str, list[str]] = {}
    pairs: set[tuple[str, str]] = set()
    for subject in sorted(candidate["subjects"], key=lambda row: row["key"]):
        key = subject["key"]
        paths = sorted({projections[item]["path"] for item in subject["evidence_ids"]})
        for path in paths:
            prior = subjects_by_path.setdefault(path, [])
            for other in prior:
                pairs.add(tuple(sorted((other, key))))
                if len(pairs) > _OVERLAP_PAIR_LIMIT:
                    raise DiscoveryReviewError("discovery-review-overlap-bound")
            prior.append(key)
    return tuple(sorted(pairs))


class DiscoveryReviewBoundary:
    """Authenticate one proposal and passively admit one bounded review."""

    @_closed_errors
    def __init__(self, discovery: DiscoveryBoundary) -> None:
        if not isinstance(discovery, DiscoveryBoundary):
            raise DiscoveryReviewError("invalid-discovery-review-boundary")
        self._discovery = discovery
        self._objects = discovery.object_store

    @property
    def discovery(self) -> DiscoveryBoundary:
        return self._discovery

    def _context_value(self, binding_id: str, proposal_receipt_id: str) -> dict:
        candidate = self._discovery.read_proposal(binding_id, proposal_receipt_id)
        safe_context = _load(self._discovery.provider_bytes(binding_id))
        candidate_id = content_digest(canonical_json_bytes(candidate))
        overlap_pairs = _overlap_pairs(candidate, safe_context)
        return {
            "schema_version": 1,
            "kind": "untrusted_discovery_review_context",
            "candidate_id": candidate_id,
            "candidate": candidate,
            "safe_discovery_context": safe_context,
            "overlap_pairs": [list(pair) for pair in overlap_pairs],
            "review_obligations": {
                "independence": "fresh-independent-execution-certification-required",
                "candidate_integrity": "review-without-editing-candidate-ownership",
                "domains": "cover-every-candidate-domain-key-exactly-once",
                "subjects": "cover-every-candidate-subject-key-exactly-once",
                "inventory": "reconcile-every-candidate-inventory-path-exactly-once",
                "overlaps": "reconcile-every-common-path-subject-pair-exactly-once",
                "questions": "preserve-all-candidate-questions",
                "categories": "preserve-all-candidate-category-obligations-without-completeness-claim",
                "execution": "passive-review-does-not-certify-execution-or-analysis",
            },
        }

    @_closed_errors
    def provider_bytes(self, binding_id: str, proposal_receipt_id: str) -> bytes:
        payload = canonical_json_bytes(self._context_value(binding_id, proposal_receipt_id))
        if len(payload) > _CONTEXT_BYTE_LIMIT:
            raise DiscoveryReviewError("discovery-review-context-bound")
        return payload

    @_admission_errors
    def _normalize(self, value, review_context):
        if (not isinstance(value, dict)
                or type(value.get("schema_version")) is not int
                or not isinstance(review_context, dict)
                or not isinstance(review_context.get("candidate"), dict)
                or type(review_context["candidate"].get("schema_version")) is not int):
            raise DiscoveryReviewAdmissionError("invalid-discovery-review-response")
        version = value["schema_version"]
        if version != review_context["candidate"]["schema_version"]:
            raise DiscoveryReviewAdmissionError("discovery-review-schema-mismatch")
        if version == 1:
            return self._normalize_v1(value, review_context)
        if version == 2:
            return self._normalize_v2(value, review_context)
        raise DiscoveryReviewAdmissionError("invalid-discovery-review-response")

    def _normalize_v1(self, value, review_context):
        review = _review_obj(value, _REVIEW_FIELDS)
        candidate = review_context["candidate"]
        proposal_id = review_context["candidate_id"]
        if (type(review["schema_version"]) is not int or review["schema_version"] != 1
                or review["kind"] != "discovery_review"
                or review["proposal_id"] != proposal_id
                or review["verdict"] not in {"ready", "revise"}):
            raise DiscoveryReviewAdmissionError("invalid-discovery-review-response")

        evidence_rows = review_context["safe_discovery_context"]["evidence"]
        projections = {row["projection_id"]: row["projection"] for row in evidence_rows}
        supplied = set(projections)
        visible = {
            projection_id for projection_id, projection in projections.items()
            if projection["disposition"] != "withheld"
            and projection["text"].strip("*\n\r\t ")
        }

        def refs(value, *, visible_only=False):
            rows = _review_rows(value, 64)
            if (any(not isinstance(item, str) or item not in supplied for item in rows)
                    or len(set(rows)) != len(rows)
                    or (visible_only and (not rows or any(item not in visible for item in rows)))):
                raise DiscoveryReviewAdmissionError("invalid-discovery-review-evidence")
            return sorted(rows)

        def assessed_rows(value, candidates, kind):
            normalized = {}
            for raw in _review_rows(value, 1024):
                row = _review_obj(raw, ("key", "verdict", "rationale", "evidence_ids"))
                key = row["key"]
                if not isinstance(key, str) or key not in candidates or key in normalized:
                    raise DiscoveryReviewAdmissionError("invalid-discovery-review-coverage")
                if row["verdict"] not in {"supported", "revise"}:
                    raise DiscoveryReviewAdmissionError("invalid-discovery-review-verdict")
                evidence_ids = refs(
                    row["evidence_ids"], visible_only=row["verdict"] == "supported"
                )
                if (row["verdict"] == "supported"
                        and not set(evidence_ids).intersection(candidates[key]["evidence_ids"])):
                    raise DiscoveryReviewAdmissionError("unsupported-discovery-review-row")
                base = {
                    "key": key,
                    "verdict": row["verdict"],
                    "rationale": _review_text(row["rationale"]),
                    "evidence_ids": evidence_ids,
                }
                normalized[key] = {
                    **base, "row_id": _row_identity(proposal_id, kind, base)
                }
            if set(normalized) != set(candidates):
                raise DiscoveryReviewAdmissionError("incomplete-discovery-review-coverage")
            return [normalized[key] for key in sorted(normalized)]

        candidate_domains = {row["key"]: row for row in candidate["domains"]}
        candidate_subjects = {row["key"]: row for row in candidate["subjects"]}
        domains = assessed_rows(review["domains"], candidate_domains, "domain")
        subjects = assessed_rows(review["subjects"], candidate_subjects, "subject")

        inventory_context = {
            row["path"]: row
            for row in review_context["safe_discovery_context"]["inventory"]
        }
        candidate_inventory = {row["path"]: row for row in candidate["inventory"]}
        inventory = {}
        unresolved_inventory = False
        for raw in _review_rows(review["inventory"]):
            row = _review_obj(
                raw, ("path", "owner", "disposition", "rationale", "evidence_ids")
            )
            path = row["path"]
            if (not isinstance(path, str) or path not in candidate_inventory
                    or path in inventory or row["owner"] != candidate_inventory[path]["owner"]):
                raise DiscoveryReviewAdmissionError("invalid-discovery-review-inventory")
            evidence_ids = refs(row["evidence_ids"])
            disposition = row["disposition"]
            matching_visible = {
                item for item in evidence_ids
                if item in visible and projections[item]["path"] == path
            }
            if disposition == "owned":
                owner = row["owner"]
                if (owner is None or not matching_visible
                        or not matching_visible.intersection(
                            candidate_subjects[owner]["evidence_ids"]
                        )):
                    raise DiscoveryReviewAdmissionError("unsupported-discovery-review-ownership")
            elif disposition == "non-behavioral":
                record = inventory_context[path]
                whole_file = any(
                    projections[item]["path"] == path
                    and projections[item]["disposition"] == "available"
                    and projections[item]["byte_start"] == 0
                    and projections[item]["byte_end"] == record["byte_count"]
                    and not projections[item]["withheld_ranges"]
                    for item in evidence_ids
                )
                if row["owner"] is not None or not whole_file:
                    raise DiscoveryReviewAdmissionError("unsupported-nonbehavioral-disposition")
            elif disposition == "excluded":
                record = inventory_context[path]
                deterministic = (
                    record["byte_count"] == 0
                    or record["object_kind"] != "regular"
                    or record["text_status"] != "eligible_utf8"
                    or any(
                        projections[item]["path"] == path
                        and projections[item]["reason_code"] == "excluded-path"
                        for item in evidence_ids
                    )
                )
                if row["owner"] is not None or not deterministic:
                    raise DiscoveryReviewAdmissionError("unsupported-excluded-disposition")
            elif disposition in {"unknown", "needs-assignment"}:
                unresolved_inventory = True
            else:
                raise DiscoveryReviewAdmissionError("invalid-discovery-review-disposition")
            base = {
                "path": path,
                "owner": row["owner"],
                "disposition": disposition,
                "rationale": _review_text(row["rationale"]),
                "evidence_ids": evidence_ids,
            }
            inventory[path] = {
                **base, "row_id": _row_identity(proposal_id, "inventory", base)
            }
        if set(inventory) != set(candidate_inventory):
            raise DiscoveryReviewAdmissionError("incomplete-discovery-review-inventory")

        subject_paths = {
            key: {projections[item]["path"] for item in row["evidence_ids"]}
            for key, row in candidate_subjects.items()
        }
        calculated_pairs = _overlap_pairs(
            candidate, review_context["safe_discovery_context"]
        )
        if review_context.get("overlap_pairs") != [list(pair) for pair in calculated_pairs]:
            raise DiscoveryReviewAdmissionError("invalid-discovery-review-overlap-context")
        expected_pairs = set(calculated_pairs)
        overlaps = {}
        overlap_conflict = False
        for raw in _review_rows(review["overlaps"], 4096):
            row = _review_obj(
                raw, ("subject_keys", "disposition", "rationale", "evidence_ids")
            )
            pair_value = row["subject_keys"]
            if (not isinstance(pair_value, list) or len(pair_value) != 2
                    or any(not isinstance(item, str) for item in pair_value)):
                raise DiscoveryReviewAdmissionError("invalid-discovery-review-overlap")
            pair = tuple(sorted(pair_value))
            if pair not in expected_pairs or pair in overlaps:
                raise DiscoveryReviewAdmissionError("invalid-discovery-review-overlap")
            evidence_ids = refs(row["evidence_ids"])
            disposition = row["disposition"]
            if disposition in {"shared-evidence", "distinct"}:
                common_paths = subject_paths[pair[0]].intersection(subject_paths[pair[1]])
                supported = any(
                    any(
                        item in evidence_ids and item in visible
                        and projections[item]["path"] == path
                        for item in candidate_subjects[pair[0]]["evidence_ids"]
                    )
                    and any(
                        item in evidence_ids and item in visible
                        and projections[item]["path"] == path
                        for item in candidate_subjects[pair[1]]["evidence_ids"]
                    )
                    for path in common_paths
                )
                if not supported:
                    raise DiscoveryReviewAdmissionError("unsupported-discovery-review-overlap")
            elif disposition == "conflict":
                overlap_conflict = True
            else:
                raise DiscoveryReviewAdmissionError("invalid-discovery-review-overlap")
            base = {
                "subject_keys": list(pair),
                "disposition": disposition,
                "rationale": _review_text(row["rationale"]),
                "evidence_ids": evidence_ids,
            }
            overlaps[pair] = {
                **base, "row_id": _row_identity(proposal_id, "overlap", base)
            }
        if set(overlaps) != expected_pairs:
            raise DiscoveryReviewAdmissionError("incomplete-discovery-review-overlap")

        findings = {}
        allowed_targets = {"source", *candidate_domains}
        for raw in _review_rows(review["findings"], 1024):
            row = _review_obj(raw, ("target", "reason_class", "rationale", "evidence_ids"))
            if row["target"] not in allowed_targets or row["reason_class"] not in _FINDING_REASONS:
                raise DiscoveryReviewAdmissionError("invalid-discovery-review-finding")
            base = {
                "target": row["target"],
                "reason_class": row["reason_class"],
                "rationale": _review_text(row["rationale"]),
                "evidence_ids": refs(row["evidence_ids"]),
            }
            finding_id = _row_identity(proposal_id, "finding", base)
            if finding_id in findings:
                raise DiscoveryReviewAdmissionError("duplicate-discovery-review-finding")
            findings[finding_id] = {**base, "finding_id": finding_id}

        has_revision_row = (
            any(row["verdict"] == "revise" for row in domains)
            or any(row["verdict"] == "revise" for row in subjects)
            or unresolved_inventory
            or overlap_conflict
        )
        if (review["verdict"] == "ready" and (findings or has_revision_row)):
            raise DiscoveryReviewAdmissionError("false-ready-discovery-review")
        if review["verdict"] == "revise" and not findings:
            raise DiscoveryReviewAdmissionError("discovery-review-finding-required")

        return {
            "schema_version": 1,
            "kind": "discovery_review",
            "proposal_id": proposal_id,
            "verdict": review["verdict"],
            "domains": domains,
            "subjects": subjects,
            "inventory": [inventory[path] for path in sorted(inventory)],
            "overlaps": [overlaps[pair] for pair in sorted(overlaps)],
            "findings": [findings[item] for item in sorted(findings)],
        }

    def _normalize_v2(self, value, review_context):
        review = _review_obj(value, _REVIEW_V2_FIELDS)
        candidate = review_context["candidate"]
        proposal_id = review_context["candidate_id"]
        if (review["schema_version"] != 2
                or candidate.get("schema_version") != 2
                or review["kind"] != "discovery_review"
                or review["proposal_id"] != proposal_id
                or review["verdict"] not in {"ready", "revise"}):
            raise DiscoveryReviewAdmissionError("invalid-discovery-review-response")

        legacy_shape = {
            key: (1 if key == "schema_version" else review[key])
            for key in _REVIEW_FIELDS
        }
        common = self._normalize_v1(legacy_shape, review_context)

        evidence_rows = review_context["safe_discovery_context"]["evidence"]
        projections = {
            row["projection_id"]: row["projection"] for row in evidence_rows
        }
        supplied = set(projections)
        visible = {
            projection_id for projection_id, projection in projections.items()
            if projection["disposition"] != "withheld"
            and projection["text"].strip("*\n\r\t ")
        }
        safe_context = review_context["safe_discovery_context"]
        if (safe_context.get("schema_version") not in {2, 3}
                or safe_context.get("category_depth_applicability")
                != category_depth_applicability()):
            raise DiscoveryReviewAdmissionError(
                "invalid-discovery-review-depth-authority"
            )

        def refs(value):
            rows = _review_rows(value, 64)
            if (any(not isinstance(item, str) or item not in supplied for item in rows)
                    or len(set(rows)) != len(rows)):
                raise DiscoveryReviewAdmissionError("invalid-discovery-review-evidence")
            return sorted(rows)

        candidate_obligations = {
            (row["target"], row["category"]): row
            for row in candidate["obligations"]
        }
        candidate_subjects = {row["key"]: row for row in candidate["subjects"]}
        empty_source = (
            not review_context["safe_discovery_context"]["inventory"]
            or all(
                row["byte_count"] == 0
                for row in review_context["safe_discovery_context"]["inventory"]
            )
        )

        def target_evidence(target, *, visible_only=False):
            allowed = visible if visible_only else supplied
            if target == "source":
                return set(allowed)
            target_paths = {
                projections[item]["path"]
                for item in (
                    set(next(
                        domain["evidence_ids"] for domain in candidate["domains"]
                        if domain["key"] == target
                    ))
                    | set().union(*(
                        set(subject["evidence_ids"])
                        for subject in candidate["subjects"]
                        if subject["target"] == target
                    ))
                )
            }
            return {
                item for item in allowed if projections[item]["path"] in target_paths
            }

        obligations = {}
        obligation_revision = False
        for raw in _review_rows(review["obligations"]):
            row = _review_obj(raw, (
                "target", "category", "disposition", "subject_keys", "verdict",
                "rationale", "evidence_ids",
            ))
            pair = (row["target"], row["category"])
            if pair not in candidate_obligations or pair in obligations:
                raise DiscoveryReviewAdmissionError("invalid-discovery-review-obligation")
            candidate_row = candidate_obligations[pair]
            subject_keys = row["subject_keys"]
            if (not isinstance(subject_keys, list)
                    or any(not isinstance(key, str) for key in subject_keys)
                    or len(set(subject_keys)) != len(subject_keys)
                    or sorted(subject_keys) != candidate_row["subject_keys"]
                    or row["disposition"] != candidate_row["disposition"]):
                raise DiscoveryReviewAdmissionError(
                    "altered-discovery-review-obligation"
                )
            verdict = row["verdict"]
            if verdict not in {"supported", "revise"}:
                raise DiscoveryReviewAdmissionError(
                    "invalid-discovery-review-verdict"
                )
            evidence_ids = refs(row["evidence_ids"])
            if verdict == "supported":
                disposition = candidate_row["disposition"]
                candidate_evidence = set(candidate_row["evidence_ids"])
                cited = set(evidence_ids)
                local = target_evidence(candidate_row["target"])
                local_visible = target_evidence(
                    candidate_row["target"], visible_only=True
                )
                if disposition == "analyze":
                    supported = (
                        cited.issubset(local_visible)
                        and bool(cited.intersection(candidate_evidence).intersection(visible))
                        and all(
                            bool(cited.intersection(candidate_subjects[key]["evidence_ids"]))
                            for key in candidate_row["subject_keys"]
                        )
                    )
                elif disposition == "not-applicable":
                    supported = (
                        cited.issubset(local_visible)
                        and bool(cited.intersection(candidate_evidence).intersection(visible))
                    ) or (
                        candidate_row["target"] == "source"
                        and empty_source
                        and not cited
                    )
                elif disposition == "unknown":
                    supported = (
                        bool(cited)
                        and cited.issubset(local)
                        and bool(cited.intersection(candidate_evidence))
                    ) or (
                        candidate_row["target"] == "source"
                        and empty_source
                        and not cited
                        and not candidate_evidence
                    )
                else:
                    supported = (
                        cited.issubset(local_visible)
                        and bool(cited.intersection(candidate_evidence).intersection(visible))
                    ) or (
                        candidate_row["target"] == "source"
                        and empty_source
                        and not cited
                        and not candidate_evidence
                    )
                if not supported:
                    raise DiscoveryReviewAdmissionError(
                        "unsupported-discovery-review-obligation"
                    )
            else:
                obligation_revision = True

            base = {
                "obligation_id": candidate_row["obligation_id"],
                "target": candidate_row["target"],
                "category": candidate_row["category"],
                "disposition": candidate_row["disposition"],
                "subject_keys": candidate_row["subject_keys"],
                "verdict": verdict,
                "rationale": _review_text(row["rationale"]),
                "evidence_ids": evidence_ids,
            }
            obligations[pair] = {
                **base,
                "row_id": _row_identity(proposal_id, "obligation", base),
            }
        if set(obligations) != set(candidate_obligations):
            raise DiscoveryReviewAdmissionError(
                "incomplete-discovery-review-obligations"
            )
        if review["verdict"] == "ready" and obligation_revision:
            raise DiscoveryReviewAdmissionError("false-ready-discovery-review")

        safe_context_id = content_digest(
            canonical_json_bytes(review_context["safe_discovery_context"])
        )
        return {
            **common,
            "schema_version": 2,
            "safe_context_id": safe_context_id,
            "obligations": [obligations[pair] for pair in sorted(obligations)],
            "unknown_obligation_ids": sorted(
                row["obligation_id"] for row in candidate_obligations.values()
                if row["disposition"] == "unknown"
            ),
        }

    def _receipt(
        self, binding_id, proposal_receipt_id, normalized, response_id, context_id
    ) -> bytes:
        review_id = content_digest(canonical_json_bytes(normalized))
        return canonical_json_bytes({
            "schema_version": 1,
            "state": "review_validated",
            "binding_id": binding_id,
            "proposal_receipt_id": proposal_receipt_id,
            "proposal_id": normalized["proposal_id"],
            "review_id": review_id,
            "authorial_response_id": response_id,
            "reviewer_context_id": context_id,
            "outcome": (
                "ready_for_planning" if normalized["verdict"] == "ready"
                else "revision_required"
            ),
            "execution_certification_required": True,
            "analysis_certified": False,
            "findings": normalized["findings"],
        })

    @_closed_errors
    def admit(
        self, binding_id: str, proposal_receipt_id: str, output: bytes
    ) -> str:
        # Screen the complete response before parsing, diagnostics or ordinary storage.
        try:
            safe_output = self._discovery.screen_output(output)
        except KnowledgeEvidenceError as exc:
            if str(exc) == "unsafe-quarantine-store":
                raise DiscoveryReviewStorageError(
                    "discovery-review-storage-unavailable"
                ) from None
            raise DiscoveryReviewAdmissionError(str(exc)) from None
        context_bytes = self.provider_bytes(binding_id, proposal_receipt_id)
        try:
            decoded = _load(safe_output)
        except DiscoveryError as exc:
            raise DiscoveryReviewAdmissionError(str(exc)) from None
        normalized = self._normalize(decoded, _load(context_bytes))
        normalized_bytes = canonical_json_bytes(normalized)
        if len(normalized_bytes) > _CONTEXT_BYTE_LIMIT:
            raise DiscoveryReviewAdmissionError("discovery-review-normalized-bound")
        response_id = content_digest(safe_output)
        receipt = self._receipt(
            binding_id, proposal_receipt_id, normalized, response_id,
            content_digest(context_bytes),
        )
        if len(receipt) > _CONTEXT_BYTE_LIMIT:
            raise DiscoveryReviewAdmissionError("discovery-review-receipt-bound")
        self._objects.put_blob(safe_output)
        self._objects.put_blob(normalized_bytes)
        return self._objects.put_blob(receipt)

    @_closed_errors
    def read_review(
        self, binding_id: str, proposal_receipt_id: str, review_receipt_id: str
    ) -> dict:
        """Reconstruct a receipt without creating or repairing any object."""
        context_bytes = self.provider_bytes(binding_id, proposal_receipt_id)
        receipt_bytes = self._objects.read_blob(review_receipt_id)
        receipt = _load(receipt_bytes)
        try:
            _obj(receipt, _RECEIPT_FIELDS)
        except DiscoveryError:
            raise DiscoveryReviewError("invalid-discovery-review-receipt") from None
        if (receipt["schema_version"] != 1 or receipt["state"] != "review_validated"
                or receipt["binding_id"] != binding_id
                or receipt["proposal_receipt_id"] != proposal_receipt_id):
            raise DiscoveryReviewError("discovery-review-receipt-mismatch")
        response_bytes = self._objects.read_blob(receipt["authorial_response_id"])
        _validate_replay_bytes(response_bytes)
        response = _load(response_bytes)
        try:
            normalized = self._normalize(response, _load(context_bytes))
        except DiscoveryReviewAdmissionError:
            raise DiscoveryReviewError("discovery-review-receipt-mismatch") from None
        normalized_bytes = canonical_json_bytes(normalized)
        stored_review = self._objects.read_blob(receipt["review_id"])
        _validate_replay_bytes(stored_review)
        if (content_digest(normalized_bytes) != receipt["review_id"]
                or stored_review != normalized_bytes):
            raise DiscoveryReviewError("discovery-review-object-mismatch")
        expected = self._receipt(
            binding_id, proposal_receipt_id, normalized,
            receipt["authorial_response_id"], content_digest(context_bytes),
        )
        if expected != receipt_bytes or content_digest(expected) != review_receipt_id:
            raise DiscoveryReviewError("discovery-review-receipt-mismatch")
        return receipt
