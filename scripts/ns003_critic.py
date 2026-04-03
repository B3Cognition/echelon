#!/usr/bin/env python3
"""
ns003_critic.py — NS-003-A Schema Validator

Two-component validator for Echelon agent artifacts:
  Component 1: Deterministic JSON Schema field validation (T-006)
  Component 2: Claude API prose structure assessment (T-007)
  Combined output + FRR calibration measurement (T-008)

Implements ADR-002 two-component design, contracts/ns003_interfaces.md §1.

Usage:
    python3 scripts/ns003_critic.py --artifact <path> --schema-dir scripts/schemas/
    python3 scripts/ns003_critic.py --artifact <path> --schema-dir scripts/schemas/ --dry-run
    python3 scripts/ns003_critic.py --help   (works without ANTHROPIC_API_KEY)

Exit codes:
    0 — validation completed (PASS or FAIL produced)
    1 — runtime error (API key absent, artifact not found, category inference failed)
    2 — schema configuration error (missing or malformed schema file)

Security: ANTHROPIC_API_KEY read ONLY from environment (P-014, FR-DEP-001).
"""

from __future__ import annotations

import argparse
import json
import jsonschema
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Import shared parser (T-004 prerequisite)
# ---------------------------------------------------------------------------
# Allow running from repo root or scripts/ directory
_SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPT_DIR))
from md_parser import extract_kv_pairs, extract_section_headers, compute_prose_ratio

# ---------------------------------------------------------------------------
# claude -p wrapper (no ANTHROPIC_API_KEY env var needed in subprocess)
# ---------------------------------------------------------------------------

def _claude_p_call(prompt: str, timeout: int) -> str:
    """
    Call 'claude -p' as a subprocess. Returns raw response text.
    Raises RuntimeError on timeout or non-zero exit.
    Claude Code manages auth internally — no ANTHROPIC_API_KEY env var required.
    """
    import subprocess
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        err = result.stderr.strip()[:200]
        raise RuntimeError(f"claude -p exited {result.returncode}: {err}")
    return result.stdout

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "1.0.0"
MODEL_IDENTIFIER = "claude-sonnet-4-6"
DEFAULT_TIMEOUT = 30

# Artifact category schemas (six files)
SCHEMA_NAMES = ["discover", "assess", "how", "plan", "build", "learn"]

# Map artifact filenames to pipeline stage/category labels
# (reused from contradiction-scanner.py ARTIFACT_STAGE_MAP pattern)
ARTIFACT_STAGE_MAP: dict[str, str] = {
    # DISCOVER
    "assumptions.md": "DISCOVER",
    "glossary.md": "DISCOVER",
    "mental-model.md": "DISCOVER",
    "domain-analysis.md": "DISCOVER",
    "unknowns.md": "DISCOVER",
    "boundaries.md": "DISCOVER",
    "user-intent.md": "DISCOVER",
    # ASSESS
    "feasibility.md": "ASSESS",
    "estimates.md": "ASSESS",
    "risks.md": "ASSESS",
    "risk-matrix.md": "ASSESS",
    "alternatives.md": "ASSESS",
    "assumption-review.md": "ASSESS",
    "issues.md": "ASSESS",
    # HOW
    "spec.md": "HOW",
    "data-model.md": "HOW",
    "test-strategy.md": "HOW",
    "test-architecture.md": "HOW",
    # PLAN
    "tasks.md": "PLAN",
    "plan.md": "PLAN",
    "critical-path.md": "PLAN",
    "prioritization.md": "PLAN",
    "mvp-scope.md": "PLAN",
    # BUILD
    "ground-check.md": "BUILD",
    "implementation-notes.md": "BUILD",
    "build-report.md": "BUILD",
    # LEARN
    "learnings.md": "LEARN",
    "evolution-report.md": "LEARN",
    "retrospective.md": "LEARN",
}

# Prose assessment prompt template (ADR-002, fixed versioned text)
_PROSE_PROMPT_TEMPLATE = """\
You are a structured document quality assessor evaluating Echelon squad artifacts.

Artifact category: {CATEGORY}
Required sections for this category: {REQUIRED_SECTIONS}

Artifact text:
---
{ARTIFACT_TEXT}
---

For each required section listed above, respond with exactly one line per section in this format:
SECTION_VERDICT: <section_name> | <PRESENT|ABSENT|EMPTY> | <confidence 0.50-0.85>

After all section verdicts, respond with:
OVERALL_PROSE: <PASS|FAIL> | <confidence 0.50-0.85>

Do not include any other text.\
"""

