from __future__ import annotations

from pathlib import Path

from harness.re_architecture import (
    ARCHITECTURE_CATALOG_VERSION,
    build_re_architecture_map,
    load_re_architecture_map,
    write_re_architecture_catalog,
)
from harness.re_fingerprint import ReFingerprintProfile, SourceFingerprint
from harness.re_planner import ReExecutionPlan, RePlanSource


def _plan(root: Path) -> ReExecutionPlan:
    profile = ReFingerprintProfile()
    fingerprint = SourceFingerprint(
        value="a" * 64,
        kind="file-tree",
        dirty=False,
        profile_hash=profile.profile_hash(),
    )
    source = RePlanSource(
        id="api",
        path="sources/api",
        absolute_path=str(root / "sources" / "api"),
        action="refresh",
        fingerprint=fingerprint,
        cache_path=".cache/sources/api/" + fingerprint.value,
        dirty=False,
        selected=True,
        classification="refresh",
    )
    return ReExecutionPlan(
        policy="refresh-all",
        requested_policy="refresh-all",
        target_source="",
        sources=(source,),
        forbidden_source_roots=[],
        profile=profile,
        analysis_required=True,
        workspace_synthesis_required=True,
        publication_required=True,
    )


def test_architecture_map_classifies_domains_and_orders_import_prerequisites(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    source = root / "sources" / "api" / "src"
    (source / "shared").mkdir(parents=True)
    (source / "persistence").mkdir()
    (source / "services").mkdir()
    (source / "routes").mkdir()
    (source / "shared" / "types.ts").write_text("export type Id = string;\n")
    (source / "shared" / "constants.ts").write_text("export const prefix = 'order';\n")
    (source / "persistence" / "store.ts").write_text(
        'import type { Id } from "../shared/types";\nexport const read = (id: Id) => id;\n'
    )
    (source / "persistence" / "schema.ts").write_text("export type StoredOrder = { id: string };\n")
    (source / "services" / "orders.ts").write_text(
        'import { read } from "../persistence/store";\nexport const order = read;\n'
    )
    (source / "services" / "validation.ts").write_text("export const valid = true;\n")
    (source / "routes" / "orders.ts").write_text(
        'import { order } from "../services/orders";\nexport const route = order;\n'
    )
    (source / "routes" / "health.ts").write_text("export const health = true;\n")

    architecture = build_re_architecture_map(_plan(root))
    by_root = {domain.root: domain for domain in architecture.domains}

    assert by_root["src/shared"].layer == "foundation"
    assert by_root["src/persistence"].layer == "persistence"
    assert by_root["src/services"].layer == "application"
    assert by_root["src/routes"].layer == "backend"
    assert by_root["src/shared"].migration_wave < by_root["src/persistence"].migration_wave
    assert by_root["src/persistence"].migration_wave < by_root["src/services"].migration_wave
    assert by_root["src/services"].migration_wave < by_root["src/routes"].migration_wave
    assert by_root["src/persistence"].key in by_root["src/services"].dependencies
    assert [wave["label"] for wave in architecture.waves] == [
        "Foundation",
        "Persistence",
        "Application",
        "Backend/API",
    ]


def test_architecture_map_keeps_cycles_explicit_and_writes_catalog(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    source = root / "sources" / "api" / "src"
    (source / "services").mkdir(parents=True)
    (source / "routes").mkdir()
    (source / "services" / "orders.ts").write_text(
        'import { route } from "../routes/orders";\nexport const order = route;\n'
    )
    (source / "services" / "validation.ts").write_text("export const valid = true;\n")
    (source / "routes" / "orders.ts").write_text(
        'import { order } from "../services/orders";\nexport const route = order;\n'
    )
    (source / "routes" / "health.ts").write_text("export const health = true;\n")

    architecture = build_re_architecture_map(_plan(root))
    assert len(architecture.cycles) == 1
    assert {domain.cycle_group for domain in architecture.domains} == {"cycle-001"}

    map_path, catalog_path = write_re_architecture_catalog(root / "runs" / "run-1" / "re", architecture)
    loaded = load_re_architecture_map(map_path)

    assert map_path.is_file()
    assert catalog_path.is_file()
    assert ARCHITECTURE_CATALOG_VERSION == 1
    assert loaded == architecture
    assert "# Architecture Domain Catalog" in catalog_path.read_text(encoding="utf-8")
    assert "## Cycles" in catalog_path.read_text(encoding="utf-8")
