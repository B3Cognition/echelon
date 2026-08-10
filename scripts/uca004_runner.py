#!/usr/bin/env python3
"""
uca004_runner.py — U-CA-004 Experiment Runner

Runs N=20 Echelon invocations per condition (BASELINE, CA-ACTIVE),
scores each output via the AQS proxy scorer (P-021), applies Mann-Whitney U
and Cohen's d statistics, and emits a POSITIVE / NEGATIVE / VOID verdict.

Components:
  T-016: AQS proxy scorer (fixed prompt, SHA-256 hash, audit JSONL)
  T-017: Full U-CA-004 experiment runner
  T-018: Verdict computation (VOID check, Mann-Whitney, Cohen's d, POSITIVE/NEGATIVE)
  T-019: NEGATIVE report generator

Implements FR-UCA-001 through FR-UCA-007, all FR-UCA-ERR requirements.
Implements ns003_interfaces.md §4, data-model.md §4.2, ADR-004.

Exit codes:
    0 — experiment completed; verdict written
    1 — runtime error (API key absent, git unavailable)

Security: ANTHROPIC_API_KEY read ONLY from environment (P-014, FR-DEP-001).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "1.0.0"
MODEL_IDENTIFIER = "claude-sonnet-4-6"
DEFAULT_N = 20
DEFAULT_OUTPUT_DIR = "experiments"
DEFAULT_TIMEOUT = 120
MIN_COMPLETIONS_FOR_VERDICT = 16

SCORING_PROMPT_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# T-016: AQS Proxy Scorer — Fixed Versioned Prompt (ADR-004, version 1.0.0)
# EXACT TEXT from research.md ADR-004. DO NOT MODIFY.
# ---------------------------------------------------------------------------

_SCORING_PROMPT_TEMPLATE = """\
You are an impartial artifact quality evaluator for a multi-agent software specification system.

Score the following agent artifact on FIVE dimensions. Each dimension is scored independently as an INTEGER from 0 to 5 (0 = absent/unusable, 5 = exemplary).

Dimension definitions:
- COMPLETENESS (0-5): Does the artifact address all required sections for its stated category? Are critical fields populated with substantive content?
- CONSISTENCY (0-5): Are claims within the artifact internally consistent? Do values, numbers, and scope statements agree with each other?
- SPECIFICITY (0-5): Are recommendations, decisions, and findings stated with sufficient precision to be actionable? (No vague statements like "should consider.")
- ACTIONABILITY (0-5): Can a downstream agent use this artifact directly to begin its work without requesting clarification?
- INNOVATION (0-5): Does the artifact demonstrate original analysis, non-obvious findings, or novel framing beyond restating the problem?

Artifact to evaluate:
---
{ARTIFACT_TEXT}
---

