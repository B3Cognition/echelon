"""Safety boundaries for Phase A implementation target selection."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.unit
def test_spec_run_rejects_unsupported_source_option_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon import cli

    monkeypatch.setattr(cli, "_enforce_project_config_compatibility", lambda _root: None)
    monkeypatch.setattr(cli, "_workspace_git_preflight", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        cli,
        "_resolve_spec_run_implementation_targets",
        lambda *_args, **_kwargs: pytest.fail("target resolution must not run"),
    )

    with pytest.raises(SystemExit) as raised:
        cli._cmd_run(
            ["hello", "--source", "sources/demo"],
            project_root=tmp_path,
            ext_dir=tmp_path,
        )

    assert raised.value.code == 2
    error = capsys.readouterr().err
    assert "unknown option '--source'" in error
    assert "use --target" in error


@pytest.mark.unit
def test_spec_run_requires_explicit_target_when_workspace_has_no_sources(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _resolve_spec_run_implementation_targets

    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text("sources: []\n", encoding="utf-8")

    with pytest.raises(SystemExit) as raised:
        _resolve_spec_run_implementation_targets(
            tmp_path,
            [],
            allow_missing=False,
        )

    assert raised.value.code == 1
    assert "no implementation target" in capsys.readouterr().err.lower()
