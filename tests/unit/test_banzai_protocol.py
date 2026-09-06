"""Tests for the deployed Banzai candidate-protocol fingerprint."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.banzai_protocol import active_banzai_default_protocol_fingerprint


def _write_protocol_bundle(project_root: Path, *, why2: str = "why2") -> None:
    files = {
        ".echelon/runtime/workflow/definition.yaml": "workflow: current\n",
        ".echelon/runtime/workflow/phases/phase1-why2.md": why2,
        ".echelon/prosaic/subagents/echelon.sage.md": "sage: current\n",
    }
    for relative, content in files.items():
        path = project_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_active_protocol_fingerprint_changes_when_deployed_why2_changes(
    tmp_path: Path,
) -> None:
    """Catch a fingerprint that ignores the deployed WHY2 candidate contract."""
    _write_protocol_bundle(tmp_path, why2="candidate protocol v1\n")

    before = active_banzai_default_protocol_fingerprint(tmp_path)

    _write_protocol_bundle(tmp_path, why2="candidate protocol v2\n")
    after = active_banzai_default_protocol_fingerprint(tmp_path)

    assert before.fingerprint is not None
    assert after.fingerprint is not None
    assert before.fingerprint.startswith("sha256:")
    assert after.fingerprint.startswith("sha256:")
    assert before.fingerprint != after.fingerprint
    assert before.diagnostic == ""
    assert after.diagnostic == ""


@pytest.mark.parametrize("breakage", ["missing", "directory", "oversized"])
def test_active_protocol_fingerprint_rejects_unverifiable_protocol_file(
    tmp_path: Path,
    breakage: str,
) -> None:
    """Catch a retry route that treats incomplete workspace evidence as valid."""
    _write_protocol_bundle(tmp_path)
    why2 = tmp_path / ".echelon/runtime/workflow/phases/phase1-why2.md"
    if breakage == "missing":
        why2.unlink()
    elif breakage == "directory":
        why2.unlink()
        why2.mkdir()
    else:
        why2.write_bytes(b"x" * (1024 * 1024 + 1))

    result = active_banzai_default_protocol_fingerprint(tmp_path)

    assert result.fingerprint is None
    assert "phase1-why2.md" in result.diagnostic


def test_active_protocol_fingerprint_rejects_symlinked_protocol_file(
    tmp_path: Path,
) -> None:
    """Catch a retry route that follows a workspace-controlled symlink."""
    _write_protocol_bundle(tmp_path)
    why2 = tmp_path / ".echelon/runtime/workflow/phases/phase1-why2.md"
    replacement = tmp_path / "replacement.md"
    replacement.write_text("candidate protocol outside bundle\n", encoding="utf-8")
    why2.unlink()
    why2.symlink_to(replacement)

    result = active_banzai_default_protocol_fingerprint(tmp_path)

    assert result.fingerprint is None
    assert "phase1-why2.md" in result.diagnostic


def test_active_protocol_fingerprint_rejects_platform_without_nofollow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch a portability fallback that would follow a protocol symlink."""
    _write_protocol_bundle(tmp_path)
    monkeypatch.delattr("harness.banzai_protocol.os.O_NOFOLLOW")

    result = active_banzai_default_protocol_fingerprint(tmp_path)

    assert result.fingerprint is None
    assert "symlink-safe open" in result.diagnostic
