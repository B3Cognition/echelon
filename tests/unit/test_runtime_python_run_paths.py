from pathlib import Path

from scripts import ns003_agm
from scripts.ca import soar
from scripts.python import trace_shim


def test_runtime_python_utilities_honor_echelon_run_dir(tmp_path, monkeypatch):
    run_dir = tmp_path / "runs" / "spec-current"
    run_dir.mkdir(parents=True)
    monkeypatch.setenv("ECHELON_RUN_DIR", str(run_dir))

    assert ns003_agm._default_run_dir("spec-other") == run_dir
    assert Path(soar._run_dir("spec-other")) == run_dir
    assert trace_shim._auto_detect_trace_dir() == run_dir


def test_run_id_resolvers_do_not_discover_legacy_squad_directory(tmp_path, monkeypatch):
    legacy_run = tmp_path / "squad" / "legacy-run"
    legacy_run.mkdir(parents=True)
    (tmp_path / "squad" / ".current").write_text("legacy-run\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ECHELON_RUN_DIR", raising=False)
    monkeypatch.delenv("ECHELON_SQUAD_DIR", raising=False)

    assert ns003_agm._default_run_dir("spec-new") == tmp_path / "runs" / "spec-new"
    assert Path(soar._run_dir("spec-new")) == tmp_path / "runs" / "spec-new"


def test_soar_loads_chunking_from_canonical_workspace_config(tmp_path, monkeypatch):
    config = tmp_path / ".echelon" / "config.yml"
    config.parent.mkdir()
    config.write_text(
        "ca_overlays:\n  soar:\n    chunking_enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(soar, "_repo_root", lambda: str(tmp_path))

    assert soar._load_config() == {"chunking_enabled": True}


def test_soar_discovers_workspace_from_echelon_directory(tmp_path, monkeypatch):
    (tmp_path / ".echelon").mkdir()
    nested = tmp_path / "sources" / "api"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert Path(soar._repo_root()) == tmp_path
