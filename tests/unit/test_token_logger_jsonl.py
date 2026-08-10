import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN_LOGGER_PATH = REPO_ROOT / "runtime" / "scripts" / "token-logger.py"


def _load_token_logger():
    spec = importlib.util.spec_from_file_location("token_logger", TOKEN_LOGGER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_token_logger_loads_jsonl_journal(tmp_path):
    token_logger = _load_token_logger()
    journal = tmp_path / "reasoning-journal.jsonl"
    journal.write_text(
        '{"agent":"SCOUT","type":"phase_complete","total_tokens":10}\n'
        '{"agent":"SAGE","type":"phase_complete","total_tokens":20}\n',
        encoding="utf-8",
    )

    entries = token_logger.load_journal(journal)

    assert [entry["agent"] for entry in entries] == ["SCOUT", "SAGE"]
    assert [entry["total_tokens"] for entry in entries] == [10, 20]


def test_token_logger_prefers_runs_current(tmp_path):
    token_logger = _load_token_logger()
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text("run-123\n", encoding="utf-8")
    assert token_logger.find_active_run_dir(tmp_path) == run_dir


def test_token_logger_defaults_to_runs_without_an_active_run(tmp_path):
    token_logger = _load_token_logger()
    legacy = tmp_path / ".specify" / "squad"
    legacy.mkdir(parents=True)

    assert token_logger.find_active_run_dir(tmp_path) == tmp_path / "runs"


def test_runtime_token_logger_is_the_only_source_copy():
    assert not (REPO_ROOT / "scripts" / "token-logger.py").exists()
    assert ".echelon/runtime/scripts/token-logger.py" in TOKEN_LOGGER_PATH.read_text(
        encoding="utf-8"
    )
