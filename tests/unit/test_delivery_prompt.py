"""Delivery command loading must resolve one role or fail before execution."""

from pathlib import Path
import json
import subprocess

import pytest
import yaml

from harness.prosaic_prompt_loader import ProsaicCommandArtifact, ProsaicPromptLoader


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Only Prosaic's external process is substituted; loading/rendering is real."""
    command = tmp_path / ".echelon/prosaic/commands/echelon.build.md"
    command.parent.mkdir(parents=True)
    command.write_text(
        "---\nname: echelon.build\nmodel_tier: strong\neffort: high\n---\n"
        "You are MANAGER. Implement {{args}}.\n",
        encoding="utf-8",
    )
    real_run = subprocess.run

    def inspect(argv, **kwargs):
        if argv[:2] != ["prosaic", "inspect"]:
            return real_run(argv, **kwargs)
        assert argv[:2] == ["prosaic", "inspect"]
        assert kwargs["cwd"] == str(tmp_path)
        source = Path(argv[argv.index("--source") + 1])
        content = (source / argv[2]).read_text(encoding="utf-8")
        _, frontmatter, body = content.split("---", 2)
        return subprocess.CompletedProcess(
            argv, 0,
            stdout=json.dumps({
                "id": argv[2], "type": "command",
                "frontmatter": yaml.safe_load(frontmatter), "body": body.strip(),
            }),
            stderr="",
        )

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", inspect)
    return command


def test_delivery_uses_selected_role_and_literal_arguments(bundle: Path, tmp_path: Path):
    from harness.delivery_prompt import resolve_delivery_build_prompt

    arguments = 'spec 001\nKeep `$HOME`, "quotes", and $(literal) as data.'
    prompt = resolve_delivery_build_prompt("echelon build", arguments, tmp_path)

    assert "You are MANAGER." in prompt
    assert "You are COMMANDER" not in prompt
    assert arguments in prompt
    assert "{{args}}" not in prompt


def test_delivery_resolves_companions_before_dispatch(bundle: Path, tmp_path: Path):
    from harness.delivery_prompt import resolve_delivery_build_prompt

    companion = bundle.parent / "appendices/build-inputs.md"
    companion.parent.mkdir()
    companion.write_text("Only implement task T-003.\n", encoding="utf-8")
    bundle.write_text(
        "---\nname: echelon.build\n---\n"
        "You are MANAGER. Read `commands/appendices/build-inputs.md`. {{args}}\n",
        encoding="utf-8",
    )

    prompt = resolve_delivery_build_prompt("echelon build", "spec 001", tmp_path)

    assert "Only implement task T-003." in prompt
    assert "commands/appendices/build-inputs.md" not in prompt


def test_missing_delivery_command_never_falls_back_to_bare_arguments(tmp_path: Path):
    from harness.delivery_prompt import DeliveryPromptError, resolve_delivery_build_prompt

    with pytest.raises(DeliveryPromptError, match="canonical.*echelon.build"):
        resolve_delivery_build_prompt("echelon build", "spec 001", tmp_path)


@pytest.mark.parametrize("command", [
    "", "make build", "echelon review", "echelon alternate", "echelon build --fix",
    "echelon build; echo ignored",
])
def test_unsupported_llm_strategy_command_is_rejected_before_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str,
):
    from harness.delivery_prompt import DeliveryPromptError, resolve_delivery_build_prompt

    def unexpected_inspect(*args, **kwargs):
        pytest.fail("Unsupported commands must be rejected before inspecting a bundle")

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", unexpected_inspect)
    with pytest.raises(DeliveryPromptError, match="Unsupported LLM delivery command"):
        resolve_delivery_build_prompt(command, "spec 001", tmp_path)


@pytest.mark.parametrize("name, body", [
    ("echelon.review", "You are REVIEWER."),
    (None, "You are MANAGER."),
    ("echelon.build", "   \n"),
])
def test_wrong_identity_or_empty_command_cannot_be_dispatched(
    bundle: Path, tmp_path: Path, name: str | None, body: str,
):
    from harness.delivery_prompt import DeliveryPromptError, resolve_delivery_build_prompt

    bundle.write_text(
        f"---\n{yaml.safe_dump({'name': name})}---\n{body}", encoding="utf-8",
    )
    with pytest.raises(DeliveryPromptError):
        resolve_delivery_build_prompt("echelon build", "spec 001", tmp_path)


