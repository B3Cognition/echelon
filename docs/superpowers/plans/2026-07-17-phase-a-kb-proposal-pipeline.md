# Phase A KB Proposal Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Phase A KB proposal pipeline so LLM agents write run-local proposal artifacts and deterministic code validates/applies them without blocking the product run.

**Architecture:** Add a focused `echelon.kb_proposals` module that owns proposal parsing, validation, report generation, and deterministic list-target application. Expose it through `echelon kb validate` and `echelon kb apply` Typer commands, then update Phase A templates/prompts so agents propose KB changes instead of editing canonical YAML directly.

**Tech Stack:** Python 3, Typer CLI, PyYAML, pytest, existing `src/codegen/memory/kb_schema_validator.py`, existing Phase A markdown workflow files.

## Global Constraints

- KB read, proposal, validation, apply, and usage failures are non-blocking for Phase A product runs.
- LLM agents own semantic proposal content; deterministic code owns schema validation, mutation, reporting, and recovery.
- Run-local proposal files live under `${SQUAD_DIR}/kb-proposals/`, resolving to paths such as `runs/squad-001/kb-proposals/`.
- Published KB provenance summaries live under `{spec_dir}/kb/` when possible.
- Canonical KB mutation must happen only through `echelon kb apply` for Phase A.
- Proposal operation identity is `<run_id>/<proposal_id>`.
- Proposal documents use `targets: [...]`, not a scalar `target`.
- Implement append-only/list-target proposal application first; aggregate/map appliers may return `needs_review` in this first slice.
- Preserve existing legacy KB debt reporting; do not require full legacy migration before valid new proposals can be processed.

---

## File Structure

- Create `src/echelon/kb_proposals.py`: pure Python proposal parsing, validation, normalization, application, and report writing.
- Modify `src/echelon/cli_app.py`: add top-level `echelon kb validate` and `echelon kb apply` Typer commands that call `kb_proposals`.
- Create `tests/unit/test_kb_proposals.py`: unit tests for envelope validation, type/target pairing, idempotency, and non-blocking failures.
- Create `tests/integration/test_kb_proposals_cli.py`: CLI-level tests with temporary run and KB directories.
- Create `extension/templates/kb-proposals/*.yaml`: proposal templates for initial Phase A types.
- Modify `extension/workflow/phases/phase4-document.md`: instruct COMMANDER to run KB validate/apply non-blockingly and publish `{spec_dir}/kb/`.
- Modify `extension/agents/exploration/sage.md` and `extension/agents/learning/mirror.md`: switch durable KB writes to proposal artifacts for SAGE, patterns, and pitfalls in the first slice.
- Modify `extension/scripts/bash/finalize-run.sh`: stage `{SPEC_DIR}/kb/` if present. Existing `git add "${SPEC_DIR}/"` already covers this, but add an explicit log line for observability.

---

### Task 1: Proposal Model and Validator

**Files:**
- Create: `src/echelon/kb_proposals.py`
- Create: `tests/unit/test_kb_proposals.py`

**Interfaces:**
- Produces: `validate_proposal_document(filename: str, data: Any, *, expected_run_id: str | None = None) -> ProposalValidationResult`
- Produces: `load_proposals(proposal_dir: Path, *, expected_run_id: str | None = None) -> list[LoadedProposal]`
- Produces: dataclasses `ProposalValidationIssue`, `ProposalValidationResult`, `LoadedProposal`
- Consumes: PyYAML for parsing only; no canonical KB mutation yet.

- [ ] **Step 1: Write failing validator tests**

Add `tests/unit/test_kb_proposals.py`:

```python
"""Tests for Phase A KB proposal validation."""

from __future__ import annotations

from pathlib import Path

from echelon.kb_proposals import load_proposals, validate_proposal_document


def _base_proposal(**overrides):
    data = {
        "schema_version": 1,
        "proposal_id": "kb-prop-0001",
        "proposal_type": "pattern",
        "run_id": "squad-001",
        "agent": "speckit-echelon-mirror",
        "created_at": "2026-07-17T12:00:00Z",
        "targets": ["knowledge-base/patterns.yaml"],
        "confidence": 0.72,
        "source_artifacts": ["runs/squad-001/reasoning-journal.jsonl"],
        "evidence_refs": [
            {
                "artifact": "runs/squad-001/reasoning-journal.jsonl",
                "locator": "RJ-001",
                "claim": "WHY3 passed after constraint was added.",
            }
        ],
        "payload": {
            "name": "Architecture constraint before estimates",
            "domain": "planning",
            "description": "Apply explicit architecture constraints before estimates.",
            "tags": ["planning"],
            "status": "active",
            "project_fingerprint": "auto",
            "scope": "local_only",
        },
    }
    data.update(overrides)
    return data


def test_valid_pattern_proposal_passes() -> None:
    result = validate_proposal_document(
        "kb-prop-0001.yaml",
        _base_proposal(),
        expected_run_id="squad-001",
    )

    assert result.ok is True
    assert result.issues == []


def test_rejects_scalar_target_contract() -> None:
    data = _base_proposal(target="knowledge-base/patterns.yaml")
    data.pop("targets")

    result = validate_proposal_document("bad.yaml", data)

    assert result.ok is False
    assert any(issue.path == "targets" for issue in result.issues)


def test_rejects_wrong_target_for_type() -> None:
    result = validate_proposal_document(
        "bad.yaml",
        _base_proposal(targets=["knowledge-base/sage-decisions.yaml"]),
    )

    assert result.ok is False
    assert any(issue.path == "targets[0]" for issue in result.issues)


def test_operation_identity_is_run_id_plus_proposal_id() -> None:
    result = validate_proposal_document(
        "kb-prop-0001.yaml",
        _base_proposal(),
        expected_run_id="squad-001",
    )

    assert result.operation_id == "squad-001/kb-prop-0001"


def test_load_proposals_reports_yaml_parse_failure(tmp_path: Path) -> None:
    proposal_dir = tmp_path / "kb-proposals"
    proposal_dir.mkdir()
    (proposal_dir / "bad.yaml").write_text("schema_version: [", encoding="utf-8")

    loaded = load_proposals(proposal_dir)

    assert len(loaded) == 1
    assert loaded[0].validation.ok is False
    assert loaded[0].data is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_kb_proposals.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'echelon.kb_proposals'`.

