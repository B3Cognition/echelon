"""
validate_cq_isc.py — CLI validator for CQ-ISC YAML library files.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Spec 018: /codegen 7-Feature Extension — rule_content_hash + overridden status
Version: 1.1.0

Usage:
  python validate_cq_isc.py <library.yaml>
  python validate_cq_isc.py <library.yaml> --strict

Exit codes:
  0: All entries valid.
  1: One or more entries fail schema validation.
  2: File not found or parse error.

Used in CI lint: any change to cq-isc-default-*.yaml runs this validator.
Enforces all rules from cq_isc_schema.yaml validation_rules section.

INV-005 check: soar_predicate must NOT start with '(build' — the phase-gate
condition is prepended automatically by the smem_loader.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------

CQ_ISC_ID_PATTERN = re.compile(r"^CQ-ISC-[A-Z]+-[0-9]{3}$")
SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
VALID_CONSTRAINT_CLASSES = {"SECURITY", "STRUCTURAL", "TEST", "QUALITY"}
VALID_PHASE_SCOPES = {"VERIFY", "DELIVER", "ALL"}
VALID_DRIFT_STATUSES = {"current", "drifted", "pending-review", "overridden"}
VALID_SEVERITIES = {"critical", "high", "medium", "low"}
VALID_LANGUAGE_SCOPES = {"all", "typescript", "python", "go", "java"}


def compute_rule_content_hash(rule_text: str) -> str:
    """SHA-256 of rule_text as loaded by yaml.safe_load (UTF-8 encoded)."""
    return hashlib.sha256(rule_text.encode("utf-8")).hexdigest()

REQUIRED_FIELDS = [
    "cq_isc_id",
    "rule_text",
    "rule_content_hash",
    "constraint_class",
    "phase_scope",
    "language_scope",
    "source_authority",
    "policy_drift_status",
    "psi_contribution_weight",
    "soar_predicate",
    "wme_source",
    "test_proxy_observable",
]


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------

def validate_entry(entry: dict, index: int, all_ids: set[str]) -> list[str]:
    """
    Validate a single CQ-ISC entry dict.
    Returns a list of error messages (empty list = valid).
    """
    errors: list[str] = []
    prefix = f"Entry #{index} ({entry.get('cq_isc_id', 'NO_ID')})"

    # ------------------------------------------------------------------
    # Required fields
    # ------------------------------------------------------------------
    for field in REQUIRED_FIELDS:
        if field not in entry or entry[field] is None:
            errors.append(f"{prefix}: Missing required field '{field}'")

    if errors:
        return errors  # Skip further validation if required fields missing

    cq_id = str(entry["cq_isc_id"])

    # ------------------------------------------------------------------
    # ID format (id_format rule)
    # ------------------------------------------------------------------
    if not CQ_ISC_ID_PATTERN.match(cq_id):
        errors.append(
            f"{prefix}: cq_isc_id '{cq_id}' does not match pattern CQ-ISC-[A-Z]+-[0-9]{{3}}"
        )

    # ------------------------------------------------------------------
    # ID uniqueness (id_unique rule)
    # ------------------------------------------------------------------
    if cq_id in all_ids:
        errors.append(f"{prefix}: Duplicate cq_isc_id '{cq_id}'")
    else:
        all_ids.add(cq_id)

    # ------------------------------------------------------------------
    # constraint_class (constraint_class_valid rule)
    # ------------------------------------------------------------------
    cc = str(entry.get("constraint_class", "")).upper()
    if cc not in VALID_CONSTRAINT_CLASSES:
        errors.append(
            f"{prefix}: constraint_class '{cc}' invalid. "
            f"Must be one of {sorted(VALID_CONSTRAINT_CLASSES)}"
        )

    # ------------------------------------------------------------------
    # phase_scope (phase_scope_valid rule)
    # ------------------------------------------------------------------
    ps = str(entry.get("phase_scope", "")).upper()
    if ps not in VALID_PHASE_SCOPES:
        errors.append(
            f"{prefix}: phase_scope '{ps}' invalid. "
            f"Must be one of {sorted(VALID_PHASE_SCOPES)}"
        )

    # ------------------------------------------------------------------
    # language_scope
    # ------------------------------------------------------------------
    lang_scope = str(entry.get("language_scope", "")).strip()
    if lang_scope:
        langs = [l.strip().lower() for l in lang_scope.split(",")]
        invalid_langs = [l for l in langs if l not in VALID_LANGUAGE_SCOPES]
        if invalid_langs:
            errors.append(
                f"{prefix}: language_scope contains invalid values: {invalid_langs}. "
                f"Valid: {sorted(VALID_LANGUAGE_SCOPES)}"
            )
    else:
        errors.append(f"{prefix}: language_scope is empty")

    # ------------------------------------------------------------------
    # policy_drift_status (policy_drift_status_valid rule)
    # ------------------------------------------------------------------
    drift = str(entry.get("policy_drift_status", "")).lower()
    if drift not in VALID_DRIFT_STATUSES:
        errors.append(
            f"{prefix}: policy_drift_status '{drift}' invalid. "
            f"Must be one of {sorted(VALID_DRIFT_STATUSES)}"
        )

    # ------------------------------------------------------------------
    # psi_contribution_weight (psi_weight_range rule)
    # ------------------------------------------------------------------
    psi_w = entry.get("psi_contribution_weight")
    try:
        psi_f = float(psi_w)
        if not (0.0 <= psi_f <= 10.0):
            errors.append(
                f"{prefix}: psi_contribution_weight={psi_f} out of range [0.0, 10.0]. "
                "Values > 1.0 indicate the entry covers multiple reference constitution rules."
            )
    except (TypeError, ValueError):
        errors.append(f"{prefix}: psi_contribution_weight '{psi_w}' is not a valid float")

    # ------------------------------------------------------------------
    # soar_predicate (soar_predicate_nonempty + inv005 check)
    # ------------------------------------------------------------------
    pred = str(entry.get("soar_predicate", "")).strip()
    if not pred:
        errors.append(f"{prefix}: soar_predicate is empty — required for prohibit preference generation")

    # INV-005: soar_predicate must NOT start with (build — phase-gate is prepended automatically
    if pred.lstrip().startswith("(build"):
        errors.append(
            f"{prefix}: soar_predicate starts with '(build' — INV-005 VIOLATION. "
            "The phase-gate condition (build ^current-phase <phase>) is prepended "
            "automatically by smem_loader. Do not include it in soar_predicate."
        )

    # ------------------------------------------------------------------
    # wme_source (wme_source_nonempty rule)
    # ------------------------------------------------------------------
    wme_src = str(entry.get("wme_source", "")).strip()
    if not wme_src:
        errors.append(f"{prefix}: wme_source is empty — required for WME Translator mapping")

    # ------------------------------------------------------------------
    # rule_text (rule_text_meaningful rule)
    # ------------------------------------------------------------------
    rule_text = str(entry.get("rule_text", "")).strip()
    if len(rule_text) < 10:
        errors.append(
            f"{prefix}: rule_text '{rule_text[:30]}' too short (min 10 chars)"
        )

    # ------------------------------------------------------------------
    # rule_content_hash (rule_content_hash_required + hash_matches_rule_text)
    # Spec 018 TP-005: hash must be SHA-256(rule_text as loaded by yaml.safe_load)
    # ------------------------------------------------------------------
    rch = entry.get("rule_content_hash", "")
    if not rch:
        errors.append(f"{prefix}: rule_content_hash is missing — required by Spec 018 (TP-005)")
    else:
        rch_str = str(rch).strip()
        if not SHA256_HEX_PATTERN.match(rch_str):
            errors.append(
                f"{prefix}: rule_content_hash '{rch_str[:16]}...' is not a valid SHA-256 hex "
                "digest (must be 64 lowercase hex chars)"
            )
        else:
            # Validate hash matches rule_text (use raw YAML-loaded value, not stripped)
            raw_rule_text = entry.get("rule_text", "")
            expected_hash = compute_rule_content_hash(raw_rule_text)
            if rch_str != expected_hash:
                errors.append(
                    f"{prefix}: rule_content_hash mismatch. "
                    f"Stored: {rch_str[:16]}... "
                    f"Expected: {expected_hash[:16]}... "
                    "(rule_text was edited without recomputing hash — run: "
                    "hashlib.sha256(rule_text.encode('utf-8')).hexdigest())"
                )

    # ------------------------------------------------------------------
    # test_proxy_observable
    # ------------------------------------------------------------------
    tpo = entry.get("test_proxy_observable")
    if not isinstance(tpo, bool):
        errors.append(
            f"{prefix}: test_proxy_observable must be boolean (true/false), got '{tpo}'"
        )

    # ------------------------------------------------------------------
    # severity (optional but validated if present)
    # ------------------------------------------------------------------
    severity = entry.get("severity")
    if severity is not None:
        if str(severity).lower() not in VALID_SEVERITIES:
            errors.append(
                f"{prefix}: severity '{severity}' invalid. "
                f"Must be one of {sorted(VALID_SEVERITIES)}"
            )

    return errors


def validate_library(library_file: Path, strict: bool = False) -> tuple[bool, list[str]]:
    """
    Validate all entries in a CQ-ISC YAML library file.

    Returns (is_valid, list_of_error_messages).
    """
    if not library_file.exists():
        return False, [f"File not found: {library_file}"]

    try:
        text = library_file.read_text()
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return False, [f"YAML parse error in {library_file}: {exc}"]
    except OSError as exc:
        return False, [f"File read error: {exc}"]

    if raw is None:
        return False, [f"Empty or null YAML in {library_file}"]

    if isinstance(raw, dict):
        if "entries" not in raw:
            return False, [f"No 'entries' key in {library_file}. Expected 'entries: [...]'"]
        entries_raw = raw.get("entries", [])
        metadata = {k: v for k, v in raw.items() if k != "entries"}
    elif isinstance(raw, list):
        entries_raw = raw
        metadata = {}
    else:
        return False, [f"Unexpected YAML root type {type(raw).__name__} in {library_file}"]

    all_errors: list[str] = []
    seen_ids: set[str] = set()

    for i, entry in enumerate(entries_raw):
        if not isinstance(entry, dict):
            all_errors.append(f"Entry #{i}: not a dict, got {type(entry).__name__}")
            continue
        entry_errors = validate_entry(entry, i, seen_ids)
        all_errors.extend(entry_errors)

    # Strict mode: also validate library-level metadata
    if strict and metadata:
        if "library_version" not in metadata:
            all_errors.append("STRICT: Missing 'library_version' in library metadata")
        if "psi_seed_target" not in metadata:
            all_errors.append("STRICT: Missing 'psi_seed_target' in library metadata")

    # Compute Ψ_seed from psi_contribution_weight
    if entries_raw:
        total_psi = sum(
            float(e.get("psi_contribution_weight", 1.0))
            for e in entries_raw
            if isinstance(e, dict) and e.get("policy_drift_status", "current") == "current"
        )
        total_rules_reference = metadata.get("reference_constitution_rules", 50)
        psi_seed = total_psi / total_rules_reference if total_rules_reference > 0 else 0.0
        if psi_seed < 0.70:
            all_errors.append(
                f"WARNING: Ψ_seed = {psi_seed:.3f} < 0.70 (FR-ISC-DEFAULT-003). "
                "Default library covers less than 70% of reference constitution. "
                "Custom authoring is required before inviolability claim applies to all rules."
            )

    return len(all_errors) == 0, all_errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="CQ-ISC YAML library validator. Exit 0=valid, 1=invalid, 2=file error."
    )
    parser.add_argument("library_file", type=Path, help="Path to CQ-ISC YAML library file")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode: also validate library metadata (library_version, psi_seed_target)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print summary statistics even on success",
    )
    args = parser.parse_args()

    if not args.library_file.exists():
        print(f"ERROR: File not found: {args.library_file}", file=sys.stderr)
        sys.exit(2)

    is_valid, errors = validate_library(args.library_file, strict=args.strict)

    warnings = [e for e in errors if e.startswith("WARNING:")]
    real_errors = [e for e in errors if not e.startswith("WARNING:")]

    if real_errors:
        print(f"VALIDATION FAILED: {len(real_errors)} error(s) in {args.library_file}", file=sys.stderr)
        for err in real_errors:
            print(f"  ERROR: {err}", file=sys.stderr)
        for warn in warnings:
            print(f"  WARN: {warn}", file=sys.stderr)
        sys.exit(1)

    if warnings:
        for warn in warnings:
            print(f"  WARN: {warn}", file=sys.stderr)

    if args.summary or not is_valid:
        # Load for stats
        try:
            raw = yaml.safe_load(args.library_file.read_text())
            entries = raw.get("entries", raw) if isinstance(raw, dict) else raw
            n = len(entries) if entries else 0
            classes = {}
            for e in (entries or []):
                if isinstance(e, dict):
                    c = e.get("constraint_class", "UNKNOWN")
                    classes[c] = classes.get(c, 0) + 1
            print(f"\nLibrary: {args.library_file.name}")
            print(f"  Total entries: {n}")
            for cls, cnt in sorted(classes.items()):
                print(f"  {cls}: {cnt}")
        except Exception:
            pass

    print(f"VALIDATION OK: {args.library_file}")
    sys.exit(0)


if __name__ == "__main__":
    main()
