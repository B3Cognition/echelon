from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.publication import (
    EMPTY_INDEX_HASH,
    GenerationManifest,
    PublishedV2Index,
    ReV2PublicationConflict,
    ReV2PublicationError,
    current_index_hash,
    load_published_v2_index,
    publish_generation,
)


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _publish(
    workspace: Path,
    *,
    roots: tuple[str, ...],
    run_id: str = "re-run-1",
    policy_hash: str | None = None,
    expected_index_hash: str | None = None,
    fault_hook=None,
) -> PublishedV2Index:
    return publish_generation(
        workspace,
        run_id,
        roots,
        policy_hash or _digest("policy"),
        expected_index_hash=(
            current_index_hash(workspace)
            if expected_index_hash is None
            else expected_index_hash
        ),
        fault_hook=fault_hook,
    )


@pytest.mark.unit
def test_same_root_set_publishes_at_most_one_generation(tmp_path: Path) -> None:
    first = _publish(tmp_path, roots=(_digest("a"), _digest("b")))
    second = _publish(
        tmp_path,
        roots=(_digest("b"), _digest("a"), _digest("a")),
        run_id="re-run-2",
        expected_index_hash=first.index_hash,
    )

    assert second.generation_id == first.generation_id
    assert second.run_id == "re-run-2"
    assert second.index_hash != first.index_hash
    assert len(list((tmp_path / "re/v2/generations").iterdir())) == 1
    manifest = json.loads(
        (
            tmp_path
            / "re/v2/generations"
            / first.generation_id
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert "run_id" not in manifest


@pytest.mark.unit
def test_index_cas_preserves_competing_publication(tmp_path: Path) -> None:
    stale = current_index_hash(tmp_path)
    newer = _publish(
        tmp_path, roots=(_digest("newer"),), expected_index_hash=stale
    )
    published_bytes = (tmp_path / "re/v2/index.json").read_bytes()

    with pytest.raises(ReV2PublicationConflict, match="expected index"):
        _publish(tmp_path, roots=(_digest("stale"),), expected_index_hash=stale)

    assert (tmp_path / "re/v2/index.json").read_bytes() == published_bytes
    assert load_published_v2_index(tmp_path) == newer
    assert not (
        tmp_path
        / "re/v2/generations"
        / GenerationManifest.create(
            (_digest("stale"),), _digest("policy")
        ).generation_id
    ).exists()


@pytest.mark.unit
def test_generation_identity_binds_only_exact_semantic_inputs() -> None:
    roots = (_digest("b"), _digest("a"), _digest("b"))
    manifest = GenerationManifest.create(roots, _digest("policy"))

    canonical_roots = tuple(sorted((_digest("a"), _digest("b"))))
    assert manifest.accepted_root_hashes == canonical_roots
    assert manifest.generation_id == content_digest(
        {
            "accepted_root_hashes": list(canonical_roots),
            "schema_version": 1,
            "synthesis_policy_hash": _digest("policy"),
        }
    )
    assert GenerationManifest.create(
        roots, _digest("other-policy")
    ).generation_id != manifest.generation_id
    assert GenerationManifest.create(
        (_digest("a"),), _digest("policy")
    ).generation_id != manifest.generation_id


@pytest.mark.unit
def test_publication_writes_only_canonical_manifests_and_index(tmp_path: Path) -> None:
    published = _publish(tmp_path, roots=(_digest("root"),))
    generation = tmp_path / "re/v2/generations" / published.generation_id
    manifest_bytes = (generation / "manifest.json").read_bytes()
    manifest = GenerationManifest.from_bytes(manifest_bytes)
    index_bytes = (tmp_path / "re/v2/index.json").read_bytes()

    assert manifest_bytes == canonical_json_bytes(manifest.to_json_dict())
    assert index_bytes == canonical_json_bytes(published.to_json_dict())
    assert published.generation_manifest_hash == content_digest(manifest_bytes)
    assert published.index_hash == content_digest(index_bytes)
    assert sorted(path.name for path in generation.iterdir()) == ["manifest.json"]
    assert stat.S_IMODE(generation.stat().st_mode) == 0o500
    assert stat.S_IMODE((generation / "manifest.json").stat().st_mode) == 0o400
    assert (generation / "manifest.json").stat().st_nlink == 1
    assert sorted(path.name for path in tmp_path.iterdir()) == ["re"]
    assert EMPTY_INDEX_HASH == content_digest(b"")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("run_id", "roots", "policy", "message"),
    [
        ("", (_digest("root"),), _digest("policy"), "run_id"),
        ("../escape", (_digest("root"),), _digest("policy"), "run_id"),
        ("re-run", (), _digest("policy"), "non-empty"),
        ("re-run", ("sha256:ABC",), _digest("policy"), "accepted_root"),
        ("re-run", (_digest("root"),), "policy", "synthesis_policy_hash"),
    ],
)
def test_generation_inputs_fail_closed(
    tmp_path: Path,
    run_id: str,
    roots: tuple[str, ...],
    policy: str,
    message: str,
) -> None:
    with pytest.raises(ReV2PublicationError, match=message):
        publish_generation(
            tmp_path,
            run_id,
            roots,
            policy,
            expected_index_hash=EMPTY_INDEX_HASH,
        )
    assert not (tmp_path / "re/v2/index.json").exists()


@pytest.mark.unit
def test_workspace_and_publication_symlinks_are_rejected(tmp_path: Path) -> None:
    real_workspace = tmp_path / "real"
    real_workspace.mkdir()
    linked_workspace = tmp_path / "linked"
    linked_workspace.symlink_to(real_workspace, target_is_directory=True)

    with pytest.raises(ReV2PublicationError, match="workspace.*symlink"):
        _publish(linked_workspace, roots=(_digest("root"),))

    outside = tmp_path / "outside"
    outside.mkdir()
    (real_workspace / "re").mkdir()
    (real_workspace / "re/v2").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ReV2PublicationError, match="symlink"):
        _publish(real_workspace, roots=(_digest("root"),))
    assert not list(outside.iterdir())


