from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from echelon.spec_graph import build_spec_graph, write_spec_graph
from echelon.spec_graph_audit import audit_spec_graph


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


@pytest.mark.integration
def test_spec_graph_reconciles_source_memory_and_graph_refreshes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec_dir = tmp_path / "specs" / "101-generic"
    spec_dir.mkdir(parents=True)
    spec_file = spec_dir / "spec.md"
    spec_file.write_text("- **FR-001**: Generate a report.\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-001 depends=none\n",
        encoding="utf-8",
    )
    memory = {"artifact_hash": _sha256(spec_file)}

    class FakeAdapter:
        wing = "generic-wing"

        def plan_canonical_rows(self, content, *, source, artifact_metadata):
            return [
                SimpleNamespace(
                    drawer_id="drawer-fr-001",
                    requirement_id="FR-001",
                    room="functional-requirements",
                    source=source,
                    artifact_hash=artifact_metadata["artifact_hash"],
                    canonical_spec_sha256=hashlib.sha256(content).hexdigest(),
                    requirement_content_sha256="content-hash",
                )
            ]

        def plan_canonical_support_rows(self, content, *, source, artifact_metadata):
            return []

    def audit_memory(project_root, selector):
        current_hash = _sha256(spec_file)
        stale = current_hash != memory["artifact_hash"]
        return SimpleNamespace(
            schema_version=1,
            wing="generic-wing",
            status="fail" if stale else "pass",
            expected_count=1,
            present_current_count=0 if stale else 1,
            missing=[],
            stale=["drawer-fr-001"] if stale else [],
            wrong_wing=[],
            wrong_room=[],
            duplicate=[],
            non_canonical=[],
            lifecycle_excluded=[],
            errors=[],
        )

    import echelon.mempalace_audit  # noqa: F401

    monkeypatch.setattr(
        "echelon.mempalace_requirements.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(),
    )
    monkeypatch.setattr(
        "echelon.mempalace_audit.audit_spec_memory",
        audit_memory,
    )

    initial = build_spec_graph(tmp_path, spec_dir)
    write_spec_graph(initial, spec_dir)
    assert audit_spec_graph(tmp_path, spec_dir).status == "pass"

    spec_file.write_text(
        "- **FR-001**: Generate a machine-readable report.\n",
        encoding="utf-8",
    )
    stale_memory = audit_spec_graph(tmp_path, spec_dir)
    stale_codes = {finding.code for finding in stale_memory.findings}
    assert "graph_source_set_stale" in stale_codes
    assert "mempalace_reconciliation_failed" in stale_codes

    memory["artifact_hash"] = _sha256(spec_file)
    refreshed_memory = audit_spec_graph(tmp_path, spec_dir)
    refreshed_codes = {finding.code for finding in refreshed_memory.findings}
    assert "graph_source_set_stale" in refreshed_codes
    assert "graph_memory_state_stale" in refreshed_codes
    assert "mempalace_reconciliation_failed" not in refreshed_codes

    rebuilt = build_spec_graph(tmp_path, spec_dir)
    write_spec_graph(rebuilt, spec_dir)
    final = audit_spec_graph(tmp_path, spec_dir)
    assert final.status == "pass"
    assert final.findings == ()