_SECTION_VERDICT_RE = re.compile(
    r"^SECTION_VERDICT:\s*(\S+)\s*\|\s*(PRESENT|ABSENT|EMPTY)\s*\|\s*([0-9.]+)\s*$"
)
_OVERALL_PROSE_RE = re.compile(
    r"^OVERALL_PROSE:\s*(PASS|FAIL)\s*\|\s*([0-9.]+)\s*$"
)

# FPCR classification thresholds (P-022)
PATENT_GRADE_THRESHOLD = 0.80
PROTOTYPE_VIABLE_THRESHOLD = 0.70

# Prose fraction threshold for IS-007 coverage limitation flag
PROSE_FRACTION_LIMIT = 0.40


# ---------------------------------------------------------------------------
# Custom errors
# ---------------------------------------------------------------------------

class SchemaLoadError(Exception):
    """Raised when a required JSON schema file is missing or malformed."""


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------

def load_schemas(schema_dir: Path) -> dict[str, dict]:
    """
    Load all six category JSON schemas from schema_dir.
    Raises SchemaLoadError (exit code 2) if any schema is missing or malformed.
    """
    schemas: dict[str, dict] = {}
    for name in SCHEMA_NAMES:
        path = schema_dir / f"{name}.json"
        if not path.exists():
            raise SchemaLoadError(f"Required schema file missing: {path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                schemas[name.upper()] = json.load(f)
        except json.JSONDecodeError as e:
            raise SchemaLoadError(f"Malformed schema file {path}: {e}")
    return schemas


# ---------------------------------------------------------------------------
# Category inference
# ---------------------------------------------------------------------------

def infer_category(artifact_path: Path) -> Optional[str]:
    """
    Infer artifact category from filename using ARTIFACT_STAGE_MAP.
    Returns None if inference fails.
    """
    name = artifact_path.name.lower()
    return ARTIFACT_STAGE_MAP.get(name)


# ---------------------------------------------------------------------------
# Component 1: Deterministic JSON Schema Validator (T-006)
# ---------------------------------------------------------------------------

def _validate_field(
    field_name: str,
    field_schema: dict,
    extracted_dict: dict[str, str],
    required_fields: list[str],
) -> dict[str, Any]:
    """
    Validate a single required field from the extracted dict.
    Returns a per-field verdict dict with confidence=0.95 (deterministic).
    """
    # Normalize field_name for lookup
    norm_key = field_name.lower().replace(" ", "_").replace("-", "_")
    value = extracted_dict.get(norm_key) or extracted_dict.get(field_name)

    if value is None:
        verdict = "FAIL"
        reason = "Field absent"
    elif value.strip() == "":
        verdict = "FAIL"
        reason = "Field present but empty"
    else:
        # Check minLength if applicable
        prop = field_schema.get("properties", {}).get(field_name, {})
        min_len = prop.get("minLength", 0)
        if isinstance(min_len, int) and len(value.strip()) < min_len:
            verdict = "FAIL"
            reason = f"Field value shorter than minLength={min_len}"
        else:
            # FR-NS3A-001: call jsonschema.validate() for enum/type constraints
            prop_schema = field_schema.get("properties", {}).get(field_name, {})
            enum_values = prop_schema.get("enum")
            if enum_values is not None:
                try:
                    jsonschema.validate(value.strip(), {"enum": enum_values})
                    verdict = "PASS"
                    reason = "Field present and value matches enum constraint"
                except jsonschema.ValidationError as e:
                    verdict = "FAIL"
                    reason = f"Field value '{value.strip()}' not in enum {enum_values}: {e.message}"
            else:
                verdict = "PASS"
                reason = "Field present and non-empty"

    return {
        "field_name": field_name,
        "verdict": verdict,
        "confidence": 0.95,
        "component": "deterministic",
        "reason": reason,
    }


def run_deterministic_validation(
    artifact_text: str,
    category: str,
    schema: dict,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """
    Component 1: Parse artifact Markdown into a dict, validate required fields.
    Returns list of per-field verdict dicts.
    """
    extracted = extract_kv_pairs(artifact_text)
    required_fields = schema.get("required", [])
    verdicts: list[dict[str, Any]] = []

    for field_name in required_fields:
        result = _validate_field(field_name, schema, extracted, required_fields)
        verdicts.append(result)
        if verbose:
            print(
                f"  [deterministic] {field_name}: {result['verdict']} "
                f"(confidence={result['confidence']:.2f})",
                file=sys.stderr,
            )

    return verdicts


# ---------------------------------------------------------------------------
# Component 2: Claude API Prose Structure Assessment (T-007)
# ---------------------------------------------------------------------------

def run_prose_assessment(
    artifact_text: str,
    category: str,
    schema: dict,
    timeout: int,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """
    Component 2: Call Claude API to assess prose section structure.
    Returns list of per-section verdict dicts with confidence in [0.5, 0.85].

    On timeout: returns a single TIMEOUT verdict record.
    On HTTP 401: raises an exception with 'HTTP 401' in message for caller to handle.
    """
    required_sections = schema.get("required_sections", [])
    required_sections_str = ", ".join(required_sections)

    prompt = _PROSE_PROMPT_TEMPLATE.format(
        CATEGORY=category,
        REQUIRED_SECTIONS=required_sections_str,
        ARTIFACT_TEXT=artifact_text,
    )

    verdicts: list[dict[str, Any]] = []

    try:
        raw_text = _claude_p_call(prompt, timeout)

        if verbose:
            print(f"  [prose] raw response:\n{raw_text}", file=sys.stderr)

        # Parse response lines
        overall_prose_verdict: Optional[str] = None
        overall_prose_conf: float = 0.70

        for line in raw_text.strip().splitlines():
            line = line.strip()
            m = _SECTION_VERDICT_RE.match(line)
            if m:
                section_name = m.group(1)
                presence = m.group(2)
                conf = float(m.group(3))
                # Cap confidence to [0.5, 0.85] per ADR-002
                conf = max(0.5, min(0.85, conf))
                field_verdict = "PASS" if presence == "PRESENT" else "FAIL"
                verdicts.append({
                    "field_name": section_name,
                    "verdict": field_verdict,
                    "confidence": conf,
                    "component": "prose_assessment",
                    "reason": f"Prose section {presence}",
                })
                if verbose:
                    print(
                        f"  [prose] {section_name}: {field_verdict} ({presence}, conf={conf:.2f})",
                        file=sys.stderr,
                    )
                continue

            m = _OVERALL_PROSE_RE.match(line)
            if m:
                overall_prose_verdict = m.group(1)
                overall_prose_conf = max(0.5, min(0.85, float(m.group(2))))

        if overall_prose_verdict:
            verdicts.append({
                "field_name": "_overall_prose",
                "verdict": overall_prose_verdict,
                "confidence": overall_prose_conf,
                "component": "prose_assessment",
                "reason": "Overall prose structure assessment",
            })

    except Exception as e:
        err_str = str(e)
        if "401" in err_str or "authentication" in err_str.lower() or "api_key" in err_str.lower():
            raise RuntimeError(f"HTTP 401: {err_str}")
        if "timeout" in err_str.lower() or "timed out" in err_str.lower() or "Timeout" in err_str:
            verdicts.append({
                "field_name": "_prose_timeout",
                "verdict": "TIMEOUT",
                "confidence": 0.0,
                "component": "prose_assessment",
                "reason": f"API timeout after {timeout}s: {err_str}",
            })
        else:
            verdicts.append({
                "field_name": "_prose_error",
                "verdict": "FAIL",
                "confidence": 0.5,
                "component": "prose_assessment",
                "reason": f"API error: {err_str}",
            })

    return verdicts


# ---------------------------------------------------------------------------
# Combined output and FPCR computation (T-008)
# ---------------------------------------------------------------------------

def compute_overall_verdict(per_field_verdicts: list[dict[str, Any]]) -> str:
    """
    PASS if all deterministic required-field verdicts are PASS.
    FAIL if any required-field verdict is FAIL.
    TIMEOUT if any verdict is TIMEOUT.
    """
    for v in per_field_verdicts:
        if v["verdict"] == "TIMEOUT":
            return "TIMEOUT"
    for v in per_field_verdicts:
        if v["component"] == "deterministic" and v["verdict"] == "FAIL":
            return "FAIL"
    return "PASS"


def classify_fpcr(fpcr: float) -> str:
    """Classify FPCR per P-022 thresholds."""
    if fpcr >= PATENT_GRADE_THRESHOLD:
        return "PATENT_GRADE"
    elif fpcr >= PROTOTYPE_VIABLE_THRESHOLD:
        return "PROTOTYPE_VIABLE"
    else:
        return "INCONCLUSIVE"


def validate_artifact(
    artifact_path: Path,
    schemas: dict[str, dict],
    category: Optional[str],
    timeout: int,
    dry_run: bool,
    verbose: bool,
) -> dict[str, Any]:
    """
    Run full two-component validation on a single artifact.
    Returns the output JSON dict per ns003_interfaces.md §1.
    """
    start_time = time.time()
    timestamp = datetime.now(timezone.utc).isoformat()

    # Read artifact
    try:
        artifact_text = artifact_path.read_text(encoding="utf-8")
    except OSError as e:
        return {
            "schema_version": VERSION,
            "artifact_path": str(artifact_path),
            "artifact_category": category or "UNKNOWN",
            "validation_timestamp": timestamp,
            "model_identifier": MODEL_IDENTIFIER,
            "overall_verdict": "FAIL",
            "elapsed_seconds": 0.0,
            "structured_to_prose_ratio": 0.0,
            "per_field_verdicts": [],
            "partial_results": False,
            "error": f"Could not read artifact: {e}",
        }

    # Skip very short artifacts
    if len(artifact_text.strip()) < 10:
        return {
            "schema_version": VERSION,
            "artifact_path": str(artifact_path),
            "artifact_category": category or "UNKNOWN",
            "validation_timestamp": timestamp,
            "model_identifier": MODEL_IDENTIFIER,
            "overall_verdict": "SKIP",
            "elapsed_seconds": time.time() - start_time,
            "structured_to_prose_ratio": 0.0,
            "per_field_verdicts": [],
            "partial_results": False,
            "error": "Artifact too short (< 10 characters)",
        }

    # Compute structured-to-prose ratio (IS-007)
    prose_ratio = compute_prose_ratio(artifact_text)
    structured_to_prose_ratio = 1.0 - prose_ratio

    schema = schemas[category]
    all_verdicts: list[dict[str, Any]] = []

    # Component 1: Deterministic validation
    det_verdicts = run_deterministic_validation(artifact_text, category, schema, verbose)
    all_verdicts.extend(det_verdicts)

    # Component 2: Prose assessment (skip if --dry-run)
    partial_results = False
    error_str = None

    if not dry_run:
        try:
            prose_verdicts = run_prose_assessment(artifact_text, category, schema, timeout, verbose)
            all_verdicts.extend(prose_verdicts)
        except RuntimeError as e:
            if "HTTP 401" in str(e):
                partial_results = True
                error_str = str(e)
                # Return partial results immediately; caller handles batch stop
                return {
                    "schema_version": VERSION,
                    "artifact_path": str(artifact_path),
                    "artifact_category": category,
                    "validation_timestamp": timestamp,
                    "model_identifier": MODEL_IDENTIFIER,
                    "overall_verdict": "PARTIAL",
                    "elapsed_seconds": time.time() - start_time,
                    "structured_to_prose_ratio": structured_to_prose_ratio,
                    "per_field_verdicts": all_verdicts,
                    "partial_results": True,
                    "error": error_str,
                }

    overall_verdict = compute_overall_verdict(all_verdicts)
    elapsed = time.time() - start_time

    # IS-007: flag if prose fraction > 40%
    coverage_limitation = prose_ratio > PROSE_FRACTION_LIMIT

    result = {
        "schema_version": VERSION,
        "artifact_path": str(artifact_path),
        "artifact_category": category,
        "validation_timestamp": timestamp,
        "model_identifier": MODEL_IDENTIFIER,
        "overall_verdict": overall_verdict,
        "elapsed_seconds": round(elapsed, 3),
        "structured_to_prose_ratio": round(structured_to_prose_ratio, 4),
        "per_field_verdicts": all_verdicts,
        "partial_results": partial_results,
        "error": error_str,
    }
    if coverage_limitation:
        result["coverage_limitation_flag"] = True

    return result


def run_calibration_set(
    calibration_dir: Path,
    schemas: dict[str, dict],
    timeout: int,
    dry_run: bool,
    verbose: bool,
) -> tuple[float, int, dict[str, float]]:
    """
    Run validation on all artifacts in calibration_dir.
    Returns (frr, calibration_set_size, per_category_prose_ratios).
    FRR = known-good artifacts rejected / total known-good artifacts.
    """
    artifact_files = list(calibration_dir.glob("*.md"))
    if not artifact_files:
        return 0.0, 0, {}

    total = 0
    rejected = 0
    category_prose_totals: dict[str, list[float]] = {cat: [] for cat in ["DISCOVER", "ASSESS", "HOW", "PLAN", "BUILD", "LEARN"]}

    for af in artifact_files:
        category = infer_category(af)
        if category is None or category not in schemas:
            continue

        result = validate_artifact(af, schemas, category, timeout, dry_run, verbose)
        total += 1

        prose_ratio = 1.0 - result.get("structured_to_prose_ratio", 0.0)
        category_prose_totals[category].append(prose_ratio)

        if result["overall_verdict"] == "FAIL":
            rejected += 1

    frr = rejected / total if total > 0 else 0.0
    per_category_ratios = {
        cat: (sum(vals) / len(vals) if vals else 0.0)
        for cat, vals in category_prose_totals.items()
    }
    return frr, total, per_category_ratios


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ns003_critic.py",
        description=(
            "NS-003-A Schema Validator — validates a single Echelon artifact against its\n"
            "category JSON schema using deterministic field validation and Claude API\n"
            "prose-structure assessment.\n\n"
            "NOTE: --help works without ANTHROPIC_API_KEY set (FR-DEP-002)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--artifact",
        required=True,
        help="Path to the Markdown artifact file to validate.",
    )
    parser.add_argument(
        "--schema-dir",
        required=True,
        help="Path to directory containing the 6 category JSON schemas.",
    )
    parser.add_argument(
        "--category",
        choices=["DISCOVER", "ASSESS", "HOW", "PLAN", "BUILD", "LEARN"],
        help="Force artifact category. If omitted, inferred from filename.",
    )
    parser.add_argument(
        "--output",
        help="Path to write the JSON validation report. Prints to stdout if omitted.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Per-artifact API call timeout in seconds. Default: {DEFAULT_TIMEOUT}.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run deterministic validation only; skip Claude API prose assessment.",
    )
    parser.add_argument(
        "--calibration-set",
        dest="calibration_set",
        help="Path to directory of known-good calibration artifacts. Computes FRR.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-field verdict details to stderr during processing.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Auth handled by claude -p (Claude Code manages key internally).
    # No ANTHROPIC_API_KEY env var needed. Use --dry-run to skip prose assessment.

    # Load schemas (exit 2 on error)
    schema_dir = Path(args.schema_dir)
    try:
        schemas = load_schemas(schema_dir)
    except SchemaLoadError as e:
        print(f"SCHEMA ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    artifact_path = Path(args.artifact)
    if not artifact_path.exists():
        print(f"ERROR: Artifact file not found: {artifact_path}", file=sys.stderr)
        sys.exit(1)

    # Category resolution
    category = args.category
    if category is None:
        category = infer_category(artifact_path)
        if category is None:
            print(
                f"ERROR: Cannot infer category from filename '{artifact_path.name}'. "
                "Use --category to specify.",
                file=sys.stderr,
            )
            sys.exit(1)
        if args.verbose:
            print(f"[ns003_critic] Inferred category: {category}", file=sys.stderr)

    # Run calibration set if provided
    calibration_info: Optional[dict] = None
    if args.calibration_set:
        cal_dir = Path(args.calibration_set)
        if not cal_dir.exists():
            print(f"ERROR: Calibration set directory not found: {cal_dir}", file=sys.stderr)
            sys.exit(1)
        frr, cal_size, cat_ratios = run_calibration_set(
            cal_dir, schemas, args.timeout, args.dry_run, args.verbose
        )
        calibration_info = {
            "frr": frr,
            "calibration_set_size": cal_size,
            "per_category_prose_ratios": cat_ratios,
        }
        if args.verbose:
            print(f"[calibration] FRR={frr:.3f} on {cal_size} artifacts", file=sys.stderr)

    # Validate artifact
    result = validate_artifact(
        artifact_path, schemas, category, args.timeout, args.dry_run, args.verbose
    )

    # Handle partial results (HTTP 401)
    if result.get("partial_results"):
        print(
            f"AUTHENTICATION ERROR: {result['error']}\n"
            "PARTIAL_RESULTS written. Batch stopped.",
            file=sys.stderr,
        )
        output_data = result
        if args.output:
            Path(args.output).write_text(json.dumps(output_data, indent=2))
        else:
            print(json.dumps(output_data, indent=2))
        sys.exit(1)

    # Attach calibration info if available
    if calibration_info:
        result["calibration_set_frr"] = calibration_info["frr"]
        result["calibration_set_size"] = calibration_info["calibration_set_size"]
        result["per_category_prose_ratios"] = calibration_info["per_category_prose_ratios"]
        # Check for coverage limitation
        for cat, prose in calibration_info["per_category_prose_ratios"].items():
            if prose > PROSE_FRACTION_LIMIT:
                result["coverage_limitation_flag"] = True
                break

    # Compute FPCR from per-field verdicts
    deterministic_verdicts = [v for v in result["per_field_verdicts"] if v["component"] == "deterministic"]
    n_pass = sum(1 for v in deterministic_verdicts if v["verdict"] == "PASS")
    n_total = len(deterministic_verdicts)
    fpcr = n_pass / n_total if n_total > 0 else 0.0
    result["fpcr"] = round(fpcr, 4)
    result["fpcr_classification"] = classify_fpcr(fpcr)

    # Output
    output_json = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        if args.verbose:
            print(f"[ns003_critic] Report written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
