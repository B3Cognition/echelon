"""Project-aware quality gate resolution for the Understanding CLI."""

from pathlib import Path

import understanding.cli as cli


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
