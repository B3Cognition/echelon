from __future__ import annotations

import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


def test_load_stack_catalog_includes_bundled_and_serializable_definitions() -> None:
    from echelon.stack_service import load_stack_catalog, stack_definition_to_dict

    project_root = Path(__file__).resolve().parents[2]

    catalog = load_stack_catalog(project_root)
    playbook = stack_definition_to_dict(catalog["statsperform-playbook"])

    assert playbook["id"] == "statsperform-playbook"
    assert playbook["detection"]["positive"]["technologies"] == ["playbook"]
    assert playbook["requirements"] == {
        "commands": ["npx"],
        "registries": ["statsperform-nexus"],
    }


def test_detect_stack_candidates_returns_report_and_optional_written_paths(
    tmp_path: Path,
) -> None:
    from echelon.stack_service import detect_stack_candidates

    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {
                    "react": "latest",
                    "@statsperform/react-playbook": "latest",
                }
            }
        ),
        encoding="utf-8",
    )

    outcome = detect_stack_candidates(
        tmp_path,
        target=tmp_path,
        artifact_roots=[],
        write_report=True,
    )

    assert outcome.report.suggested_config == {
        "stacks": {
            "selected": ["statsperform-playbook"],
            "target_archetypes": ["web_app"],
        }
    }
    assert outcome.written is not None
    assert outcome.written.yaml_path.is_file()
    assert outcome.written.markdown_path.is_file()


def test_preflight_stacks_returns_typed_no_selection_outcome(tmp_path: Path) -> None:
    from echelon.stack_service import preflight_stacks

    outcome = preflight_stacks(
        tmp_path,
        selected=[],
        target_archetypes=[],
        from_detection=None,
        target_root=None,
        probe_tools=False,
        environment={},
    )

    assert outcome.resolved is None
    assert outcome.result is None
    assert outcome.message == (
        "No Echelon stacks selected. Use --stack <id> or configure stacks.selected."
    )


def test_provision_stacks_returns_generated_files_and_final_statuses(
    tmp_path: Path,
) -> None:
    from echelon.stack_service import provision_stacks

    outcome = provision_stacks(
        tmp_path,
        selected=["game-persistence-postgres"],
        target_root=tmp_path,
        force=False,
        environment={},
    )

    assert outcome.message is None
    assert [path.name for path in outcome.generated] == [
        "docker-compose.echelon-verify.yml",
        ".env.echelon-verify.example",
    ]
    assert [status.state for status in outcome.statuses] == ["prepared"]
    assert (tmp_path / "docker-compose.echelon-verify.yml").is_file()
    assert (tmp_path / ".env.echelon-verify.example").is_file()


def test_change_and_read_stack_selection_use_committed_workspace_config(
    tmp_path: Path,
) -> None:
    from echelon.stack_service import change_selected_stacks, read_selected_stacks

    config_dir = tmp_path / ".echelon"
    config_dir.mkdir()
    (config_dir / "config.yml").write_text(
        "stacks:\n  selected: []\n",
        encoding="utf-8",
    )

    changed = change_selected_stacks(
        tmp_path,
        ["statsperform-playbook"],
        operation="enable",
        dry_run=False,
    )
    loaded = read_selected_stacks(tmp_path)

    assert changed.explicit == ["statsperform-playbook"]
    assert loaded.explicit == ["statsperform-playbook"]
    assert loaded.resolved == ["statsperform-playbook"]
    assert "- statsperform-playbook" in (config_dir / "config.yml").read_text(
        encoding="utf-8"
    )
