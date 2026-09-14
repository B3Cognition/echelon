"""Named host read roots retain the existing descriptor boundary."""
import os

import pytest


def _read(channel, path="audit.md", root="evidence", **kwargs):
    return channel.request({"op": "read_file", "root": root, "path": path,
                            "start_line": 1, "line_count": 2, **kwargs})


def test_named_roots_and_copied_mapping(tmp_path):
    from harness.inspection_io import BoundedReadChannel, InspectionReadError
    roots = {}
    for name in ("worktree", "spec", "evidence"):
        path = tmp_path / name
        path.mkdir()
        (path / "audit.md").write_text(f"{name}\nFR-000001\nFR-1000000\n")
        roots[name] = path
    channel = BoundedReadChannel(roots)
    roots["evidence"] = roots["worktree"]
    with channel:
        assert _read(channel, start_line=2) == {
            "status": "ok", "text": "FR-000001\nFR-1000000\n", "start_line": 2, "total_lines": 3}
        assert _read(channel)["text"] == "evidence\nFR-000001\n"
        assert _read(channel, root="spec")["text"] == "spec\nFR-000001\n"
        assert _read(channel, root="worktree")["text"] == "worktree\nFR-000001\n"
        with pytest.raises(InspectionReadError):
            _read(channel, root="other")
    with pytest.raises(InspectionReadError):
        _read(channel)


@pytest.mark.parametrize("roots", [{}, {"": "/x"}, {1: "/x"}, None, ["/x"]])
def test_invalid_host_aliases_are_rejected(roots):
    from harness.inspection_io import BoundedReadChannel, InspectionReadError
    with pytest.raises(InspectionReadError):
        BoundedReadChannel(roots)


@pytest.mark.parametrize("kwargs", [{"path": "../secret"}, {"path": "/secret"},
                                   {"start_line": True}, {"line_count": 201}, {"extra": True}])
def test_invalid_model_read_schema_is_rejected(tmp_path, kwargs):
    from harness.inspection_io import BoundedReadChannel, InspectionReadError
    with BoundedReadChannel({"evidence": tmp_path}) as channel:
        with pytest.raises(InspectionReadError):
            _read(channel, **kwargs)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_unsafe_file_aliases_are_rejected(tmp_path, kind):
    from harness.inspection_io import BoundedReadChannel, InspectionReadError
    target = tmp_path / "target"
    target.write_text("private")
    alias = tmp_path / "audit.md"
    if kind == "symlink":
        alias.symlink_to(target)
    elif kind == "hardlink":
        os.link(target, alias)
    else:
        os.mkfifo(alias)
    with BoundedReadChannel({"evidence": tmp_path}) as channel:
        with pytest.raises(InspectionReadError):
            _read(channel)


@pytest.mark.parametrize("content", [b"binary\0", b"\xff", b"x" * 1048577, b"x" * 65537])
def test_unavailable_evidence_is_not_truncated_success(tmp_path, content):
    from harness.inspection_io import BoundedReadChannel
    (tmp_path / "audit.md").write_bytes(content)
    with BoundedReadChannel({"evidence": tmp_path}) as channel:
        result = _read(channel)
        assert result["status"] == "unavailable"
        assert "text" not in result


def test_root_replacement_does_not_redirect_named_alias(tmp_path):
    from harness.inspection_io import BoundedReadChannel
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "audit.md").write_text("original")
    with BoundedReadChannel({"evidence": root}) as channel:
        root.rename(tmp_path / "retained")
        root.mkdir()
        (root / "audit.md").write_text("replacement")
        assert _read(channel)["text"] == "original"


def test_mutation_during_read_is_rejected(tmp_path, monkeypatch):
    import harness.inspection_io as io
    target = tmp_path / "audit.md"
    target.write_text("original")
    original = io._read_exact
    def mutate(fd, size):
        value = original(fd, size)
        target.write_text("changed")
        return value
    monkeypatch.setattr(io, "_read_exact", mutate)
    with io.BoundedReadChannel({"evidence": tmp_path}) as channel:
        with pytest.raises(io.InspectionReadError, match="changed"):
            _read(channel)


