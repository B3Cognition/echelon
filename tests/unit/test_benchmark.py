from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from echelon.benchmark import (
    BenchmarkRunRecord,
    collect_benchmark_record,
    latest_summary_path,
    load_saved_scorecard,
    load_summary,
    list_fixtures,
    list_variants,
    plan_variant_commands,
    run_benchmark_variant,
    snapshot_benchmark_baseline,
    summarize_records,
    write_summary,
)
from echelon.cli import _cmd_benchmark


def test_lists_tiny_notes_fixture() -> None:
    fixtures = {fixture.id: fixture for fixture in list_fixtures()}

    fixture = fixtures["tiny-notes"]

    assert "notes" in fixture.prompt.lower()
    assert "local persistence" in fixture.prompt.lower()
    assert "automated test" in fixture.prompt.lower()


def test_lists_expected_variants() -> None:
    variants = {variant.id: variant for variant in list_variants()}

    assert list(variants) == [
        "baseline",
        "constitution",
        "constitution-tasks",
        "constitution-tasks-adrs",
    ]
    assert variants["constitution-tasks"].phases == (
        "phase-exp-constitution-quality",
        "phase-exp-tasks-quality",
    )


def test_plans_baseline_without_cleanse_phases() -> None:
    plan = plan_variant_commands("tiny-notes", "baseline")

    assert plan.fixture_id == "tiny-notes"
    assert plan.variant_id == "baseline"
    assert plan.phase_ids == ()
    assert plan.commands[0] == (
        "echelon",
        "spec",
        "run",
        "--mode",
        "banzai",
        list_fixtures()[0].prompt,
    )
    assert plan.commands[-1] == (
        "echelon",
        "delivery",
        "run",
        "RESOLVE_SPEC_ID_FROM_CURRENT_RUN",
        "mode=banzai",
    )


def test_plans_artifact_only_baseline_without_delivery() -> None:
    plan = plan_variant_commands("tiny-notes", "baseline", artifact_only=True)

    assert plan.fixture_id == "tiny-notes"
    assert plan.variant_id == "baseline"
    assert plan.phase_ids == ()
    assert len(plan.commands) == 1
    assert plan.commands[0][:3] == ("echelon", "spec", "run")
    assert not any(command[:3] == ("echelon", "delivery", "run") for command in plan.commands)


def test_plans_constitution_tasks_adrs_with_ordered_phases() -> None:
    plan = plan_variant_commands("tiny-notes", "constitution-tasks-adrs")

    assert plan.phase_ids == (
        "phase-exp-constitution-quality",
        "phase-exp-tasks-quality",
        "phase-exp-adr-quality",
    )
    assert (
        "echelon",
        "phase",
        "run",
        "phase-exp-constitution-quality",
        "--spec",
        "RESOLVE_SPEC_ID_FROM_CURRENT_RUN",
        "--mode",
        "banzai",
    ) in plan.commands
    assert (
        "echelon",
        "phase",
        "run",
        "phase-exp-tasks-quality",
        "--spec",
        "RESOLVE_SPEC_ID_FROM_CURRENT_RUN",
        "--mode",
        "banzai",
    ) in plan.commands
    assert (
        "echelon",
        "phase",
        "run",
        "phase-exp-adr-quality",
        "--spec",
        "RESOLVE_SPEC_ID_FROM_CURRENT_RUN",
        "--mode",
        "banzai",
    ) in plan.commands


def test_unknown_fixture_and_variant_fail_clearly() -> None:
    with pytest.raises(ValueError, match="Unknown benchmark fixture"):
        plan_variant_commands("missing", "baseline")

    with pytest.raises(ValueError, match="Unknown benchmark variant"):
        plan_variant_commands("tiny-notes", "missing")


