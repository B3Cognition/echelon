"""Tests for the deterministic spec-switch CLI boundary."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from echelon.spec_lifecycle import SpecRun
from echelon.spec_switch import (
    DirtySpecWorktreeError,
    SpecSwitchOutcome,
    ValidatedSpecCheckpoint,
)
from echelon.spec_switch_cli import (
    SpecSwitchCliError,
    parse_spec_switch_args,
    run_spec_switch_command,
)


class _TTYStringIO(StringIO):
    def isatty(self) -> bool:
        return True


def _outcome(root: Path, *, action: str = "switched") -> SpecSwitchOutcome:
    source = SpecRun(
        run_dir=root / "runs" / "run-a",
        run_dir_name="run-a",
        run_id="runtime-a",
        spec_id="001-spec-a",
        feature_branch="001-spec-a",
        spec_dir=root / "runs" / "run-a" / "specs" / "001-spec-a",
        published_spec_dir=root / "specs" / "001-spec-a",
    )
    target = SpecRun(
        run_dir=root / "runs" / "run-b",
        run_dir_name="run-b",
        run_id="runtime-b",
        spec_id="002-spec-b",
        feature_branch="002-spec-b",
        spec_dir=root / "runs" / "run-b" / "specs" / "002-spec-b",
        published_spec_dir=root / "specs" / "002-spec-b",
    )
    source_checkpoint = ValidatedSpecCheckpoint("phase-a", "phase-a", "a" * 40, source)
    target_checkpoint = ValidatedSpecCheckpoint("phase-b", "phase-b", "b" * 40, target)
    return SpecSwitchOutcome(
        action=action,
        source=source,
        target=target,
        source_checkpoint=source_checkpoint,
        target_checkpoint=target_checkpoint,
    )


@pytest.mark.parametrize(
    ("args", "identity", "dirty_action", "confirm", "restore"),
    [
        (["002-spec-b"], "002-spec-b", "refuse", False, False),
        (["runtime-b", "--stash"], "runtime-b", "stash", False, False),
        (
            ["run-b", "--discard", "--confirm", "--restore-stash"],
            "run-b",
            "discard",
            True,
            True,
        ),
        (["002", "--restore-stash"], "002", "refuse", False, True),
    ],
)
def test_parse_spec_switch_args_accepts_supported_options(
    args: list[str],
    identity: str,
    dirty_action: str,
    confirm: bool,
    restore: bool,
) -> None:
    options = parse_spec_switch_args(args)

    assert options.identity == identity
    assert options.dirty_action == dirty_action
    assert options.confirm_discard is confirm
    assert options.restore_stash is restore


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ([], "requires a spec or run identity"),
        (["run-b", "--stash", "--discard", "--confirm"], "mutually exclusive"),
        (["run-b", "--discard"], "requires --confirm"),
        (["run-b", "--confirm"], "requires --discard"),
        (["run-b", "--unknown"], "unknown option"),
        (["run-a", "run-b"], "unexpected argument"),
    ],
)
def test_parse_spec_switch_args_rejects_unsafe_or_ambiguous_options(
    args: list[str],
    message: str,
) -> None:
    with pytest.raises(SpecSwitchCliError, match=message):
        parse_spec_switch_args(args)


def test_noninteractive_command_forwards_options_and_prints_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, str, str, bool, bool]] = []

    def fake_switch(root, identity, *, dirty_action, confirm_discard, restore_stash):
        calls.append((root, identity, dirty_action, confirm_discard, restore_stash))
        return _outcome(root)

    monkeypatch.setattr("echelon.spec_switch_cli.switch_spec", fake_switch)
    stdout = StringIO()
    stderr = StringIO()

    result = run_spec_switch_command(
        ["run-b", "--stash", "--restore-stash"],
        project_root=tmp_path,
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert calls == [(tmp_path.resolve(), "run-b", "stash", False, True)]
    assert "run-b" in stdout.getvalue()
    assert "002-spec-b" in stdout.getvalue()
    assert "phase-b" in stdout.getvalue()
    assert "bbbbbbb" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_noninteractive_dirty_refusal_lists_paths_and_retry_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_args, **_kwargs):
        raise DirtySpecWorktreeError(("src/app.py", "notes.txt"))

    monkeypatch.setattr("echelon.spec_switch_cli.switch_spec", refuse)
    stderr = StringIO()

    result = run_spec_switch_command(
        ["run-b"],
        project_root=tmp_path,
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert result == 1
    assert "src/app.py" in stderr.getvalue()
    assert "notes.txt" in stderr.getvalue()
    assert "--stash" in stderr.getvalue()
    assert "--discard --confirm" in stderr.getvalue()


def test_interactive_stash_choice_retries_switch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    def fake_switch(_root, _identity, *, dirty_action, confirm_discard, **_kwargs):
        calls.append((dirty_action, confirm_discard))
        if dirty_action == "refuse":
            raise DirtySpecWorktreeError(("src/app.py",))
        return _outcome(tmp_path)

    monkeypatch.setattr("echelon.spec_switch_cli.switch_spec", fake_switch)

    result = run_spec_switch_command(
        ["run-b"],
        project_root=tmp_path,
        stdin=_TTYStringIO("s\n"),
        stdout=_TTYStringIO(),
        stderr=StringIO(),
    )

    assert result == 0
    assert calls == [("refuse", False), ("stash", False)]


def test_interactive_discard_requires_second_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    def fake_switch(_root, _identity, *, dirty_action, confirm_discard, **_kwargs):
        calls.append((dirty_action, confirm_discard))
        if dirty_action == "refuse":
            raise DirtySpecWorktreeError(("src/app.py",))
        return _outcome(tmp_path)

    monkeypatch.setattr("echelon.spec_switch_cli.switch_spec", fake_switch)

    result = run_spec_switch_command(
        ["run-b"],
        project_root=tmp_path,
        stdin=_TTYStringIO("d\ny\n"),
        stdout=_TTYStringIO(),
        stderr=StringIO(),
    )

    assert result == 0
    assert calls == [("refuse", False), ("discard", True)]


@pytest.mark.parametrize("answer", ["\n", "c\n", "d\nn\n"])
def test_interactive_cancel_is_the_default_and_does_not_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
) -> None:
    calls = 0

    def refuse(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise DirtySpecWorktreeError(("src/app.py",))

    monkeypatch.setattr("echelon.spec_switch_cli.switch_spec", refuse)
    stdout = _TTYStringIO()

    result = run_spec_switch_command(
        ["run-b"],
        project_root=tmp_path,
        stdin=_TTYStringIO(answer),
        stdout=stdout,
        stderr=StringIO(),
    )

    assert result == 1
    assert calls == 1
    assert "cancelled" in stdout.getvalue().lower()
