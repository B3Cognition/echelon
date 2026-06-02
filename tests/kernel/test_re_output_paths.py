from pathlib import Path

from kernel.re_state import resolve_re_output_dir


def test_resolve_re_output_dir_uses_active_run_when_config_is_default(tmp_path):
    run_dir = tmp_path / "runs" / "spec-20260602"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text("spec-20260602")

    assert resolve_re_output_dir(tmp_path) == "runs/spec-20260602/re"


def test_resolve_re_output_dir_keeps_explicit_config_override(tmp_path):
    run_dir = tmp_path / "runs" / "spec-20260602"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text("spec-20260602")

    assert resolve_re_output_dir(tmp_path, "custom/re-output") == "custom/re-output"


def test_resolve_re_output_dir_falls_back_for_standalone_re(tmp_path):
    assert resolve_re_output_dir(tmp_path) == ".specify/echelon/re"
