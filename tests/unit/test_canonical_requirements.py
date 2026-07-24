from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from harness.canonical_requirements import (
    write_canonical_requirements,
    write_requirement_audit,
)


def _run_harness(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_path = str(Path(__file__).resolve().parents[2] / "src")
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    )
    return subprocess.run(
        [sys.executable, "-m", "harness", *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


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


def test_write_canonical_requirements_ignores_ids_extended_by_lowercase_prose(
    tmp_path,
):
    spec_dir = tmp_path / "specs" / "001-demo"
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "- **FR-001**: Users can start a mission.\n",
        encoding="utf-8",
    )
    (spec_dir / "coverage-map.md").write_text(
        "| Requirement | Limitation |\n"
        "| --- | --- |\n"
        "| FR-001 | This does not create a second NFR-001-violating path. |\n",
        encoding="utf-8",
    )

    result = write_canonical_requirements(
        spec_dir=spec_dir, verify_run_dir=verify_run_dir
    )

    assert result.count == 1
    payload = json.loads((verify_run_dir / "canonical-requirements.json").read_text())
    assert [row["id"] for row in payload["requirements"]] == ["FR-001"]


def test_write_requirement_audit_renders_deterministic_audit_table(tmp_path):
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    verify_run_dir.mkdir(parents=True)
    (verify_run_dir / "canonical-requirements.json").write_text(
        json.dumps(
            {
                "requirements": [
                    {
                        "id": "EDGE-004",
                        "source_kind": "spec",
                        "source_file": "spec.md",
                        "source_line": 8,
                        "source_text": "EDGE-004: Invalid fuel is rejected.",
                    },
                    {
                        "id": "FR-001",
                        "source_kind": "spec",
                        "source_file": "spec.md",
                        "source_line": 3,
                        "source_text": "- **FR-001**: Users can start a mission.",
                    },
                    {
                        "id": "NFR-002",
                        "source_kind": "spec",
                        "source_file": "spec.md",
                        "source_line": 4,
                        "source_text": "- **NFR-002**: Startup stays below 500ms.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = write_requirement_audit(verify_run_dir=verify_run_dir)

    assert result.count == 3
    audit = result.audit_path.read_text(encoding="utf-8")
    assert "| ID | Category | Source | Requirement | Acceptance Signal |" in audit
    assert "| EDGE-004 | edge_case | spec.md:8 | Invalid fuel is rejected. | Source-defined observable behavior for EDGE-004. |" in audit
    assert "| FR-001 | functional | spec.md:3 | Users can start a mission. | Source-defined observable behavior for FR-001. |" in audit
    assert "| NFR-002 | non_functional | spec.md:4 | Startup stays below 500ms. | Source-defined observable behavior for NFR-002. |" in audit


def test_write_requirement_audit_cli_uses_canonical_inventory(tmp_path):
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    verify_run_dir.mkdir(parents=True)
    (verify_run_dir / "canonical-requirements.json").write_text(
        json.dumps(
            {
                "requirements": [
                    {
                        "id": "FR-001",
                        "source_kind": "spec",
                        "source_file": "spec.md",
                        "source_line": 3,
                        "source_text": "- **FR-001**: Users can start a mission.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (verify_run_dir / "state.json").write_text("{}", encoding="utf-8")

    completed = _run_harness(["write-requirement-audit", str(verify_run_dir)])

    assert completed.returncode == 0, completed.stderr
    assert "OK: wrote requirement audit" in completed.stdout
    audit = (verify_run_dir / "requirement-audit.md").read_text(encoding="utf-8")
    assert "| FR-001 | functional | spec.md:3 | Users can start a mission. |" in audit


def test_write_canonical_requirements_cli_stamps_state(tmp_path):
    spec_dir = tmp_path / "specs" / "001-demo"
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    spec_dir.mkdir(parents=True)
    verify_run_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "- **FR-001**: Users can start a mission.\n",
        encoding="utf-8",
    )
    (verify_run_dir / "state.json").write_text("{}", encoding="utf-8")

    completed = _run_harness(
        ["write-canonical-requirements", str(spec_dir), str(verify_run_dir)]
    )

    assert completed.returncode == 0, completed.stderr
    state = json.loads((verify_run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["canonical_requirements"] == "ready"
    assert state["canonical_requirements_count"] == 1


def test_write_canonical_requirements_cli_fails_when_verify_state_missing(tmp_path):
    spec_dir = tmp_path / "specs" / "001-demo"
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    spec_dir.mkdir(parents=True)
    verify_run_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "- **FR-001**: Users can start a mission.\n",
        encoding="utf-8",
    )

    completed = _run_harness(
        ["write-canonical-requirements", str(spec_dir), str(verify_run_dir)]
    )

    assert completed.returncode == 1
    assert "state.json missing" in completed.stderr
    assert not (verify_run_dir / "state.json").exists()
    assert not (verify_run_dir / "canonical-requirements.json").exists()
    assert not (verify_run_dir / "canonical-requirements.md").exists()


def test_write_requirement_audit_cli_stamps_state(tmp_path):
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    verify_run_dir.mkdir(parents=True)
    (verify_run_dir / "canonical-requirements.json").write_text(
        json.dumps(
            {
                "requirements": [
                    {
                        "id": "FR-001",
                        "source_kind": "spec",
                        "source_file": "spec.md",
                        "source_line": 3,
                        "source_text": "- **FR-001**: Users can start a mission.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (verify_run_dir / "state.json").write_text("{}", encoding="utf-8")

    completed = _run_harness(["write-requirement-audit", str(verify_run_dir)])

    assert completed.returncode == 0, completed.stderr
    state = json.loads((verify_run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["requirement_audit"] == "ready"
    assert state["requirement_audit_count"] == 1


def test_write_requirement_audit_cli_fails_before_writing_when_state_missing(tmp_path):
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    verify_run_dir.mkdir(parents=True)
    (verify_run_dir / "canonical-requirements.json").write_text(
        json.dumps(
            {
                "requirements": [
                    {
                        "id": "FR-001",
                        "source_kind": "spec",
                        "source_file": "spec.md",
                        "source_line": 3,
                        "source_text": "- **FR-001**: Users can start a mission.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    completed = _run_harness(["write-requirement-audit", str(verify_run_dir)])

    assert completed.returncode == 1
    assert "state.json missing" in completed.stderr
    assert not (verify_run_dir / "requirement-audit.md").exists()
