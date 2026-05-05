"""Integration tests for MemPalace requirements mining and retrieval.

Tests the full mine → store → search round-trip with a real isolated ChromaDB
palace. Does NOT require SOAR. Uses Python API directly.

Run with: pytest tests/integration/test_mempalace_mine_search.py -v -m integration
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.integration]

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mempalace"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="session")
def require_mempalace():
    pytest.importorskip("mempalace", reason="mempalace not installed in this environment")


@pytest.fixture
def isolated_palace(tmp_path, monkeypatch):
    """Isolated ChromaDB palace in a temp directory — never touches ~/.mempalace."""
    palace = tmp_path / "palace"
    palace.mkdir()
    monkeypatch.setenv("MEMPALACE_PALACE_PATH", str(palace))
    return palace


@pytest.fixture
def project_alpha(tmp_path, isolated_palace):
    proj = tmp_path / "project-alpha"
    proj.mkdir()
    echelon_cfg = proj / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
    echelon_cfg.parent.mkdir(parents=True, exist_ok=True)
    echelon_cfg.write_text(
        yaml.dump({"mempalace": {"wing": "alpha"}, "deploy": {"type": "http", "blue_port": 3000, "green_port": 3001}})
    )
    (proj / "spec.md").write_text((FIXTURES / "spec-alpha.md").read_text())
    return proj


@pytest.fixture
def project_beta(tmp_path, isolated_palace):
    proj = tmp_path / "project-beta"
    proj.mkdir()
    echelon_cfg = proj / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
    echelon_cfg.parent.mkdir(parents=True, exist_ok=True)
    echelon_cfg.write_text(
        yaml.dump({"mempalace": {"wing": "beta"}, "deploy": {"type": "http", "blue_port": 3100, "green_port": 3101}})
    )
    (proj / "spec.md").write_text((FIXTURES / "spec-beta.md").read_text())
    return proj


def _ctx(wing: str, palace_path: str):
    from codegen.memory.context import MemPalaceContext
    return MemPalaceContext(wing=wing, run_id="integration-test", palace_path=palace_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_mine_writes_drawers_to_chromadb(project_alpha, isolated_palace):
    """Mine a spec and verify drawers are written to ChromaDB."""
    from codegen.memory.requirements_miner import RequirementsMiner

    ctx = _ctx("alpha", str(isolated_palace))
    miner = RequirementsMiner(ctx, project_dir=project_alpha)
    result = miner.mine_file(project_alpha / "spec.md")

    assert result.failed == 0, f"Mine errors: {result.errors}"
    assert result.written > 0, "Expected at least one drawer written"
    req_ids = [r.req_id for r in result.requirements]
    assert "FR-AUTH-001" in req_ids
    assert "NFR-AUTH-001" in req_ids
    assert "AC-AUTH-001" in req_ids


def test_mined_drawers_are_semantically_searchable(project_alpha, isolated_palace):
    """Mine a spec then search — verify semantic retrieval returns correct wing's content."""
    from codegen.memory.requirements_miner import RequirementsMiner
    from codegen.memory.mempalace_reader import MemPalaceReader

    ctx = _ctx("alpha", str(isolated_palace))
    miner = RequirementsMiner(ctx, project_dir=project_alpha)
    miner.mine_file(project_alpha / "spec.md")

    reader = MemPalaceReader(ctx)
    result = reader.search("user authentication OAuth2 token")

    assert result.available, "MemPalace must be available"
    assert len(result.drawers) > 0, "Expected at least one search result"
    for drawer in result.drawers:
        assert drawer.wing == "alpha", f"Drawer from wrong wing: {drawer.wing}"


def test_wing_isolation_prevents_cross_project_leakage(project_alpha, project_beta, isolated_palace):
    """Two projects sharing a palace but different wings must not see each other's drawers."""
    from codegen.memory.requirements_miner import RequirementsMiner
    from codegen.memory.mempalace_reader import MemPalaceReader

    ctx_alpha = _ctx("alpha", str(isolated_palace))
    ctx_beta = _ctx("beta", str(isolated_palace))

    RequirementsMiner(ctx_alpha, project_dir=project_alpha).mine_file(project_alpha / "spec.md")
    RequirementsMiner(ctx_beta, project_dir=project_beta).mine_file(project_beta / "spec.md")

    # Alpha reader must not see payment requirements
    alpha_result = MemPalaceReader(ctx_alpha).search("payment Stripe PayPal")
    payment_ids = [d.req_id or "" for d in alpha_result.drawers]
    assert all("FR-PAY" not in pid for pid in payment_ids), (
        f"Alpha wing leaked beta content: {payment_ids}"
    )

    # Beta reader must not see auth requirements
    beta_result = MemPalaceReader(ctx_beta).search("OAuth2 authentication JWT session")
    auth_ids = [d.req_id or "" for d in beta_result.drawers]
    assert all("FR-AUTH" not in aid for aid in auth_ids), (
        f"Beta wing leaked alpha content: {auth_ids}"
    )


