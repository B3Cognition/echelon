"""Tests for static verdict-contract drift validation."""

from pathlib import Path

from harness.verdict_contract_validator import validate_verdict_contracts


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_minimal_repo(
    tmp_path: Path,
    *,
    workflow_condition: str = "verdict = ALIGNED OR verdict = DRIFT",
    legacy_line: str = "",
    agent_verdict_line: str = "  verdict: <ALIGNED | DRIFT>",
) -> Path:
    root = tmp_path / "repo"
    (root / "runtime/workflow/phases").mkdir(parents=True)
    (root / "runtime/templates").mkdir(parents=True)
    (root / "prosaic/subagents").mkdir(parents=True)

    (root / "runtime/workflow/definition.yaml").write_text(
        f"""
phases:
  - id: phase2-tracker-alignment
    spec_file: workflow/phases/phase2-tracker-alignment.md
    type: agent
    agent: echelon.tracker
    transitions:
      - to: done
        condition: "{workflow_condition}"
  - id: done
    type: terminal
""".lstrip(),
        encoding="utf-8",
    )
    (root / "runtime/workflow/phases/phase2-tracker-alignment.md").write_text(
        f"""
### Routing Verdict Contract -- MANDATORY

TRACKER must emit one of these canonical `echelon_result.verdict` values:

- `ALIGNED` -- scope still matches user intent.
- `DRIFT` -- scope drift was detected.

{legacy_line}

### Output Filename -- MANDATORY

Use `.echelon/runtime/templates/intent-alignment-check-template.md`.
""".lstrip(),
        encoding="utf-8",
    )
    (root / "prosaic/subagents/echelon.tracker.md").write_text(
        f"""
## Output Block

echelon_result:
{agent_verdict_line}
""".lstrip(),
        encoding="utf-8",
    )
    (root / "runtime/templates/intent-alignment-check-template.md").write_text(
        "- Verdict: ALIGNED/DRIFT\n",
        encoding="utf-8",
    )
    return root


def test_real_verdict_contracts_match_canonical_sources() -> None:
    findings = validate_verdict_contracts(REPO_ROOT)

    assert not findings, "\n".join(
        f"{finding.path.relative_to(REPO_ROOT)}:{finding.line}: "
        f"{finding.phase_id}: {finding.reason}: {finding.details}"
        for finding in findings
    )


def test_validator_rejects_prompt_verdict_drift(tmp_path: Path) -> None:
    root = _write_minimal_repo(
        tmp_path,
        agent_verdict_line="  verdict: <ALIGNED | DRIFTING | ESCALATE>",
    )

    findings = validate_verdict_contracts(root)

    assert any(finding.reason == "prompt_verdict_contract_drift" for finding in findings)


def test_validator_accepts_declared_legacy_workflow_verdicts(tmp_path: Path) -> None:
    root = _write_minimal_repo(
        tmp_path,
        workflow_condition="verdict = ALIGNED OR verdict = DRIFT OR verdict = DRIFTING",
        legacy_line="The workflow still accepts legacy `DRIFTING` verdicts for compatibility.",
    )

    findings = validate_verdict_contracts(root)

    assert not findings, "\n".join(f"{finding.reason}: {finding.details}" for finding in findings)
