from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from harness.provider_dispatch_finalizer import (
    ProviderDispatchContext,
    ProviderDispatchFailure,
    ProviderDispatchFinalizer,
)
from harness.provider_output_publication import (
    compile_provider_artifact_contract,
    resolve_provider_artifact_contract,
)
from harness.squad_provider import SquadAgentResult


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _result(
    verdict: str = "PASS",
    *,
    output_files: list[str] | None = None,
    extra: dict[str, object] | None = None,
) -> SquadAgentResult:
    payload: dict[str, object] = {
        "verdict": verdict,
        "state_updates": {},
        "journal_entries": [],
        "output_files": output_files or [],
    }
    payload.update(extra or {})
    return SquadAgentResult(
        exit_code=0,
        echelon_result=payload,
        raw_output="validated output",
        duration_ms=1,
        timed_out=False,
        provider_name="codex",
        model_name="gpt-test",
        provider_attempts=(
            {
                "attempt_id": "attempt-primary",
                "kind": "primary",
                "provider": "codex",
                "model": "gpt-test",
                "started_at": "2026-09-26T10:00:00Z",
                "ended_at": "2026-09-26T10:00:01Z",
                "outcome": "OK",
                "response_sha256": "a" * 64,
            },
        ),
    )


def _context(
    tmp_path: Path,
    *,
    artifacts: tuple[tuple[str, str, str], ...] = (
        ("issues.md", "file", "required"),
    ),
    mode: str = "publish",
    allow_shadow_recovery: bool = False,
    occurrence_id: str = "why2:initial:1",
) -> ProviderDispatchContext:
    raw_artifacts = [
        {
            "root": "active_spec",
            "path": path,
            "kind": kind,
            "requirement": requirement,
        }
        for path, kind, requirement in artifacts
    ]
    contract = compile_provider_artifact_contract(
        {
            "mode": mode,
            "artifacts": raw_artifacts,
            "allow_shadow_recovery": allow_shadow_recovery,
        },
        assignment_id="phase1-why2",
    )
    resolved = resolve_provider_artifact_contract(
        contract,
        assignment_id="phase1-why2",
        roots={
            "active_spec": tmp_path / "spec",
            "project": tmp_path,
            "squad": tmp_path / "squad",
        },
    )
    return ProviderDispatchContext(
        phase_id="phase1-why2",
        assignment_id="phase1-why2",
        occurrence_id=occurrence_id,
        state_revision=7,
        contract=resolved,
        prompt_sha256=_sha("prompt"),
        prompt_metadata_sha256=_sha("metadata"),
    )


def _dispatch(
    context: ProviderDispatchContext,
    execute,
    *,
    classify=lambda result: "published",
    semantic_validator=None,
):
    return ProviderDispatchFinalizer().dispatch(
        context,
        execute=execute,
        validate_result=lambda result: result,
        classify_outcome=classify,
        semantic_validator=semantic_validator,
    )


