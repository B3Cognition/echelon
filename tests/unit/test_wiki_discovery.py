from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from echelon.wiki.discovery import canonical_input_hashes, discover_wiki_model
from echelon.wiki.model import WikiWarning


def _write_yaml(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_spec(
    path: Path,
    *,
    status: str = "phase_a",
    title: str = "Demo Feature",
) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "spec.md").write_text(
        f"---\nstatus: {status}\n---\n# {title}\n\n## Requirements\n\n- **FR-001** Do it.\n",
        encoding="utf-8",
    )
    (path / "plan.md").write_text("# Plan\n", encoding="utf-8")
    (path / "tasks.md").write_text("# Tasks\n\n- [ ] T-001 Build it\n", encoding="utf-8")
    return path


@pytest.mark.unit
def test_discovery_uses_local_source_override_without_leaking_secrets(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / ".echelon/config.yml",
        {
            "workspace": {"git_role": "orchestration"},
            "sources": [{"id": "api", "path": "sources/api"}],
            "llm": {"api_key": "committed-secret"},
        },
    )
    _write_yaml(
        tmp_path / ".echelon/local.yml",
        {
            "sources": [{"id": "web", "path": "sources/web"}],
            "deploy": {"token": "local-secret"},
        },
    )
    _write_spec(tmp_path / "specs/001-demo")

    model = discover_wiki_model(tmp_path, generated_at="2026-07-18T10:00:00Z")

    assert [(source.source_id, source.path) for source in model.sources] == [
        ("web", "sources/web")
    ]
    serialized = repr(model)
    assert "committed-secret" not in serialized
    assert "local-secret" not in serialized


@pytest.mark.unit
def test_discovery_namespaces_ids_and_records_explicit_target_relationship(
    tmp_path: Path,
) -> None:
    _write_yaml(
        tmp_path / ".echelon/config.yml",
        {"sources": [{"id": "api", "path": "sources/api"}]},
    )
    spec = _write_spec(tmp_path / "specs/001-demo", status="ready_to_land")
    _write_yaml(spec / "targets.yml", {"targets": ["api"]})

    model = discover_wiki_model(tmp_path, generated_at="2026-07-18T10:00:00Z")

    assert model.specs[0].stable_id == "spec:001-demo"
    assert model.specs[0].lifecycle_status == "ready_to_land"
    assert model.specs[0].requirement_ids == ("001-demo:FR-001",)
    assert model.specs[0].task_ids == ("001-demo:T-001",)
    assert any(
        edge.kind == "targets"
        and edge.source_id == "spec:001-demo"
        and edge.target_id == "source:api"
        and edge.evidence_path == "specs/001-demo/targets.yml"
        for edge in model.relationships
    )


@pytest.mark.unit
def test_discovery_reads_spec_publication_provenance(tmp_path: Path) -> None:
    _write_yaml(tmp_path / ".echelon/config.yml", {"sources": []})
    spec = _write_spec(tmp_path / "specs/003-search")
    (spec / ".echelon-publication.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "spec_id": "003-search",
                "source_branch": "003-search",
                "source_commit": "a" * 40,
            }
        ),
        encoding="utf-8",
    )

    model = discover_wiki_model(tmp_path, generated_at="2026-07-19T10:00:00Z")

    assert model.specs[0].publication_branch == "003-search"
    assert model.specs[0].publication_commit == "a" * 40
    assert not any(
        warning.code == "invalid-spec-publication" for warning in model.warnings
    )


@pytest.mark.unit
def test_discovery_warns_and_ignores_mismatched_publication_manifest(
    tmp_path: Path,
) -> None:
    _write_yaml(tmp_path / ".echelon/config.yml", {"sources": []})
    spec = _write_spec(tmp_path / "specs/003-search")
    manifest = spec / ".echelon-publication.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "spec_id": "003-other",
                "source_branch": "003-other",
                "source_commit": "not-a-commit",
            }
        ),
        encoding="utf-8",
    )

    model = discover_wiki_model(tmp_path, generated_at="2026-07-19T10:00:00Z")

    assert model.specs[0].publication_branch is None
    assert model.specs[0].publication_commit is None
    warnings = [
        warning
        for warning in model.warnings
        if warning.code == "invalid-spec-publication"
    ]
    assert warnings == [
        WikiWarning(
            "invalid-spec-publication",
            "Publication manifest is invalid or does not match its spec directory.",
            "specs/003-search/.echelon-publication.json",
        )
    ]


