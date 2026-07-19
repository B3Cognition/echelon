from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from echelon.wiki.discovery import discover_wiki_model
from echelon.wiki.render import render_wiki, validate_rendered_links


def _write_yaml(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _workspace(tmp_path: Path) -> tuple[Path, object]:
    _write_yaml(
        tmp_path / ".echelon/config.yml",
        {"sources": [{"id": "api", "path": "sources/api"}]},
    )
    spec = tmp_path / "specs/001-demo"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text(
        "---\nstatus: phase_a\n---\n# 001 Demo\n\n## Requirements\n\n- **FR-001** Work.\n",
        encoding="utf-8",
    )
    (spec / "plan.md").write_text("# Plan\n", encoding="utf-8")
    (spec / "tasks.md").write_text("# Tasks\n\n- [ ] T-001 Work\n", encoding="utf-8")
    (spec / "risk-matrix.md").write_text("# Risks\n", encoding="utf-8")
    (spec / "verification-summary.md").write_text("# Verification\n", encoding="utf-8")
    _write_yaml(spec / "targets.yml", {"targets": ["api"]})
    model = discover_wiki_model(tmp_path, generated_at="2026-07-18T10:00:00Z")
    return tmp_path, model


@pytest.mark.unit
def test_render_writes_navigation_views_and_self_contained_projection(tmp_path: Path) -> None:
    project_root, model = _workspace(tmp_path)
    output = tmp_path / "out"

    result = render_wiki(model, project_root, output)

    assert result.required_pages == (
        "Home.md",
        "Reverse Engineering/Index.md",
        "Specs/Index.md",
        "Views/Active Work.md",
        "Views/Decisions.md",
        "Views/Requirements.md",
        "Views/Risks and Issues.md",
        "Views/Verification.md",
        "Warnings.md",
    )
    home = (output / "Home.md").read_text(encoding="utf-8")
    assert "[001 Demo](Specs/001-demo/Overview.md)" in home
    assert "Recent Changes" in home
    overview = (output / "Specs/001-demo/Overview.md").read_text(encoding="utf-8")
    assert "Lifecycle status: `phase_a`" in overview
    assert "Implementation targets: `api`" in overview
    projection = output / "Artifacts/specs/001-demo/spec.md"
    assert "Canonical source: `specs/001-demo/spec.md`" in projection.read_text()
    assert (output / ".obsidian/app.json").is_file()
    assert validate_rendered_links(output) == ()


@pytest.mark.unit
def test_render_writes_reverse_engineering_source_and_domain_pages(tmp_path: Path) -> None:
    project_root, _model = _workspace(tmp_path)
    re_spec = project_root / "re/sources/api/specs/auth/spec.md"
    re_spec.parent.mkdir(parents=True)
    re_spec.write_text("# Authentication Domain\n", encoding="utf-8")
    (project_root / "re/index.json").write_text(
        '{"sources":{"api":{"published_path":"re/sources/api"}}}\n',
        encoding="utf-8",
    )
    model = discover_wiki_model(project_root, generated_at="2026-07-18T10:00:00Z")

    render_wiki(model, project_root, tmp_path / "out")

    re_index = (tmp_path / "out/Reverse Engineering/Index.md").read_text()
    assert "[api](Sources/api.md)" in re_index
    assert "[Authentication Domain](Domains/api--auth.md)" in re_index
    source_page = (tmp_path / "out/Reverse Engineering/Sources/api.md").read_text()
    assert "Published artifacts: `re/sources/api`" in source_page
    assert "[Authentication Domain](../Domains/api--auth.md)" in source_page
    domain_page = (tmp_path / "out/Reverse Engineering/Domains/api--auth.md").read_text()
    assert "[Open canonical projection](../../Artifacts/re/sources/api/specs/auth/spec.md)" in domain_page
    assert validate_rendered_links(tmp_path / "out") == ()


@pytest.mark.unit
def test_projection_preserves_frontmatter_and_fenced_code(tmp_path: Path) -> None:
    project_root, _model = _workspace(tmp_path)
    source = project_root / "specs/001-demo/spec.md"
    source.write_text(
        "---\nstatus: phase_a\n---\n# Spec\n```md\n[not a link](missing.md)\n```\n",
        encoding="utf-8",
    )
    model = discover_wiki_model(project_root, generated_at="2026-07-18T10:00:00Z")

    render_wiki(model, project_root, tmp_path / "out")

    rendered = (tmp_path / "out/Artifacts/specs/001-demo/spec.md").read_text(
        encoding="utf-8"
    )
    assert rendered.startswith("---\nstatus: phase_a\n---\n")
    assert "Canonical source: `specs/001-demo/spec.md`" in rendered
    assert "```md\n[not a link](missing.md)\n```" in rendered
    assert validate_rendered_links(tmp_path / "out") == ()


@pytest.mark.unit
def test_render_catalogs_oversized_attachment_without_copying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, _model = _workspace(tmp_path)
    attachment = project_root / "specs/001-demo/large.pdf"
    attachment.write_bytes(b"pdf")
    monkeypatch.setattr("echelon.wiki.discovery.MAX_COPIED_ATTACHMENT_BYTES", 1)
    model = discover_wiki_model(project_root, generated_at="2026-07-18T10:00:00Z")

    result = render_wiki(model, project_root, tmp_path / "out")

    assert not (tmp_path / "out/Artifacts/specs/001-demo/large.pdf").exists()
    assert any(warning.code == "attachment-catalogued" for warning in result.warnings)
    artifacts = (tmp_path / "out/Specs/001-demo/Artifacts.md").read_text(encoding="utf-8")
    assert "large.pdf" in artifacts
    assert "catalogued" in artifacts


@pytest.mark.unit
def test_link_validator_reports_missing_local_target(tmp_path: Path) -> None:
    (tmp_path / "Home.md").write_text(
        "# Home\n\n[Missing](Specs/missing.md)\n", encoding="utf-8"
    )

    warnings = validate_rendered_links(tmp_path)

    assert len(warnings) == 1
    assert warnings[0].code == "broken-link"
    assert warnings[0].source_path == "Home.md"