- [ ] **Step 3: Implement proposal model and validation**

Create `src/echelon/kb_proposals.py`:

```python
"""Phase A knowledge-base proposal validation and application."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

PROPOSAL_TARGETS: dict[str, set[str]] = {
    "sage_decision": {"knowledge-base/sage-decisions.yaml"},
    "pattern": {"knowledge-base/patterns.yaml"},
    "pitfall": {"knowledge-base/pitfalls.yaml"},
    "calibration_observation": {
        "knowledge-base/calibration-profile.yaml",
        "knowledge-base/estimates-log.yaml",
    },
    "internalization_observation": {
        "knowledge-base/internalization-log.yaml",
        "knowledge-base/agent-scores.yaml",
        "knowledge-base/evolution-signals.yaml",
    },
}


@dataclass(frozen=True)
class ProposalValidationIssue:
    path: str
    message: str


@dataclass(frozen=True)
class ProposalValidationResult:
    ok: bool
    issues: list[ProposalValidationIssue] = field(default_factory=list)
    operation_id: str | None = None


@dataclass(frozen=True)
class LoadedProposal:
    path: Path
    data: dict[str, Any] | None
    validation: ProposalValidationResult


def validate_proposal_document(
    filename: str,
    data: Any,
    *,
    expected_run_id: str | None = None,
) -> ProposalValidationResult:
    issues: list[ProposalValidationIssue] = []
    if not isinstance(data, dict):
        return _result([_issue("$", "proposal must be a mapping")])

    _require(data, "schema_version", issues)
    _require(data, "proposal_id", issues)
    _require(data, "proposal_type", issues)
    _require(data, "run_id", issues)
    _require(data, "agent", issues)
    _require(data, "created_at", issues)
    _require(data, "targets", issues)
    _require(data, "source_artifacts", issues)
    _require(data, "evidence_refs", issues)
    _require(data, "payload", issues)

    if data.get("schema_version") != 1:
        issues.append(_issue("schema_version", "expected 1"))

    proposal_id = data.get("proposal_id")
    if not isinstance(proposal_id, str) or not proposal_id.strip():
        issues.append(_issue("proposal_id", "expected non-empty string"))

    run_id = data.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        issues.append(_issue("run_id", "expected non-empty string"))
    elif expected_run_id is not None and run_id != expected_run_id:
        issues.append(_issue("run_id", f"expected {expected_run_id!r}"))

    operation_id = (
        f"{run_id}/{proposal_id}"
        if isinstance(run_id, str) and isinstance(proposal_id, str)
        else None
    )

    proposal_type = data.get("proposal_type")
    allowed_targets = PROPOSAL_TARGETS.get(proposal_type)
    if not isinstance(proposal_type, str) or allowed_targets is None:
        issues.append(_issue("proposal_type", "unsupported proposal type"))

    created_at = data.get("created_at")
    if not isinstance(created_at, str) or not _ISO_DATETIME_RE.match(created_at):
        issues.append(_issue("created_at", "expected ISO-8601 date-time"))

    confidence = data.get("confidence")
    if confidence is not None and (
        not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1
    ):
        issues.append(_issue("confidence", "expected number between 0 and 1"))

    targets = data.get("targets")
    if not isinstance(targets, list) or not targets:
        issues.append(_issue("targets", "expected non-empty list"))
    elif allowed_targets is not None:
        for index, target in enumerate(targets):
            if target not in allowed_targets:
                issues.append(_issue(f"targets[{index}]", "target incompatible with proposal_type"))

    for key in ("source_artifacts", "evidence_refs"):
        value = data.get(key)
        if not isinstance(value, list) or not value:
            issues.append(_issue(key, "expected non-empty list"))

    if not isinstance(data.get("payload"), dict):
        issues.append(_issue("payload", "expected mapping"))

    _validate_payload(data, issues)
    return _result(issues, operation_id=operation_id)


def load_proposals(
    proposal_dir: Path,
    *,
    expected_run_id: str | None = None,
) -> list[LoadedProposal]:
    import yaml

    if not proposal_dir.exists():
        return []

    loaded: list[LoadedProposal] = []
    for path in sorted(proposal_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            loaded.append(
                LoadedProposal(
                    path=path,
                    data=None,
                    validation=_result([_issue("$", f"cannot parse YAML: {exc}")]),
                )
            )
            continue
        loaded.append(
            LoadedProposal(
                path=path,
                data=data if isinstance(data, dict) else None,
                validation=validate_proposal_document(
                    path.name,
                    data,
                    expected_run_id=expected_run_id,
                ),
            )
        )
    return loaded


def _validate_payload(data: dict[str, Any], issues: list[ProposalValidationIssue]) -> None:
    proposal_type = data.get("proposal_type")
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return
    required_by_type = {
        "sage_decision": ("artifact", "challenge_type", "challenge_summary", "outcome", "resolution"),
        "pattern": ("name", "domain", "description", "tags", "status", "project_fingerprint", "scope"),
        "pitfall": ("name", "domain", "trigger", "impact", "avoidance", "tags", "status", "project_fingerprint", "scope"),
        "calibration_observation": ("domain", "observation_kind"),
        "internalization_observation": ("subject_agent", "agent_tier", "metrics", "gate_verdict", "computation_health"),
    }
    for key in required_by_type.get(proposal_type, ()):
        if key not in payload:
            issues.append(_issue(f"payload.{key}", "required"))


def _require(data: dict[str, Any], key: str, issues: list[ProposalValidationIssue]) -> None:
    if key not in data:
        issues.append(_issue(key, "required"))


def _issue(path: str, message: str) -> ProposalValidationIssue:
    return ProposalValidationIssue(path=path, message=message)


def _result(
    issues: list[ProposalValidationIssue],
    *,
    operation_id: str | None = None,
) -> ProposalValidationResult:
    return ProposalValidationResult(ok=not issues, issues=issues, operation_id=operation_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_kb_proposals.py -q
```

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/kb_proposals.py tests/unit/test_kb_proposals.py
git commit -m "feat: validate phase a kb proposals"
```

---

### Task 2: Deterministic Apply Report and List-Target Appliers

**Files:**
- Modify: `src/echelon/kb_proposals.py`
- Modify: `tests/unit/test_kb_proposals.py`

**Interfaces:**
- Consumes: `load_proposals(...)` and `validate_proposal_document(...)` from Task 1.
- Produces: `apply_proposals(project_root: Path, run_id: str) -> KBApplyReport`
- Produces: `KBApplyReport.to_dict() -> dict[str, object]`
- Applies: `sage_decision`, `pattern`, and `pitfall` proposals to canonical list targets.
- Marks: `calibration_observation` and `internalization_observation` as `needs_review` in this slice.

- [ ] **Step 1: Write failing apply tests**

Append to `tests/unit/test_kb_proposals.py`:

```python
import yaml

