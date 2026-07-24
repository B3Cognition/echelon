"""Project-aware quality gate resolution for the Understanding CLI."""

from io import StringIO
from pathlib import Path

import understanding.cli as cli
from rich.console import Console


def test_understanding_uses_nearest_project_quality_gate_config(tmp_path: Path) -> None:
    config = tmp_path / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "quality_gates:\n"
        "  overall: 0.91\n"
        "  structure: 0.92\n"
        "  testability: 0.93\n",
        encoding="utf-8",
    )
    spec = tmp_path / "runs" / "run-1" / "specs" / "001-demo" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Spec\n", encoding="utf-8")

    configure = getattr(cli, "_configure_quality_gates_for_spec", None)
    assert configure is not None

    original = dict(cli.QUALITY_GATES)
    try:
        configure(spec)
        assert cli.QUALITY_GATES["overall"] == 0.91
        assert cli.QUALITY_GATES["structure"] == 0.92
        assert cli.QUALITY_GATES["testability"] == 0.93
        assert cli.QUALITY_GATES["semantic"] == original["semantic"]
        assert not cli._check_quality_gates(
            {
                "overall_weighted_average": 0.92,
                "category_averages": {
                    "structure": 0.91,
                    "testability": 0.94,
                    "semantic": 0.90,
                    "cognitive": 0.90,
                    "readability": 0.90,
                },
            }
        )
    finally:
        cli.QUALITY_GATES.clear()
        cli.QUALITY_GATES.update(original)


def test_understanding_cli_enforces_depth_and_behavioral_gates() -> None:
    metrics = {
        "overall_weighted_average": 0.92,
        "category_averages": {
            "structure": 0.92,
            "testability": 0.92,
            "semantic": 0.92,
            "cognitive": 0.92,
            "readability": 0.92,
            "depth": cli.QUALITY_GATES["depth"] - 0.01,
            "behavioral": cli.QUALITY_GATES["behavioral"] - 0.01,
        },
    }

    assert cli._check_quality_gates(metrics) is False


def test_human_validation_output_displays_all_eight_gates(
    tmp_path: Path, monkeypatch,
) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text("# Spec\n", encoding="utf-8")
    output = StringIO()
    monkeypatch.setattr(
        cli,
        "console",
        Console(file=output, force_terminal=False, color_system=None, width=120),
    )
    categories = {
        key: 0.90
        for key in (
            "structure",
            "testability",
            "semantic",
            "cognitive",
            "readability",
            "depth",
            "behavioral",
        )
    }

    cli._print_test_result(
        {
            "spec_path": str(spec),
            "metrics": {
                "overall_weighted_average": 0.90,
                "category_averages": categories,
            },
        }
    )

    gate_output = output.getvalue().split("Quality Gates", maxsplit=1)[1]
    assert "Depth" in gate_output
    assert "Behavioral" in gate_output