@pytest.mark.unit
def test_workspace_path_rejects_symlinked_parent_traversal(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    workspace = parent / "workspace"
    workspace.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(parent, target_is_directory=True)

    with pytest.raises(ReV2PublicationError, match="workspace.*symlink"):
        _publish(alias / "workspace", roots=(_digest("root"),))

    assert not (workspace / "re").exists()


@pytest.mark.unit
@pytest.mark.parametrize("swap_target", ("workspace", "re"))
def test_layout_creation_never_follows_a_swapped_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swap_target: str
) -> None:
    import harness.re_v2.publication as publication_module

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    held = tmp_path / f"held-{swap_target}"
    if swap_target == "re":
        (workspace / "re").mkdir()
    original_mkdir = publication_module.os.mkdir
    swapped = False

    def swap_before_mkdir(path, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        name = Path(path).name
        trigger = "re" if swap_target == "workspace" else "v2"
        if not swapped and name == trigger:
            swapped = True
            victim = workspace if swap_target == "workspace" else workspace / "re"
            victim.rename(held)
            victim.symlink_to(outside, target_is_directory=True)
        if dir_fd is None:
            return original_mkdir(path, mode)
        return original_mkdir(path, mode, dir_fd=dir_fd)

    monkeypatch.setattr(publication_module.os, "mkdir", swap_before_mkdir)
    failure: Exception | None = None
    try:
        _publish(workspace, roots=(_digest("root"),))
    except Exception as exc:
        failure = exc

    assert swapped
    assert isinstance(failure, ReV2PublicationError)
    assert "replaced" in str(failure) or "symlink" in str(failure) or "continuity" in str(failure)
    assert not list(outside.iterdir())


@pytest.mark.unit
def test_rejected_ancestor_swap_closes_the_unbound_child_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import harness.re_v2.publication as publication_module

    workspace = tmp_path / "workspace"
    re_root = workspace / "re"
    re_root.mkdir(parents=True)
    displaced = tmp_path / "displaced-re"
    outside = tmp_path / "outside"
    outside.mkdir()
    original_open = publication_module.os.open
    opened_re_fd: int | None = None

    def swap_after_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal opened_re_fd
        if dir_fd is None:
            return original_open(path, flags, mode)
        fd = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == "re" and opened_re_fd is None:
            opened_re_fd = fd
            re_root.rename(displaced)
            re_root.symlink_to(outside, target_is_directory=True)
        return fd

    monkeypatch.setattr(publication_module.os, "open", swap_after_open)
    with pytest.raises(ReV2PublicationError, match="replaced"):
        _publish(workspace, roots=(_digest("root"),))

    assert opened_re_fd is not None
    with pytest.raises(OSError):
        publication_module.os.fstat(opened_re_fd)


@pytest.mark.unit
def test_schema_versions_reject_boolean_values() -> None:
    manifest_identity = {
        "accepted_root_hashes": [_digest("root")],
        "schema_version": True,
        "synthesis_policy_hash": _digest("policy"),
    }
    manifest_payload = canonical_json_bytes(
        {**manifest_identity, "generation_id": content_digest(manifest_identity)}
    )
    with pytest.raises(ReV2PublicationError, match="schema_version"):
        GenerationManifest.from_bytes(manifest_payload)

    index_payload = canonical_json_bytes(
        {
            "generation_id": _digest("generation"),
            "generation_manifest_hash": _digest("manifest"),
            "run_id": "re-run-1",
            "schema_version": True,
        }
    )
    with pytest.raises(ReV2PublicationError, match="schema_version"):
        PublishedV2Index.from_bytes(index_payload)


@pytest.mark.unit
def test_existing_generation_requires_exact_manifest_and_no_extra_bytes(
    tmp_path: Path,
) -> None:
    first = _publish(tmp_path, roots=(_digest("root"),))
    generation = tmp_path / "re/v2/generations" / first.generation_id
    generation.chmod(0o700)
    (generation / "extra").write_bytes(b"unexpected")
    generation.chmod(0o500)

    with pytest.raises(ReV2PublicationError, match="generation.*collision"):
        _publish(
            tmp_path,
            roots=(_digest("root"),),
            expected_index_hash=first.index_hash,
        )


@pytest.mark.unit
@pytest.mark.parametrize("mutation", ("directory_mode", "manifest_mode", "hardlink"))
def test_existing_generation_reuse_requires_immutable_single_link_state(
    tmp_path: Path, mutation: str
) -> None:
    first = _publish(tmp_path, roots=(_digest("root"),))
    index = tmp_path / "re/v2/index.json"
    prior_index = index.read_bytes()
    generation = tmp_path / "re/v2/generations" / first.generation_id
    manifest = generation / "manifest.json"
    if mutation == "directory_mode":
        generation.chmod(0o700)
    elif mutation == "manifest_mode":
        manifest.chmod(0o600)
    else:
        (tmp_path / "manifest-hardlink.json").hardlink_to(manifest)

    with pytest.raises(ReV2PublicationError, match="generation"):
        _publish(
            tmp_path,
            roots=(_digest("root"),),
            run_id="re-run-2",
            expected_index_hash=first.index_hash,
        )

    assert index.read_bytes() == prior_index


@pytest.mark.unit
def test_generation_promotion_never_replaces_a_racing_collision(
    tmp_path: Path,
) -> None:
    manifest = GenerationManifest.create(
        (_digest("root"),), _digest("policy")
    )
    collision = tmp_path / "re/v2/generations" / manifest.generation_id
    competing_inode: int | None = None

    def install_collision(point: str) -> None:
        nonlocal competing_inode
        if point == "generation_temporary_written":
            collision.mkdir()
            competing_inode = collision.stat().st_ino

    with pytest.raises(ReV2PublicationError, match="generation"):
        _publish(
            tmp_path,
            roots=(_digest("root"),),
            fault_hook=install_collision,
        )

    assert collision.stat().st_ino == competing_inode
    assert not list(collision.iterdir())
    assert not (tmp_path / "re/v2/index.json").exists()


@pytest.mark.unit
def test_noncanonical_or_dangling_current_index_fails_before_cas(tmp_path: Path) -> None:
    first = _publish(tmp_path, roots=(_digest("root"),))
    index = tmp_path / "re/v2/index.json"
    parsed = json.loads(index.read_text(encoding="utf-8"))
    index.chmod(0o600)
    index.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ReV2PublicationError, match="canonical"):
        _publish(
            tmp_path,
            roots=(_digest("next"),),
            expected_index_hash=content_digest(index.read_bytes()),
        )

    index.write_bytes(canonical_json_bytes(first.to_json_dict()))
    generation = tmp_path / "re/v2/generations" / first.generation_id
    generation.chmod(0o700)
    (generation / "manifest.json").unlink()
    generation.chmod(0o500)
    with pytest.raises(ReV2PublicationError, match="manifest"):
        load_published_v2_index(tmp_path)


