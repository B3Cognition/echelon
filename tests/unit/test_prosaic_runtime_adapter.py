"""Echelon's compatibility adapter must not broaden explicit Prosaic grants."""
import json

from prosaic_runtime.openai_compatible import OpenAICompatibleBackend as SharedBackend
from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend, _OpenAIToolRegistry


def _write(registry):
    result = registry.execute_message({"id": "write", "function": {
        "name": "write_file", "arguments": '{"path":"output","content":"bad"}'}})
    return json.loads(result["content"])


def test_echelon_inherits_shared_transport():
    assert issubclass(OpenAICompatibleBackend, SharedBackend)


def test_explicit_read_role_cannot_write(tmp_path):
    registry = _OpenAIToolRegistry(tmp_path, {}, {"tools": "read"})
    assert "write_file" not in {item["function"]["name"] for item in registry.openai_tools()}
    assert _write(registry)["status"] == "error"
    assert not (tmp_path / "output").exists()


def test_exclusive_empty_write_scope_denies_writes(tmp_path):
    registry = _OpenAIToolRegistry(tmp_path, {}, {"tool_write_scope_exclusive": True, "tool_write_paths": []})
    assert _write(registry)["status"] == "error"
    assert not (tmp_path / "output").exists()