@pytest.mark.parametrize("kind", ["file", "subtree", "second_alias"])
def test_denied_path_is_rejected_before_target_open(tmp_path, monkeypatch, kind):
    import harness.inspection_io as io
    secret = tmp_path / "denied-area"
    secret.mkdir()
    (secret / "audit.md").write_text("secret")
    denied = secret / "audit.md" if kind == "file" else secret
    roots = {"evidence": tmp_path}
    if kind == "second_alias":
        roots["other"] = secret
    real_open = os.open
    def guarded_open(path, *args, **kwargs):
        assert str(path) not in {"denied-area", "audit.md"}, "denied target was opened"
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(io.os, "open", guarded_open)
    with pytest.raises(io.InspectionReadError, match="denied"):
        with io.BoundedReadChannel(roots, forbidden_paths=(denied,)) as channel:
            _read(channel, "denied-area/audit.md")


def test_denial_is_component_based_and_listing_hides_denied_children(tmp_path):
    from harness.inspection_io import BoundedReadChannel, InspectionReadError
    (tmp_path / "private").mkdir()
    (tmp_path / "private-copy").mkdir()
    (tmp_path / "private-copy/audit.md").write_text("allowed")
    # Listing must not stat a denied symlink and accidentally expose or follow it.
    (tmp_path / "secret-link").symlink_to(tmp_path / "private", target_is_directory=True)
    with BoundedReadChannel({"evidence": tmp_path},
                            forbidden_paths=(tmp_path / "private", tmp_path / "secret-link")) as channel:
        assert _read(channel, "private-copy/audit.md")["text"] == "allowed"
        assert channel.request({"op": "list_directory", "root": "evidence", "path": "."}) == {
            "status": "ok", "entries": [{"name": "private-copy", "type": "directory"}]}
        with pytest.raises(InspectionReadError, match="denied"):
            channel.request({"op": "list_directory", "root": "evidence", "path": "private"})


@pytest.mark.parametrize("root_kind", ["exact", "descendant", "symlink"])
def test_alternate_roots_cannot_reopen_denied_content(tmp_path, root_kind):
    from harness.inspection_io import BoundedReadChannel, InspectionReadError
    private = tmp_path / "private"
    (private / "nested").mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(private, target_is_directory=True)
    root = {"exact": private, "descendant": private / "nested", "symlink": alias}[root_kind]
    with pytest.raises(InspectionReadError):
        with BoundedReadChannel({"evidence": root}, forbidden_paths=(private,)):
            pytest.fail("denied source was admitted")


def test_forbidden_paths_and_relative_roots_are_captured_at_construction(tmp_path, monkeypatch):
    from pathlib import Path
    from harness.inspection_io import BoundedReadChannel, InspectionReadError
    source = tmp_path / "source"
    source.mkdir()
    (source / "secret").write_text("private")
    monkeypatch.chdir(tmp_path)
    denied = [Path("source/secret")]
    channel = BoundedReadChannel({"evidence": Path("source")}, forbidden_paths=denied)
    denied.clear()
    monkeypatch.chdir(source)
    with channel:
        with pytest.raises(InspectionReadError, match="denied"):
            _read(channel, "secret")


@pytest.mark.parametrize("denied", [None, [None], ["../private"], ["bad\0path"]])
def test_invalid_denied_policy_fails_closed(tmp_path, denied):
    from harness.inspection_io import BoundedReadChannel, InspectionReadError
    with pytest.raises(InspectionReadError):
        BoundedReadChannel({"evidence": tmp_path}, forbidden_paths=denied)


@pytest.mark.parametrize("name,alias", [("Secret", "secret"), ("Café", "Cafe\u0301")])
@pytest.mark.parametrize("operation", ["read", "root", "listing"])
def test_filesystem_case_alias_cannot_bypass_denied_path(tmp_path, name, alias, operation):
    from harness.inspection_io import BoundedReadChannel, InspectionReadError
    secret = tmp_path / name
    secret.mkdir()
    (secret / "audit.md").write_text("private")
    if not (tmp_path / alias / "audit.md").is_file():
        pytest.skip("filesystem does not expose case aliases")
    if operation == "root":
        with pytest.raises(InspectionReadError, match="denied"):
            BoundedReadChannel({"evidence": tmp_path / alias}, forbidden_paths=(secret,))
    elif operation == "listing":
        with BoundedReadChannel({"evidence": tmp_path}, forbidden_paths=(tmp_path / alias,)) as channel:
            assert channel.request({"op": "list_directory", "root": "evidence", "path": "."}) == {
                "status": "ok", "entries": []}
    else:
        with BoundedReadChannel({"evidence": tmp_path}, forbidden_paths=(secret,)) as channel:
            with pytest.raises(InspectionReadError, match="denied"):
                _read(channel, f"{alias}/audit.md")