@pytest.mark.unit
def test_generation_validation_rejects_bytes_added_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import harness.re_v2.publication as publication_module

    published = _publish(tmp_path, roots=(_digest("root"),))
    generation = tmp_path / "re/v2/generations" / published.generation_id
    original_scandir = publication_module.os.scandir
    injected = False

    def inject_after_first_listing(path):
        nonlocal injected
        iterator = original_scandir(path)
        entries = list(iterator)
        iterator.close()
        if not injected:
            injected = True
            generation.chmod(0o700)
            (generation / "late").write_bytes(b"late bytes")
            generation.chmod(0o500)
        return iter(entries)

    monkeypatch.setattr(publication_module.os, "scandir", inject_after_first_listing)
    with pytest.raises(ReV2PublicationError, match="generation.*mutated"):
        load_published_v2_index(tmp_path)


class _InjectedCrash(RuntimeError):
    pass


@pytest.mark.unit
@pytest.mark.parametrize(
    "boundary", ("generation_promoted", "index_temporary_written")
)
def test_generation_replacement_at_last_moment_preserves_prior_index(
    tmp_path: Path, boundary: str
) -> None:
    old = _publish(tmp_path, roots=(_digest("old"),))
    index_path = tmp_path / "re/v2/index.json"
    prior_index = index_path.read_bytes()
    generations = tmp_path / "re/v2/generations"
    displaced = generations / ".displaced-generation"

    def replace_generation(point: str) -> None:
        if point != boundary:
            return
        candidates = [
            path
            for path in generations.iterdir()
            if not path.name.startswith(".") and path.name != old.generation_id
        ]
        assert len(candidates) == 1
        generation = candidates[0]
        payload = (generation / "manifest.json").read_bytes()
        generation.chmod(0o700)
        generation.rename(displaced)
        generation.mkdir(mode=0o700)
        replacement_manifest = generation / "manifest.json"
        replacement_manifest.write_bytes(payload)
        replacement_manifest.chmod(0o400)
        generation.chmod(0o500)

    with pytest.raises(ReV2PublicationError, match="generation.*replaced"):
        _publish(
            tmp_path,
            roots=(_digest("new"),),
            expected_index_hash=old.index_hash,
            fault_hook=replace_generation,
        )

    assert index_path.read_bytes() == prior_index


