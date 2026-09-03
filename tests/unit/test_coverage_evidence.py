from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from harness.coverage_evidence import (
    build_coverage_evidence,
    write_coverage_evidence,
)


def _write_map(spec_dir: Path, rows: str) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "coverage-map.md").write_text(
        "# Coverage Map\n\n"
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "|---|---|---|---|---|---|---|\n"
        + rows,
        encoding="utf-8",
    )


@pytest.mark.unit
def test_build_coverage_evidence_expands_ranges_and_preserves_test_ids(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_map(
        spec_dir,
        "| FR-001–FR-003 | E-SMOKE-001 / E-VIS-001..004 | e2e | automated | automated | test-results/playwright.json | |\n",
    )

    result = build_coverage_evidence(
        spec_dir=spec_dir,
        canonical_ids=("FR-001", "FR-002", "FR-003", "FR-004"),
        deferred_ids=set(),
    )

    assert result.by_requirement["FR-001"].status == "automated"
    assert result.by_requirement["FR-003"].test_case_ids == (
        "E-SMOKE-001",
        "E-VIS-001..004",
    )
    assert result.by_requirement["FR-004"].status == "missing"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("automation", "coverage", "expected"),
    [
        ("deferred-automation", "deferred-automation", "deferred"),
        ("escalate", "escalate", "escalated"),
        ("automated", "deferred-automation", "contradictory"),
        ("automated", "automated", "automated"),
    ],
)
def test_build_coverage_evidence_classifies_declared_status(
    tmp_path: Path,
    automation: str,
    coverage: str,
    expected: str,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_map(
        spec_dir,
        f"| FR-001 | E-001 | e2e | {automation} | {coverage} | tests/e2e/demo.spec.ts | repair |\n",
    )

    result = build_coverage_evidence(
        spec_dir=spec_dir,
        canonical_ids=("FR-001",),
        deferred_ids=set(),
    )

    assert result.by_requirement["FR-001"].status == expected


@pytest.mark.unit
def test_automated_coverage_without_evidence_is_contradictory(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_map(
        spec_dir,
        "| FR-001 | E-001 | e2e | automated | automated | | none |\n",
    )

    result = build_coverage_evidence(
        spec_dir=spec_dir,
        canonical_ids=("FR-001",),
        deferred_ids=set(),
    )

    assert result.by_requirement["FR-001"].status == "contradictory"
    assert "evidence" in result.by_requirement["FR-001"].reason


@pytest.mark.unit
def test_owner_controlled_deferral_overrides_candidate_coverage_status(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_map(
        spec_dir,
        "| FR-001 | E-001 | e2e | deferred-automation | deferred-automation | planned | later |\n",
    )

    result = build_coverage_evidence(
        spec_dir=spec_dir,
        canonical_ids=("FR-001",),
        deferred_ids={"FR-001"},
    )

    assert result.by_requirement["FR-001"].status == "owner_deferred"


@pytest.mark.unit
def test_write_coverage_evidence_emits_deterministic_json_and_markdown(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    verify_dir = tmp_path / "runs" / "verify"
    _write_map(
        spec_dir,
        "| FR-001 | E-001 | e2e | deferred-automation | deferred-automation | planned | implement |\n",
    )

    result = write_coverage_evidence(
        spec_dir=spec_dir,
        verify_run_dir=verify_dir,
        canonical_ids=("FR-001", "FR-002"),
        deferred_ids=set(),
    )
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))

    assert payload["requirements"]["FR-001"]["status"] == "deferred"
    assert payload["requirements"]["FR-002"]["status"] == "missing"
    assert "| FR-001 | deferred |" in result.markdown_path.read_text(
        encoding="utf-8"
    )


@pytest.mark.unit
def test_write_coverage_evidence_cli_uses_canonical_inventory(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    verify_dir = tmp_path / "runs" / "verify"
    verify_dir.mkdir(parents=True)
    _write_map(
        spec_dir,
        "| FR-001 | E-001 | e2e | automated | automated | tests/e2e/demo.spec.ts | |\n",
    )
    (verify_dir / "canonical-requirements.json").write_text(
        json.dumps({"requirements": [{"id": "FR-001"}]}),
        encoding="utf-8",
    )
    (verify_dir / "state.json").write_text("{}\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness",
            "write-coverage-evidence",
            str(spec_dir),
            str(verify_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (verify_dir / "coverage-evidence.json").is_file()
    state = json.loads((verify_dir / "state.json").read_text(encoding="utf-8"))
    assert state["coverage_evidence"] == "ready"