from echelon.kb_proposals import apply_proposals


def test_apply_valid_pattern_writes_canonical_entry(tmp_path: Path) -> None:
    project = tmp_path
    kb = project / "knowledge-base"
    kb.mkdir()
    (kb / "patterns.yaml").write_text("schema_version: 1\nentries: []\n", encoding="utf-8")
    run = project / "runs" / "squad-001" / "kb-proposals"
    run.mkdir(parents=True)
    proposal = _base_proposal()
    (run / "kb-prop-0001.yaml").write_text(yaml.safe_dump(proposal), encoding="utf-8")

    report = apply_proposals(project, "squad-001")

    assert report.status == "applied"
    assert report.accepted_count == 1
    data = yaml.safe_load((kb / "patterns.yaml").read_text(encoding="utf-8"))
    assert data["entries"][0]["operation_id"] == "squad-001/kb-prop-0001"
    assert data["entries"][0]["run_id"] == "squad-001"
    assert data["entries"][0]["project_fingerprint"] != "auto"


def test_apply_invalid_and_valid_mixed_run_continues(tmp_path: Path) -> None:
    project = tmp_path
    kb = project / "knowledge-base"
    kb.mkdir()
    (kb / "patterns.yaml").write_text("schema_version: 1\nentries: []\n", encoding="utf-8")
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "bad.yaml").write_text("schema_version: [", encoding="utf-8")
    (proposal_dir / "good.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")

    report = apply_proposals(project, "squad-001")

    assert report.accepted_count == 1
    assert report.rejected_count == 1
    assert (project / "runs" / "squad-001" / "kb-apply-report.yaml").exists()