@pytest.mark.unit
@pytest.mark.parametrize(
    ("boundary", "new_index_visible"),
    [
        ("generation_temporary_written", False),
        ("generation_promoted", False),
        ("index_temporary_written", False),
        ("index_replaced", True),
    ],
)
def test_fault_boundaries_expose_old_or_complete_new_index(
    tmp_path: Path, boundary: str, new_index_visible: bool
) -> None:
    old = _publish(tmp_path, roots=(_digest("old"),))
    desired_manifest = GenerationManifest.create(
        (_digest("new"),), _digest("policy")
    )

    def crash(point: str) -> None:
        if point == boundary:
            raise _InjectedCrash(point)

    with pytest.raises(_InjectedCrash, match=boundary):
        _publish(
            tmp_path,
            roots=(_digest("new"),),
            expected_index_hash=old.index_hash,
            fault_hook=crash,
        )

    visible = load_published_v2_index(tmp_path)
    assert visible is not None
    assert visible.generation_id == (
        desired_manifest.generation_id if new_index_visible else old.generation_id
    )
    assert not list((tmp_path / "re/v2").rglob("*.tmp"))

    if new_index_visible:
        restarted = _publish(
            tmp_path,
            roots=(_digest("new"),),
            expected_index_hash=visible.index_hash,
        )
    else:
        restarted = _publish(
            tmp_path,
            roots=(_digest("new"),),
            expected_index_hash=old.index_hash,
        )
    assert restarted.generation_id == desired_manifest.generation_id
    assert load_published_v2_index(tmp_path) == restarted


@pytest.mark.unit
def test_durable_writes_retry_eintr_and_short_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import harness.re_v2.publication as publication_module

    original_write = publication_module.os.write
    interrupted = False

    def interrupted_short_write(fd: int, payload: bytes) -> int:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise InterruptedError
        return original_write(fd, payload[: max(1, len(payload) // 3)])

    monkeypatch.setattr(publication_module.os, "write", interrupted_short_write)
    published = _publish(tmp_path, roots=(_digest("root"),))

    assert interrupted
    assert load_published_v2_index(tmp_path) == published


@pytest.mark.unit
def test_failure_cleans_only_the_call_owned_temporary(tmp_path: Path) -> None:
    _publish(tmp_path, roots=(_digest("old"),))
    unrelated = tmp_path / "re/v2/generations/.generation.keep.tmp"
    unrelated.mkdir()
    (unrelated / "owner").write_text("someone else", encoding="utf-8")

    def crash(point: str) -> None:
        if point == "generation_temporary_written":
            raise _InjectedCrash(point)

    with pytest.raises(_InjectedCrash):
        _publish(tmp_path, roots=(_digest("new"),), fault_hook=crash)

    assert (unrelated / "owner").read_text(encoding="utf-8") == "someone else"
