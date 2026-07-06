from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from harness.stacks import load_stack_definitions
from harness.stacks.detection import (
    detect_stacks,
    detection_report_from_file,
    detection_report_to_yaml,
    render_detection_markdown,
    write_detection_report,
)


ROOT = Path(__file__).resolve().parents[2]
EXTENSION_ROOT = ROOT / "extension"


def _definitions():
    return load_stack_definitions(extension_root=EXTENSION_ROOT)


def _write_package_json(path: Path, dependencies: dict[str, str]) -> None:
    path.write_text(
        json.dumps(
            {
                "scripts": {"build": "nx build web"},
                "dependencies": dependencies,
                "devDependencies": {"nx": "latest", "@nx/next": "latest"},
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.unit
def test_detects_source_tree_stacks_and_keeps_msa_out_for_nestjs(tmp_path: Path) -> None:
    _write_package_json(
        tmp_path / "package.json",
        {
            "react": "latest",
            "next": "latest",
            "@statsperform/react-playbook": "latest",
            "@nestjs/core": "latest",
            "pg": "latest",
        },
    )
    (tmp_path / "nx.json").write_text("{}", encoding="utf-8")
    (tmp_path / "Legacy.Api.csproj").write_text("<Project />", encoding="utf-8")

    report = detect_stacks(
        target=tmp_path,
        stack_definitions=_definitions(),
    )

    observed_ids = {stack.id for stack in report.observed_stacks}
    assert "playbook-design-system" in observed_ids
    assert "nextjs-nx-webapp" in observed_ids
    assert "nestjs-api-service" in observed_ids
    assert "postgres-data-store" in observed_ids
    assert "legacy-dotnet-api" in observed_ids

    matching = {stack.id: stack for stack in report.matching_echelon_stacks}
    assert matching["statsperform-playbook"].recommendation == "adopt"
    assert "statsperform-msa-service" not in matching

    modernization = {stack.id: stack for stack in report.modernization_candidates}
    assert modernization["statsperform-stark-webapp"].recommendation == "consider"
    assert report.suggested_config == {
        "stacks": {
            "selected": ["statsperform-playbook"],
            "target_archetypes": ["web_app"],
        }
    }


@pytest.mark.unit
def test_artifact_detection_blocks_adoption_when_target_stack_unresolved(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "specs" / "000-re-overview"
    artifacts.mkdir(parents=True)
    (artifacts / "overview.md").write_text(
        "\n".join(
            [
                "# Overview",
                "| Area | Technology |",
                "|---|---|",
                "| Frontend | React, TypeScript, Next.js, Nx, Playbook |",
                "| Backend | NestJS, tRPC, PostgreSQL |",
            ]
        ),
        encoding="utf-8",
    )
    (artifacts / "validation-report.md").write_text(
        "Target stack selection requires human input before adoption.",
        encoding="utf-8",
    )

    report = detect_stacks(
        target=tmp_path,
        stack_definitions=_definitions(),
        artifact_roots=[artifacts],
    )

    assert any(decision.code == "TARGET_STACK_UNRESOLVED" for decision in report.decisions_required)
    assert "statsperform-playbook" in {stack.id for stack in report.matching_echelon_stacks}
    assert "statsperform-stark-webapp" in {
        stack.id for stack in report.modernization_candidates
    }
    assert "statsperform-msa-service" not in {
        stack.id for stack in report.matching_echelon_stacks
    }
    assert report.suggested_config is None


@pytest.mark.unit
def test_detection_report_yaml_round_trips(tmp_path: Path) -> None:
    _write_package_json(
        tmp_path / "package.json",
        {
            "react": "latest",
            "@statsperform/react-playbook": "latest",
        },
    )

    report = detect_stacks(target=tmp_path, stack_definitions=_definitions())

    payload = yaml.safe_load(detection_report_to_yaml(report))
    assert payload == report.to_dict()
    written = write_detection_report(report, project_root=tmp_path)
    assert detection_report_from_file(written.yaml_path).to_dict() == report.to_dict()


@pytest.mark.unit
def test_render_detection_markdown_summarizes_matches(tmp_path: Path) -> None:
    _write_package_json(
        tmp_path / "package.json",
        {
            "react": "latest",
            "@statsperform/react-playbook": "latest",
        },
    )

    markdown = render_detection_markdown(
        detect_stacks(target=tmp_path, stack_definitions=_definitions())
    )

    assert "Matching Echelon stacks" in markdown
    assert "statsperform-playbook" in markdown


@pytest.mark.unit
def test_detection_report_is_no_match_without_evidence(tmp_path: Path) -> None:
    report = detect_stacks(target=tmp_path, stack_definitions=_definitions())

    assert report.status == "no_match"
    assert report.suggested_config is None
    assert report.observed_stacks == []
