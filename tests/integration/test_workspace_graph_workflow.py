from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.unit.test_re_publication import write_valid_re_run
from tests.unit.test_spec_publish import _create_spec_branch, _git, _init_repo


class _MemoryCollection:
    """Minimal in-memory stand-in for the external MemPalace collection."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, dict[str, object]]] = {}

    def get(
        self,
        ids: list[str] | None = None,
        where: dict[str, object] | None = None,
        include: list[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, list[object]]:
        rows = self.rows.items()
        if ids is not None:
            rows = ((drawer_id, self.rows[drawer_id]) for drawer_id in ids if drawer_id in self.rows)
        elif where is not None:
            rows = (
                (drawer_id, row)
                for drawer_id, row in rows
                if all(
                    row[1].get(key)
                    == (expected.get("$eq") if isinstance(expected, dict) else expected)
                    for key, expected in where.items()
                )
            )
        selected = list(rows)
        if limit is not None:
            selected = selected[:limit]
        return {
            "ids": [drawer_id for drawer_id, _row in selected],
            "documents": [document for _drawer_id, (document, _metadata) in selected],
            "metadatas": [metadata for _drawer_id, (_document, metadata) in selected],
        }

    def delete(self, ids: list[str]) -> None:
        for drawer_id in ids:
            self.rows.pop(drawer_id, None)


class _MemoryWriter:
    """External storage boundary used by the real Echelon mining adapters."""

    def __init__(self, collection: _MemoryCollection, wing: str) -> None:
        self.collection = collection
        self.wing = wing

    def get_collection_read_only(self) -> _MemoryCollection:
        return self.collection

    def write_exact(
        self,
        *,
        room: str,
        content: str,
        phase: str,
        drawer_id: str,
        spec_sha256: str,
        requirement_id: str,
        provenance_type: str,
        source_file: str,
        extra_metadata: dict[str, object] | None,
    ) -> SimpleNamespace:
        metadata = dict(extra_metadata or {})
        metadata.update(
            {
                "artifact_path": metadata.get("artifact_path", source_file),
                "canonical": True,
                "canonical_spec_sha256": spec_sha256,
                "deterministic_identity_schema_version": 1,
                "lifecycle_status": metadata.get("lifecycle_status", "active"),
                "phase": phase,
                "provenance_type": provenance_type,
                "requirement_content_sha256": hashlib.sha256(
                    content.encode("utf-8")
                ).hexdigest(),
                "requirement_id": requirement_id,
                "room": room,
                "source_file": source_file,
                "wing": self.wing,
            }
        )
        existing = self.collection.rows.get(drawer_id)
        if existing == (content, metadata):
            return SimpleNamespace(outcome="already_present", drawer_id=drawer_id)
        self.collection.rows[drawer_id] = (content, metadata)
        return SimpleNamespace(outcome="written", drawer_id=drawer_id)

    def verify_exact(
        self,
        *,
        room: str,
        content: str,
        drawer_id: str,
        spec_sha256: str,
        requirement_id: str,
    ) -> SimpleNamespace:
        row = self.collection.rows.get(drawer_id)
        if row is None:
            return SimpleNamespace(outcome="drift", drawer_id=None)
        document, metadata = row
        if (
            document == content
            and metadata.get("room") == room
            and metadata.get("canonical_spec_sha256") == spec_sha256
            and metadata.get("requirement_id") == requirement_id
        ):
            return SimpleNamespace(outcome="already_present", drawer_id=drawer_id)
        return SimpleNamespace(outcome="drift", drawer_id=None)


def _write_verify_evidence(root: Path, spec_id: str) -> Path:
    verify_dir = root / "runs" / f"verify-{spec_id}" / "verify-spec" / spec_id
    verify_dir.mkdir(parents=True)
    (verify_dir / "state.json").write_text('{"status": "complete"}\n', encoding="utf-8")
    (verify_dir / "implementation-map.md").write_text(
        "# Implementation Map\n\nFixture evidence for the published specification.\n",
        encoding="utf-8",
    )
    return verify_dir


def _publish_fixture_workspace(root: Path) -> str:
    (root / ".echelon").mkdir()
    (root / ".echelon" / "config.yml").write_text(
        "mempalace:\n  wing: fixture-workspace\nworkspace:\n  git_role: orchestration\n"
        "sources:\n  - id: fixture-source\n    path: sources/fixture-source\n",
        encoding="utf-8",
    )
    _git(root, "add", ".echelon/config.yml")
    _git(root, "commit", "-m", "chore: configure fixture workspace")

    spec_id = "001-fixture"
    _create_spec_branch(
        root,
        spec_id,
        "---\nstatus: landed\n---\n# Fixture specification\n\n"
        "- **FR-001**: Validate fixture import records.\n",
        extra_files={
            f"specs/{spec_id}/tasks.md": (
                "- [ ] T-001 complexity=standard phase=build req=FR-001 depends=none\n"
            ),
            f"specs/{spec_id}/inputs/manifest.json": '{"schema_version": 1}\n',
            f"specs/{spec_id}/inputs/catalog.json": (
                '{"schema_version": 1, "units": [{"id": "IN-REQ-001"}]}\n'
            ),
            f"specs/{spec_id}/inputs/traceability.json": (
                '{"schema_version": 1, "requirements": [{"input_unit_id": '
                '"IN-REQ-001", "disposition": "included", "spec_ids": '
                '["FR-001"], "task_ids": ["T-001"], "targets": []}]}\n'
            ),
            f"specs/{spec_id}/verified-fulfillment-ledger.json": (
                '{"schema_version": 1, "rows": [{"requirement_id": "FR-001", '
                '"status": "IMPLEMENTED", "evidence_refs": ["fixture"], '
                '"verified_commit": "fixture", "verify_scope": "full"}]}\n'
            ),
        },
    )

    from echelon.spec_publish import publish_specs
    from harness.re_publication import publish_re_run

    spec_publication = publish_specs(root, identity=spec_id)
    assert spec_publication.created_commit is True
    published_spec_id = spec_publication.published[0].spec_id

    re_publication = publish_re_run(
        root,
        write_valid_re_run(root, ("fixture-source",), run_id="fixture-re"),
    )
    assert re_publication.generation == 1

    from echelon.mempalace_spec_evidence import publish_spec_evidence_package

    evidence_publication = publish_spec_evidence_package(
        root,
        published_spec_id,
        run_id=_write_verify_evidence(root, published_spec_id).parents[1].name,
    )
    assert evidence_publication.status == "published"
    return published_spec_id


@pytest.mark.integration
def test_workspace_graph_cli_runs_the_published_workspace_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _init_repo(tmp_path)
    spec_id = _publish_fixture_workspace(root)
    collection = _MemoryCollection()
    writer = _MemoryWriter(collection, "fixture-workspace")

    monkeypatch.chdir(root)
    monkeypatch.setattr(
        "echelon.spec_memory_miner.SpecMemoryMiner._get_writer",
        lambda _miner: writer,
    )
    monkeypatch.setattr(
        "echelon.spec_memory_miner.check_wing_collision",
        lambda *args: [],
    )

    from echelon.cli_app import app

    runner = CliRunner()
    refreshed = runner.invoke(app, ["graph", "workspace", "refresh", "--write"])

    assert refreshed.exit_code == 0, refreshed.output
    assert "requirements_memory (pass)" in refreshed.output
    assert "evidence_memory (pass)" in refreshed.output
    assert "re_memory (pass)" in refreshed.output
    assert "spec_graph (pass)" in refreshed.output

    graph_path = (
        root
        / ".echelon"
        / "runtime"
        / "graph"
        / "workspace-artifact-graph.json"
    )
    workspace_graph_bytes = graph_path.read_bytes()
    workspace_graph = json.loads(workspace_graph_bytes)
    members = workspace_graph["members"]
    assert members and all(member["included"] for member in members)
    assert {member["spec_id"] for member in members} == {spec_id}
    assert all((root / member["graph_path"]).is_file() for member in members)

    requirement = next(
        node for node in workspace_graph["nodes"] if node["type"] == "Requirement"
    )
    requirement_id = requirement["id"]
    requirement_phrase = requirement["properties"]["source_text"].partition(":")[2].strip()
    linked_edges = [
        edge
        for edge in workspace_graph["edges"]
        if edge["source"] == requirement_id or edge["target"] == requirement_id
    ]
    artifact_id = next(
        edge["target"]
        for edge in linked_edges
        if edge["source"] == requirement_id and edge["type"] == "DERIVED_FROM"
    )
    task_id = next(
        edge["source"]
        for edge in linked_edges
        if edge["target"] == requirement_id and edge["type"] == "IMPLEMENTS"
    )

    query = runner.invoke(app, ["graph", "query", requirement_phrase, "--json"])
    assert query.exit_code == 0, query.output
    query_payload = json.loads(query.output)
    queried_requirement = next(
        node for node in query_payload["nodes"] if node["id"] == requirement_id
    )

    explain = runner.invoke(
        app, ["graph", "explain", queried_requirement["id"], "--json"]
    )
    assert explain.exit_code == 0, explain.output
    explain_payload = json.loads(explain.output)
    explained_requirement = next(
        node for node in explain_payload["nodes"] if node["id"] == requirement_id
    )
    assert explained_requirement["properties"]
    assert explained_requirement["properties"] == requirement["properties"]
    assert explain_payload["edges"]
    assert any(
        edge["source"] == requirement_id or edge["target"] == requirement_id
        for edge in explain_payload["edges"]
    )

    path = runner.invoke(
        app, ["graph", "path", requirement_id, artifact_id, "--json"]
    )
    assert path.exit_code == 0, path.output
    path_payload = json.loads(path.output)
    assert path_payload["paths"]
    selected_path = path_payload["paths"][0]
    assert selected_path["node_ids"][0] == requirement_id
    assert selected_path["node_ids"][-1] == artifact_id
    assert selected_path["steps"]
    assert selected_path["steps"][0]["source"] == requirement_id
    assert selected_path["steps"][-1]["target"] == artifact_id

    neighbors = runner.invoke(app, ["graph", "neighbors", task_id, "--json"])
    impact = runner.invoke(app, ["graph", "impact", requirement_id, "--json"])
    assert neighbors.exit_code == impact.exit_code == 0
    assert any(node["id"] == requirement_id for node in json.loads(neighbors.output)["nodes"])
    assert any(node["id"] == task_id for node in json.loads(impact.output)["nodes"])

    cytoscape_view = runner.invoke(
        app,
        [
            "graph",
            "workspace",
            "view",
            "--renderer",
            "cytoscape",
            "--no-open",
        ],
    )
    vis_view = runner.invoke(
        app,
        ["graph", "workspace", "view", "--renderer", "vis", "--no-open"],
    )
    assert cytoscape_view.exit_code == vis_view.exit_code == 0
    assert (graph_path.parent / "workspace.html").is_file()
    assert (graph_path.parent / "workspace-vis.html").is_file()

    member_graph_bytes = {
        member["graph_path"]: (root / member["graph_path"]).read_bytes()
        for member in members
    }
    repeated_refresh = runner.invoke(
        app, ["graph", "workspace", "refresh", "--write"]
    )
    assert repeated_refresh.exit_code == 0, repeated_refresh.output
    assert graph_path.read_bytes() == workspace_graph_bytes
    assert {
        path: (root / path).read_bytes() for path in member_graph_bytes
    } == member_graph_bytes