def test_summarize_records_prefers_build_outcomes() -> None:
    records = [
        BenchmarkRunRecord(
            variant_id="baseline",
            status="complete",
            build_dispatches=8,
            retries=2,
            blocked_states=1,
            verification_failures=2,
            fulfillment_gaps=3,
            elapsed_seconds=600.0,
        ),
        BenchmarkRunRecord(
            variant_id="constitution-tasks",
            status="complete",
            build_dispatches=5,
            retries=0,
            blocked_states=0,
            verification_failures=0,
            fulfillment_gaps=1,
            elapsed_seconds=420.0,
        ),
    ]

    summary = summarize_records(records)

    assert summary["best_variant"] == "constitution-tasks"
    assert summary["variants"]["baseline"]["build_dispatches"] == 8
    assert summary["variants"]["constitution-tasks"]["fulfillment_gaps"] == 1


def test_summarize_records_does_not_prefer_failed_empty_metrics() -> None:
    records = [
        BenchmarkRunRecord(variant_id="baseline", status="failed"),
        BenchmarkRunRecord(
            variant_id="constitution",
            status="complete",
            fulfillment_gaps=1,
            elapsed_seconds=120.0,
        ),
    ]

    summary = summarize_records(records)

    assert summary["best_variant"] == "constitution"


def test_write_summary_outputs_json_and_markdown(tmp_path: Path) -> None:
    records = [
        BenchmarkRunRecord(
            variant_id="baseline",
            status="complete",
            build_dispatches=8,
            retries=2,
            blocked_states=1,
            verification_failures=2,
            fulfillment_gaps=3,
            elapsed_seconds=600.0,
        )
    ]

    json_path, md_path = write_summary(tmp_path, records)

    assert json.loads(json_path.read_text(encoding="utf-8"))["best_variant"] == "baseline"
    assert (
        "| baseline | bounded | complete | - | - | 0 | 0 | 8 | 2 | 1 | 2 | 3 | 0 | 0 | 0 | 600.0 |"
        in md_path.read_text(encoding="utf-8")
    )


def test_collect_benchmark_record_reads_squad_and_delivery_state(tmp_path: Path) -> None:
    squad_dir = tmp_path / "runs" / "spec-20260704-120000-000001"
    squad_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(f"{squad_dir.name}\n", encoding="utf-8")
    (squad_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "squad-1",
                "status": "done",
                "spec_id": "001",
                "spec_dir": "specs/001-simple-notes-app",
                "phase_dispatch_counts": {"phase1-what": 2, "phase1-why2": 2},
                "quality_scores": [
                    {"pass": True, "pass_id": "WHY1-iter-0"},
                    {"pass": False, "pass_id": "WHY2-iter-0"},
                    {"pass": True, "pass_id": "WHY2-iter-1"},
                ],
                "cost_usd": 12.5,
            }
        ),
        encoding="utf-8",
    )
    budget_dir = squad_dir / "context-budget"
    budget_dir.mkdir()
    (budget_dir / "dispatch-001.json").write_text(
        json.dumps(
            {
                "selected_render_mode": "bounded",
                "bounded": {"bytes": 4000, "approx_tokens": 1000},
                "savings": {"reduction_pct": 40},
            }
        ),
        encoding="utf-8",
    )
    (budget_dir / "dispatch-002.json").write_text(
        json.dumps(
            {
                "selected_render_mode": "bounded",
                "bounded": {"bytes": 2000, "approx_tokens": 500},
                "savings": {"reduction_pct": 20},
            }
        ),
        encoding="utf-8",
    )
    build_dir = tmp_path / "runs" / "build-20260704-130000-000001"
    state_dir = build_dir / "state"
    state_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current-build-001").write_text(f"{build_dir.name}\n", encoding="utf-8")
    (state_dir / "default.json").write_text(
        json.dumps(
            {
                "run_id": "build-1",
                "status": "converged",
                "outer_iter": 3,
                "inner_iter": 1,
                "iteration_log": [
                    {"verify": {"status": "failed"}},
                    {"verify": {"status": "passed"}},
                ],
                "last_verify_result": {
                    "status": "failed",
                    "verification_failures": 2,
                    "fulfillment_gaps": 1,
                },
            }
        ),
        encoding="utf-8",
    )

    record = collect_benchmark_record(tmp_path, "constitution", status="complete", elapsed_seconds=42.0)

    assert record.variant_id == "constitution"
    assert record.status == "complete"
    assert record.spec_id == "001"
    assert record.run_id == "squad-1"
    assert record.delivery_run_id == "build-1"
    assert record.context_render == "bounded"
    assert record.context_prompt_bytes == 6000
    assert record.context_prompt_tokens_estimate == 1500
    assert record.context_reduction_pct == 30
    assert record.phase_a_dispatches == 4
    assert record.why_failures == 1
    assert record.build_dispatches == 3
    assert record.verification_failures == 2
    assert record.fulfillment_gaps == 1
    assert record.cost_usd == 12.5


