from __future__ import annotations

import json

from harness.canonical_requirements import write_canonical_requirements


def test_write_canonical_requirements_extracts_stable_ids_from_spec_inputs(tmp_path):
    spec_dir = tmp_path / "specs" / "001-demo"
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    spec_dir.mkdir(parents=True)
    verify_run_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "## Requirements\n\n"
        "- **FR-001**: Users can start a mission.\n"
        "- **NFR-002**: Startup stays below 500ms.\n"
        "### Edge Cases\n"
        "- EDGE-004: Invalid fuel is rejected.\n",
        encoding="utf-8",
    )
    (spec_dir / "plan.md").write_text(
        "## Architecture Decisions\n\n"
        "- AD-001 supports FR-001 but is not a requirement row.\n",
        encoding="utf-8",
    )
    (spec_dir / "coverage-map.md").write_text(
        "| Requirement | Source |\n"
        "| --- | --- |\n"
        "| FR-003 | coverage note |\n",
        encoding="utf-8",
    )
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-001,FR-005 depends=none\n",
        encoding="utf-8",
    )

    result = write_canonical_requirements(spec_dir=spec_dir, verify_run_dir=verify_run_dir)

    assert result.count == 5
    payload = json.loads((verify_run_dir / "canonical-requirements.json").read_text())
    assert [row["id"] for row in payload["requirements"]] == [
        "EDGE-004",
        "FR-001",
        "FR-003",
        "FR-005",
        "NFR-002",
    ]
    markdown = (verify_run_dir / "canonical-requirements.md").read_text()
    assert "| FR-005 | task_metadata | tasks.md |" in markdown