def test_finalizer_accepts_identical_content_with_new_identity(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    target = tmp_path / "spec/issues.md"
    target.parent.mkdir()
    target.write_text("same\n", encoding="utf-8")

    def execute(_metadata):
        replacement = target.with_suffix(".tmp")
        replacement.write_text("same\n", encoding="utf-8")
        os.replace(replacement, target)
        return _result(output_files=[str(target)])

    finalized = _dispatch(context, execute)

    assert finalized.receipt.outcome == "published"
    assert finalized.receipt.outputs[0]["evidence_kind"] == "replaced"
    assert finalized.receipt.outputs[0]["preimage_identity_sha256"] != (
        finalized.receipt.outputs[0]["postimage_identity_sha256"]
    )


def test_domain_blocked_without_artifact_preserves_policy_outcome(
    tmp_path: Path,
) -> None:
    finalized = _dispatch(
        _context(tmp_path),
        lambda _metadata: _result("BLOCKED"),
        classify=lambda _result: "domain_blocked",
    )

    assert finalized.result.verdict == "BLOCKED"
    assert finalized.receipt.outcome == "domain_blocked"
    assert finalized.receipt.outputs == ()


@pytest.mark.parametrize("behavior", ["missing", "stale"])
def test_published_required_output_needs_current_dispatch_evidence(
    tmp_path: Path,
    behavior: str,
) -> None:
    context = _context(tmp_path)
    target = tmp_path / "spec/issues.md"
    target.parent.mkdir()
    if behavior == "stale":
        target.write_text("old\n", encoding="utf-8")

    with pytest.raises(ProviderDispatchFailure, match=behavior):
        _dispatch(
            context,
            lambda _metadata: _result(output_files=[str(target)]),
        )


def test_optional_omission_is_allowed_but_unclaimed_mutation_is_not(
    tmp_path: Path,
) -> None:
    context = _context(
        tmp_path,
        artifacts=(("notes.md", "file", "optional"),),
    )
    omitted = _dispatch(context, lambda _metadata: _result())
    assert omitted.receipt.outputs == ()

    target = tmp_path / "spec/notes.md"

    def mutate_without_claim(_metadata):
        target.parent.mkdir(exist_ok=True)
        target.write_text("new\n", encoding="utf-8")
        return _result()

    with pytest.raises(ProviderDispatchFailure, match="unclaimed"):
        _dispatch(context, mutate_without_claim)


def test_false_or_out_of_contract_claim_is_rejected(tmp_path: Path) -> None:
    context = _context(tmp_path)
    target = tmp_path / "spec/issues.md"

    def execute(_metadata):
        target.parent.mkdir()
        target.write_text("new\n", encoding="utf-8")
        return _result(output_files=[str(tmp_path / "spec/other.md")])

    with pytest.raises(ProviderDispatchFailure, match="outside contract"):
        _dispatch(context, execute)


def test_exact_workspace_relative_file_claim_publishes_current_artifact(tmp_path: Path) -> None:
    context = _context(tmp_path)
    target = tmp_path / "spec/issues.md"

    def execute(_metadata):
        target.parent.mkdir()
        target.write_text("current\n", encoding="utf-8")
        return _result(output_files=["spec/issues.md"])

    finalized = _dispatch(context, execute)

    assert finalized.receipt.outcome == "published"
    assert [item["path"] for item in finalized.receipt.outputs] == ["issues.md"]


def test_exact_workspace_relative_directory_member_claim_publishes_leaf(tmp_path: Path) -> None:
    context = _context(tmp_path, artifacts=(("reports", "directory", "required"),))
    target = tmp_path / "spec/reports/result.md"

    def execute(_metadata):
        target.parent.mkdir(parents=True)
        target.write_text("current\n", encoding="utf-8")
        return _result(output_files=["spec/reports/result.md"])

    finalized = _dispatch(context, execute)

    assert finalized.receipt.outcome == "published"
    assert [item["path"] for item in finalized.receipt.outputs[0]["members"]] == ["result.md"]


@pytest.mark.parametrize("claim", [
    "other/spec/issues.md", "spec/../spec/issues.md", "spec/issues.md/extra",
])
def test_workspace_relative_lookalike_claim_does_not_publish(tmp_path: Path, claim: str) -> None:
    context = _context(tmp_path)
    target = tmp_path / "spec/issues.md"

    def execute(_metadata):
        target.parent.mkdir()
        target.write_text("current\n", encoding="utf-8")
        return _result(output_files=[claim])

    with pytest.raises(ProviderDispatchFailure, match="outside contract"):
        _dispatch(context, execute)


def test_provider_forged_receipt_fields_are_removed(tmp_path: Path) -> None:
    context = _context(tmp_path, mode="result_only", artifacts=())
    finalized = _dispatch(
        context,
        lambda _metadata: _result(
            extra={
                "provider_output_receipts": [{"forged": True}],
                "provider_dispatch_receipt": {"forged": True},
            }
        ),
    )

    assert "provider_output_receipts" not in finalized.result.echelon_result
    assert "provider_dispatch_receipt" not in finalized.result.echelon_result


@pytest.mark.parametrize("unsafe_kind", ["file_for_directory", "symlink", "special"])
def test_finalizer_rejects_wrong_or_unsafe_artifact_kind(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    context = _context(
        tmp_path,
        artifacts=(("reports", "directory", "required"),),
    )
    target = tmp_path / "spec/reports"

    def execute(_metadata):
        target.parent.mkdir()
        if unsafe_kind == "file_for_directory":
            target.write_text("wrong\n", encoding="utf-8")
        elif unsafe_kind == "symlink":
            target.symlink_to(tmp_path / "elsewhere", target_is_directory=True)
        else:
            target.mkdir()
            os.mkfifo(target / "pipe")
        return _result(output_files=[str(target / "report.md")])

    with pytest.raises(ProviderDispatchFailure):
        _dispatch(context, execute)


def test_directory_requires_changed_claimed_leaves_and_sorts_manifest(
    tmp_path: Path,
) -> None:
    context = _context(
        tmp_path,
        artifacts=(("reports", "directory", "required"),),
    )
    target = tmp_path / "spec/reports"

    def execute(_metadata):
        target.mkdir(parents=True)
        (target / "z.md").write_text("z\n", encoding="utf-8")
        (target / "a.md").write_text("a\n", encoding="utf-8")
        return _result(
            output_files=[str(target / "z.md"), str(target / "a.md")]
        )

    finalized = _dispatch(context, execute)
    assert [member["path"] for member in finalized.receipt.outputs[0]["members"]] == [
        "a.md",
        "z.md",
    ]


@pytest.mark.parametrize("behavior", ["empty", "metadata_touch"])
def test_directory_metadata_without_current_leaf_is_not_publication(
    tmp_path: Path,
    behavior: str,
) -> None:
    context = _context(
        tmp_path,
        artifacts=(("reports", "directory", "required"),),
    )
    target = tmp_path / "spec/reports"
    if behavior == "metadata_touch":
        target.mkdir(parents=True)
        (target / "old.md").write_text("old\n", encoding="utf-8")

    def execute(_metadata):
        target.mkdir(parents=True, exist_ok=True)
        os.utime(target, None)
        return _result(output_files=[str(target)])

    with pytest.raises(ProviderDispatchFailure, match="directory"):
        _dispatch(context, execute)


def test_retry_baseline_requires_rewrite_after_invalid_attempt(tmp_path: Path) -> None:
    context = _context(tmp_path)
    target = tmp_path / "spec/issues.md"

    def invalid_write(_metadata):
        target.parent.mkdir()
        target.write_text("unsealed\n", encoding="utf-8")
        return _result("FAIL", output_files=[str(target)])

    invalid = _dispatch(
        context,
        invalid_write,
        classify=lambda _result: "invalid",
    )
    assert invalid.receipt.outcome == "invalid"
    assert invalid.receipt.outputs == ()

    retry = _context(tmp_path, occurrence_id="why2:retry:2")
    with pytest.raises(ProviderDispatchFailure, match="stale"):
        _dispatch(retry, lambda _metadata: _result(output_files=[str(target)]))


def test_dispatch_rejects_cross_assignment_sibling_mutation(tmp_path: Path) -> None:
    context = _context(tmp_path)
    target = tmp_path / "spec/issues.md"
    foreign = tmp_path / "spec/quality-gates.md"

    def execute(metadata):
        assert metadata["tool_write_paths"] == [str(target.resolve())]
        target.parent.mkdir()
        target.write_text("owned\n", encoding="utf-8")
        foreign.write_text("foreign\n", encoding="utf-8")
        return _result(output_files=[str(target)])

    with pytest.raises(ProviderDispatchFailure, match="outside write scope"):
        _dispatch(context, execute)


def test_squad_guard_ignores_only_harness_telemetry_writes(
    tmp_path: Path,
) -> None:
    squad = tmp_path / "squad"
    contract = compile_provider_artifact_contract(
        {
            "mode": "publish",
            "artifacts": [
                {
                    "root": "squad",
                    "path": "constitution.draft.md",
                    "kind": "file",
                    "requirement": "required",
                }
            ],
        },
        assignment_id="phase1-constitution",
    )
    resolved = resolve_provider_artifact_contract(
        contract,
        assignment_id="phase1-constitution",
        roots={"squad": squad},
    )
    context = ProviderDispatchContext(
        phase_id="phase1-constitution",
        assignment_id="phase1-constitution",
        occurrence_id="ordinary",
        state_revision=7,
        contract=resolved,
        prompt_sha256=_sha("prompt"),
        prompt_metadata_sha256=_sha("metadata"),
    )
    target = squad / "constitution.draft.md"

    def telemetry_and_output(_metadata):
        target.parent.mkdir(parents=True)
        target.write_text("# Constitution\n", encoding="utf-8")
        (squad / "telemetry").mkdir()
        (squad / "telemetry" / "spans.jsonl").write_text(
            "{}\n", encoding="utf-8"
        )
        (squad / "telemetry" / "events.jsonl").write_text(
            "{}\n", encoding="utf-8"
        )
        (squad / "telemetry" / "phase-timing.lock").write_text(
            "", encoding="utf-8"
        )
        return _result(output_files=[str(target)])

    finalized = _dispatch(context, telemetry_and_output)
    assert finalized.receipt.outputs[0]["path"] == "constitution.draft.md"

    retry_context = ProviderDispatchContext(
        **{
            **context.__dict__,
            "occurrence_id": "ordinary/retry",
        }
    )

    def mutate_controller_state(_metadata):
        replacement = target.with_suffix(".tmp")
        replacement.write_text("# Constitution v2\n", encoding="utf-8")
        os.replace(replacement, target)
        (squad / "state.json").write_text("{}\n", encoding="utf-8")
        return _result(output_files=[str(target)])

    with pytest.raises(ProviderDispatchFailure, match="outside write scope"):
        _dispatch(retry_context, mutate_controller_state)

    for attempt, relative in enumerate(
        (
            "telemetry/rogue.json",
            "events.jsonl",
            "phase-timing.lock",
        ),
        start=2,
    ):
        foreign_context = ProviderDispatchContext(
            **{
                **context.__dict__,
                "occurrence_id": f"ordinary/retry/{attempt}",
            }
        )

        def mutate_lookalike(_metadata, *, path=relative, version=attempt):
            target.write_text(
                f"# Constitution v{version}\n",
                encoding="utf-8",
            )
            foreign = squad / path
            foreign.parent.mkdir(parents=True, exist_ok=True)
            foreign.write_text("provider-owned\n", encoding="utf-8")
            return _result(output_files=[str(target)])

        with pytest.raises(
            ProviderDispatchFailure,
            match="outside write scope",
        ):
            _dispatch(foreign_context, mutate_lookalike)


def test_fresh_shadow_is_promoted_but_stale_shadow_is_rejected(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, allow_shadow_recovery=True)
    shadow = tmp_path / "squad/specs/spec/issues.md"
    shadow.parent.mkdir(parents=True)
    shadow.write_text("stale\n", encoding="utf-8")

    with pytest.raises(ProviderDispatchFailure, match="missing"):
        _dispatch(context, lambda _metadata: _result(output_files=[str(shadow)]))

    def fresh_shadow(_metadata):
        replacement = shadow.with_suffix(".tmp")
        replacement.write_text("fresh\n", encoding="utf-8")
        os.replace(replacement, shadow)
        return _result(output_files=[str(shadow)])

    finalized = _dispatch(context, fresh_shadow)
    assert (tmp_path / "spec/issues.md").read_text(encoding="utf-8") == "fresh\n"
    assert finalized.receipt.outputs[0]["evidence_kind"] == "shadow_promoted"


def test_receipt_binds_prompt_validator_result_and_attempt_chain(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, mode="result_only", artifacts=())

    class Validator:
        semantic_validator_id = "why2.semantic.v3"

        def validate(self, result, receipt):
            assert result.verdict == "PASS"
            assert receipt.prompt_sha256 == _sha("prompt")
            return {"status": "accepted", "receipt_dispatch": receipt.dispatch_id}

    finalized = _dispatch(
        context,
        lambda _metadata: _result(),
        semantic_validator=Validator(),
    )

    receipt = finalized.receipt
    assert receipt.prompt_sha256 == _sha("prompt")
    assert receipt.prompt_metadata_sha256 == _sha("metadata")
    assert receipt.semantic_validator_id == "why2.semantic.v3"
    assert len(receipt.semantic_result_sha256 or "") == 64
    assert len(receipt.provider_attempts_sha256) == 64
    assert len(receipt.validated_result_sha256) == 64