@pytest.mark.unit
def test_discovery_records_structured_traceability_dependencies_and_deferrals(
    tmp_path: Path,
) -> None:
    _write_yaml(tmp_path / ".echelon/config.yml", {"sources": []})
    spec = _write_spec(tmp_path / "specs/001-demo")
    (spec / "spec.md").write_text(
        "# Demo\n\nREQ: FR-001\nDEPENDS: none\n\nREQ: FR-002\nDEPENDS: FR-001\n",
        encoding="utf-8",
    )
    (spec / "tasks.md").write_text("# Tasks\n\n- [x] T-001 Build it\n", encoding="utf-8")
    (spec / "traceability-matrix.md").write_text(
        "# Traceability\n\n"
        "| Requirement | Task | Source Location | Test File | Status |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| FR-001 | T-001 | `src/demo.py` | `tests/test_demo.py` | COVERED |\n",
        encoding="utf-8",
    )
    (spec / "deferred-scope.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "entry_id": "DS-001",
                        "status": "deferred",
                        "selected_ids": ["FR-002"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    model = discover_wiki_model(tmp_path, generated_at="2026-07-18T10:00:00Z")
    edges = {(edge.kind, edge.source_id, edge.target_id): edge for edge in model.relationships}

    assert ("depends_on", "001-demo:FR-002", "001-demo:FR-001") in edges
    assert ("implements", "001-demo:T-001", "001-demo:FR-001") in edges
    assert (
        "verifies",
        "artifact:specs/001-demo/traceability-matrix.md",
        "001-demo:FR-001",
    ) in edges
    assert ("defers", "spec:001-demo", "001-demo:FR-002") in edges
    assert edges[("defers", "spec:001-demo", "001-demo:FR-002")].evidence_key == (
        "entries:DS-001:selected_ids:FR-002"
    )


@pytest.mark.unit
def test_discovery_reads_published_re_sources_and_domains(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / ".echelon/config.yml",
        {"sources": [{"id": "api", "path": "sources/api"}]},
    )
    re_root = tmp_path / "re"
    (re_root / "sources/api/specs/search").mkdir(parents=True)
    (re_root / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generation": 2,
                "sources": {
                    "api": {
                        "path": "sources/api",
                        "published_path": "re/sources/api",
                        "manifest": "re/sources/api/manifest.json",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (re_root / "sources/api/manifest.json").write_text(
        json.dumps({"source_id": "api"}), encoding="utf-8"
    )
    (re_root / "sources/api/specs/search/spec.md").write_text(
        "# Search Domain\n", encoding="utf-8"
    )

    model = discover_wiki_model(tmp_path, generated_at="2026-07-18T10:00:00Z")

    assert model.sources[0].published_path == "re/sources/api"
    assert [(domain.stable_id, domain.title) for domain in model.domains] == [
        ("domain:api:search", "Search Domain")
    ]


@pytest.mark.unit
def test_canonical_hashes_ignore_runtime_re_directories_and_reject_escaping_symlinks(
    tmp_path: Path,
) -> None:
    _write_yaml(tmp_path / ".echelon/config.yml", {"sources": []})
    _write_spec(tmp_path / "specs/001-demo")
    ignored = tmp_path / "re/.cache/heavy.md"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("ignored\n", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("secret\n", encoding="utf-8")
    link = tmp_path / "specs/001-demo/escape.md"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("symlinks unavailable")

    hashes = canonical_input_hashes(tmp_path)
    model = discover_wiki_model(tmp_path, generated_at="2026-07-18T10:00:00Z")

    assert "re/.cache/heavy.md" not in hashes
    assert "specs/001-demo/escape.md" not in hashes
    assert any(warning.code == "path-escape" for warning in model.warnings)


@pytest.mark.unit
def test_recent_changes_come_from_git_and_dirty_worktree_not_mtime(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "wiki@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Wiki Test"], cwd=tmp_path, check=True
    )
    _write_yaml(tmp_path / ".echelon/config.yml", {"sources": []})
    spec = _write_spec(tmp_path / "specs/001-demo")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "docs: publish demo spec"], cwd=tmp_path, check=True
    )
    (spec / "tasks.md").write_text("# Tasks\n\n- [x] T-001 Done\n", encoding="utf-8")

    model = discover_wiki_model(tmp_path, generated_at="2026-07-18T10:00:00Z")

    assert model.recent_changes[0].commit == "WORKTREE"
    assert model.recent_changes[0].paths == ("specs/001-demo/tasks.md",)
    assert any(change.subject == "docs: publish demo spec" for change in model.recent_changes)
