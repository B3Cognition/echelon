import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN_LOGGER_PATH = REPO_ROOT / "extension" / "scripts" / "token-logger.py"


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
