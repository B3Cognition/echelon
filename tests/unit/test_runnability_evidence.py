from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.runnability_evidence import (
    OUTPUT_TAIL_BYTES,
    RunnabilityEvidenceRef,
    RunnabilityStage,
    validate_runnability_report,
    write_runnability_report,
)


def _write_report(
    root: Path,
    *,
    sequence: int = 1,
    status: str = "runnable",
    candidate_commit: str = "a" * 40,
    candidate_fingerprint: str = "product-1",
    contract_hash: str = "contract-1",
    stack_hash: str = "stack-1",
    stdout: bytes = b"checkpoint persisted\n",
    sensitive_environment: dict[str, str] | None = None,
) -> RunnabilityEvidenceRef:
    return write_runnability_report(
        evidence_dir=root,
        spec_id="003-browser-game",
        target_id="browser-game",
        strategy_id="default",
        build_id="build-1",
        candidate_commit=candidate_commit,
        candidate_fingerprint=candidate_fingerprint,
        contract_hash=contract_hash,
        stack_hash=stack_hash,
        status=status,
        failure_class="" if status == "runnable" else "primary_journey_failed",
        summary="The real checkpoint journey passed." if status == "runnable" else "Journey failed.",
        stages=(
            RunnabilityStage(name="install", status="passed", exit_code=0),
            RunnabilityStage(name="provision", status="passed", exit_code=0),
            RunnabilityStage(name="start", status="passed", exit_code=0),
            RunnabilityStage(name="readiness", status="passed", exit_code=0),
            RunnabilityStage(
                name="primary_journey",
                status="passed" if status == "runnable" else "failed",
                exit_code=0 if status == "runnable" else 1,
                stdout=stdout,
            ),
            RunnabilityStage(name="teardown", status="passed", exit_code=0),
        ),
        required_stages=(
            "install",
            "provision",
            "start",
            "readiness",
            "primary_journey",
            "teardown",
        ),
        attempt_sequence=sequence,
        sensitive_environment=sensitive_environment or {},
        user_commands={"start": ("pnpm start:local",), "stop": ("pnpm stop:local",)},
    )


@pytest.mark.unit
def test_passing_report_survives_commit_only_change(tmp_path: Path) -> None:
    ref = _write_report(tmp_path, candidate_commit="a" * 40)

    result = validate_runnability_report(
        ref,
        candidate_commit="b" * 40,
        candidate_fingerprint="product-1",
        contract_hash="contract-1",
        stack_hash="stack-1",
    )

    assert result.valid is True


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("candidate_fingerprint", "product-2"),
        ("contract_hash", "contract-2"),
        ("stack_hash", "stack-2"),
    ],
)
def test_report_rejects_changed_authoritative_hash(
    tmp_path: Path,
    field: str,
    changed: str,
) -> None:
    ref = _write_report(tmp_path)
    inputs = {
        "candidate_commit": "a" * 40,
        "candidate_fingerprint": "product-1",
        "contract_hash": "contract-1",
        "stack_hash": "stack-1",
    }
    inputs[field] = changed

    result = validate_runnability_report(ref, **inputs)

    assert result.valid is False
    assert field in result.reason


@pytest.mark.unit
def test_report_redacts_generated_credentials_and_bounds_output(tmp_path: Path) -> None:
    secret = "generated-session-token-value"
    ref = _write_report(
        tmp_path,
        stdout=(secret + "\n" + "x" * 100_000).encode(),
        sensitive_environment={"ECHELON_SESSION_TOKEN": secret},
    )
    payload = json.loads(ref.path.read_text(encoding="utf-8"))

    assert secret not in json.dumps(payload)
    assert len(payload["stages"][4]["stdout_tail"].encode()) <= OUTPUT_TAIL_BYTES


@pytest.mark.unit
def test_runnable_report_requires_every_required_stage_to_pass(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="required stage readiness did not pass"):
        write_runnability_report(
            evidence_dir=tmp_path,
            spec_id="003",
            target_id="game",
            strategy_id="default",
            build_id="build-1",
            candidate_commit="a" * 40,
            candidate_fingerprint="product-1",
            contract_hash="contract-1",
            stack_hash="stack-1",
            status="runnable",
            failure_class="",
            summary="",
            stages=(RunnabilityStage(name="readiness", status="failed", exit_code=1),),
            required_stages=("readiness",),
            attempt_sequence=1,
            sensitive_environment={},
            user_commands={},
        )


@pytest.mark.unit
def test_failed_report_markdown_contains_actionable_context(tmp_path: Path) -> None:
    ref = _write_report(tmp_path, status="not_runnable")
    markdown = ref.markdown_path.read_text(encoding="utf-8")

    assert "primary_journey_failed" in markdown
    assert "primary_journey" in markdown
    assert ".echelon/runnability.yml" in markdown
    assert "Repair the candidate" in markdown


@pytest.mark.unit
def test_report_preserves_separate_unverified_local_journey(tmp_path: Path) -> None:
    ref = write_runnability_report(
        evidence_dir=tmp_path,
        spec_id="003",
        target_id="game",
        strategy_id="default",
        build_id="build-1",
        candidate_commit="a" * 40,
        candidate_fingerprint="product-1",
        contract_hash="contract-1",
        stack_hash="stack-1",
        status="runnable",
        failure_class="",
        summary="Sandbox journey passed.",
        stages=(RunnabilityStage(name="primary_journey", status="passed"),),
        required_stages=("primary_journey",),
        attempt_sequence=1,
        sensitive_environment={},
        user_commands={"start": ("pnpm start:sandbox",)},
        local_journey_status="unverified",
        local_journey_reason="No compatible local runner executed these commands.",
        local_user_commands={
            "provision": ("docker compose up -d postgres",),
            "cleanup": ("docker compose down -v",),
        },
    )
    payload = json.loads(ref.path.read_text(encoding="utf-8"))
    markdown = ref.markdown_path.read_text(encoding="utf-8")

    assert payload["status"] == "runnable"
    assert payload["local_journey"] == {
        "status": "unverified",
        "reason": "No compatible local runner executed these commands.",
        "commands": {
            "cleanup": ["docker compose down -v"],
            "provision": ["docker compose up -d postgres"],
        },
    }
    assert "Local journey: `unverified`" in markdown
    assert "docker compose up -d postgres" in markdown


@pytest.mark.unit
def test_tampered_report_is_rejected(tmp_path: Path) -> None:
    ref = _write_report(tmp_path)
    payload = json.loads(ref.path.read_text(encoding="utf-8"))
    payload["status"] = "not_runnable"
    ref.path.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_runnability_report(
        ref,
        candidate_commit="a" * 40,
        candidate_fingerprint="product-1",
        contract_hash="contract-1",
        stack_hash="stack-1",
    )

    assert result.valid is False
    assert "digest" in result.reason


@pytest.mark.unit
def test_latest_human_report_cannot_follow_symlink_outside_evidence_root(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("owner content\n", encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "report.md").symlink_to(outside)

    with pytest.raises(OSError, match="symlink"):
        _write_report(evidence)

    assert outside.read_text(encoding="utf-8") == "owner content\n"
