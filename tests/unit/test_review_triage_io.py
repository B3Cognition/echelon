"""Tests for the bounded PR-triage read and Prosaic loading boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from harness.review_triage_io import (
    ReviewReadChannel,
    ReviewTriageError,
    load_review_prose,
)


ROLE_NAMES = (
    "echelon.review-debugger",
    "echelon.review-sentinel",
    "echelon.review-spec-guard",
)


def _write_bundle(root: Path, *, body: str = "Bounded review prose.\n") -> None:
    command = root / ".echelon" / "prosaic" / "commands" / "echelon.review.md"
    command.parent.mkdir(parents=True)
    command.write_text(
        "---\nname: echelon.review\nmodel_tier: strong\neffort: medium\n---\n"
        + body,
        encoding="utf-8",
    )
    for name in ROLE_NAMES:
        role = root / ".echelon" / "prosaic" / "subagents" / f"{name}.md"
        role.parent.mkdir(parents=True, exist_ok=True)
        role.write_text(
            f"---\nname: {name}\ndescription: Bounded review role\n"
            "execution: agent\ntools: write\ncolor: red\nmodel_tier: strong\n"
            "effort: medium\n---\n"
            + body,
            encoding="utf-8",
        )


def _fake_inspect(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
    artifact_id = command[2]
    source = Path(command[command.index("--source") + 1])
    raw = source.joinpath(artifact_id).read_text(encoding="utf-8")
    _empty, frontmatter, body = raw.split("---", 2)
    return subprocess.CompletedProcess(
        command,
        0,
        stdout=json.dumps(
            {
                "id": artifact_id,
                "type": "command" if artifact_id.startswith("commands/") else "subagent",
                "frontmatter": yaml.safe_load(frontmatter),
                "body": body.lstrip("\n"),
            }
        ),
        stderr="",
    )


@pytest.mark.unit
def test_read_returns_requested_lines_from_supplied_root(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n")
    with ReviewReadChannel(tmp_path, tmp_path) as channel:
        result = channel.request(
            {
                "op": "read_file",
                "root": "worktree",
                "path": "a.py",
                "start_line": 2,
                "line_count": 1,
            }
        )
    assert result == {
        "status": "ok",
        "text": "two\n",
        "start_line": 2,
        "total_lines": 3,
    }


@pytest.mark.unit
def test_read_uses_the_named_logical_root(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    spec = tmp_path / "spec"
    worktree.mkdir()
    spec.mkdir()
    (worktree / "same.md").write_text("source\n")
    (spec / "same.md").write_text("requirement\n")
    with ReviewReadChannel(worktree, spec) as channel:
        result = channel.request(
            {
                "op": "read_file",
                "root": "spec",
                "path": "same.md",
                "start_line": 1,
                "line_count": 1,
            }
        )
    assert result["text"] == "requirement\n"


@pytest.mark.unit
@pytest.mark.parametrize(
    "candidate",
    (
        None,
        {"op": "write_file", "root": "worktree", "path": "a"},
        {"op": "list_directory", "root": "other", "path": "."},
        {"op": "list_directory", "root": "worktree", "path": ".", "extra": 1},
        {"op": "list_directory", "root": "worktree", "path": ""},
        {"op": "list_directory", "root": "worktree", "path": "/tmp"},
        {"op": "list_directory", "root": "worktree", "path": "a//b"},
        {"op": "list_directory", "root": "worktree", "path": "a/./b"},
        {"op": "list_directory", "root": "worktree", "path": "../escape"},
        {"op": "list_directory", "root": "worktree", "path": "bad\0name"},
        {
            "op": "read_file",
            "root": "worktree",
            "path": "a",
            "start_line": True,
            "line_count": 1,
        },
        {
            "op": "read_file",
            "root": "worktree",
            "path": "a",
            "start_line": 1,
            "line_count": False,
        },
        {
            "op": "read_file",
            "root": "worktree",
            "path": "a",
            "start_line": 0,
            "line_count": 1,
        },
        {
            "op": "read_file",
            "root": "worktree",
            "path": "a",
            "start_line": 1,
            "line_count": 201,
        },
    ),
)
def test_request_rejects_values_outside_the_closed_schema(
    tmp_path: Path, candidate: object
) -> None:
    with ReviewReadChannel(tmp_path, tmp_path) as channel:
        with pytest.raises(ReviewTriageError):
            channel.request(candidate)


@pytest.mark.unit
def test_request_rejects_symlink_path_components_and_files(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    root = tmp_path / "root"
    outside.mkdir()
    root.mkdir()
    (outside / "secret").write_text("secret\n")
    (root / "linked-dir").symlink_to(outside, target_is_directory=True)
    (root / "linked-file").symlink_to(outside / "secret")
    with ReviewReadChannel(root, root) as channel:
        for path in ("linked-dir/secret", "linked-file"):
            with pytest.raises(ReviewTriageError):
                channel.request(
                    {
                        "op": "read_file",
                        "root": "worktree",
                        "path": path,
                        "start_line": 1,
                        "line_count": 1,
                    }
                )


@pytest.mark.unit
def test_channel_rejects_a_symlink_in_the_supplied_root_chain(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(ReviewTriageError):
        with ReviewReadChannel(linked, real):
            pass


@pytest.mark.unit
def test_root_replacement_does_not_redirect_a_read(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "value.txt").write_text("pinned\n")
    with ReviewReadChannel(root, root) as channel:
        root.rename(tmp_path / "original")
        root.mkdir()
        (root / "value.txt").write_text("replacement\n")
        result = channel.request(
            {
                "op": "read_file",
                "root": "worktree",
                "path": "value.txt",
                "start_line": 1,
                "line_count": 1,
            }
        )
    assert result["text"] == "pinned\n"


@pytest.mark.unit
def test_read_rejects_hard_links_and_special_files(tmp_path: Path) -> None:
    original = tmp_path / "original"
    original.write_text("shared\n")
    os.link(original, tmp_path / "hard-link")
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    with ReviewReadChannel(tmp_path, tmp_path) as channel:
        for path in ("hard-link", "pipe"):
            with pytest.raises(ReviewTriageError):
                channel.request(
                    {
                        "op": "read_file",
                        "root": "worktree",
                        "path": path,
                        "start_line": 1,
                        "line_count": 1,
                    }
                )


@pytest.mark.unit
@pytest.mark.parametrize("content", (b"nul\0byte\n", b"bad-utf8-\xff\n"))
def test_read_reports_binary_content_as_unavailable(tmp_path: Path, content: bytes) -> None:
    (tmp_path / "binary").write_bytes(content)
    with ReviewReadChannel(tmp_path, tmp_path) as channel:
        result = channel.request(
            {
                "op": "read_file",
                "root": "worktree",
                "path": "binary",
                "start_line": 1,
                "line_count": 1,
            }
        )
    assert result["status"] == "unavailable"
    assert isinstance(result["reason"], str)


@pytest.mark.unit
def test_read_reports_oversized_source_and_output_as_unavailable(tmp_path: Path) -> None:
    (tmp_path / "large-source").write_bytes(b"x" * (1024 * 1024 + 1))
    (tmp_path / "large-output").write_bytes(b"y" * (64 * 1024 + 1) + b"\n")
    with ReviewReadChannel(tmp_path, tmp_path) as channel:
        source_result = channel.request(
            {
                "op": "read_file",
                "root": "worktree",
                "path": "large-source",
                "start_line": 1,
                "line_count": 1,
            }
        )
        output_result = channel.request(
            {
                "op": "read_file",
                "root": "worktree",
                "path": "large-output",
                "start_line": 1,
                "line_count": 1,
            }
        )
    assert source_result["status"] == "unavailable"
    assert output_result["status"] == "unavailable"


@pytest.mark.unit
def test_read_reports_json_expanded_output_as_unavailable(tmp_path: Path) -> None:
    (tmp_path / "unicode").write_text("😀" * 10_000 + "\n", encoding="utf-8")
    with ReviewReadChannel(tmp_path, tmp_path) as channel:
        result = channel.request(
            {
                "op": "read_file",
                "root": "worktree",
                "path": "unicode",
                "start_line": 1,
                "line_count": 1,
            }
        )
    assert result["status"] == "unavailable"


@pytest.mark.unit
def test_list_directory_returns_sorted_bounded_regular_entries(tmp_path: Path) -> None:
    (tmp_path / "z.txt").write_text("z")
    (tmp_path / "a-dir").mkdir()
    (tmp_path / "m.txt").write_text("m")
    with ReviewReadChannel(tmp_path, tmp_path) as channel:
        result = channel.request(
            {"op": "list_directory", "root": "worktree", "path": "."}
        )
    assert result == {
        "status": "ok",
        "entries": [
            {"name": "a-dir", "type": "directory"},
            {"name": "m.txt", "type": "file"},
            {"name": "z.txt", "type": "file"},
        ],
    }


@pytest.mark.unit
def test_list_directory_rejects_symlink_and_special_entries(tmp_path: Path) -> None:
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "target").write_text("ok")
    (clean / "link").symlink_to(clean / "target")
    with ReviewReadChannel(tmp_path, tmp_path) as channel:
        with pytest.raises(ReviewTriageError):
            channel.request(
                {"op": "list_directory", "root": "worktree", "path": "clean"}
            )


@pytest.mark.unit
def test_list_directory_reports_more_than_500_entries_as_unavailable(tmp_path: Path) -> None:
    for index in range(501):
        (tmp_path / f"entry-{index:03d}").write_text("")
    with ReviewReadChannel(tmp_path, tmp_path) as channel:
        result = channel.request(
            {"op": "list_directory", "root": "worktree", "path": "."}
        )
    assert result["status"] == "unavailable"


@pytest.mark.unit
def test_list_directory_reports_oversized_serialized_reply_as_unavailable(
    tmp_path: Path,
) -> None:
    for index in range(500):
        name = f"entry-{index:03d}-" + "x" * 190
        (tmp_path / name).write_text("")
    with ReviewReadChannel(tmp_path, tmp_path) as channel:
        result = channel.request(
            {"op": "list_directory", "root": "worktree", "path": "."}
        )
    assert result["status"] == "unavailable"


@pytest.mark.unit
def test_closed_channel_rejects_requests(tmp_path: Path) -> None:
    channel = ReviewReadChannel(tmp_path, tmp_path)
    with pytest.raises(ReviewTriageError):
        channel.request({"op": "list_directory", "root": "worktree", "path": "."})
    with channel:
        pass
    with pytest.raises(ReviewTriageError):
        channel.request({"op": "list_directory", "root": "worktree", "path": "."})


@pytest.mark.unit
def test_load_review_prose_inspects_exact_captured_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_bundle(tmp_path, body="ORIGINAL\n")
    inspected: list[tuple[str, bytes]] = []

    def inspect(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        source = Path(command[command.index("--source") + 1])
        artifact_id = command[2]
        inspected.append((artifact_id, source.joinpath(artifact_id).read_bytes()))
        if len(inspected) == 1:
            for path in (tmp_path / ".echelon/prosaic").rglob("echelon.review*.md"):
                path.write_text("MUTATED\n")
        return _fake_inspect(command, **kwargs)

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", inspect)

    artifacts = load_review_prose(tmp_path, timeout_s=10.0)

    assert list(artifacts) == ["echelon.review", *ROLE_NAMES]
    assert all(artifact.body == "ORIGINAL\n" for artifact in artifacts.values())
    assert [item[0] for item in inspected] == [
        "commands/echelon.review.md",
        *(f"subagents/{name}.md" for name in ROLE_NAMES),
    ]
    assert all(b"ORIGINAL" in item[1] for item in inspected)


@pytest.mark.unit
def test_load_review_prose_uses_one_decreasing_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_bundle(tmp_path)
    timeouts: list[float] = []

    def inspect(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        timeouts.append(kwargs["timeout"])  # type: ignore[arg-type]
        return _fake_inspect(command, **kwargs)

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", inspect)
    load_review_prose(tmp_path, timeout_s=2.0)

    assert len(timeouts) == 4
    assert all(0 < timeout <= 2.0 for timeout in timeouts)
    assert timeouts == sorted(timeouts, reverse=True)


@pytest.mark.unit
@pytest.mark.parametrize("missing", ("echelon.review", *ROLE_NAMES))
def test_load_review_prose_rejects_a_missing_fixed_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    _write_bundle(tmp_path)
    directory = "commands" if missing == "echelon.review" else "subagents"
    (tmp_path / ".echelon/prosaic" / directory / f"{missing}.md").unlink()
    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", _fake_inspect)
    with pytest.raises(ReviewTriageError):
        load_review_prose(tmp_path, timeout_s=2.0)


@pytest.mark.unit
@pytest.mark.parametrize("unsafe", ("symlink", "hard-link", "oversize", "binary"))
def test_load_review_prose_rejects_unsafe_source_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str
) -> None:
    _write_bundle(tmp_path)
    target = tmp_path / ".echelon/prosaic/subagents/echelon.review-debugger.md"
    if unsafe == "symlink":
        target.unlink()
        target.symlink_to(tmp_path / ".echelon/prosaic/commands/echelon.review.md")
    elif unsafe == "hard-link":
        target.unlink()
        os.link(tmp_path / ".echelon/prosaic/commands/echelon.review.md", target)
    elif unsafe == "oversize":
        target.write_bytes(b"x" * (128 * 1024 + 1))
    else:
        target.write_bytes(b"---\nname: bad\n---\n\xff")
    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", _fake_inspect)
    with pytest.raises(ReviewTriageError):
        load_review_prose(tmp_path, timeout_s=2.0)


@pytest.mark.unit
def test_load_review_prose_rejects_companions_before_loader_expansion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_bundle(tmp_path, body="Load `agents/extra.md` before acting.\n")
    inspected = False

    def inspect(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal inspected
        inspected = True
        return _fake_inspect(command, **kwargs)

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", inspect)
    with pytest.raises(ReviewTriageError, match="companion"):
        load_review_prose(tmp_path, timeout_s=2.0)
    assert inspected is False


@pytest.mark.unit
def test_load_review_prose_maps_inspection_timeout_to_boundary_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_bundle(tmp_path)

    def inspect(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", inspect)
    with pytest.raises(ReviewTriageError, match="could not be inspected"):
        load_review_prose(tmp_path, timeout_s=2.0)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("body", "metadata_update"),
    (
        ("   \n", {}),
        ("ok\n", {"model": "claude-opus"}),
        ("ok\n", {"provider": "claude"}),
        ("ok\n", {"model_tier": "vendor-special"}),
        ("ok\n", {"effort": "maximum"}),
    ),
)
def test_load_review_prose_rejects_empty_or_non_neutral_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: str,
    metadata_update: dict[str, str],
) -> None:
    _write_bundle(tmp_path)

    def inspect(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        result = _fake_inspect(command, **kwargs)
        payload = json.loads(result.stdout)
        payload["body"] = body
        payload["frontmatter"].update(metadata_update)
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", inspect)
    with pytest.raises(ReviewTriageError):
        load_review_prose(tmp_path, timeout_s=2.0)


@pytest.mark.unit
def test_load_review_prose_rejects_nonpositive_timeout(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    with pytest.raises(ReviewTriageError):
        load_review_prose(tmp_path, timeout_s=0)


@pytest.mark.unit
@pytest.mark.skipif(shutil.which("prosaic") is None, reason="local Prosaic unavailable")
def test_load_review_prose_smokes_real_local_prosaic_without_model_invocation(
    tmp_path: Path,
) -> None:
    _write_bundle(tmp_path)
    artifacts = load_review_prose(tmp_path, timeout_s=10.0)
    assert artifacts["echelon.review"].body == "Bounded review prose.\n"