def test_drawer_id_uses_sha256_not_md5(project_alpha, isolated_palace):
    """Verify drawer IDs written to ChromaDB use SHA256[:24] — the fixed format."""
    from codegen.memory.requirements_miner import RequirementsMiner

    ctx = _ctx("alpha", str(isolated_palace))
    miner = RequirementsMiner(ctx, project_dir=project_alpha)
    result = miner.mine_file(project_alpha / "spec.md")

    assert len(result.drawer_ids) > 0, "Expected drawer IDs from mine result"
    for drawer_id in result.drawer_ids:
        # format: drawer_{wing}_{room}_{sha256[:24]}
        parts = drawer_id.split("_", 3)
        assert parts[0] == "drawer", f"Unexpected prefix: {drawer_id}"
        hash_part = parts[-1]
        assert len(hash_part) == 24, (
            f"Expected SHA256[:24] (len=24), got len={len(hash_part)}: {drawer_id}\n"
            "This indicates the old MD5[:16] bug is still present."
        )


def test_collision_detection_finds_foreign_drawers(project_alpha, project_beta, isolated_palace):
    """Mine project-B's spec under wing 'shared', verify collision detected from project-A."""
    from codegen.memory.requirements_miner import RequirementsMiner
    from codegen.memory.collision import check_wing_collision

    ctx_polluted = _ctx("shared", str(isolated_palace))
    # Mine project-B's spec under wing "shared" — source_file will be project-B path
    RequirementsMiner(ctx_polluted, project_dir=project_beta).mine_file(project_beta / "spec.md")

    foreign = check_wing_collision("shared", project_alpha, str(isolated_palace))

    assert len(foreign) > 0, "Expected collision detected via miner-written drawers"
    assert all(str(project_beta) in p for p in foreign), (
        f"Expected foreign paths under project-beta, got: {foreign}"
    )


def test_requirements_clean_removes_miner_drawers(project_alpha, isolated_palace):
    """requirements clean correctly removes drawers written by RequirementsMiner (real source_file)."""
    from codegen.memory.requirements_miner import RequirementsMiner
    from codegen.memory.collision import check_wing_collision

    ctx = _ctx("alpha", str(isolated_palace))
    miner = RequirementsMiner(ctx, project_dir=project_alpha)
    mine_result = miner.mine_file(project_alpha / "spec.md")
    assert mine_result.written > 0

    # Import collection directly to simulate what requirements clean does
    from mempalace.miner import get_collection
    collection = get_collection(str(isolated_palace))

    results = collection.get(
        where={"wing": {"$eq": "alpha"}},
        limit=1000,
        include=["metadatas"],
    )
    project_prefix = str(project_alpha)
    ids_to_delete = [
        drawer_id for drawer_id, meta in zip(results["ids"], results["metadatas"] or [])
        if (meta or {}).get("source_file", "").startswith(project_prefix)
    ]

    assert len(ids_to_delete) > 0, (
        "Expected miner drawers to have real source_file paths — "
        "requirements clean would find nothing to delete if source_file is still 'codegen/RE'"
    )
    collection.delete(ids=ids_to_delete)

    # Verify they're gone
    after = collection.get(where={"wing": {"$eq": "alpha"}}, limit=1000, include=["metadatas"])
    remaining = [
        m for m in (after.get("metadatas") or [])
        if (m or {}).get("source_file", "").startswith(project_prefix)
    ]
    assert len(remaining) == 0, f"Expected all project drawers deleted, {len(remaining)} remain"


def test_provision_wing_full_lifecycle(tmp_path, isolated_palace):
    """_provision_wing writes wing to echelon-config.yml and is idempotent on re-call."""
    from unittest.mock import patch
    from echelon.cli import _provision_wing

    echelon_yml = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
    echelon_yml.parent.mkdir(parents=True, exist_ok=True)
    echelon_yml.write_text(yaml.dump({
        "deploy": {"type": "http", "blue_port": 3000, "green_port": 3001},
    }))

    with patch("echelon.cli.check_wing_collision", return_value=[]):
        with patch("builtins.input", return_value="my-project"):
            wing1 = _provision_wing(tmp_path, echelon_yml)

    assert wing1 == "my-project"
    config = yaml.safe_load(echelon_yml.read_text())
    assert config["mempalace"]["wing"] == "my-project"
    assert config["deploy"]["blue_port"] == 3000  # other keys preserved

    # Second call — must be idempotent
    with patch("builtins.print") as mock_print:
        wing2 = _provision_wing(tmp_path, echelon_yml)

    assert wing2 == "my-project"
    printed = " ".join(str(c) for c in mock_print.call_args_list)
    assert "already configured" in printed
