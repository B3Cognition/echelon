"""Integration gate for the hard RE v1/v2 engine boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import stat
import subprocess

import pytest
from typer.testing import CliRunner

from harness.re_lifecycle import ReLifecycleController
from harness.re_profiles import builtin_re_profile
from harness.squad_provider import SquadAgentResult
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.run_store import detect_re_engine
from tests.unit.test_re_publication import _deep_spec, write_valid_re_run


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True)
class LegacyFixture:
    name: str
    project_root: Path
    run_dir: Path | None


def _legacy_fixture(project_root: Path, name: str) -> LegacyFixture:
    if name == "fresh":
        project_root.mkdir(exist_ok=True)
        return LegacyFixture(name, project_root, None)

    run_id = f"re-v1-{name}"
    run_dir = project_root / "runs" / run_id
    re_dir = run_dir / "re"
    re_dir.mkdir(parents=True)
    (project_root / "runs" / ".current-re").write_text(
        run_id + "\n",
        encoding="utf-8",
    )
    outer: dict[str, object] = {
        "run_id": run_id,
        "run_kind": "re",
        "status": "running",
        "phase": "re-extract-2-specify",
        "re_policy": "changed",
        "expected_generation": 0,
        "extraction_complete": False,
        "publication_pending": False,
        "publication_complete": False,
        "re_execution_profile": builtin_re_profile("balanced").to_json_dict(),
    }
    inner: dict[str, object] = {
        "status": "in_progress",
        "phase": "re-extract-2-specify",
        "coverage_threshold": 99,
        "resolution_threshold": 99,
        "re_workspace_synthesis_complete": False,
        "re_source_order": ["api"],
        "re_source_states": {
            "api": {"status": "active", "coverage_pct": 50.0}
        },
        "re_source_budgets": {
            "max_domain_repairs": 3,
            "max_source_cycles": 2,
            "max_source_reanalysis": 2,
        },
        "re_execution_profile": builtin_re_profile("balanced").to_json_dict(),
    }
    if name == "blocked":
        outer.update(
            status="blocked",
            blocked_reason="re_token_budget_exhausted",
        )
        inner.update(
            status="blocked",
            blocked_reason="re_token_budget_exhausted",
        )
    elif name == "partial":
        outer.update(
            status="done",
            extraction_complete=True,
            publication_pending=True,
            golddigger_status="partial",
            finalized_partial=True,
        )
        inner.update(
            status="done",
            publication_status="partial",
            re_source_states={
                "api": {
                    "status": "partial_quality_debt",
                    "coverage_pct": 95.0,
                }
            },
        )
    elif name == "published":
        outer.update(
            status="done",
            extraction_complete=True,
            publication_complete=True,
            generation=4,
            golddigger_status="complete",
        )
        inner.update(
            status="done",
            publication_status="complete",
            publication_generation=4,
            re_workspace_synthesis_complete=True,
            re_source_states={"api": {"status": "passed", "coverage_pct": 100.0}},
        )
    elif name != "running":  # pragma: no cover - test matrix owns names.
        raise AssertionError(f"unknown legacy fixture {name}")
    _write_json(run_dir / "state.json", outer)
    _write_json(re_dir / "state.json", inner)
    return LegacyFixture(name, project_root, run_dir)


@dataclass
class V1ProviderBoundary:
    """Script only the external provider boundary; controller behavior stays real."""

    provider_configs: list[object] = field(default_factory=list)
    provider_phases: list[str] = field(default_factory=list)
    provider_kwargs: list[dict[str, object]] = field(default_factory=list)
    artifact_writes: list[str] = field(default_factory=list)
    fail_once_at: str | None = None
    failure_emitted: bool = False


def _provider_phase_label(phase: str, prompt: str) -> str:
    if phase != "re-extract-2-specify":
        return phase
    if "Source ID: `" in prompt:
        return f"{phase}:source-domain"
    if "workspace-synthesis" in prompt:
        return f"{phase}:workspace-synthesis"
    return f"{phase}:unknown-target"


def _write_scripted_provider_artifacts(
    prompt: str,
    run_re_dir: Path,
    boundary: V1ProviderBoundary,
) -> None:
    """Write only files explicitly assigned to the provider in its real prompt."""
    if "Source ID: `" in prompt:
        source_id = prompt.split("Source ID: `", 1)[1].split("`", 1)[0]
        domain_id = prompt.split("Domain ID: `", 1)[1].split("`", 1)[0]
        path = run_re_dir / "sources" / source_id / "specs" / domain_id / "spec.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_deep_spec(source_id, "v1"), encoding="utf-8")
        boundary.artifact_writes.append(path.relative_to(run_re_dir).as_posix())
        return

    marker = "Required workspace-synthesis output files (write every file exactly once):\n"
    if marker not in prompt:
        marker = (
            "Repair only these missing workspace-synthesis output files. "
            "Do not rewrite already-valid synthesis artifacts:\n"
        )
    if marker not in prompt:
        return
    for line in prompt.split(marker, 1)[1].splitlines():
        if not line.startswith("- `"):
            break
        path = Path(line.removeprefix("- `").removesuffix("`"))
        assert path.is_absolute()
        resolved = path.resolve()
        assert resolved.is_relative_to(run_re_dir.resolve())
        relative = resolved.relative_to(run_re_dir.resolve()).as_posix()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(f"# Scripted provider artifact: {relative}\n", encoding="utf-8")
        boundary.artifact_writes.append(relative)


def _install_v1_provider_boundary(
    monkeypatch: pytest.MonkeyPatch,
    project_root: Path,
    *,
    fail_once_at: str | None = None,
) -> V1ProviderBoundary:
    """Install a real workspace and fake only ``SquadCliProvider`` execution."""
    boundary = V1ProviderBoundary(fail_once_at=fail_once_at)

    echelon_root = project_root / ".echelon"
    echelon_root.mkdir()
    (echelon_root / "config.yml").write_text(
        "workspace:\n"
        "  git_role: orchestration\n"
        "  sources:\n"
        "    - id: api\n"
        "      path: sources/api\n"
        "re:\n"
        "  default_profile: fast\n",
        encoding="utf-8",
    )
    (echelon_root / "runtime").symlink_to(
        REPO_ROOT / "runtime",
        target_is_directory=True,
    )
    (echelon_root / "prosaic").symlink_to(
        REPO_ROOT / "prosaic",
        target_is_directory=True,
    )
    source_root = project_root / "sources" / "api" / "src"
    source_root.mkdir(parents=True)
    for number in range(1, 6):
        (source_root / f"file-{number}.ts").write_text(
            f"export const value{number} = {number};\n",
            encoding="utf-8",
        )

    class ScriptedSquadProvider:
        supports_result_contract = True
        supports_prompt_metadata = True
        enforces_workspace_synthesis_boundary = True

        def __init__(self, received_config: object) -> None:
            boundary.provider_configs.append(received_config)

        def exec_agent(
            self,
            provider_project_root: str,
            prompt: str,
            **kwargs: object,
        ) -> SquadAgentResult:
            assert Path(provider_project_root).resolve() == project_root.resolve()
            phase = prompt.split("RE phase: ", 1)[1].split("\n", 1)[0]
            label = _provider_phase_label(phase, prompt)
            boundary.provider_phases.append(label)
            boundary.provider_kwargs.append(dict(kwargs))
            if boundary.fail_once_at == label and not boundary.failure_emitted:
                boundary.failure_emitted = True
                return SquadAgentResult(
                    exit_code=1,
                    echelon_result=None,
                    raw_output="scripted provider interruption",
                    duration_ms=1,
                    timed_out=False,
                    provider_name="scripted-v1",
                    model_name="fixture",
                    stderr="scripted provider interruption",
                )
            run_re_dir = Path(
                prompt.split("RE output directory: ", 1)[1]
                .split("\n", 1)[0]
                .strip("`")
            )
            _write_scripted_provider_artifacts(prompt, run_re_dir, boundary)
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {},
                    "journal_entries": [],
                },
                raw_output="",
                duration_ms=1,
                timed_out=False,
                token_usage=10,
                token_usage_details={"input_tokens": 8, "output_tokens": 2},
                provider_name="scripted-v1",
                model_name="fixture",
            )

    monkeypatch.setattr(
        "harness.squad_provider.SquadCliProvider",
        ScriptedSquadProvider,
    )
    return boundary


def _assert_no_v2_state(project_root: Path) -> None:
    assert not (project_root / "re" / "v2").exists()
    runs = project_root / "runs"
    if runs.exists():
        assert not any(path.name == "v2" for path in runs.glob("*/v2"))


def _assert_valid_v1_state(fixture: LegacyFixture) -> None:
    if fixture.run_dir is None:
        return
    from harness.re_lifecycle import ReLifecycleController

    controller = ReLifecycleController(
        project_root=fixture.project_root,
        extension_root=fixture.project_root / "extension",
        provider_factory=lambda: pytest.fail("state validation constructed a provider"),
    )
    state = controller._load_state(fixture.run_dir)
    assert state["run_id"] == fixture.run_dir.name
    assert state["run_kind"] == "re"
    assert detect_re_engine(fixture.run_dir) == "v1"


def _never_v2(*_args: object, **_kwargs: object) -> object:
    pytest.fail("a legacy RE operation constructed or invoked the v2 controller")


def _install_v2_sentinels(monkeypatch: pytest.MonkeyPatch) -> None:
    for target in (
        "echelon.cli._run_re_v2_create",
        "echelon.cli._run_re_v2_continue",
        "echelon.cli._re_v2_context",
        "echelon.cli._re_v2_snapshot_root",
        "harness.re_v2.controller.ReV2Controller",
        "harness.re_v2.controller.DeterministicInventoryExecutor",
        "harness.re_v2.controller.production_executor_registry",
        "harness.re_v2.snapshot.capture_source_snapshot",
        "harness.re_v2.snapshot.validate_source_snapshot",
        "harness.re_v2.status.render_v2_status",
        "harness.re_v2.run_store.create_run_store",
        "harness.re_v2.run_store.load_run_manifest",
        "harness.re_v2.publication.publish_generation",
    ):
        monkeypatch.setattr(target, _never_v2)


def _invoke_re(*args: str):
    from echelon.cli_app import app

    return CliRunner().invoke(app, ["re", *args])


def _captured_stderr(result: object) -> str:
    """Normalize Click versions that merge stderr into the output stream."""
    stderr_bytes = getattr(result, "stderr_bytes", None)
    return "" if stderr_bytes is None else str(getattr(result, "stderr"))


def _tree_delta(
    before: dict[str, tuple[str, int, bytes | None]],
    after: dict[str, tuple[str, int, bytes | None]],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(sorted(after.keys() - before.keys())),
        tuple(sorted(before.keys() - after.keys())),
        tuple(sorted(path for path in before.keys() & after.keys() if before[path] != after[path])),
    )


def _complete_output(run_id: str) -> str:
    return (
        f"RE run {run_id} complete; publication is pending. "
        f"Publish explicitly with: echelon re publish {run_id}\n"
        "\n"
        "╭─ ✈ echelon · RE FINAL STATE — COMPLETE "
        "──────────────────────────────────────╮\n"
        "│  Reverse engineering completed; publication is pending."
        "                      │\n"
        "╰──────────────────────────────────────────────────────────────────────────────╯\n"
        "\n"
        f"  run         {run_id}\n"
        "  generation  0\n"
        "\n"
        "  next step\n"
        "  ─────────\n"
        f"  echelon re publish {run_id}\n"
        "\n"
    )


def _running_status_output() -> str:
    return (
        "\n"
        "╭─ ✈ echelon · RE STATUS "
        "──────────────────────────────────────────────────────╮\n"
        "│  Live controller state and deterministic source-quality outcomes."
        "            │\n"
        "╰──────────────────────────────────────────────────────────────────────────────╯\n"
        "\n"
        "  run           re-v1-running\n"
        "  controller    in_progress\n"
        "  lifecycle     running\n"
        "  phase         re-extract-2-specify — domain specification and workspace synthesis\n"
        "  policy        changed\n"
        "  sources       0/1 passed · 1 active\n"
        "  synthesis     pending\n"
        "  token budget  not available\n"
        "\n"
        "\n"
        "Note: outer lifecycle state is running while the live controller state is in_progress.\n"
        "\n"
        "Source quality\n"
        "  source                                 status                 coverage / debt\n"
        "  ─────────────────────────────────────  ─────────────────────  ─────────────────\n"
        "  api                                    active                 50.0%\n"
        "\n"
        "Next action: Do not start another continuation while the controller is active.\n"
    )


def _continue_output(project_root: Path) -> str:
    return (
        "\n"
        "╭─ ✈ echelon · RE CONTINUE "
        "────────────────────────────────────────────────────╮\n"
        "│  Controller state before provider dispatch."
        "                                  │\n"
        "╰──────────────────────────────────────────────────────────────────────────────╯\n"
        "\n"
        "  run            re-v1-blocked\n"
        "  status         blocked → continuing\n"
        "  phase          re-extract-2-specify — domain specification and workspace synthesis\n"
        "  policy         changed\n"
        "  sources        0/1 passed · 1 active\n"
        "  domains        not available\n"
        "  synthesis      pending\n"
        "  quality        coverage 99% · resolution 99%\n"
        "  repair budget  5 source-local attempts\n"
        f"  artifacts      {project_root}/runs/re-v1-blocked/re\n"
        "\n"
        + _complete_output("re-v1-blocked")
    )


def _published_status_output() -> str:
    return (
        "\n"
        "╭─ ✈ echelon · RE STATUS "
        "──────────────────────────────────────────────────────╮\n"
        "│  Live controller state and deterministic source-quality outcomes."
        "            │\n"
        "╰──────────────────────────────────────────────────────────────────────────────╯\n"
        "\n"
        "  run            re-v1-partial\n"
        "  controller     done\n"
        "  lifecycle      done\n"
        "  phase          re-extract-6-complete — current controller phase\n"
        "  policy         changed\n"
        "  sources        1/1 passed\n"
        "  synthesis      complete\n"
        "  token budget   not available\n"
        "  semantic debt  0 findings across no named source\n"
        "  publication    generation 1 (partial)\n"
        "\n"
        "\n"
        "Source quality\n"
        "  source                                 status                 coverage / debt\n"
        "  ─────────────────────────────────────  ─────────────────────  ─────────────────\n"
        "  api                                    passed                 100.0%\n"
        "\n"
        "Next action: This run is finalized and published as partial; debt remains explicit. "
        "No continuation is required.\n"
    )


def _fresh_created_paths(run_id: str) -> tuple[str, ...]:
    run = f"runs/{run_id}"
    return tuple(
        sorted(
            {
                "runs",
                "runs/.current-re",
                "runs/.gitignore",
                run,
                f"{run}/state.json",
                f"{run}/re",
                f"{run}/re/analysis.json",
                f"{run}/re/cross-repo.json",
                f"{run}/re/quality",
                f"{run}/re/quality/semantic-quality-review.json",
                f"{run}/re/re-analysis-manifest.json",
                f"{run}/re/re-execution-plan.json",
                f"{run}/re/re-source-index.json",
                f"{run}/re/re-workspace-inputs.json",
                f"{run}/re/state.json",
                f"{run}/re/sources",
                f"{run}/re/sources/api",
                f"{run}/re/sources/api/adrs",
                f"{run}/re/sources/api/adrs/ADR-001-source-boundary.md",
                f"{run}/re/sources/api/analysis.json",
                f"{run}/re/sources/api/architecture.md",
                f"{run}/re/sources/api/components.md",
                f"{run}/re/sources/api/contracts.md",
                f"{run}/re/sources/api/domain-manifest.json",
                f"{run}/re/sources/api/overview.md",
                f"{run}/re/sources/api/specs",
                f"{run}/re/sources/api/specs/001-re-domain",
                f"{run}/re/sources/api/specs/001-re-domain/spec.md",
                f"{run}/re/workspace",
                f"{run}/re/workspace-manifest.json",
                f"{run}/re/workspace/architecture-map.json",
                f"{run}/re/workspace/contracts.md",
                f"{run}/re/workspace/domain-catalog.md",
                f"{run}/re/workspace/domains",
                f"{run}/re/workspace/domains/001-re-domain.md",
                f"{run}/re/workspace/overview.md",
                f"{run}/re/workspace/relationships.md",
                "sources",
                "sources/api",
                "sources/api/src",
                "sources/api/src/file-1.ts",
                "sources/api/src/file-2.ts",
                "sources/api/src/file-3.ts",
                "sources/api/src/file-4.ts",
                "sources/api/src/file-5.ts",
            }
        )
    )


def _provider_result_created_paths(run_id: str) -> tuple[str, ...]:
    run = f"runs/{run_id}/re"
    return tuple(
        sorted(
            {
                f"{run}/quality",
                f"{run}/quality/semantic-quality-review.json",
                f"{run}/re-execution-plan.json",
                f"{run}/re-source-index.json",
                f"{run}/re-workspace-inputs.json",
                f"{run}/sources",
                f"{run}/sources/api",
                f"{run}/sources/api/adrs",
                f"{run}/sources/api/adrs/ADR-001-source-boundary.md",
                f"{run}/sources/api/analysis.json",
                f"{run}/sources/api/architecture.md",
                f"{run}/sources/api/components.md",
                f"{run}/sources/api/contracts.md",
                f"{run}/sources/api/domain-manifest.json",
                f"{run}/sources/api/overview.md",
                f"{run}/sources/api/specs",
                f"{run}/sources/api/specs/001-re-domain",
                f"{run}/sources/api/specs/001-re-domain/spec.md",
                f"{run}/workspace",
                f"{run}/workspace/architecture-map.json",
                f"{run}/workspace/contracts.md",
                f"{run}/workspace/domain-catalog.md",
                f"{run}/workspace/domains",
                f"{run}/workspace/domains/001-re-domain.md",
                f"{run}/workspace/overview.md",
                f"{run}/workspace/relationships.md",
                "sources",
                "sources/api",
                "sources/api/src",
                "sources/api/src/file-1.ts",
                "sources/api/src/file-2.ts",
                "sources/api/src/file-3.ts",
                "sources/api/src/file-4.ts",
                "sources/api/src/file-5.ts",
            }
        )
    )


def _minimal_fixture_paths(run_id: str) -> tuple[str, ...]:
    return (
        "runs",
        "runs/.current-re",
        f"runs/{run_id}",
        f"runs/{run_id}/re",
        f"runs/{run_id}/re/state.json",
        f"runs/{run_id}/state.json",
    )


def _staged_v1_tree_paths(run_id: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            set(_minimal_fixture_paths(run_id))
            | set(_provider_result_created_paths(run_id))
        )
    )


def _partial_publication_created_paths() -> tuple[str, ...]:
    fingerprint = "94b47a150a80d91fe927bb84d86a2f676d2ffec287d8d9ccc1651ca917230c8d"
    cache = f"re/.cache/sources/api/{fingerprint}"
    return tuple(
        sorted(
            {
                "re",
                "re/.cache",
                "re/.cache/sources",
                "re/.cache/sources/api",
                cache,
                f"{cache}/analysis.json",
                f"{cache}/cache-manifest.json",
                f"{cache}/domain-manifest.json",
                "re/.gitignore",
                "re/.locks",
                "re/.locks/.publish-claim.guard",
                "re/.staging",
                "re/index.json",
                "re/sources",
                "re/sources/api",
                "re/sources/api/adrs",
                "re/sources/api/adrs/ADR-001-source-boundary.md",
                "re/sources/api/analysis.json",
                "re/sources/api/architecture.md",
                "re/sources/api/components.md",
                "re/sources/api/contracts.md",
                "re/sources/api/domain-manifest.json",
                "re/sources/api/manifest.json",
                "re/sources/api/overview.md",
                "re/sources/api/specs",
                "re/sources/api/specs/001-re-domain",
                "re/sources/api/specs/001-re-domain/spec.md",
                "re/workspace",
                "re/workspace/architecture-map.json",
                "re/workspace/contracts.md",
                "re/workspace/domain-catalog.md",
                "re/workspace/domains",
                "re/workspace/domains/001-re-domain.md",
                "re/workspace/manifest.json",
                "re/workspace/overview.md",
                "re/workspace/relationships.md",
            }
        )
    )


@pytest.mark.integration
def test_fresh_v1_front_door_runs_real_lifecycle_without_v2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_v1_provider_boundary(monkeypatch, tmp_path)
    before = _tree_snapshot(tmp_path)
    _install_v2_sentinels(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = _invoke_re("run", "--re-policy", "refresh-all", "--profile", "fast")

    assert result.exit_code == 0, result.output
    assert result.exception is None
    assert _captured_stderr(result) == ""
    assert len(boundary.provider_configs) == 1
    assert boundary.provider_phases == [
        "re-extract-2-specify:source-domain",
        "re-extract-2-specify:workspace-synthesis",
        "re-extract-6-checklist",
        "re-extract-7-constitute",
    ]
    assert all("result_contract" in kwargs for kwargs in boundary.provider_kwargs)
    assert all("prompt_metadata" in kwargs for kwargs in boundary.provider_kwargs)
    run_id = (tmp_path / "runs/.current-re").read_text(encoding="utf-8").strip()
    run_dir = tmp_path / "runs" / run_id
    assert _tree_delta(before, _tree_snapshot(tmp_path))[1:] == ((), ())
    fixture = LegacyFixture("fresh", tmp_path, run_dir)
    _assert_valid_v1_state(fixture)
    assert detect_re_engine(run_dir) == "v1"
    outer = json.loads((run_dir / "state.json").read_text())
    inner = json.loads((run_dir / "re/state.json").read_text())
    assert outer["status"] == "done"
    assert outer["extraction_complete"] is True
    assert outer["publication_pending"] is True
    assert inner["status"] == "done"
    assert inner["phase"] == "re-extract-7-constitute"
    assert inner["re_workspace_synthesis_complete"] is True
    assert inner["re_source_states"]["api"]["status"] == "passed"
    assert inner["re_source_states"]["api"]["coverage_pct"] == 100.0
    assert inner["re_token_usage"] == 40
    assert result.stdout.endswith(_complete_output(run_id))
    _assert_no_v2_state(tmp_path)


@pytest.mark.integration
def test_running_v1_front_door_status_is_exact_and_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _legacy_fixture(tmp_path, "running")
    assert fixture.run_dir is not None
    before = _tree_snapshot(tmp_path)
    _install_v2_sentinels(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = _invoke_re("status")

    assert result.exit_code == 0, result.output
    assert result.exception is None
    assert _captured_stderr(result) == ""
    assert result.stdout == _running_status_output()
    assert tuple(before) == _minimal_fixture_paths("re-v1-running")
    assert _tree_snapshot(tmp_path) == before
    _assert_valid_v1_state(fixture)
    _assert_no_v2_state(tmp_path)


@pytest.mark.integration
def test_blocked_v1_front_door_continue_runs_real_lifecycle_without_v2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_v1_provider_boundary(
        monkeypatch,
        tmp_path,
        fail_once_at="re-extract-2-specify:source-domain",
    )
    _install_v2_sentinels(monkeypatch)
    monkeypatch.chdir(tmp_path)

    interrupted = _invoke_re(
        "run",
        "--re-policy",
        "refresh-all",
        "--profile",
        "fast",
    )

    assert interrupted.exit_code == 1, interrupted.output
    run_id = (tmp_path / "runs/.current-re").read_text(encoding="utf-8").strip()
    run_dir = tmp_path / "runs" / run_id
    plan_before = (run_dir / "re/re-execution-plan.json").read_bytes()
    blocked_outer = json.loads((run_dir / "state.json").read_text())
    blocked_inner = json.loads((run_dir / "re/state.json").read_text())
    assert blocked_outer["status"] == "blocked"
    assert blocked_outer["blocked_reason"] == "re_agent_dispatch_failed"
    assert blocked_inner["status"] == "blocked"
    assert blocked_inner["blocked_reason"] == "re_agent_dispatch_failed"
    assert boundary.provider_phases == ["re-extract-2-specify:source-domain"]

    before_continue = _tree_snapshot(tmp_path)
    result = _invoke_re("continue")

    assert result.exit_code == 0, result.output
    assert result.exception is None
    assert _captured_stderr(result) == ""
    assert len(boundary.provider_configs) == 2
    assert boundary.provider_phases == [
        "re-extract-2-specify:source-domain",
        "re-extract-2-specify:source-domain",
        "re-extract-2-specify:workspace-synthesis",
        "re-extract-6-checklist",
        "re-extract-7-constitute",
    ]
    after = _tree_snapshot(tmp_path)
    created, removed, modified = _tree_delta(before_continue, after)
    assert created
    assert removed == ()
    assert modified
    assert (run_dir / "re/re-execution-plan.json").read_bytes() == plan_before
    fixture = LegacyFixture("blocked", tmp_path, run_dir)
    _assert_valid_v1_state(fixture)
    outer = json.loads((run_dir / "state.json").read_text())
    inner = json.loads((run_dir / "re/state.json").read_text())
    assert outer["status"] == "done"
    assert inner["status"] == "done"
    assert inner["phase"] == "re-extract-7-constitute"
    assert inner["re_source_states"]["api"]["status"] == "passed"
    assert result.stdout.endswith(_complete_output(run_id))
    _assert_no_v2_state(tmp_path)


@pytest.mark.integration
def test_partial_v1_front_door_real_publication_then_published_status_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "re-v1-partial"
    run_dir = write_valid_re_run(tmp_path, ("api",), run_id=run_id, status="partial")
    outer = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    outer.update(
        {
            "run_kind": "re",
            "status": "done",
            "re_policy": "changed",
            "expected_generation": 0,
            "extraction_complete": True,
            "publication_pending": True,
            "publication_complete": False,
            "finalized_partial": True,
            "re_execution_profile": builtin_re_profile("balanced").to_json_dict(),
        }
    )
    _write_json(run_dir / "state.json", outer)
    inner = json.loads((run_dir / "re/state.json").read_text(encoding="utf-8"))
    inner.update(
        {
            "status": "done",
            "phase": "re-extract-6-complete",
            "publication_status": "partial",
            "re_workspace_synthesis_complete": True,
            "re_source_order": ["api"],
            "re_source_states": {
                "api": {"status": "passed", "coverage_pct": 100.0}
            },
        }
    )
    _write_json(run_dir / "re/state.json", inner)
    (tmp_path / "runs/.current-re").write_text(run_id + "\n", encoding="utf-8")
    fixture = LegacyFixture("partial", tmp_path, run_dir)
    before = _tree_snapshot(tmp_path)
    assert tuple(before) == _staged_v1_tree_paths(run_id)
    _install_v2_sentinels(monkeypatch)
    monkeypatch.chdir(tmp_path)

    publication = _invoke_re("publish", run_id, "--allow-partial")

    assert publication.exit_code == 0, publication.output
    assert publication.exception is None
    assert publication.stdout == (
        "Published RE generation 1 (partial)\n"
        "Changed sources: api\n"
        "Git commit: not requested\n"
    )
    assert _captured_stderr(publication) == ""
    after_publication = _tree_snapshot(tmp_path)
    created, removed, modified = _tree_delta(before, after_publication)
    assert created == _partial_publication_created_paths()
    assert removed == ()
    assert modified == (
        f"runs/{run_id}/re/state.json",
        f"runs/{run_id}/state.json",
    )
    assert tuple(after_publication) == tuple(
        sorted(
            set(_staged_v1_tree_paths(run_id))
            | set(_partial_publication_created_paths())
        )
    )
    published_outer = json.loads((run_dir / "state.json").read_text())
    published_inner = json.loads((run_dir / "re/state.json").read_text())
    published_index = json.loads((tmp_path / "re/index.json").read_text())
    assert published_outer["publication_complete"] is True
    assert published_outer["generation"] == 1
    assert published_inner["publication_status"] == "partial"
    assert published_index["generation"] == 1
    assert published_index["publication_status"] == "partial"

    status = _invoke_re("status")

    assert status.exit_code == 0, status.output
    assert status.exception is None
    assert _captured_stderr(status) == ""
    assert status.stdout == _published_status_output()
    assert _tree_snapshot(tmp_path) == after_publication
    _assert_valid_v1_state(fixture)
    _assert_no_v2_state(tmp_path)


def _unsupported_manifest(run_id: str) -> bytes:
    return canonical_json_bytes(
        {
            "artifact_policy_versions": {"L0": "egr-164-v1"},
            "created_at": "2026-08-14T12:00:00Z",
            "engine": "re-v2",
            "engine_protocol_version": "99.0",
            "initial_budget_policy": {
                "active_ms_limit": 60_000,
                "artifact_generation_attempt_limit": 1,
                "provider_attempt_limit": 1,
                "result_contract_retry_limit": 0,
                "semantic_repair_round_limit": 0,
                "token_limit": 100,
            },
            "parent_run_id": None,
            "partition_manifest_id": content_digest(b"partitions"),
            "provider_contract": {
                "provider": "deterministic-inventory",
                "provider_protocol_version": "re-v2-l0-v1",
                "result_contract_id": "deterministic-inventory-v1",
            },
            "requested_goals": ["inventory"],
            "run_id": run_id,
            "schema_version": 1,
            "source_snapshot_id": content_digest(b"snapshot"),
            "source_snapshot_kind": "content-snapshot",
        }
    )


def _tree_snapshot(root: Path) -> dict[str, tuple[str, int, bytes | None]]:
    snapshot: dict[str, tuple[str, int, bytes | None]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        details = path.lstat()
        if stat.S_ISLNK(details.st_mode):
            kind = "symlink"
            payload = os.readlink(path).encode()
        elif stat.S_ISDIR(details.st_mode):
            kind = "dir"
            payload = None
        else:
            kind = "file"
            payload = path.read_bytes()
        snapshot[relative] = (kind, stat.S_IMODE(details.st_mode), payload)
    return snapshot


def _init_clean_isolation_source(path: Path) -> None:
    path.mkdir()
    (path / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )


@pytest.mark.integration
def test_dirty_composite_preflight_preserves_active_v1_run_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _legacy_fixture(tmp_path, "running")
    assert fixture.run_dir is not None
    first = tmp_path / "first"
    second = tmp_path / "second"
    _init_clean_isolation_source(first)
    _init_clean_isolation_source(second)
    (second / "dirty.py").write_text("dirty\n", encoding="utf-8")
    pointer = tmp_path / "runs" / ".current-re"
    pointer_before = pointer.read_bytes()
    v1_before = _tree_snapshot(fixture.run_dir)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "ECHELON_HOME",
        str(tmp_path.parent / f"{tmp_path.name}-echelon-home"),
    )
    monkeypatch.setattr("echelon.cli._re_lifecycle_controller", _never_v2)

    result = _invoke_re("run", "--engine", "v2", "--shadow")

    assert result.exit_code == 2
    assert "untracked" in result.output and "stash" in result.output
    assert pointer.read_bytes() == pointer_before
    assert _tree_snapshot(fixture.run_dir) == v1_before


@pytest.mark.integration
@pytest.mark.parametrize(
    "manifest_payload",
    (
        b"{malformed-json",
        pytest.param(_unsupported_manifest("re-v2-invalid"), id="unsupported-protocol"),
    ),
)
@pytest.mark.parametrize("operation", ("continue", "status"))
def test_invalid_v2_pin_fails_before_execution_or_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manifest_payload: bytes,
    operation: str,
) -> None:
    run_id = "re-v2-invalid"
    run_dir = tmp_path / "runs" / run_id
    v2_dir = run_dir / "v2"
    v2_dir.mkdir(parents=True)
    (v2_dir / "run.json").write_bytes(manifest_payload)
    (tmp_path / "runs" / ".current-re").write_text(run_id + "\n", encoding="utf-8")
    before = _tree_snapshot(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.cli._re_lifecycle_controller", _never_v2)
    monkeypatch.setattr("echelon.cli._re_v2_context", _never_v2)
    monkeypatch.setattr("harness.re_v2.controller.ReV2Controller", _never_v2)
    monkeypatch.setattr("harness.re_v2.controller.production_executor_registry", _never_v2)

    result = _invoke_re(operation)

    assert result.exit_code == 2
    assert isinstance(result.exception, SystemExit)
    assert _captured_stderr(result) in {"", result.output}
    assert result.output.startswith(f"echelon re {operation}: ")
    assert _tree_snapshot(tmp_path) == before
    assert not (v2_dir / "events.jsonl").exists()
    assert not (v2_dir / "ledger.jsonl").exists()
    assert not (v2_dir / "candidates").exists()
    assert not (v2_dir / ".execution").exists()