def test_apply_duplicate_operation_is_skipped(tmp_path: Path) -> None:
    project = tmp_path
    kb = project / "knowledge-base"
    kb.mkdir()
    (kb / "patterns.yaml").write_text(
        "schema_version: 1\nentries:\n"
        "  - operation_id: squad-001/kb-prop-0001\n"
        "    run_id: squad-001\n"
        "    source: speckit-echelon-mirror\n"
        "    created_at: 2026-07-17T12:00:00Z\n"
        "    confidence: 0.8\n"
        "    project_fingerprint: a1b2c3d4e5f6\n"
        "    scope: local_only\n",
        encoding="utf-8",
    )
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "kb-prop-0001.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")

    report = apply_proposals(project, "squad-001")

    assert report.accepted_count == 0
    assert report.skipped_duplicate_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_kb_proposals.py -q
```

Expected: FAIL with `ImportError` or missing `apply_proposals`.

- [ ] **Step 3: Implement apply/report support**

Extend `src/echelon/kb_proposals.py` with:

```python
import hashlib
from datetime import datetime, timezone


LIST_TARGET_ENTRY_KEYS = {
    "knowledge-base/sage-decisions.yaml": "entries",
    "knowledge-base/patterns.yaml": "entries",
    "knowledge-base/pitfalls.yaml": "entries",
}


@dataclass(frozen=True)
class ProposalApplyOutcome:
    proposal_id: str
    operation_id: str | None
    proposal_type: str | None
    outcome: str
    targets: list[str]
    reason: str | None = None


@dataclass(frozen=True)
class KBApplyReport:
    run_id: str
    status: str
    outcomes: list[ProposalApplyOutcome]
    report_path: Path

    @property
    def accepted_count(self) -> int:
        return sum(1 for item in self.outcomes if item.outcome == "accepted")

    @property
    def rejected_count(self) -> int:
        return sum(1 for item in self.outcomes if item.outcome == "rejected")

    @property
    def skipped_duplicate_count(self) -> int:
        return sum(1 for item in self.outcomes if item.outcome == "skipped_duplicate")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "status": self.status,
            "proposal_count": len(self.outcomes),
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "skipped_duplicate_count": self.skipped_duplicate_count,
            "outcomes": [item.__dict__ for item in self.outcomes],
        }


def apply_proposals(project_root: Path, run_id: str) -> KBApplyReport:
    import yaml

    proposal_dir = project_root / "runs" / run_id / "kb-proposals"
    report_path = project_root / "runs" / run_id / "kb-apply-report.yaml"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    outcomes: list[ProposalApplyOutcome] = []

    for loaded in load_proposals(proposal_dir, expected_run_id=run_id):
        data = loaded.data or {}
        proposal_id = str(data.get("proposal_id") or loaded.path.name)
        proposal_type = data.get("proposal_type") if isinstance(data.get("proposal_type"), str) else None
        targets = data.get("targets") if isinstance(data.get("targets"), list) else []
        if not loaded.validation.ok:
            outcomes.append(
                ProposalApplyOutcome(
                    proposal_id=proposal_id,
                    operation_id=loaded.validation.operation_id,
                    proposal_type=proposal_type,
                    outcome="rejected",
                    targets=[str(target) for target in targets],
                    reason="; ".join(f"{i.path}: {i.message}" for i in loaded.validation.issues),
                )
            )
            continue
        if proposal_type in {"calibration_observation", "internalization_observation"}:
            outcomes.append(
                ProposalApplyOutcome(
                    proposal_id=proposal_id,
                    operation_id=loaded.validation.operation_id,
                    proposal_type=proposal_type,
                    outcome="needs_review",
                    targets=[str(target) for target in targets],
                    reason="aggregate target applier not implemented in first slice",
                )
            )
            continue
        outcome = _apply_list_proposal(project_root, data, loaded.validation.operation_id)
        outcomes.append(outcome)

    status = "applied" if any(item.outcome == "accepted" for item in outcomes) else "degraded"
    report = KBApplyReport(run_id=run_id, status=status, outcomes=outcomes, report_path=report_path)
    report_path.write_text(yaml.safe_dump(report.to_dict(), sort_keys=False), encoding="utf-8")
    return report


def _apply_list_proposal(
    project_root: Path,
    data: dict[str, Any],
    operation_id: str | None,
) -> ProposalApplyOutcome:
    import yaml

    targets = [str(target) for target in data.get("targets", [])]
    target = targets[0]
    target_path = project_root / target
    proposal_id = str(data["proposal_id"])
    proposal_type = str(data["proposal_type"])
    if not target_path.exists():
        return ProposalApplyOutcome(proposal_id, operation_id, proposal_type, "rejected", targets, "target file missing")

    document = yaml.safe_load(target_path.read_text(encoding="utf-8")) or {}
    entries_key = LIST_TARGET_ENTRY_KEYS[target]
    entries = document.setdefault(entries_key, [])
    if any(isinstance(entry, dict) and entry.get("operation_id") == operation_id for entry in entries):
        return ProposalApplyOutcome(proposal_id, operation_id, proposal_type, "skipped_duplicate", targets)

    entry = _canonical_entry(data, operation_id)
    entries.append(entry)
    target_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return ProposalApplyOutcome(proposal_id, operation_id, proposal_type, "accepted", targets)