def test_benchmark_list_prints_fixtures_and_variants(tmp_path: Path, capsys) -> None:
    _cmd_benchmark(["list"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "Fixtures:" in out
    assert "Variants (--variant <id>):" in out
    assert "tiny-notes" in out
    assert "baseline" in out
    assert "constitution-tasks-adrs" in out
    assert "echelon benchmark run tiny-notes --variant baseline" in out


def test_benchmark_dry_run_prints_commands(tmp_path: Path, capsys) -> None:
    _cmd_benchmark(
        [
            "run",
            "tiny-notes",
            "--variant",
            "constitution-tasks",
            "--baseline-ref",
            "baseline-artifacts",
            "--dry-run",
        ],
        project_root=tmp_path,
    )

    out = capsys.readouterr().out
    assert "git reset --hard baseline-artifacts" in out
    assert "git clean -fd -e runs/benchmarks/" in out
    assert "echelon spec run --mode banzai" in out
    assert "phase-exp-constitution-quality" in out
    assert "phase-exp-tasks-quality" in out
    assert "echelon delivery run RESOLVE_SPEC_ID_FROM_CURRENT_RUN mode=banzai" in out


def test_benchmark_dry_run_includes_context_render_env(tmp_path: Path, capsys) -> None:
    _cmd_benchmark(
        [
            "run",
            "tiny-notes",
            "--variant",
            "baseline",
            "--baseline-ref",
            "baseline-artifacts",
            "--context-render",
            "bounded",
            "--dry-run",
        ],
        project_root=tmp_path,
    )

    out = capsys.readouterr().out
    assert "ECHELON_CONTEXT_RENDER_MODE=bounded echelon spec run --mode banzai" in out


def test_benchmark_artifact_only_dry_run_skips_delivery(tmp_path: Path, capsys) -> None:
    _cmd_benchmark(
        [
            "run",
            "tiny-notes",
            "--variant",
            "baseline",
            "--baseline-ref",
            "baseline-artifacts",
            "--artifact-only",
            "--dry-run",
        ],
        project_root=tmp_path,
    )

    out = capsys.readouterr().out
    assert "git reset --hard baseline-artifacts" in out
    assert "echelon spec run --mode banzai" in out
    assert "echelon delivery run" not in out


def test_benchmark_dry_run_without_baseline_ref_prints_snapshot_wrapper(tmp_path: Path, capsys) -> None:
    _cmd_benchmark(
        [
            "run",
            "tiny-notes",
            "--variant",
            "baseline",
            "--dry-run",
        ],
        project_root=tmp_path,
    )

    out = capsys.readouterr().out
    assert "git add -u -- . :(exclude)runs :(exclude).harness-build-status.json" in out
    assert "git ls-files --others --exclude-standard -z | git add --pathspec-from-file=-" in out
    assert "git commit -m chore: snapshot workspace before benchmark" in out
    assert "git reset --hard BENCHMARK_BASELINE_SNAPSHOT" in out


def test_benchmark_rejects_unknown_variant(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _cmd_benchmark(["run", "tiny-notes", "--variant", "missing"], project_root=tmp_path)

    assert exc.value.code == 1
    assert "Unknown benchmark variant" in capsys.readouterr().err


def test_benchmark_rejects_unknown_context_render(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _cmd_benchmark(
            ["run", "tiny-notes", "--variant", "baseline", "--context-render", "bad"],
            project_root=tmp_path,
        )

    assert exc.value.code == 1
    assert "Unknown context render mode" in capsys.readouterr().err


def test_benchmark_suggests_run_subcommand_for_fixture_argument(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _cmd_benchmark(["tiny-notes"], project_root=tmp_path)

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Missing benchmark subcommand: run" in err
    assert "echelon benchmark run tiny-notes --variant baseline --baseline-ref <ref>" in err


def test_benchmark_requires_fixture_before_options(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _cmd_benchmark(["run", "--variant", "baseline"], project_root=tmp_path)

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Missing benchmark fixture id" in err
    assert "echelon benchmark run tiny-notes --variant baseline --baseline-ref <ref>" in err
    assert "Unknown benchmark argument" not in err


def test_benchmark_explains_fixture_used_as_variant(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _cmd_benchmark(["run", "tiny-notes", "--variant", "tiny-notes"], project_root=tmp_path)

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "tiny-notes is a fixture id, not a variant id" in err
    assert "Use --variant baseline" in err


def test_benchmark_run_allows_missing_baseline_ref(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_run_benchmark_variant(
        project_root: Path,
        fixture_id: str,
        variant_id: str,
        *,
        baseline_ref: str | None = None,
        artifact_only: bool = False,
        context_render: str = "bounded",
    ) -> Path:
        calls.append(
            {
                "project_root": project_root,
                "fixture_id": fixture_id,
                "variant_id": variant_id,
                "baseline_ref": baseline_ref,
                "artifact_only": artifact_only,
                "context_render": context_render,
            }
        )
        output_dir = tmp_path / "runs" / "benchmarks" / "fake" / variant_id
        output_dir.mkdir(parents=True)
        return output_dir

    monkeypatch.setattr("echelon.benchmark.run_benchmark_variant", fake_run_benchmark_variant)

    _cmd_benchmark(["run", "tiny-notes", "--variant", "baseline"], project_root=tmp_path)

    assert calls == [
        {
            "project_root": tmp_path,
            "fixture_id": "tiny-notes",
            "variant_id": "baseline",
            "baseline_ref": None,
            "artifact_only": False,
            "context_render": "bounded",
        }
    ]


def test_benchmark_run_passes_context_render(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_run_benchmark_variant(
        project_root: Path,
        fixture_id: str,
        variant_id: str,
        *,
        baseline_ref: str | None = None,
        artifact_only: bool = False,
        context_render: str = "bounded",
    ) -> Path:
        calls.append({"context_render": context_render, "variant_id": variant_id})
        output_dir = tmp_path / "runs" / "benchmarks" / "fake" / variant_id
        output_dir.mkdir(parents=True)
        return output_dir

    monkeypatch.setattr("echelon.benchmark.run_benchmark_variant", fake_run_benchmark_variant)

    _cmd_benchmark(
        ["run", "tiny-notes", "--variant", "baseline", "--context-render", "legacy"],
        project_root=tmp_path,
    )

    assert calls == [{"context_render": "legacy", "variant_id": "baseline"}]


def test_run_benchmark_variant_writes_summary_with_injected_runner(tmp_path: Path) -> None:
    commands: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...]) -> int:
        commands.append(command)
        if command[:3] == ("echelon", "spec", "run"):
            squad_dir = tmp_path / "runs" / "spec-20260704-120000-000001"
            squad_dir.mkdir(parents=True)
            (tmp_path / "runs" / ".current").write_text(f"{squad_dir.name}\n", encoding="utf-8")
            (squad_dir / "state.json").write_text(
                json.dumps({"run_id": "squad-1", "status": "done", "spec_id": "001"}),
                encoding="utf-8",
            )
        if command[:3] == ("echelon", "delivery", "run"):
            build_dir = tmp_path / "runs" / "build-20260704-130000-000001"
            state_dir = build_dir / "state"
            state_dir.mkdir(parents=True)
            (tmp_path / "runs" / ".current-build-001").write_text(f"{build_dir.name}\n", encoding="utf-8")
            (state_dir / "default.json").write_text(
                json.dumps({"run_id": "build-1", "status": "converged", "outer_iter": 2}),
                encoding="utf-8",
            )
        return 0

    output_dir = run_benchmark_variant(
        tmp_path,
        "tiny-notes",
        "constitution",
        baseline_ref="baseline-artifacts",
        runner=runner,
        timestamp="20260701-120000",
    )

    assert output_dir == tmp_path / "runs" / "benchmarks" / "20260701-120000-tiny-notes" / "constitution"
    assert commands[:2] == [
        ("git", "reset", "--hard", "baseline-artifacts"),
        ("git", "clean", "-fd", "-e", "runs/benchmarks/"),
    ]
    assert commands[2][:3] == ("echelon", "spec", "run")
    assert (
        "echelon",
        "phase",
        "run",
        "phase-exp-constitution-quality",
        "--spec",
        "001",
        "--mode",
        "banzai",
    ) in commands
    assert ("echelon", "delivery", "run", "001", "mode=banzai") in commands
    assert commands[-2:] == [
        ("git", "reset", "--hard", "baseline-artifacts"),
        ("git", "clean", "-fd", "-e", "runs/benchmarks/"),
    ]
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["variants"]["constitution"]["spec_id"] == "001"
    assert summary["variants"]["constitution"]["delivery_run_id"] == "build-1"
    assert (output_dir / "summary.md").exists()


def test_run_benchmark_variant_records_metrics_before_trailing_clean(tmp_path: Path) -> None:
    commands: list[tuple[str, ...]] = []

    def simulate_git_clean_removing_run_state() -> None:
        runs_dir = tmp_path / "runs"
        for marker in (runs_dir / ".current", runs_dir / ".current-build-001"):
            marker.unlink(missing_ok=True)
        for run_dir in runs_dir.glob("*"):
            if run_dir.name == "benchmarks":
                continue
            if run_dir.is_dir():
                shutil.rmtree(run_dir)

    def runner(command: tuple[str, ...]) -> int:
        commands.append(command)
        if command == ("git", "clean", "-fd", "-e", "runs/benchmarks/"):
            simulate_git_clean_removing_run_state()
        if command[:3] == ("echelon", "spec", "run"):
            squad_dir = tmp_path / "runs" / "spec-20260704-120000-000001"
            budget_dir = squad_dir / "context-budget"
            budget_dir.mkdir(parents=True)
            (tmp_path / "runs" / ".current").write_text(f"{squad_dir.name}\n", encoding="utf-8")
            (squad_dir / "state.json").write_text(
                json.dumps({"run_id": "squad-1", "status": "done", "spec_id": "001", "cost_usd": 2.5}),
                encoding="utf-8",
            )
            (budget_dir / "dispatch-001.json").write_text(
                json.dumps(
                    {
                        "selected_render_mode": "bounded",
                        "bounded": {"bytes": 1200, "approx_tokens": 300},
                        "savings": {"reduction_pct": 25},
                    }
                ),
                encoding="utf-8",
            )
        if command[:3] == ("echelon", "delivery", "run"):
            build_dir = tmp_path / "runs" / "build-20260704-130000-000001"
            state_dir = build_dir / "state"
            state_dir.mkdir(parents=True)
            (tmp_path / "runs" / ".current-build-001").write_text(f"{build_dir.name}\n", encoding="utf-8")
            (state_dir / "default.json").write_text(
                json.dumps({"run_id": "build-1", "status": "converged", "outer_iter": 2}),
                encoding="utf-8",
            )
        return 0

    output_dir = run_benchmark_variant(
        tmp_path,
        "tiny-notes",
        "baseline",
        baseline_ref="baseline-artifacts",
        runner=runner,
        timestamp="20260701-120000",
    )

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    record = summary["variants"]["baseline"]
    assert record["spec_id"] == "001"
    assert record["run_id"] == "squad-1"
    assert record["delivery_run_id"] == "build-1"
    assert record["context_prompt_bytes"] == 1200
    assert record["context_prompt_tokens_estimate"] == 300
    assert record["context_reduction_pct"] == 25
    assert commands[-2:] == [
        ("git", "reset", "--hard", "baseline-artifacts"),
        ("git", "clean", "-fd", "-e", "runs/benchmarks/"),
    ]
    assert not (tmp_path / "runs" / ".current").exists()


def test_run_benchmark_variant_both_uses_same_baseline_and_qualified_records(tmp_path: Path) -> None:
    commands: list[tuple[str, ...]] = []
    render_modes: list[str] = []

    def runner(command: tuple[str, ...]) -> int:
        commands.append(command)
        if command[:3] == ("echelon", "spec", "run"):
            render_modes.append(__import__("os").environ["ECHELON_CONTEXT_RENDER_MODE"])
            run_number = len(render_modes)
            squad_dir = tmp_path / "runs" / f"spec-20260704-120000-00000{run_number}"
            squad_dir.mkdir(parents=True)
            (tmp_path / "runs" / ".current").write_text(f"{squad_dir.name}\n", encoding="utf-8")
            (squad_dir / "state.json").write_text(
                json.dumps({"run_id": f"squad-{run_number}", "status": "done", "spec_id": f"00{run_number}"}),
                encoding="utf-8",
            )
        return 0

    output_dir = run_benchmark_variant(
        tmp_path,
        "tiny-notes",
        "baseline",
        baseline_ref="baseline-artifacts",
        runner=runner,
        timestamp="20260701-120000",
        artifact_only=True,
        context_render="both",
    )

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert output_dir == tmp_path / "runs" / "benchmarks" / "20260701-120000-tiny-notes" / "baseline"
    assert render_modes == ["legacy", "bounded"]
    assert set(summary["variants"]) == {"baseline:legacy", "baseline:bounded"}
    assert summary["variants"]["baseline:legacy"]["context_render"] == "legacy"
    assert summary["variants"]["baseline:legacy"]["base_variant_id"] == "baseline"
    assert summary["variants"]["baseline:bounded"]["context_render"] == "bounded"
    assert [command for command in commands if command[:3] == ("git", "reset", "--hard")] == [
        ("git", "reset", "--hard", "baseline-artifacts"),
        ("git", "reset", "--hard", "baseline-artifacts"),
        ("git", "reset", "--hard", "baseline-artifacts"),
        ("git", "reset", "--hard", "baseline-artifacts"),
    ]


def test_run_benchmark_variant_artifact_only_skips_delivery(tmp_path: Path) -> None:
    commands: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...]) -> int:
        commands.append(command)
        if command[:3] == ("echelon", "spec", "run"):
            squad_dir = tmp_path / "runs" / "spec-20260704-120000-000001"
            squad_dir.mkdir(parents=True)
            (tmp_path / "runs" / ".current").write_text(f"{squad_dir.name}\n", encoding="utf-8")
            (squad_dir / "state.json").write_text(
                json.dumps({"run_id": "squad-1", "status": "done", "spec_id": "001"}),
                encoding="utf-8",
            )
        return 0

    output_dir = run_benchmark_variant(
        tmp_path,
        "tiny-notes",
        "baseline",
        baseline_ref="baseline-artifacts",
        runner=runner,
        timestamp="20260701-120000",
        artifact_only=True,
    )

    assert not any(command[:3] == ("echelon", "delivery", "run") for command in commands)
    assert commands[-2:] == [
        ("git", "reset", "--hard", "baseline-artifacts"),
        ("git", "clean", "-fd", "-e", "runs/benchmarks/"),
    ]
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    baseline = summary["variants"]["baseline"]
    assert baseline["status"] == "complete"
    assert baseline["spec_id"] == "001"
    assert baseline["delivery_run_id"] == ""
    assert baseline["build_dispatches"] == 0


def test_run_benchmark_variant_snapshots_workspace_when_baseline_ref_missing(tmp_path: Path) -> None:
    subprocess_run = __import__("subprocess").run
    subprocess_run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess_run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    subprocess_run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess_run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess_run(["git", "commit", "-m", "Initial commit from Specify template"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("/runs/\n", encoding="utf-8")
    config_path = tmp_path / ".echelon" / "config.yml"
    config_path.parent.mkdir()
    config_path.write_text("deploy:\n  enabled: false\n", encoding="utf-8")

    commands: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...]) -> int:
        commands.append(command)
        if command[:3] == ("echelon", "spec", "run"):
            squad_dir = tmp_path / "runs" / "spec-20260704-120000-000001"
            squad_dir.mkdir(parents=True)
            (tmp_path / "runs" / ".current").write_text(f"{squad_dir.name}\n", encoding="utf-8")
            (squad_dir / "state.json").write_text(
                json.dumps({"run_id": "squad-1", "status": "done", "spec_id": "001"}),
                encoding="utf-8",
            )
        if command[:3] == ("echelon", "delivery", "run"):
            build_dir = tmp_path / "runs" / "build-20260704-130000-000001"
            state_dir = build_dir / "state"
            state_dir.mkdir(parents=True)
            (tmp_path / "runs" / ".current-build-001").write_text(f"{build_dir.name}\n", encoding="utf-8")
            (state_dir / "default.json").write_text(
                json.dumps({"run_id": "build-1", "status": "converged"}),
                encoding="utf-8",
            )
        return 0

    run_benchmark_variant(
        tmp_path,
        "tiny-notes",
        "baseline",
        runner=runner,
        timestamp="20260701-120000",
    )

    subject = subprocess_run(
        ["git", "log", "-1", "--format=%s"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    body = subprocess_run(
        ["git", "log", "-1", "--format=%B"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert subject == "chore: snapshot workspace before benchmark"
    assert "Co-authored-by: Echelon <echelon@b3cognition.dev>" in body
    assert config_path.exists()
    assert commands[0][:3] == ("git", "reset", "--hard")
    assert commands[1] == ("git", "clean", "-fd", "-e", "runs/benchmarks/")
    assert commands[-2][:3] == ("git", "reset", "--hard")
    assert commands[-1] == ("git", "clean", "-fd", "-e", "runs/benchmarks/")


def test_benchmark_baseline_snapshot_ignores_existing_runs_dir(tmp_path: Path) -> None:
    subprocess_run = __import__("subprocess").run
    subprocess_run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / ".gitignore").write_text("/runs/\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "transient.txt").write_text("runtime\n", encoding="utf-8")

    ref = snapshot_benchmark_baseline(tmp_path)

    assert ref
    tracked = subprocess_run(
        ["git", "ls-files"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert ".gitignore" in tracked
    assert "README.md" in tracked
    assert not any(path.startswith("runs/") for path in tracked)


def test_run_benchmark_variant_resets_after_failed_variant(tmp_path: Path) -> None:
    commands: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...]) -> int:
        commands.append(command)
        if command[:3] == ("echelon", "spec", "run"):
            return 9
        return 0

    output_dir = run_benchmark_variant(
        tmp_path,
        "tiny-notes",
        "constitution",
        baseline_ref="baseline-artifacts",
        runner=runner,
        timestamp="20260701-120000",
    )

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))

    assert summary["variants"]["constitution"]["status"] == "failed"
    assert commands[-2:] == [
        ("git", "reset", "--hard", "baseline-artifacts"),
        ("git", "clean", "-fd", "-e", "runs/benchmarks/"),
    ]


def test_run_benchmark_variant_stops_when_spec_run_exits_zero_but_blocks(
    tmp_path: Path,
) -> None:
    commands: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...]) -> int:
        commands.append(command)
        if command[:3] == ("echelon", "spec", "run"):
            squad_dir = tmp_path / "runs" / "spec-20260704-120000-000001"
            squad_dir.mkdir(parents=True)
            (tmp_path / "runs" / ".current").write_text(f"{squad_dir.name}\n", encoding="utf-8")
            (squad_dir / "state.json").write_text(
                json.dumps(
                    {
                        "run_id": "squad-1",
                        "status": "blocked",
                        "phase": "terminal-blocked",
                        "spec_id": "001",
                        "blocked_reason": "phase3-consensus failed",
                    }
                ),
                encoding="utf-8",
            )
        return 0

    output_dir = run_benchmark_variant(
        tmp_path,
        "tiny-notes",
        "baseline",
        baseline_ref="baseline-artifacts",
        runner=runner,
        timestamp="20260701-120000",
    )

    assert not any(command[:3] == ("echelon", "delivery", "run") for command in commands)
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    baseline = summary["variants"]["baseline"]
    assert baseline["status"] == "failed"
    assert baseline["failure_kind"] == "spec_run_blocked"


def test_latest_summary_path_and_load_summary(tmp_path: Path) -> None:
    older = tmp_path / "runs" / "benchmarks" / "20260701-120000-tiny-notes" / "baseline"
    newer = tmp_path / "runs" / "benchmarks" / "20260702-120000-tiny-notes" / "baseline"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    (older / "summary.json").write_text('{"best_variant": "baseline", "variants": {}}\n', encoding="utf-8")
    (newer / "summary.json").write_text(
        '{"best_variant": "constitution", "variants": {"constitution": {"status": "complete"}}}\n',
        encoding="utf-8",
    )

    assert latest_summary_path(tmp_path) == newer / "summary.json"
    assert load_summary(newer)["best_variant"] == "constitution"


def test_load_saved_scorecard_uses_latest_record_per_variant(tmp_path: Path) -> None:
    old_baseline = tmp_path / "runs" / "benchmarks" / "20260701-120000-tiny-notes" / "baseline"
    new_baseline = tmp_path / "runs" / "benchmarks" / "20260702-120000-tiny-notes" / "baseline"
    constitution = tmp_path / "runs" / "benchmarks" / "20260703-120000-tiny-notes" / "constitution"
    old_baseline.mkdir(parents=True)
    new_baseline.mkdir(parents=True)
    constitution.mkdir(parents=True)
    (old_baseline / "summary.json").write_text(
        json.dumps(
            {
                "best_variant": "baseline",
                "variants": {"baseline": {"status": "complete", "fulfillment_gaps": 3}},
            }
        ),
        encoding="utf-8",
    )
    (new_baseline / "summary.json").write_text(
        json.dumps(
            {
                "best_variant": "baseline",
                "variants": {"baseline": {"status": "complete", "fulfillment_gaps": 1}},
            }
        ),
        encoding="utf-8",
    )
    (constitution / "summary.json").write_text(
        json.dumps(
            {
                "best_variant": "constitution",
                "variants": {"constitution": {"status": "complete", "fulfillment_gaps": 0}},
            }
        ),
        encoding="utf-8",
    )

    scorecard = load_saved_scorecard(tmp_path)

    assert scorecard["best_variant"] == "constitution"
    assert scorecard["variants"]["baseline"]["fulfillment_gaps"] == 1
    assert scorecard["variants"]["constitution"]["fulfillment_gaps"] == 0


def test_benchmark_show_prints_saved_summary(tmp_path: Path, capsys) -> None:
    summary_dir = tmp_path / "runs" / "benchmarks" / "20260702-120000-tiny-notes" / "baseline"
    summary_dir.mkdir(parents=True)
    (summary_dir / "summary.json").write_text(
        json.dumps(
            {
                "best_variant": "baseline",
                "variants": {
                    "baseline": {
                        "status": "complete",
                        "spec_id": "001",
                        "delivery_run_id": "build-1",
                        "fulfillment_gaps": 0,
                        "verification_failures": 0,
                        "blocked_states": 0,
                        "retries": 0,
                        "build_dispatches": 2,
                        "elapsed_seconds": 12.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    _cmd_benchmark(["show"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "BENCHMARK SUMMARY" in out
    assert "best_variant" in out
    assert "baseline" in out
    assert "build-1" in out
