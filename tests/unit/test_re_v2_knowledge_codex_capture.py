"""RE screening policy at the Codex pipe boundary; no live provider calls."""
from __future__ import annotations

import json
import subprocess
import sys
from functools import partial

import pytest

from harness.ai_cli_backend import CliRunRequest
from harness.ai_cli_backends.codex import CodexCliBackend
from harness.config import HarnessConfig, LlmConfig
from harness.re_v2.knowledge_evidence import screen_provider_output
from harness.re_v2.ledger import ObjectStore


def _invoke(tmp_path, monkeypatch, wire: bytes, stderr: bytes = b""):
    # Only replace the external model process. The adapter, bounded pipe reader,
    # final-event handling and RE scanner/quarantine are real production code.
    real_popen = subprocess.Popen

    def launch(_command, **kwargs):
        script = f"import sys; sys.stdout.buffer.write({wire!r}); sys.stderr.buffer.write({stderr!r})"
        return real_popen([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr("harness.ai_cli_backends.codex.subprocess.Popen", launch)
    backend = CodexCliBackend(HarnessConfig(
        target_repo=".", target_default_branch="main", provider="docker", llm=LlmConfig(cli="codex"),
    ))
    quarantine = ObjectStore(tmp_path / "quarantine")
    result = backend.run_prompt_screened(
        CliRunRequest(cwd=str(tmp_path), prompt="Synthetic fixture", env={}, timeout_s=5),
        screen_output=partial(screen_provider_output, quarantine=quarantine),
        max_capture_bytes=8192,
    )
    return result, quarantine


def _answer(text: str) -> bytes:
    return (json.dumps({"type": "item.completed", "item": {
        "id": "message-1", "type": "agent_message", "text": text,
    }}) + '\n{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":5}}\n').encode()


def test_safe_codex_answer_crosses_real_re_screen_without_quarantine(tmp_path, monkeypatch, capsys):
    result, quarantine = _invoke(tmp_path, monkeypatch, _answer('{"ok":true}'))
    assert result.exit_code == 0
    assert result.stdout == '{"ok":true}'
    assert result.stderr == ""
    assert result.token_usage == 15
    assert not any(path.is_file() for path in quarantine.root.rglob("*"))
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("location", ["answer", "escaped-answer", "escaped-diagnostic", "stderr"])
def test_codex_canary_is_quarantined_before_return_or_console(tmp_path, monkeypatch, capsys, location):
    canary = "ghp_" + "K" * 36  # Synthetic scanner fixture, not a credential.
    wire, stderr = _answer('{"ok":true}'), b""
    if location in {"answer", "escaped-answer"}:
        wire = _answer(json.dumps({"claim": canary}))
        if location == "escaped-answer":
            wire = wire.replace(b"ghp_", b"\\u0067hp_")
    elif location == "escaped-diagnostic":
        diagnostic = json.dumps({"type": "unknown.diagnostic", "data": {"value": canary}})
        wire += diagnostic.replace("ghp_", r"\u0067hp_").encode() + b"\n"
    else:
        stderr = ("provider failure " + canary).encode()
    result, quarantine = _invoke(tmp_path, monkeypatch, wire, stderr)
    assert result.exit_code != 0
    assert result.stdout == ""
    assert canary not in repr(result)
    assert "K" * 36 not in repr(result)
    assert capsys.readouterr() == ("", "")
    objects = [path for path in quarantine.root.rglob("*") if path.is_file()]
    assert objects
    assert quarantine.root.stat().st_mode & 0o077 == 0
    assert all(path.stat().st_mode & 0o077 == 0 for path in objects)
    assert any(b"K" * 36 in path.read_bytes() for path in objects)


def test_duplicate_json_key_canary_is_quarantined_before_rejection(
    tmp_path, monkeypatch, capsys
):
    canary = "ghp_" + "D" * 36  # Synthetic scanner fixture, not a credential.
    wire = _answer('{"ok":true}') + (
        b'{"type":"unknown.diagnostic","data":{"value":"\\u0067hp_'
        + b"D" * 36
        + b'","value":"safe"}}\n'
    )

    result, quarantine = _invoke(tmp_path, monkeypatch, wire)

    assert result.exit_code != 0
    assert result.stdout == ""
    assert canary not in repr(result)
    assert capsys.readouterr() == ("", "")
    objects = [path for path in quarantine.root.rglob("*") if path.is_file()]
    assert objects
    assert any(b"D" * 36 in path.read_bytes() for path in objects)