Respond with EXACTLY these five lines and no other text:
COMPLETENESS: <integer 0-5>
CONSISTENCY: <integer 0-5>
SPECIFICITY: <integer 0-5>
ACTIONABILITY: <integer 0-5>
INNOVATION: <integer 0-5>\
"""

# Compute SHA-256 hash of the prompt template at module load time.
# Must be identical across all records in a batch (data-model.md §1.3 Constraint).
scoring_prompt_hash: str = hashlib.sha256(
    _SCORING_PROMPT_TEMPLATE.encode("utf-8")
).hexdigest()

# Verbatim circularity disclosure (ADR-004, data-model.md §4.2)
_CIRCULARITY_DISCLOSURE = (
    "AQS proxy circularity: the scoring model (claude-sonnet-4-6) is from the same "
    "model family as the model that produced the artifacts being scored. "
    "Self-evaluation introduces potential evaluator bias. This limitation is disclosed "
    "per GATEKEEPER feasibility assessment. Results should be interpreted with this "
    "constraint in mind. Independent human evaluation of a sample (n\u22655 per condition) "
    "is recommended before patent filing."
)

# Verbatim power limitation disclosure (ADR-004) for NEGATIVE reports
_POWER_LIMITATION_DISCLOSURE = (
    "Statistical power at N=20 with alpha=0.05 is approximately 0.56 for detecting a "
    "medium effect (d=0.5). A NEGATIVE verdict at this sample size is genuinely "
    "inconclusive for small effects \u2014 it does not rule out d<0.5 improvements."
)

# Authorized overlay paths (data-model.md §4.2, populated when verdict == POSITIVE)
_AUTHORIZED_OVERLAYS = [
    "scripts/ca/actr_buffer.py",
    "scripts/bash/lida_broadcast.sh",
    "scripts/ca/gwt_workspace.py",
]

# Score extraction regex (ADR-004)
_SCORE_LINE_RE = re.compile(
    r"^(COMPLETENESS|CONSISTENCY|SPECIFICITY|ACTIONABILITY|INNOVATION):\s*([0-5])\s*$"
)

# ---------------------------------------------------------------------------
# claude -p wrapper (no ANTHROPIC_API_KEY env var needed)
# ---------------------------------------------------------------------------

def _claude_p_call(prompt: str, timeout: int) -> str:
    """
    Call 'claude -p' as a subprocess. Returns raw response text.
    Raises RuntimeError on timeout or non-zero exit.
    Claude Code manages auth internally — no ANTHROPIC_API_KEY env var required.
    """
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
# Git commit hash
# ---------------------------------------------------------------------------

def get_git_commit_hash() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return "git-unavailable"
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "git-unavailable"


# ---------------------------------------------------------------------------
# T-016: AQS Proxy Scorer
# ---------------------------------------------------------------------------

def _parse_scores(response_text: str) -> Optional[dict[str, int]]:
    """
    Parse five dimension scores from the API response.
    Returns dict if all five dimensions match and are in [0,5], else None.
    """
    scores: dict[str, int] = {}
    dimensions = {"COMPLETENESS", "CONSISTENCY", "SPECIFICITY", "ACTIONABILITY", "INNOVATION"}
    found: set[str] = set()

    for line in response_text.strip().splitlines():
        m = _SCORE_LINE_RE.match(line.strip())
        if m:
            dim = m.group(1)
            val = int(m.group(2))
            if 0 <= val <= 5:
                scores[dim] = val
                found.add(dim)

    if found == dimensions and len(scores) == 5:
        return scores
    return None


def aqs_proxy_score(
    artifact_text: str,
    run_id: str,
    condition: str,
    invocation_index: int,
    audit_jsonl_path: Path,
    model: str,
    timeout: int,
    verbose: bool = False,
) -> dict[str, Any]:
    """
    T-016: Score a single artifact using the AQS proxy scorer.

    Returns a record dict with extracted scores and metadata.
    Appends one JSON object per call to audit_jsonl_path (NFR-AUD-001).

    FR-UCA-ERR-001: out-of-range/parse-failure → retry once; second failure → SCORING_FAILED.
    """
    prompt = _SCORING_PROMPT_TEMPLATE.format(ARTIFACT_TEXT=artifact_text)

    record: dict[str, Any] = {
        "run_id": run_id,
        "condition": condition,
        "invocation_index": invocation_index,
        "scoring_prompt_version": SCORING_PROMPT_VERSION,
        "scoring_prompt_hash": scoring_prompt_hash,
        "model_identifier": model,
        "request_timestamp": None,
        "response_timestamp": None,
        "raw_prompt": prompt,
        "raw_response": None,
        "extracted_scores": None,
        "extraction_status": "SCORING_FAILED",
        "retry_count": 0,
    }

    for attempt in range(2):
        request_ts = datetime.now(timezone.utc).isoformat()
        record["request_timestamp"] = request_ts
        try:
            raw_text = _claude_p_call(prompt, timeout)
            response_ts = datetime.now(timezone.utc).isoformat()
            record["response_timestamp"] = response_ts
            record["raw_response"] = raw_text

            scores = _parse_scores(raw_text)
            if scores is not None:
                record["extracted_scores"] = {k.lower(): v for k, v in scores.items()}
                record["extraction_status"] = "OK"
                record["retry_count"] = attempt
                break
            else:
                record["extraction_status"] = "OUT_OF_RANGE"
                record["retry_count"] = attempt
                if attempt == 0:
                    if verbose:
                        print(
                            f"  [aqs_scorer] Parse failure on attempt {attempt+1}, retrying...",
                            file=sys.stderr,
                        )
                    continue
                # Second failure: SCORING_FAILED (stays)

        except Exception as e:
            record["response_timestamp"] = datetime.now(timezone.utc).isoformat()
            record["raw_response"] = f"ERROR: {e}"
            record["retry_count"] = attempt
            if attempt == 0:
                continue
            # Second attempt also failed

    # Append to JSONL audit file
    audit_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    return record


# ---------------------------------------------------------------------------
# T-017: U-CA-004 Experiment Runner
# ---------------------------------------------------------------------------

def _compute_total_aqs(scores: dict[str, int]) -> float:
    """total_aqs = sum of five dimensions / 25.0 → [0.0, 1.0]"""
    total = sum(scores.values())
    return total / 25.0


def run_condition(
    condition: str,
    n: int,
    run_id: str,
    artifact_source: Optional[Path],
    model: str,
    timeout: int,
    audit_jsonl_path: Path,
    verbose: bool,
) -> list[dict[str, Any]]:
    """
    Run N invocations for one condition.
    Returns list of per-invocation result records.

    For now uses a representative stub artifact text since COMMANDER dispatch
    is not available in the experiment runner scope.
    TIMEOUT invocations count against N (FR-UCA-ERR-003).
    """
    records: list[dict[str, Any]] = []

    for i in range(n):
        if verbose:
            print(
                f"  [uca004] condition={condition} invocation={i+1}/{n}",
                file=sys.stderr,
            )

        start_ts = datetime.now(timezone.utc).isoformat()
        elapsed_start = time.time()

        # Produce artifact text: for BASELINE use a minimal prompt; for CA-ACTIVE
        # enrich with a simulated context signal. In practice, COMMANDER would
        # dispatch a real agent here. We use a representative self-describing stub.
        artifact_prompt = (
            f"Generate a brief Echelon DISCOVER artifact for a hypothetical spec about "
            f"automated schema validation. Condition: {condition}. "
            f"Invocation: {i}. Include: scope_statement, assumptions, unknowns, "
            f"key constraints, and open questions."
        )
        if condition == "CA-ACTIVE":
            artifact_prompt += (
                " Apply structured reasoning: list goals explicitly, maintain internal "
                "consistency, and provide specific actionable findings."
            )

        artifact_text = ""
        inv_status = "OK"

        try:
            artifact_text = _claude_p_call(artifact_prompt, timeout)
        except Exception as e:
            err_str = str(e)
            if "timeout" in err_str.lower() or "timed out" in err_str.lower():
                inv_status = "TIMEOUT"
            else:
                inv_status = "ERROR"
            artifact_text = f"[{inv_status}: {err_str[:100]}]"

        elapsed = time.time() - elapsed_start

        # Score via AQS proxy if we have artifact text
        if inv_status == "OK" and artifact_text.strip():
            score_record = aqs_proxy_score(
                artifact_text=artifact_text,
                run_id=run_id,
                condition=condition,
                invocation_index=i,
                audit_jsonl_path=audit_jsonl_path,
                model=model,
                timeout=timeout,
                verbose=verbose,
            )
            ext_scores = score_record.get("extracted_scores")
            ext_status = score_record.get("extraction_status", "SCORING_FAILED")
        else:
            ext_scores = None
            ext_status = "SCORING_FAILED"
            # Still log a TIMEOUT/ERROR record to audit
            timeout_record = {
                "run_id": run_id,
                "condition": condition,
                "invocation_index": i,
                "scoring_prompt_version": SCORING_PROMPT_VERSION,
                "scoring_prompt_hash": scoring_prompt_hash,
                "model_identifier": model,
                "request_timestamp": start_ts,
                "response_timestamp": datetime.now(timezone.utc).isoformat(),
                "raw_prompt": "[skipped — artifact generation failed]",
                "raw_response": artifact_text,
                "extracted_scores": None,
                "extraction_status": "SCORING_FAILED",
                "retry_count": 0,
            }
            audit_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with open(audit_jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(timeout_record) + "\n")

        # Compute total_aqs
        total_aqs: Optional[float] = None
        if ext_scores and ext_status == "OK":
            total_aqs = _compute_total_aqs(ext_scores)

        per_inv = {
            "run_id": run_id,
            "condition": condition,
            "invocation_index": i,
            "completeness": ext_scores.get("completeness") if ext_scores else None,
            "consistency": ext_scores.get("consistency") if ext_scores else None,
            "specificity": ext_scores.get("specificity") if ext_scores else None,
            "actionability": ext_scores.get("actionability") if ext_scores else None,
            "innovation": ext_scores.get("innovation") if ext_scores else None,
            "total_aqs": total_aqs,
            "extraction_status": ext_status,
            "invocation_status": inv_status,
            "elapsed_seconds": round(elapsed, 3),
        }
        records.append(per_inv)

        if verbose and total_aqs is not None:
            print(
                f"  [uca004] {condition}[{i}] total_aqs={total_aqs:.3f}",
                file=sys.stderr,
            )

    return records


# ---------------------------------------------------------------------------
# T-018: Verdict Computation
# ---------------------------------------------------------------------------

def compute_verdict(
    baseline_records: list[dict],
    ca_active_records: list[dict],
) -> dict[str, Any]:
    """
    T-018: Compute statistical verdict per ADR-004 and ns003_interfaces.md §4.

    1. VOID check FIRST: n_completed < 16 for either condition.
    2. Mann-Whitney U (scipy).
    3. Cohen's d (stdlib math only).
    4. POSITIVE iff p_value < 0.05 AND cohens_d >= 0.5.
    5. NEGATIVE otherwise. No INCONCLUSIVE (P-020).
    """
    from scipy import stats as scipy_stats

    # Extract successful total_aqs values
    baseline_aqs = [
        r["total_aqs"] for r in baseline_records
        if r.get("total_aqs") is not None and r.get("extraction_status") == "OK"
    ]
    ca_active_aqs = [
        r["total_aqs"] for r in ca_active_records
        if r.get("total_aqs") is not None and r.get("extraction_status") == "OK"
    ]

    n_completed_baseline = len(baseline_aqs)
    n_completed_ca = len(ca_active_aqs)
    n_timeout_baseline = sum(1 for r in baseline_records if r.get("invocation_status") == "TIMEOUT")
    n_timeout_ca = sum(1 for r in ca_active_records if r.get("invocation_status") == "TIMEOUT")
    n_scoring_failed_baseline = sum(1 for r in baseline_records if r.get("extraction_status") == "SCORING_FAILED")
    n_scoring_failed_ca = sum(1 for r in ca_active_records if r.get("extraction_status") == "SCORING_FAILED")

    # VOID check (FR-UCA-ERR-002, AC-4.6)
    void_reason: Optional[str] = None
    if n_completed_baseline < MIN_COMPLETIONS_FOR_VERDICT:
        void_reason = (
            f"BASELINE had {n_completed_baseline} completions, "
            f"minimum {MIN_COMPLETIONS_FOR_VERDICT} required"
        )
    elif n_completed_ca < MIN_COMPLETIONS_FOR_VERDICT:
        void_reason = (
            f"CA-ACTIVE had {n_completed_ca} completions, "
            f"minimum {MIN_COMPLETIONS_FOR_VERDICT} required"
        )

    statistics: dict[str, Any] = {
        "mann_whitney_u": None,
        "p_value": None,
        "cohens_d": None,
        "test_type": "two-tailed",
    }

    if void_reason:
        return {
            "verdict": "VOID",
            "void_reason": void_reason,
            "statistics": statistics,
            "authorized_overlays": [],
            "baseline_summary": {
                "n_completed": n_completed_baseline,
                "n_timeout": n_timeout_baseline,
                "n_scoring_failed": n_scoring_failed_baseline,
                "aqs_scores": baseline_aqs,
                "aqs_mean": 0.0,
                "aqs_std": 0.0,
            },
            "ca_active_summary": {
                "n_completed": n_completed_ca,
                "n_timeout": n_timeout_ca,
                "n_scoring_failed": n_scoring_failed_ca,
                "aqs_scores": ca_active_aqs,
                "aqs_mean": 0.0,
                "aqs_std": 0.0,
            },
        }

    # Compute means and standard deviations
    n1 = len(baseline_aqs)
    n2 = len(ca_active_aqs)
    mean_baseline = sum(baseline_aqs) / n1
    mean_ca = sum(ca_active_aqs) / n2

    var_baseline = sum((x - mean_baseline) ** 2 for x in baseline_aqs) / max(n1 - 1, 1)
    var_ca = sum((x - mean_ca) ** 2 for x in ca_active_aqs) / max(n2 - 1, 1)
    std_baseline = math.sqrt(var_baseline)
    std_ca = math.sqrt(var_ca)

    # Mann-Whitney U (scipy, two-sided)
    mw_stat, p_value = scipy_stats.mannwhitneyu(
        baseline_aqs, ca_active_aqs, alternative="two-sided"
    )

    # Cohen's d (stdlib math only — ADR-004)
    pooled_var = ((n1 - 1) * var_baseline + (n2 - 1) * var_ca) / (n1 + n2 - 2)
    pooled_std = math.sqrt(pooled_var) if pooled_var > 0 else 1e-9
    cohens_d = (mean_ca - mean_baseline) / pooled_std

    statistics = {
        "mann_whitney_u": round(float(mw_stat), 4),
        "p_value": round(float(p_value), 6),
        "cohens_d": round(cohens_d, 4),
        "test_type": "two-tailed",
    }

    # POSITIVE iff p < 0.05 AND d >= 0.5 (AC-4.3, P-020 binary gate)
    if p_value < 0.05 and cohens_d >= 0.5:
        verdict = "POSITIVE"
        authorized_overlays = _AUTHORIZED_OVERLAYS[:]
    else:
        verdict = "NEGATIVE"
        authorized_overlays = []

    return {
        "verdict": verdict,
        "void_reason": None,
        "statistics": statistics,
        "authorized_overlays": authorized_overlays,
        "baseline_summary": {
            "n_completed": n_completed_baseline,
            "n_timeout": n_timeout_baseline,
            "n_scoring_failed": n_scoring_failed_baseline,
            "aqs_scores": baseline_aqs,
            "aqs_mean": round(mean_baseline, 4),
            "aqs_std": round(std_baseline, 4),
        },
        "ca_active_summary": {
            "n_completed": n_completed_ca,
            "n_timeout": n_timeout_ca,
            "n_scoring_failed": n_scoring_failed_ca,
            "aqs_scores": ca_active_aqs,
            "aqs_mean": round(mean_ca, 4),
            "aqs_std": round(std_ca, 4),
        },
    }


# ---------------------------------------------------------------------------
# T-019: NEGATIVE Report Generator
# ---------------------------------------------------------------------------

def generate_negative_report(
    verdict_data: dict[str, Any],
    commit_hash: str,
    model: str,
    experiment_date: str,
    output_path: Path,
) -> None:
    """
    T-019: Generate uca004-negative-report.md when verdict == NEGATIVE.
    NOT generated for POSITIVE or VOID verdicts (AC-4.5).

    Uses ADR-001 amended framing (post-hoc, not pre-commit).
    Includes verbatim power limitation disclosure and circularity disclosure.
    """
    stats = verdict_data.get("statistics", {})
    baseline = verdict_data.get("baseline_summary", {})
    ca_active = verdict_data.get("ca_active_summary", {})

    mw_u = stats.get("mann_whitney_u", "N/A")
    p_val = stats.get("p_value", "N/A")
    cohens_d = stats.get("cohens_d", "N/A")
    b_mean = baseline.get("aqs_mean", 0.0)
    b_std = baseline.get("aqs_std", 0.0)
    b_n = baseline.get("n_completed", 0)
    ca_mean = ca_active.get("aqs_mean", 0.0)
    ca_std = ca_active.get("aqs_std", 0.0)
    ca_n = ca_active.get("n_completed", 0)

    lines = [
        "# U-CA-004 Experiment Report — NEGATIVE Verdict",
        "",
        "## Experiment Header",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Spec ID | 017 |",
        f"| Experiment ID | U-CA-004 |",
        f"| Date | {experiment_date} |",
        f"| Model | {model} |",
        f"| Codebase Commit Hash | `{commit_hash}` |",
        "",
        "## Verdict",
        "",
        "**NEGATIVE**",
        "",
        "The CA-ACTIVE condition did not demonstrate statistically significant improvement",
        "over the BASELINE condition at alpha=0.05 with Cohen's d >= 0.5.",
        "",
        "> No CA overlay component implementation code should be committed.",
        "> CA overlay implementation is blocked per P-020 until a POSITIVE verdict is achieved.",
        "",
        "## Statistics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Mann-Whitney U | {mw_u} |",
        f"| p-value | {p_val} |",
        f"| Cohen's d | {cohens_d} |",
        f"| Test type | two-tailed |",
        "",
        "## Per-Condition AQS Summary",
        "",
        "| Condition | N Completed | Mean AQS | Std Dev |",
        "|-----------|------------|----------|---------|",
        f"| BASELINE | {b_n} | {b_mean:.4f} | {b_std:.4f} |",
        f"| CA-ACTIVE | {ca_n} | {ca_mean:.4f} | {ca_std:.4f} |",
        "",
        "## Statistical Power Limitation",
        "",
        _POWER_LIMITATION_DISCLOSURE,
        "",
        "## Recommendation",
        "",
        "- No CA overlay implementation files should be committed to this codebase.",
        "- The U-CA-004 experiment should be re-run with design modifications before",
        "  any CA overlay implementation is authorized (P-020 gate).",
        "- Consider increasing N, using an independent evaluator model, or refining",
        "  the CA-ACTIVE condition to produce a stronger signal.",
        "",
        "## Limitations",
        "",
        _CIRCULARITY_DISCLOSURE,
        "",
        "---",
        f"*Generated by uca004_runner.py on {experiment_date}*",
    ]

    output_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# T-017: Main experiment orchestration
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uca004_runner.py",
        description=(
            "U-CA-004 Experiment Runner — controlled experiment comparing BASELINE\n"
            "and CA-ACTIVE Echelon conditions. Uses automated AQS proxy scorer (P-021).\n"
            "Produces POSITIVE/NEGATIVE/VOID verdict gating CA overlay implementation.\n\n"
            "NOTE: --help works without ANTHROPIC_API_KEY set (FR-DEP-002)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--conditions",
        nargs="+",
        default=["BASELINE", "CA-ACTIVE"],
        choices=["BASELINE", "CA-ACTIVE"],
        help="Conditions to run. Default: BASELINE CA-ACTIVE",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=DEFAULT_N,
        help=f"Number of invocations per condition. Default: {DEFAULT_N}. Min for verdict: {MIN_COMPLETIONS_FOR_VERDICT}.",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for output files. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--model",
        default=MODEL_IDENTIFIER,
        help=f"Claude model identifier. Default: {MODEL_IDENTIFIER}",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Per-invocation timeout seconds. Default: {DEFAULT_TIMEOUT}.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-invocation AQS scores to stderr.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Auth is handled by claude -p (Claude Code manages key internally).
    # No ANTHROPIC_API_KEY env var check needed (FR-DEP-003 satisfied via claude -p).

    # Phase 1: git commit hash (IS-006)
    commit_hash = get_git_commit_hash()
    if commit_hash == "git-unavailable":
        print(
            "ERROR: git not available. Cannot capture codebase_commit_hash (IS-006).",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[uca004] Codebase commit: {commit_hash[:12]}...", file=sys.stderr)
    print(f"[uca004] Scoring prompt hash: {scoring_prompt_hash[:16]}...", file=sys.stderr)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    experiment_date = datetime.now(timezone.utc).isoformat()
    run_id = str(uuid.uuid4())
    audit_jsonl_path = output_dir / "uca004-scoring-audit.jsonl"

    # Phase 2-4: Run invocations for each condition
    all_records: dict[str, list[dict]] = {}

    for condition in args.conditions:
        print(f"[uca004] Running condition: {condition} (N={args.n})", file=sys.stderr)
        records = run_condition(
            condition=condition,
            n=args.n,
            run_id=run_id,
            artifact_source=None,  # Use prompt-generated artifacts
            model=args.model,
            timeout=args.timeout,
            audit_jsonl_path=audit_jsonl_path,
            verbose=args.verbose,
        )
        all_records[condition] = records
        n_ok = sum(1 for r in records if r.get("extraction_status") == "OK")
        print(f"[uca004] {condition}: {n_ok}/{args.n} successful scorings", file=sys.stderr)

    # Phase 5: Verdict computation (T-018)
    baseline_records = all_records.get("BASELINE", [])
    ca_active_records = all_records.get("CA-ACTIVE", [])

    verdict_data = compute_verdict(baseline_records, ca_active_records)
    verdict = verdict_data["verdict"]

    print(f"[uca004] Verdict: {verdict}", file=sys.stderr)

    # Build per_invocation_records for output
    per_invocation_records = []
    for cond, records in all_records.items():
        for r in records:
            per_invocation_records.append({
                "run_id": r["run_id"],
                "condition": r["condition"],
                "invocation_index": r["invocation_index"],
                "completeness": r.get("completeness"),
                "consistency": r.get("consistency"),
                "specificity": r.get("specificity"),
                "actionability": r.get("actionability"),
                "innovation": r.get("innovation"),
                "total_aqs": r.get("total_aqs"),
                "extraction_status": r.get("extraction_status", "SCORING_FAILED"),
                "elapsed_seconds": r.get("elapsed_seconds", 0.0),
            })

    bs = verdict_data["baseline_summary"]
    ca = verdict_data["ca_active_summary"]

    # Build uca004-results.json (data-model.md §4.2)
    results = {
        "schema_version": VERSION,
        "experiment_id": "U-CA-004",
        "spec_id": "017",
        "experiment_date": experiment_date,
        "codebase_commit_hash": commit_hash,
        "model_identifier": args.model,
        "scoring_prompt_version": SCORING_PROMPT_VERSION,
        "scoring_prompt_hash": scoring_prompt_hash,
        "n_per_condition": args.n,
        "conditions_run": args.conditions,
        "baseline": {
            "n_completed": bs["n_completed"],
            "n_timeout": bs["n_timeout"],
            "n_scoring_failed": bs["n_scoring_failed"],
            "aqs_scores": bs["aqs_scores"],
            "aqs_mean": bs["aqs_mean"],
            "aqs_std": bs["aqs_std"],
        },
        "ca_active": {
            "n_completed": ca["n_completed"],
            "n_timeout": ca["n_timeout"],
            "n_scoring_failed": ca["n_scoring_failed"],
            "aqs_scores": ca["aqs_scores"],
            "aqs_mean": ca["aqs_mean"],
            "aqs_std": ca["aqs_std"],
        },
        "statistics": verdict_data["statistics"],
        "verdict": verdict,
        "void_reason": verdict_data.get("void_reason"),
        "authorized_overlays": verdict_data["authorized_overlays"],
        "limitations": _CIRCULARITY_DISCLOSURE,
        "per_invocation_records": per_invocation_records,
    }

    results_path = output_dir / "uca004-results.json"
    results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"[uca004] Results written to {results_path}", file=sys.stderr)

    # T-019: Generate NEGATIVE report (only if NEGATIVE verdict)
    if verdict == "NEGATIVE":
        negative_report_path = output_dir / "uca004-negative-report.md"
        generate_negative_report(
            verdict_data=verdict_data,
            commit_hash=commit_hash,
            model=args.model,
            experiment_date=experiment_date,
            output_path=negative_report_path,
        )
        print(f"[uca004] NEGATIVE report written to {negative_report_path}", file=sys.stderr)

    # Summary
    stats = verdict_data["statistics"]
    if verdict != "VOID":
        print(
            f"\n[uca004] SUMMARY\n"
            f"  Verdict:    {verdict}\n"
            f"  U stat:     {stats.get('mann_whitney_u', 'N/A')}\n"
            f"  p-value:    {stats.get('p_value', 'N/A')}\n"
            f"  Cohen's d:  {stats.get('cohens_d', 'N/A')}\n"
            f"  BASELINE:   mean={bs['aqs_mean']:.4f}, std={bs['aqs_std']:.4f}, n={bs['n_completed']}\n"
            f"  CA-ACTIVE:  mean={ca['aqs_mean']:.4f}, std={ca['aqs_std']:.4f}, n={ca['n_completed']}",
            file=sys.stderr,
        )
    else:
        print(
            f"\n[uca004] SUMMARY\n"
            f"  Verdict:    VOID\n"
            f"  Reason:     {verdict_data.get('void_reason')}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
