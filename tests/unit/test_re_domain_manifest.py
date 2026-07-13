from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_domain_manifest import discover_source_domains, load_domain_manifest, write_domain_manifest
from harness.re_fingerprint import ReFingerprintProfile, fingerprint_source
from harness.re_planner import RePlanSource


def _source(tmp_path: Path) -> RePlanSource:
    source_root = tmp_path / "sources" / "platform"
    source_root.mkdir(parents=True)
    fingerprint = fingerprint_source(source_root, ReFingerprintProfile())
    return RePlanSource(
        id="platform",
        path="sources/platform",
        absolute_path=str(source_root),
        action="refresh",
        fingerprint=fingerprint,
        cache_path=str(tmp_path / "cache"),
        dirty=False,
        selected=True,
        classification="refresh",
    )


@pytest.mark.unit
def test_discovery_requires_a_domain_for_each_independent_source_component(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    root = Path(source.absolute_path)
    for component in ("apps/api", "apps/web", "libs/shared"):
        (root / component / "package.json").parent.mkdir(parents=True, exist_ok=True)
        (root / component / "package.json").write_text("{}\n", encoding="utf-8")
        (root / component / "src").mkdir()
        (root / component / "src" / "main.ts").write_text("export {};\n", encoding="utf-8")

    manifest = discover_source_domains(source)

    assert [(domain.domain_id, domain.root) for domain in manifest.domains] == [
        ("001-re-apps-api", "apps/api"),
        ("002-re-apps-web", "apps/web"),
        ("003-re-libs-shared", "libs/shared"),
    ]


@pytest.mark.unit
def test_discovery_uses_one_root_domain_when_source_has_no_component_manifest(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    root = Path(source.absolute_path)
    (root / "src").mkdir()
    (root / "src" / "service.py").write_text("def run():\n    return None\n", encoding="utf-8")

    manifest = discover_source_domains(source)

    assert [(domain.domain_id, domain.root) for domain in manifest.domains] == [
        ("001-re-src", "src"),
    ]


@pytest.mark.unit
def test_discovery_splits_a_large_root_package_into_logical_code_domains(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    root = Path(source.absolute_path)
    (root / "package.json").write_text("{}\n", encoding="utf-8")
    for domain in ("pages", "queries", "shared"):
        directory = root / domain
        directory.mkdir()
        (directory / "one.ts").write_text("export {};\n", encoding="utf-8")
        (directory / "two.ts").write_text("export {};\n", encoding="utf-8")

    manifest = discover_source_domains(source)

    assert [(domain.domain_id, domain.root) for domain in manifest.domains] == [
        ("001-re-pages", "pages"),
        ("002-re-queries", "queries"),
        ("003-re-shared", "shared"),
    ]


@pytest.mark.unit
def test_discovery_descends_through_single_source_container_before_splitting(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    root = Path(source.absolute_path)
    (root / "package.json").write_text("{}\n", encoding="utf-8")
    for domain in ("src/api", "src/events"):
        directory = root / domain
        directory.mkdir(parents=True)
        (directory / "one.ts").write_text("export {};\n", encoding="utf-8")
        (directory / "two.ts").write_text("export {};\n", encoding="utf-8")

    manifest = discover_source_domains(source)

    assert [(domain.domain_id, domain.root) for domain in manifest.domains] == [
        ("001-re-src-api", "src/api"),
        ("002-re-src-events", "src/events"),
    ]


@pytest.mark.unit
def test_logical_partition_includes_graphql_and_excludes_mock_only_roots(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    root = Path(source.absolute_path)
    (root / "package.json").write_text("{}\n", encoding="utf-8")
    for domain in ("pages", "queries", "mocks"):
        directory = root / domain
        directory.mkdir()
        suffix = ".graphql" if domain == "queries" else ".ts"
        (directory / f"one{suffix}").write_text("query One { id }\n", encoding="utf-8")
        (directory / f"two{suffix}").write_text("query Two { id }\n", encoding="utf-8")

    manifest = discover_source_domains(source)

    assert [domain.root for domain in manifest.domains] == ["pages", "queries"]


@pytest.mark.unit
def test_discovery_preserves_code_outside_manifest_owned_components(tmp_path: Path) -> None:
    source = _source(tmp_path)
    root = Path(source.absolute_path)
    (root / "apps" / "api" / "src").mkdir(parents=True)
    (root / "apps" / "api" / "package.json").write_text("{}\n", encoding="utf-8")
    (root / "apps" / "api" / "src" / "main.ts").write_text("export {};\n", encoding="utf-8")
    (root / "apps" / "legacy" / "src").mkdir(parents=True)
    (root / "apps" / "legacy" / "src" / "worker.py").write_text("pass\n", encoding="utf-8")

    manifest = discover_source_domains(source)

    assert [(domain.domain_id, domain.root) for domain in manifest.domains] == [
        ("001-re-apps-api", "apps/api"),
        ("002-re-apps-legacy", "apps/legacy"),
    ]


@pytest.mark.unit
def test_discovery_splits_an_oversized_component_before_deep_specification(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    root = Path(source.absolute_path)
    for component in ("apps/api", "apps/web"):
        (root / component).mkdir(parents=True)
        (root / component / "package.json").write_text("{}\n", encoding="utf-8")
    for child in ("handlers", "models"):
        directory = root / "apps/api" / child
        directory.mkdir()
        for number in range(2):
            (directory / f"file-{number}.ts").write_text(
                "export const value = true;\n" * 2_000,
                encoding="utf-8",
            )
    (root / "apps/web" / "main.ts").write_text("export {};\n", encoding="utf-8")

    manifest = discover_source_domains(source)

    assert [(domain.domain_id, domain.root) for domain in manifest.domains] == [
        ("001-re-apps-api-handlers", "apps/api/handlers"),
        ("002-re-apps-api-models", "apps/api/models"),
        ("003-re-apps-web", "apps/web"),
    ]


@pytest.mark.unit
def test_discovery_excludes_hidden_directories_and_root_tooling_from_component_domains(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    root = Path(source.absolute_path)
    (root / "package.json").write_text('{"workspaces":["apps/*"]}\n', encoding="utf-8")
    (root / "workspace.mjs").write_text("export {};\n", encoding="utf-8")
    (root / "apps" / "web" / "src").mkdir(parents=True)
    (root / "apps" / "web" / "package.json").write_text("{}\n", encoding="utf-8")
    (root / "apps" / "web" / "src" / "main.ts").write_text("export {};\n", encoding="utf-8")
    (root / ".github" / "skills").mkdir(parents=True)
    (root / ".github" / "skills" / "logger.ts").write_text("export {};\n", encoding="utf-8")
    (root / ".claude" / "hooks").mkdir(parents=True)
    (root / ".claude" / "hooks" / "tool.py").write_text("pass\n", encoding="utf-8")

    manifest = discover_source_domains(source)

    assert [(domain.domain_id, domain.root) for domain in manifest.domains] == [
        ("001-re-apps-web", "apps/web"),
    ]
    assert manifest.domains[0].source_file_count == 1


@pytest.mark.unit
def test_discovery_folds_nested_helper_packages_into_their_code_owning_parent(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    root = Path(source.absolute_path)
    (root / "apps" / "service" / "src").mkdir(parents=True)
    (root / "apps" / "service" / "package.json").write_text("{}\n", encoding="utf-8")
    (root / "apps" / "service" / "src" / "main.ts").write_text("export {};\n", encoding="utf-8")
    (root / "apps" / "service" / "scripts" / "tool").mkdir(parents=True)
    (root / "apps" / "service" / "scripts" / "tool" / "package.json").write_text("{}\n", encoding="utf-8")
    (root / "apps" / "service" / "scripts" / "tool" / "index.ts").write_text("export {};\n", encoding="utf-8")

    manifest = discover_source_domains(source)

    assert [(domain.domain_id, domain.root) for domain in manifest.domains] == [
        ("001-re-apps-service", "apps/service"),
    ]




@pytest.mark.unit
def test_manifest_round_trip_rejects_duplicate_component_roots(tmp_path: Path) -> None:
    path = tmp_path / "domain-manifest.json"
    path.write_text(
        """{
  "schema_version": 1,
  "source_id": "api",
  "source_path": "sources/api",
  "domains": [
    {"domain_id": "001-re-api", "root": "src", "source_file_count": 1, "source_line_count": 1},
    {"domain_id": "002-re-worker", "root": "src", "source_file_count": 1, "source_line_count": 1}
  ]
}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unique"):
        load_domain_manifest(path)

    source = _source(tmp_path)
    root = Path(source.absolute_path)
    (root / "src").mkdir()
    (root / "src" / "main.ts").write_text("export {};\n", encoding="utf-8")
    manifest = discover_source_domains(source)
    write_domain_manifest(path, manifest)
    assert load_domain_manifest(path) == manifest