def test_unresolved_companion_is_a_delivery_setup_error(bundle: Path, tmp_path: Path):
    from harness.delivery_prompt import DeliveryPromptError, resolve_delivery_build_prompt

    bundle.write_text(
        "---\nname: echelon.build\n---\nRead `commands/appendices/missing.md`.\n",
        encoding="utf-8",
    )
    with pytest.raises(DeliveryPromptError, match="unresolved prompt companion"):
        resolve_delivery_build_prompt("echelon build", "spec 001", tmp_path)


def test_malformed_inspect_response_is_a_delivery_setup_error(
    bundle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from harness.delivery_prompt import DeliveryPromptError, resolve_delivery_build_prompt

    monkeypatch.setattr(
        "harness.prosaic_prompt_loader.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "not JSON", ""),
    )
    with pytest.raises(DeliveryPromptError, match="invalid JSON"):
        resolve_delivery_build_prompt("echelon build", "spec 001", tmp_path)


def test_ordinary_command_framing_is_unchanged():
    artifact = ProsaicCommandArtifact({"name": "echelon.review"}, "Review {{args}}.")

    rendered = ProsaicPromptLoader.render_command(artifact, "spec 001")

    assert "You are COMMANDER" in rendered.prompt
    assert "Review spec 001." in rendered.prompt
    assert rendered.frontmatter == {"name": "echelon.review"}


@pytest.mark.parametrize("content", [
    b"---\n- not-a-mapping\n---\nCompanion",
    b"---\nname: [unclosed\n---\nCompanion",
    b"\xff invalid UTF-8",
])
def test_malformed_companion_is_a_delivery_setup_error(
    bundle: Path, tmp_path: Path, content: bytes,
):
    from harness.delivery_prompt import DeliveryPromptError, resolve_delivery_build_prompt

    companion = bundle.parent / "appendices/bad.md"
    companion.parent.mkdir()
    companion.write_bytes(content)
    bundle.write_text(
        "---\nname: echelon.build\n---\nRead `commands/appendices/bad.md`.\n",
        encoding="utf-8",
    )
    with pytest.raises(DeliveryPromptError, match="Cannot load delivery command"):
        resolve_delivery_build_prompt("echelon build", "spec 001", tmp_path)


def test_coordinator_blocks_missing_command_before_build_and_releases_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from harness.run_intent import RunIntent
    from harness.state import StateStore
    from tests.unit.test_coordinator import _make_coordinator

    coordinator = _make_coordinator(tmp_path)
    coordinator._config.llm.enabled = True
    monkeypatch.setattr("harness.coordinator.AICodingCliProvider", lambda config: object())

    class UnexpectedBuild:
        def __init__(self, **kwargs):
            pass

        def run_loop(self, **kwargs):
            pytest.fail("Missing delivery instructions must prevent build execution")

    monkeypatch.setattr("harness.coordinator.RalphController", UnexpectedBuild)
    result = coordinator.start(RunIntent(spec_id="spec-001", max_outer=1, max_inner=1))[0]

    assert result.status == "blocked"
    assert result.termination_reason == "delivery_prompt_invalid"
    assert result.blocked_phase == "implementation"
    store = StateStore(tmp_path / "runs/state", "spec-001", "default")
    persisted = store.read()
    assert persisted["termination_reason"] == "delivery_prompt_invalid"
    assert persisted["blocked_phase"] == "implementation"
    assert "canonical delivery command" in persisted["build_reason"]
    assert persisted["build_status"] == "delivery_prompt_invalid"
    assert not store.lock_file.exists()


def test_coordinator_passes_resolved_role_to_build_execution(
    bundle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from harness.delivery_results import ImplementationResult
    from harness.run_intent import RunIntent
    from tests.unit.test_coordinator import _make_coordinator

    coordinator = _make_coordinator(tmp_path)
    coordinator._config.llm.enabled = True
    monkeypatch.setattr("harness.coordinator.AICodingCliProvider", lambda config: object())
    captured = []

    class BuildBoundary:
        def __init__(self, **kwargs):
            pass

        def run_loop(self, **kwargs):
            captured.append(kwargs["build_prompt"])
            return ImplementationResult("blocked", "fixture_stop", 0, 0, None, 0, None)

    monkeypatch.setattr("harness.coordinator.RalphController", BuildBoundary)
    result = coordinator.start(RunIntent(
        spec_id="spec-001", max_outer=1, max_inner=1, task_description="Repair task T-001",
    ))[0]

    assert result.termination_reason == "fixture_stop"
    assert len(captured) == 1
    assert "You are MANAGER." in captured[0]
    assert "You are COMMANDER" not in captured[0]
    assert "Repair task T-001" in captured[0]


def test_delivery_prompt_reaches_external_executor_through_real_ralph_and_runner(
    bundle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from harness.run_intent import RunIntent
    from tests.unit.test_coordinator import _make_coordinator

    captured = []

    class ExternalExecutor:
        def exec_prompt(self, worktree_path, prompt, *, extra_env=None):
            captured.append(prompt)
            # Stop after observing dispatch; no model or downstream publication.
            Path(extra_env["HARNESS_BUILD_STATUS_FILE"]).write_text(
                json.dumps({"status": "blocked", "reason": "fixture_stop"}),
                encoding="utf-8",
            )
            return 1

    coordinator = _make_coordinator(tmp_path)
    coordinator._config.llm.enabled = True
    coordinator._gitops.create_worktree.return_value = str(tmp_path)
    monkeypatch.setattr("harness.coordinator.AICodingCliProvider", lambda config: ExternalExecutor())
    coordinator.start(RunIntent(
        spec_id="spec-001", max_outer=1, max_inner=1, task_description="Repair task T-001",
    ))

    assert captured
    assert "You are MANAGER." in captured[0]
    assert "You are COMMANDER" not in captured[0]
    assert "Repair task T-001" in captured[0]


@pytest.mark.parametrize("resume_kind", ["finalization", "publication"])
def test_downstream_resume_does_not_resolve_broken_build_resources(
    bundle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resume_kind: str,
):
    from harness.delivery_results import ImplementationResult
    from harness.run_intent import RunIntent
    from harness.state import StateStore
    from harness.verify_result import VerifyResult
    from tests.unit.test_coordinator import _make_coordinator

    bundle.write_text(
        "---\nname: echelon.build\n---\nRead `commands/appendices/missing.md`.\n",
        encoding="utf-8",
    )
    coordinator = _make_coordinator(tmp_path)
    coordinator._config.llm.enabled = True
    monkeypatch.setattr("harness.coordinator.AICodingCliProvider", lambda config: object())
    store = StateStore(tmp_path / "runs/state", "spec-001", "default")
    store.initialize("run-existing", "semi", enabled_phases=["implementation", "finalization"])
    store.transition("running")
    if resume_kind == "publication":
        store.transition("blocked", updates={
            "blocked_phase": "implementation", "termination_reason": "publish_failed",
            "verified_publish_checkpoint": {"schema_version": 1, "stage": "push"},
        })
    else:
        store.transition("verified", updates={"last_completed_phase": "implementation"})
        store.transition("finalizing")

    class PublicationBoundary:
        def __init__(self, **kwargs):
            pass

        def resume_verified_publication(self):
            return ImplementationResult("verified", "verified", 1, 0, None, 0, VerifyResult(passed=True))

        def run_loop(self, **kwargs):
            pytest.fail("A downstream-only resume must not invoke implementation")

    monkeypatch.setattr("harness.coordinator.RalphController", PublicationBoundary)
    result = coordinator.start(RunIntent(
        spec_id="spec-001", max_outer=1, max_inner=1, resume=True,
    ))[0]

    assert result.status == "converged"
    assert not store.lock_file.exists()


def test_review_setup_block_retains_new_usage_and_pending_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from harness.delivery_results import ReviewResult
    from harness.run_intent import RunIntent
    from harness.state import StateStore
    from tests.unit.test_coordinator import _make_coordinator

    coordinator = _make_coordinator(tmp_path)
    coordinator._config.llm.enabled = True
    coordinator._config.review_loop.enabled = True
    coordinator._config.pr_host = "github"
    monkeypatch.setattr("harness.coordinator.AICodingCliProvider", lambda config: object())
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    store = StateStore(tmp_path / "runs/state", "spec-001", "default")
    store.initialize("run-existing", "semi", enabled_phases=["implementation", "review", "finalization"])
    store.transition("running")
    store.transition("verified", updates={
        "last_completed_phase": "implementation", "registered_worktree": str(tmp_path),
        "verified_commit": head, "pr_url": "https://github.com/t/r/pull/1",
        "outer_iter": 2, "tokens_used": 11,
        "last_verify_result": {"passed": True, "failures": [], "token_usage": 7},
    })
    store.transition("reviewing")
    artifact = tmp_path / "review-fixes.md"
    artifact.write_text("Fix T-002", encoding="utf-8")

    class ReviewBoundary:
        queued_task_ids = ("T-002",)
        published_artifacts = (artifact,)
        pending_batch_attempt_id = "review-attempt-1"

        def __init__(self, **kwargs):
            pass

        def run_loop(self, **kwargs):
            return ReviewResult("review_fix_queued", "review_fix_queued", 1, kwargs["pr_url"], 5)

    def unexpected_build(*args, **kwargs):
        pytest.fail("Missing command must not execute the queued repair")

    monkeypatch.setattr("harness.coordinator.ReviewLoopController", ReviewBoundary)
    monkeypatch.setattr("harness.coordinator.RalphController.run_loop", unexpected_build)
    result = coordinator.start(RunIntent(
        spec_id="spec-001", max_outer=1, max_inner=1, resume=True,
    ))[0]

    assert result.termination_reason == "delivery_prompt_invalid"
    assert result.blocked_phase == "review"
    assert (result.outer_iterations, result.tokens_used) == (3, 16)
    assert result.final_verify is not None
    assert result.final_verify.passed is True
    assert result.final_verify.token_usage == 7
    state = store.read()
    assert (state["outer_iter"], state["tokens_used"]) == (3, 16)
    assert "canonical delivery command" in state["build_reason"]
    assert state["last_verify_result"]["token_usage"] == 7
    assert state["pending_review_reentry"]["task_ids"] == ["T-002"]
    assert not store.lock_file.exists()


def test_visual_setup_block_persists_evidence_and_usage_in_coordinator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from harness.config import VisualTestsConfig
    from harness.run_intent import RunIntent
    from harness.state import StateStore
    from tests.unit.test_coordinator import _make_coordinator
    from tests.unit.test_visual_ralph import PLAYWRIGHT_FAIL_JSON, _exec_result

    coordinator = _make_coordinator(tmp_path)
    coordinator._config.llm.enabled = True
    coordinator._config.visual_tests = VisualTestsConfig(enabled=True, max_iterations=1)
    monkeypatch.setattr("harness.coordinator.AICodingCliProvider", lambda config: object())
    monkeypatch.setattr(
        coordinator._provider, "exec",
        lambda *args, **kwargs: _exec_result(stdout=PLAYWRIGHT_FAIL_JSON, exit_code=1),
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    store = StateStore(tmp_path / "runs/state", "spec-001", "default")
    store.initialize("run-existing", "semi", enabled_phases=["implementation", "visual", "finalization"])
    store.transition("running")
    store.transition("verified", updates={
        "last_completed_phase": "implementation", "registered_worktree": str(tmp_path),
        "verified_commit": head, "outer_iter": 2, "tokens_used": 11,
    })
    store.transition("validating")
    screenshot = tmp_path / "source.png"
    screenshot.write_bytes(b"visual-proof")
    monkeypatch.setattr(
        "harness.coordinator.VisualRalphController._retrieve_screenshots",
        lambda *args, **kwargs: [str(screenshot)],
    )

    def unexpected_build(*args, **kwargs):
        pytest.fail("Missing command must prevent model repair")

    monkeypatch.setattr("harness.coordinator.RalphController.run_downstream_feedback", unexpected_build)
    result = coordinator.start(RunIntent(
        spec_id="spec-001", max_outer=1, max_inner=1, resume=True,
    ))[0]

    assert result.termination_reason == "delivery_prompt_invalid"
    assert result.blocked_phase == "visual"
    assert result.outer_iterations == 3
    assert result.tokens_used > 11
    assert result.final_verify is not None
    assert result.tokens_used == 11 + result.final_verify.token_usage
    state = store.read()
    assert state["outer_iter"] == result.outer_iterations
    assert state["tokens_used"] == result.tokens_used
    assert "canonical delivery command" in state["build_reason"]
    assert state["last_verify_result"]["failures"]
    assert Path(state["visual_evidence"]["path"]).is_file()
    assert not store.lock_file.exists()
