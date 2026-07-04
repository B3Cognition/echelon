from __future__ import annotations

import json
from pathlib import Path

import pytest

from echelon.benchmark import (
    BenchmarkRunRecord,
    list_fixtures,
    list_variants,
    plan_variant_commands,
    run_benchmark_variant,
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
    assert plan.commands[0][:2] == ("echelon", "run")
    assert plan.commands[-1][:3] == ("echelon", "harness", "run")


def test_plans_constitution_tasks_adrs_with_ordered_phases() -> None:
    plan = plan_variant_commands("tiny-notes", "constitution-tasks-adrs")

    assert plan.phase_ids == (
        "phase-exp-constitution-quality",
        "phase-exp-tasks-quality",
        "phase-exp-adr-quality",
    )
    assert ("echelon", "phase", "run", "phase-exp-constitution-quality") in plan.commands
    assert ("echelon", "phase", "run", "phase-exp-tasks-quality") in plan.commands
    assert ("echelon", "phase", "run", "phase-exp-adr-quality") in plan.commands


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
    assert "| baseline | complete | 8 | 2 | 1 | 2 | 3 | 600.0 |" in md_path.read_text(encoding="utf-8")


def test_benchmark_list_prints_fixtures_and_variants(tmp_path: Path, capsys) -> None:
    _cmd_benchmark(["list"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "Fixtures:" in out
    assert "Variants (--variant <id>):" in out
    assert "tiny-notes" in out
    assert "baseline" in out
    assert "constitution-tasks-adrs" in out
    assert "echelon benchmark run tiny-notes --variant baseline --baseline-ref <ref>" in out


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
    assert "echelon run" in out
    assert "phase-exp-constitution-quality" in out
    assert "phase-exp-tasks-quality" in out
    assert "echelon harness run RESOLVE_SPEC_ID_FROM_CURRENT_RUN" in out


def test_benchmark_rejects_unknown_variant(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _cmd_benchmark(["run", "tiny-notes", "--variant", "missing"], project_root=tmp_path)

    assert exc.value.code == 1
    assert "Unknown benchmark variant" in capsys.readouterr().err


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


def test_benchmark_real_run_requires_baseline_ref(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _cmd_benchmark(["run", "tiny-notes", "--variant", "baseline"], project_root=tmp_path)

    assert exc.value.code == 1
    assert "--baseline-ref" in capsys.readouterr().err


def test_run_benchmark_variant_writes_summary_with_injected_runner(tmp_path: Path) -> None:
    commands: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...]) -> int:
        commands.append(command)
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
    assert commands[2][:2] == ("echelon", "run")
    assert ("echelon", "phase", "run", "phase-exp-constitution-quality") in commands
    assert commands[-2:] == [
        ("git", "reset", "--hard", "baseline-artifacts"),
        ("git", "clean", "-fd", "-e", "runs/benchmarks/"),
    ]
    assert (output_dir / "summary.json").exists()
    assert (output_dir / "summary.md").exists()


def test_run_benchmark_variant_resets_after_failed_variant(tmp_path: Path) -> None:
    commands: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...]) -> int:
        commands.append(command)
        if command[:2] == ("echelon", "run"):
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