def _canonical_entry(data: dict[str, Any], operation_id: str | None) -> dict[str, Any]:
    payload = dict(data["payload"])
    if payload.get("project_fingerprint") == "auto":
        payload["project_fingerprint"] = _project_fingerprint()
    entry = {
        "operation_id": operation_id,
        "run_id": data["run_id"],
        "source": data["agent"],
        "created_at": data["created_at"],
    }
    if "confidence" in data:
        entry["confidence"] = data["confidence"]
    entry.update(payload)
    return entry


def _project_fingerprint() -> str:
    raw = str(Path.cwd()).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_kb_proposals.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/kb_proposals.py tests/unit/test_kb_proposals.py
git commit -m "feat: apply phase a kb list proposals"
```

---

### Task 3: Typer CLI Commands

**Files:**
- Modify: `src/echelon/cli_app.py`
- Create: `tests/integration/test_kb_proposals_cli.py`

**Interfaces:**
- Consumes: `load_proposals(...)`, `apply_proposals(...)`
- Produces: `echelon kb validate --run-id squad-001`
- Produces: `echelon kb apply --run-id squad-001`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/integration/test_kb_proposals_cli.py`:

```python
"""Integration tests for `echelon kb` CLI commands."""

from __future__ import annotations

from typer.testing import CliRunner

from echelon.cli_app import app


runner = CliRunner()


def test_kb_validate_reports_missing_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["kb", "validate", "--run-id", "squad-001"])

    assert result.exit_code == 0
    assert "proposals: 0" in result.stdout
    assert "status: degraded" in result.stdout


def test_kb_apply_writes_report_for_empty_run(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["kb", "apply", "--run-id", "squad-001"])

    assert result.exit_code == 0
    assert (tmp_path / "runs" / "squad-001" / "kb-apply-report.yaml").exists()
    assert "kb_apply_status: degraded" in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src pytest tests/integration/test_kb_proposals_cli.py -q
```

Expected: FAIL because `kb` is not registered.

- [ ] **Step 3: Add Typer app and commands**

Modify `src/echelon/cli_app.py` near the other top-level Typer apps:

```python
kb_app = typer.Typer(
    add_completion=False,
    help="Validate and apply Phase A knowledge-base proposals.",
    no_args_is_help=True,
)
app.add_typer(kb_app, name="kb")
```

Add command functions:

```python
@kb_app.command("validate")
def kb_validate(
    run_id: str = typer.Option(..., "--run-id", help="Phase A run id below runs/."),
) -> None:
    """Validate Phase A KB proposal artifacts without mutating canonical KB."""
    from echelon.kb_proposals import load_proposals

    proposal_dir = Path.cwd() / "runs" / run_id / "kb-proposals"
    loaded = load_proposals(proposal_dir, expected_run_id=run_id)
    invalid = [item for item in loaded if not item.validation.ok]
    status = "valid" if loaded and not invalid else "degraded"
    typer.echo(f"kb_validation_status: {status}")
    typer.echo(f"proposals: {len(loaded)}")
    typer.echo(f"invalid: {len(invalid)}")


@kb_app.command("apply")
def kb_apply(
    run_id: str = typer.Option(..., "--run-id", help="Phase A run id below runs/."),
) -> None:
    """Apply valid Phase A KB proposal artifacts without blocking the run."""
    from echelon.kb_proposals import apply_proposals

    report = apply_proposals(Path.cwd(), run_id)
    typer.echo(f"kb_apply_status: {report.status}")
    typer.echo(f"report: {report.report_path}")
    typer.echo(f"accepted: {report.accepted_count}")
    typer.echo(f"rejected: {report.rejected_count}")
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
PYTHONPATH=src pytest tests/integration/test_kb_proposals_cli.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Run existing KB tests**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_kb_schema_validator.py tests/unit/test_kb_proposals.py tests/integration/test_kb_proposals_cli.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/echelon/cli_app.py tests/integration/test_kb_proposals_cli.py
git commit -m "feat: add kb proposal cli commands"
```

---

### Task 4: Proposal Templates

**Files:**
- Create: `extension/templates/kb-proposals/sage-decision-proposal-template.yaml`
- Create: `extension/templates/kb-proposals/pattern-proposal-template.yaml`
- Create: `extension/templates/kb-proposals/pitfall-proposal-template.yaml`
- Create: `extension/templates/kb-proposals/calibration-observation-proposal-template.yaml`
- Create: `extension/templates/kb-proposals/internalization-observation-proposal-template.yaml`
- Create: `tests/unit/test_kb_proposal_templates.py`

**Interfaces:**
- Consumes: `validate_proposal_document(...)`
- Produces: parseable template files whose placeholder-free example values validate.

- [ ] **Step 1: Write failing template test**

Create `tests/unit/test_kb_proposal_templates.py`:

```python
"""Contract tests for KB proposal templates."""

from __future__ import annotations

from pathlib import Path

import yaml

from echelon.kb_proposals import validate_proposal_document


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates" / "kb-proposals"


def test_kb_proposal_templates_parse_and_validate() -> None:
    templates = sorted(TEMPLATE_DIR.glob("*.yaml"))
    assert {path.name for path in templates} == {
        "calibration-observation-proposal-template.yaml",
        "internalization-observation-proposal-template.yaml",
        "pattern-proposal-template.yaml",
        "pitfall-proposal-template.yaml",
        "sage-decision-proposal-template.yaml",
    }
    for path in templates:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        result = validate_proposal_document(path.name, data, expected_run_id="squad-template")
        assert result.ok, (path.name, result.issues)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_kb_proposal_templates.py -q
```

Expected: FAIL because the template directory does not exist.

- [ ] **Step 3: Add templates**

Create `extension/templates/kb-proposals/pattern-proposal-template.yaml`:

```yaml
schema_version: 1
proposal_id: kb-prop-pattern-template
proposal_type: pattern
run_id: squad-template
agent: speckit-echelon-mirror
created_at: 2026-07-17T12:00:00Z
targets:
  - knowledge-base/patterns.yaml
confidence: 0.72
source_artifacts:
  - runs/squad-template/reasoning-journal.jsonl
evidence_refs:
  - artifact: runs/squad-template/reasoning-journal.jsonl
    locator: RJ-template
    claim: Pattern was supported by a completed Phase A review.
payload:
  name: Architecture constraint before estimates
  domain: planning
  evidence_grade: C
  validated_by_feedback: false
  description: Apply explicit architecture constraints before ASSESS estimates.
  tags: [planning, calibration]
  status: active
  project_fingerprint: auto
  scope: local_only
```

Create `extension/templates/kb-proposals/sage-decision-proposal-template.yaml`:

```yaml
schema_version: 1
proposal_id: kb-prop-sage-template
proposal_type: sage_decision
run_id: squad-template
agent: speckit-echelon-sage
created_at: 2026-07-17T12:00:00Z
targets:
  - knowledge-base/sage-decisions.yaml
confidence: 0.78
source_artifacts:
  - runs/squad-template/reasoning-journal.jsonl
evidence_refs:
  - artifact: runs/squad-template/reasoning-journal.jsonl
    locator: RJ-template
    claim: Decision resolved a Phase A challenge.
payload:
  artifact: spec.md
  challenge_type: ambiguity
  challenge_summary: Scope boundary required an explicit decision.
  outcome: Chose the narrower scope supported by current evidence.
  resolution: Record assumptions and defer expansion to change control.
```

Create `extension/templates/kb-proposals/pitfall-proposal-template.yaml`:

```yaml
schema_version: 1
proposal_id: kb-prop-pitfall-template
proposal_type: pitfall
run_id: squad-template
agent: speckit-echelon-mirror
created_at: 2026-07-17T12:00:00Z
targets:
  - knowledge-base/pitfalls.yaml
confidence: 0.7
source_artifacts:
  - runs/squad-template/reasoning-journal.jsonl
evidence_refs:
  - artifact: runs/squad-template/reasoning-journal.jsonl
    locator: RJ-template
    claim: Pitfall was observed during Phase A review.
payload:
  name: Hidden dependency in acceptance criteria
  domain: planning
  evidence_grade: C
  validated_by_feedback: false
  trigger: Acceptance criteria refer to behavior outside the chosen target.
  impact: Delivery may start with unresolved implementation ownership.
  avoidance: Resolve target ownership before task generation.
  tags: [planning, ownership]
  status: active
  project_fingerprint: auto
  scope: local_only
```

Create `extension/templates/kb-proposals/calibration-observation-proposal-template.yaml`:

```yaml
schema_version: 1
proposal_id: kb-prop-calibration-template
proposal_type: calibration_observation
run_id: squad-template
agent: speckit-echelon-scorekeeper
created_at: 2026-07-17T12:00:00Z
targets:
  - knowledge-base/calibration.yaml
confidence: 0.65
source_artifacts:
  - runs/squad-template/reasoning-journal.jsonl
evidence_refs:
  - artifact: runs/squad-template/reasoning-journal.jsonl
    locator: RJ-template
    claim: Estimate quality should be reviewed for later calibration.
payload:
  domain: planning
  observation_kind: estimate_quality
  estimate: medium
  observed_signal: Phase A surfaced uncertainty after initial decomposition.
  recommended_review: Compare final delivery effort against Phase A confidence.
```

Create `extension/templates/kb-proposals/internalization-observation-proposal-template.yaml`:

```yaml
schema_version: 1
proposal_id: kb-prop-internalization-template
proposal_type: internalization_observation
run_id: squad-template
agent: speckit-echelon-internalizer
created_at: 2026-07-17T12:00:00Z
targets:
  - knowledge-base/internalization.yaml
confidence: 0.68
source_artifacts:
  - runs/squad-template/reasoning-journal.jsonl
evidence_refs:
  - artifact: runs/squad-template/reasoning-journal.jsonl
    locator: RJ-template
    claim: Internalization health should be reviewed after Phase A.
payload:
  subject_agent: speckit-echelon-mirror
  agent_tier: stable
  metrics:
    artifact_coverage: 0.8
    reuse_specificity: 0.7
  gate_verdict: review
  computation_health: nominal
```

- [ ] **Step 4: Run template tests**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_kb_proposal_templates.py -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add extension/templates/kb-proposals tests/unit/test_kb_proposal_templates.py
git commit -m "feat: add kb proposal templates"
```

---

### Task 5: Phase A Prompt and Workflow Contract Updates

**Files:**
- Modify: `extension/agents/exploration/sage.md`
- Modify: `extension/agents/learning/mirror.md`
- Modify: `extension/workflow/phases/phase4-document.md`
- Modify: `extension/workflow/definition.yaml`
- Create: `tests/unit/test_kb_proposal_prompt_contracts.py`

**Interfaces:**
- Consumes: templates from Task 4.
- Produces: prompt contracts instructing proposal artifact writes and non-blocking validate/apply.

- [ ] **Step 1: Write failing prompt contract tests**

Create `tests/unit/test_kb_proposal_prompt_contracts.py`:

```python
"""Static prompt contracts for Phase A KB proposal pipeline."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_sage_records_decisions_as_kb_proposals() -> None:
    text = _read("extension/agents/exploration/sage.md")
    assert "sage-decision-proposal-template.yaml" in text
    assert "${SQUAD_DIR}/kb-proposals/" in text
    assert "Do not edit `knowledge-base/sage-decisions.yaml` directly" in text


def test_mirror_records_patterns_and_pitfalls_as_kb_proposals() -> None:
    text = _read("extension/agents/learning/mirror.md")
    assert "pattern-proposal-template.yaml" in text
    assert "pitfall-proposal-template.yaml" in text
    assert "${SQUAD_DIR}/kb-proposals/" in text
    assert "Do not edit `knowledge-base/patterns.yaml` or `knowledge-base/pitfalls.yaml` directly" in text


def test_finalize_runs_kb_apply_non_blocking() -> None:
    text = _read("extension/workflow/phases/phase4-document.md")
    assert "echelon kb validate --run-id" in text
    assert "echelon kb apply --run-id" in text
    assert "does not stop finalization" in text


def test_workflow_allows_kb_status_state_updates() -> None:
    text = _read("extension/workflow/definition.yaml")
    for key in [
        "kb_usage_status",
        "kb_validation_status",
        "kb_apply_status",
        "kb_contract_violations",
        "kb_apply_report",
    ]:
        assert key in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_kb_proposal_prompt_contracts.py -q
```

Expected: FAIL because prompts do not contain the new proposal contract.

- [ ] **Step 3: Update SAGE prompt**

In `extension/agents/exploration/sage.md`, replace direct `sage-decisions.yaml` mutation instructions with:

```markdown
## Decision Recording

After every blocking decision, write a `sage_decision` proposal under
`${SQUAD_DIR}/kb-proposals/` using
`extension/templates/kb-proposals/sage-decision-proposal-template.yaml`.

Do not edit `knowledge-base/sage-decisions.yaml` directly. The deterministic
`echelon kb apply` command is the only Phase A writer to canonical KB files.
If proposal writing fails, report the failure in `echelon_result.journal_entries`
and continue the validation result.
```

- [ ] **Step 4: Update MIRROR prompt**

In `extension/agents/learning/mirror.md`, replace append instructions for patterns/pitfalls with:

```markdown
## Knowledge Base Proposal Outputs

Write one proposal file per durable pattern or pitfall under
`${SQUAD_DIR}/kb-proposals/`.

Use:
- `extension/templates/kb-proposals/pattern-proposal-template.yaml`
- `extension/templates/kb-proposals/pitfall-proposal-template.yaml`

Do not edit `knowledge-base/patterns.yaml` or `knowledge-base/pitfalls.yaml`
directly. If proposal writing fails, record the failure in `echelon_result` and
continue finalization.
```

- [ ] **Step 5: Update FINALIZE workflow**

In `extension/workflow/phases/phase4-document.md`, add this non-blocking KB apply section before final artifact collection:

````markdown
### 12.KB Apply KB Proposals - NON-BLOCKING

Read `RUN_ID` from `runs/.current`, then run:

```bash
echelon kb validate --run-id "${RUN_ID}" || true
echelon kb apply --run-id "${RUN_ID}" || true
```

If either command fails, record `kb_validation_status` or `kb_apply_status` as
`degraded` and continue finalization. KB failures must not stop agent dispatch,
phase transitions, or publication.

If `{spec_dir}` exists and `runs/${RUN_ID}/kb-apply-report.yaml` exists, copy it
to `{spec_dir}/kb/kb-apply-report.yaml`.
````

- [ ] **Step 6: Update workflow allowed state keys**

In `extension/workflow/definition.yaml`, add the KB status keys to Phase A phases that can receive COMMANDER/finalize state updates:

```yaml
allowed_state_updates:
  - kb_usage_status
  - kb_validation_status
  - kb_apply_status
  - kb_contract_violations
  - kb_apply_report
```

Keep the keys as reporting-only. Do not add transitions that depend on them.

- [ ] **Step 7: Run prompt contract tests**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_kb_proposal_prompt_contracts.py -q
```

Expected: `4 passed`.

- [ ] **Step 8: Commit**

```bash
git add extension/agents/exploration/sage.md extension/agents/learning/mirror.md extension/workflow/phases/phase4-document.md extension/workflow/definition.yaml tests/unit/test_kb_proposal_prompt_contracts.py
git commit -m "feat: route phase a kb learning through proposals"
```

---

### Task 6: Spec-Owned KB Report Publication

**Files:**
- Modify: `src/echelon/kb_proposals.py`
- Modify: `extension/scripts/bash/finalize-run.sh`
- Modify: `tests/unit/test_kb_proposals.py`
- Modify: `tests/contract/static_contracts.py` if needed for finalize-run static checks.

**Interfaces:**
- Consumes: `KBApplyReport` from Task 2.
- Produces: `publish_kb_reports(project_root: Path, run_id: str, spec_dir: Path) -> Path | None`

- [ ] **Step 1: Write failing publication test**

Append to `tests/unit/test_kb_proposals.py`:

```python
from echelon.kb_proposals import publish_kb_reports


def test_publish_kb_reports_copies_apply_report_to_spec_dir(tmp_path: Path) -> None:
    project = tmp_path
    run_dir = project / "runs" / "squad-001"
    run_dir.mkdir(parents=True)
    (run_dir / "kb-apply-report.yaml").write_text(
        "schema_version: 1\nrun_id: squad-001\nstatus: degraded\n",
        encoding="utf-8",
    )
    spec_dir = project / "specs" / "001-feature"
    spec_dir.mkdir(parents=True)

    published = publish_kb_reports(project, "squad-001", spec_dir)

    assert published == spec_dir / "kb"
    assert (spec_dir / "kb" / "kb-apply-report.yaml").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_kb_proposals.py::test_publish_kb_reports_copies_apply_report_to_spec_dir -q
```

Expected: FAIL because `publish_kb_reports` does not exist.

- [ ] **Step 3: Implement publication helper**

Add to `src/echelon/kb_proposals.py`:

```python
def publish_kb_reports(project_root: Path, run_id: str, spec_dir: Path) -> Path | None:
    run_dir = project_root / "runs" / run_id
    apply_report = run_dir / "kb-apply-report.yaml"
    usage = run_dir / "kb-usage.yaml"
    if not apply_report.exists() and not usage.exists():
        return None
    out_dir = spec_dir / "kb"
    out_dir.mkdir(parents=True, exist_ok=True)
    if apply_report.exists():
        (out_dir / "kb-apply-report.yaml").write_text(
            apply_report.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    if usage.exists():
        (out_dir / "kb-usage-summary.yaml").write_text(
            usage.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    return out_dir
```

- [ ] **Step 4: Add finalize-run observability**

In `extension/scripts/bash/finalize-run.sh`, after `SPEC_DIR` is defined, add:

```bash
if [ -d "${SPEC_DIR}/kb" ]; then
  echo "[FINALIZE] KB provenance reports detected under ${SPEC_DIR}/kb"
fi
```

No extra `git add` is required because `git add "${SPEC_DIR}/"` already stages the directory.

- [ ] **Step 5: Run tests**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_kb_proposals.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/echelon/kb_proposals.py extension/scripts/bash/finalize-run.sh tests/unit/test_kb_proposals.py
git commit -m "feat: publish phase a kb reports with specs"
```

---

### Task 7: Verification Sweep

**Files:**
- No new source files expected.

**Interfaces:**
- Consumes all previous tasks.
- Produces a verified branch with focused passing tests.

- [ ] **Step 1: Run focused Python tests**

Run:

```bash
PYTHONPATH=src pytest \
  tests/unit/test_kb_schema_validator.py \
  tests/unit/test_kb_proposals.py \
  tests/unit/test_kb_proposal_templates.py \
  tests/unit/test_kb_proposal_prompt_contracts.py \
  tests/integration/test_kb_proposals_cli.py \
  -q
```

Expected: all tests pass.

- [ ] **Step 2: Run existing shell KB tests**

Run:

```bash
bash tests/unit/test-kb-write.sh
bash tests/integration/test-pending-merge.sh
```

Expected: both scripts exit 0.

- [ ] **Step 3: Run CLI smoke checks**

Run:

```bash
PYTHONPATH=src python - <<'PY'
from echelon.cli_app import run
run(["kb", "validate", "--run-id", "smoke-empty"])
PY
PYTHONPATH=src python - <<'PY'
from echelon.cli_app import run
run(["kb", "apply", "--run-id", "smoke-empty"])
PY
```

Expected: both commands exit 0 and report degraded/non-blocking status for missing proposals.

- [ ] **Step 4: Inspect git diff**

Run:

```bash
git diff --stat
git status --short
```

Expected: only intentional source, template, test, and prompt files changed; no runtime `runs/` files tracked.

- [ ] **Step 5: Commit any final verification fixes**

If Step 1-4 required small fixes, rerun the affected task's focused test and
commit only the files changed by that fix using that task's commit message
pattern. If no fixes were needed, do not create an empty commit.
