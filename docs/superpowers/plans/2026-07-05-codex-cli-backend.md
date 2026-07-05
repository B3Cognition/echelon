# Codex CLI Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace CLI-specific branching in the AI coding provider path with concrete backend classes and add a first-class Codex CLI backend.

**Architecture:** `AICodingCliProvider` becomes a thin facade over concrete `AICodingCliBackend` implementations. `ClaudeCliBackend` preserves current stream-json behavior, while `CodexCliBackend` owns `codex exec`, JSONL parsing, and `--output-last-message` fallback. Echelon users still select the backend once through `harness.llm.cli`; no Codex-specific model, effort, profile, or frontmatter behavior is added.

**Tech Stack:** Python 3.11+, subprocess, dataclasses, typing Protocol, pytest, existing `harness.llm_tool_policy`.

## Global Constraints

- Keep Docker as the harness sandbox provider; do not add `provider: codex`.
- Keep `harness.llm.cli` as the only LLM backend selector for this change.
- Do not add Codex-specific config for model, effort, profile, local provider, or agent frontmatter.
- Keep unsafe host execution gated by `harness.llm.tool_policy.allow_unsafe_host_execution` plus `approval_reason`.
- Preserve current Claude behavior unless a task explicitly migrates it behind the new backend interface.
- Use TDD: each task starts with a failing test, then minimal implementation.
- Do not modify unrelated uncommitted documentation files.

---

## File Structure

- Create `src/harness/ai_cli_backend.py`: shared request/result dataclasses, backend protocol, backend factory.
- Create `src/harness/ai_cli_backends/__init__.py`: exports backend classes for factory registration.
- Create `src/harness/ai_cli_backends/claude.py`: Claude stream-json backend migrated from existing provider logic.
- Create `src/harness/ai_cli_backends/plain.py`: shared plain subprocess backend for Copilot and fallback-style CLIs.
- Create `src/harness/ai_cli_backends/codex.py`: Codex JSONL backend with final-message-file fallback.
- Modify `src/harness/llm_provider.py`: facade only; no CLI-specific branching beyond backend factory use.
- Modify `src/harness/squad_provider.py`: ask the facade/backend for agent output, then keep existing `echelon_result` extraction and validation.
- Modify `src/harness/review_loop.py`: use the facade/backend or shared backend command path instead of local command construction.
- Modify `src/echelon/cli.py`: direct skill dispatch should route Codex through the same backend command behavior where practical; do not add Codex-specific config.
- Modify tests under `tests/unit/`: add backend unit tests and update provider/review tests.

---

### Task 1: Define Backend Interfaces

**Files:**
- Create: `src/harness/ai_cli_backend.py`
- Test: `tests/unit/test_ai_cli_backend.py`

**Interfaces:**
- Produces: `CliRunRequest`, `CliRunResult`, `AICodingCliBackend`, `create_ai_cli_backend(config: HarnessConfig) -> AICodingCliBackend`
- Consumes: `HarnessConfig`, `LlmToolPolicy`

- [ ] **Step 1: Write the failing tests**

Add `tests/unit/test_ai_cli_backend.py`:

```python
from __future__ import annotations

import pytest

from harness.ai_cli_backend import CliRunRequest, CliRunResult, create_ai_cli_backend
from harness.config import HarnessConfig, LlmConfig


def _config(cli: str) -> HarnessConfig:
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli=cli),
    )


def test_cli_run_result_defaults() -> None:
    result = CliRunResult(exit_code=0, stdout="ok", stderr="")

    assert result.exit_code == 0
    assert result.stdout == "ok"
    assert result.stderr == ""
    assert result.token_usage == 0
    assert result.cost_usd == 0.0
    assert result.timed_out is False


def test_cli_run_request_carries_prompt_and_timeout(tmp_path) -> None:
    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Do work.",
        env={"A": "B"},
        timeout_s=12.5,
    )

    assert request.cwd == str(tmp_path)
    assert request.prompt == "Do work."
    assert request.env == {"A": "B"}
    assert request.timeout_s == 12.5


@pytest.mark.parametrize(
    ("cli", "class_name"),
    [
        ("claude", "ClaudeCliBackend"),
        ("codex", "CodexCliBackend"),
        ("copilot", "PlainCliBackend"),
        ("opencode", "PlainCliBackend"),
    ],
)
def test_backend_factory_returns_concrete_backend(cli: str, class_name: str) -> None:
    backend = create_ai_cli_backend(_config(cli))

    assert backend.__class__.__name__ == class_name
    assert backend.name == cli
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run --extra dev pytest tests/unit/test_ai_cli_backend.py -q
```

Expected: FAIL because `harness.ai_cli_backend` does not exist.

- [ ] **Step 3: Add the interface module**

Create `src/harness/ai_cli_backend.py`:

```python
"""Shared interfaces for host-side AI coding CLI backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol

from harness.config import HarnessConfig


@dataclass(frozen=True)
class CliRunRequest:
    cwd: str
    prompt: str
    env: Mapping[str, str]
    timeout_s: float


@dataclass
class CliRunResult:
    exit_code: int
    stdout: str
    stderr: str
    token_usage: int = 0
    cost_usd: float = 0.0
    timed_out: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


class AICodingCliBackend(Protocol):
    name: str

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        ...

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        ...


def create_ai_cli_backend(config: HarnessConfig) -> AICodingCliBackend:
    from harness.ai_cli_backends.claude import ClaudeCliBackend
    from harness.ai_cli_backends.codex import CodexCliBackend
    from harness.ai_cli_backends.plain import PlainCliBackend

    cli = config.llm.cli
    if cli == "claude":
        return ClaudeCliBackend(config)
    if cli == "codex":
        return CodexCliBackend(config)
    return PlainCliBackend(config)
```

- [ ] **Step 4: Add package exports and minimal backend stubs**

Create `src/harness/ai_cli_backends/__init__.py`:

```python
"""Concrete AI coding CLI backend implementations."""
```

Create `src/harness/ai_cli_backends/claude.py`:

```python
from __future__ import annotations

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig


class ClaudeCliBackend:
    name = "claude"

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        raise NotImplementedError

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self.run_prompt(request)
```

Create `src/harness/ai_cli_backends/codex.py`:

```python
from __future__ import annotations

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig


class CodexCliBackend:
    name = "codex"

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        raise NotImplementedError

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self.run_prompt(request)
```

Create `src/harness/ai_cli_backends/plain.py`:

```python
from __future__ import annotations

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig


class PlainCliBackend:
    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self.name = config.llm.cli

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        raise NotImplementedError

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self.run_prompt(request)
```

- [ ] **Step 5: Run the test to verify it passes**

Run:

```bash
uv run --extra dev pytest tests/unit/test_ai_cli_backend.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/ai_cli_backend.py src/harness/ai_cli_backends tests/unit/test_ai_cli_backend.py
git commit -m "refactor: introduce AI CLI backend interface"
```

---

### Task 2: Migrate Claude Behavior Into `ClaudeCliBackend`

**Files:**
- Modify: `src/harness/ai_cli_backends/claude.py`
- Modify: `src/harness/llm_provider.py`
- Test: `tests/unit/test_llm_provider.py`
- Test: `tests/unit/test_ai_cli_backend.py`

**Interfaces:**
- Consumes: `CliRunRequest`
- Produces: `ClaudeCliBackend.run_prompt(request) -> CliRunResult`, `ClaudeCliBackend.run_agent(request) -> CliRunResult`

- [ ] **Step 1: Write a failing backend-level Claude test**

Append to `tests/unit/test_ai_cli_backend.py`:

```python
import io
import json
from unittest.mock import patch

from harness.ai_cli_backends.claude import ClaudeCliBackend


def test_claude_backend_streams_json_and_captures_result_error(tmp_path) -> None:
    backend = ClaudeCliBackend(_config("claude"))

    class FakeProcess:
        stdout = io.BytesIO(
            (
                json.dumps(
                    {
                        "type": "result",
                        "is_error": True,
                        "result": "session limit reached",
                        "usage": {"input_tokens": 10, "output_tokens": 2},
                    }
                )
                + "\n"
            ).encode()
        )
        returncode = 1

        def kill(self) -> None:
            return None

        def wait(self) -> int:
            return self.returncode

    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Build this.",
        env={},
        timeout_s=10,
    )

    with patch("harness.ai_cli_backends.claude.subprocess.Popen", return_value=FakeProcess()):
        result = backend.run_prompt(request)

    assert result.exit_code == 1
    assert "session limit reached" in result.stdout
    assert result.token_usage == 12
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run --extra dev pytest tests/unit/test_ai_cli_backend.py::test_claude_backend_streams_json_and_captures_result_error -q
```

Expected: FAIL because `ClaudeCliBackend.run_prompt()` raises `NotImplementedError`.

- [ ] **Step 3: Move Claude stream-json logic into `ClaudeCliBackend`**

Replace `src/harness/ai_cli_backends/claude.py` with:

```python
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from collections.abc import Mapping

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig
from harness.llm_provider import _extract_token_usage
from harness.llm_tool_policy import build_llm_cli_command
from harness.skill_loader import StreamEventPrinter


class ClaudeCliBackend:
    name = "claude"

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self._bin = shutil.which("claude") or "claude"

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        cmd = build_llm_cli_command(
            "claude",
            self._bin,
            request.prompt,
            self._config.llm.tool_policy,
            stream_json=True,
            disallow_claude_task_tools=True,
        )
        return self._run_stream_json(cmd, request)

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self.run_prompt(request)

    def _run_stream_json(self, cmd: list[str], request: CliRunRequest) -> CliRunResult:
        proc = subprocess.Popen(
            cmd,
            cwd=request.cwd,
            env=dict(request.env),
            stdout=subprocess.PIPE,
            stderr=None,
        )
        captured_lines: list[str] = []
        text_chunks: list[str] = []
        timed_out = False
        token_usage = 0
        cost_usd = 0.0
        printer = StreamEventPrinter()

        def kill() -> None:
            nonlocal timed_out
            timed_out = True
            proc.kill()

        def capture(text: object) -> None:
            line = str(text or "").strip()
            if not line:
                return
            captured_lines.append(line)
            total = 0
            bounded: list[str] = []
            for item in reversed(captured_lines):
                total += len(item) + 1
                if total > 20_000:
                    break
                bounded.append(item)
            captured_lines[:] = list(reversed(bounded))

        timer = threading.Timer(request.timeout_s, kill)
        try:
            timer.start()
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    printer(event)
                    etype = event.get("type")
                    if etype == "assistant":
                        for block in event.get("message", {}).get("content", []):
                            if block.get("type") == "text":
                                text = block.get("text", "")
                                text_chunks.append(text)
                                capture(text)
                    elif (
                        etype == "content_block_delta"
                        and event.get("delta", {}).get("type") == "text_delta"
                    ):
                        text = event["delta"].get("text", "")
                        text_chunks.append(text)
                        capture(text)
                    elif etype == "result":
                        token_usage = _extract_token_usage(event)
                        cost_usd = float(event.get("total_cost_usd") or 0)
                        if event.get("is_error"):
                            capture(event.get("result", ""))
                except json.JSONDecodeError:
                    capture(line)
                    text_chunks.append(line)
                    print(line, flush=True)
            proc.stdout.close()
            proc.wait()
        finally:
            timer.cancel()

        stdout = "".join(text_chunks).strip() or "\n".join(captured_lines)
        return CliRunResult(
            exit_code=-1 if timed_out else int(proc.returncode),
            stdout=stdout,
            stderr="",
            token_usage=token_usage,
            cost_usd=cost_usd,
            timed_out=timed_out,
        )
```

- [ ] **Step 4: Update `llm_provider.py` to delegate through backend**

Modify `AICodingCliProvider.__init__` and `exec_prompt()`:

```python
from harness.ai_cli_backend import CliRunRequest, CliRunResult, create_ai_cli_backend
```

```python
self._backend = create_ai_cli_backend(config)
```

```python
def run_prompt_result(
    self,
    worktree_path: str,
    prompt: str,
    *,
    extra_env: Mapping[str, str] | None = None,
    timeout_ms: int | None = None,
) -> CliRunResult:
    self.last_stdout = ""
    self.last_stderr = ""
    self.last_token_usage = 0
    env = self._build_env(extra_env)
    timeout_s = (timeout_ms / 1000.0) if timeout_ms else self._timeout_s
    result = self._backend.run_prompt(
        CliRunRequest(
            cwd=worktree_path,
            prompt=prompt,
            env=env,
            timeout_s=timeout_s,
        )
    )
    self.last_stdout = result.stdout
    self.last_stderr = result.stderr
    self.last_token_usage = result.token_usage
    return result

def exec_prompt(...):
    result = self.run_prompt_result(worktree_path, prompt, extra_env=extra_env)
    return result.exit_code
```

Keep `_build_env()` in `llm_provider.py`. Keep `_extract_token_usage()` in place until Task 5 moves or consolidates helpers.

- [ ] **Step 5: Run existing Claude provider tests**

Run:

```bash
uv run --extra dev pytest tests/unit/test_llm_provider.py tests/unit/test_ai_cli_backend.py -q
```

Expected: PASS after updating tests that patch old private methods to patch backend subprocess or assert through public provider state.

- [ ] **Step 6: Commit**

```bash
git add src/harness/ai_cli_backends/claude.py src/harness/llm_provider.py tests/unit/test_llm_provider.py tests/unit/test_ai_cli_backend.py
git commit -m "refactor: move Claude CLI execution into backend"
```

---

### Task 3: Implement Shared Plain Backend For Copilot And Opencode

**Files:**
- Modify: `src/harness/ai_cli_backends/plain.py`
- Test: `tests/unit/test_ai_cli_backend.py`

**Interfaces:**
- Consumes: `CliRunRequest`
- Produces: `PlainCliBackend.run_prompt(request) -> CliRunResult`

- [ ] **Step 1: Write failing plain-backend test**

Append to `tests/unit/test_ai_cli_backend.py`:

```python
from harness.ai_cli_backends.plain import PlainCliBackend


def test_plain_backend_captures_stdout_and_stderr(tmp_path) -> None:
    backend = PlainCliBackend(_config("copilot"))
    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Build this.",
        env={},
        timeout_s=10,
    )

    completed = subprocess.CompletedProcess(
        args=["copilot"],
        returncode=3,
        stdout=b"plain stdout",
        stderr=b"plain stderr",
    )

    with patch("harness.ai_cli_backends.plain.subprocess.run", return_value=completed):
        result = backend.run_prompt(request)

    assert result.exit_code == 3
    assert result.stdout == "plain stdout"
    assert result.stderr == "plain stderr"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run --extra dev pytest tests/unit/test_ai_cli_backend.py::test_plain_backend_captures_stdout_and_stderr -q
```

Expected: FAIL because `PlainCliBackend.run_prompt()` is not implemented.

- [ ] **Step 3: Implement `PlainCliBackend`**

Replace `src/harness/ai_cli_backends/plain.py` with:

```python
from __future__ import annotations

import shutil
import subprocess

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig
from harness.llm_tool_policy import build_llm_cli_command


class PlainCliBackend:
    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self.name = config.llm.cli
        self._bin = shutil.which(self.name) or self.name

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        cmd = build_llm_cli_command(
            self.name,
            self._bin,
            request.prompt,
            self._config.llm.tool_policy,
        )
        try:
            result = subprocess.run(
                cmd,
                cwd=request.cwd,
                env=dict(request.env),
                timeout=request.timeout_s,
                capture_output=True,
            )
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")
            if stdout:
                print(stdout, flush=True)
            if stderr:
                print(stderr, flush=True)
            return CliRunResult(
                exit_code=int(result.returncode),
                stdout=stdout,
                stderr=stderr,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or b"").decode("utf-8", errors="replace")
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
            return CliRunResult(
                exit_code=-1,
                stdout=stdout,
                stderr=stderr,
                timed_out=True,
            )

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self.run_prompt(request)
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run --extra dev pytest tests/unit/test_ai_cli_backend.py tests/unit/test_llm_provider.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/ai_cli_backends/plain.py tests/unit/test_ai_cli_backend.py
git commit -m "refactor: add shared plain AI CLI backend"
```

---

### Task 4: Implement `CodexCliBackend`

**Files:**
- Modify: `src/harness/ai_cli_backends/codex.py`
- Modify: `src/harness/llm_tool_policy.py`
- Test: `tests/unit/test_ai_cli_backend.py`
- Test: `tests/unit/test_llm_tool_policy.py`

**Interfaces:**
- Consumes: `CliRunRequest`
- Produces: `CodexCliBackend.run_prompt(request) -> CliRunResult`, `CodexCliBackend.run_agent(request) -> CliRunResult`

- [ ] **Step 1: Write failing command-builder test**

Append to `tests/unit/test_llm_tool_policy.py`:

```python
def test_codex_command_can_request_json_and_output_last_message() -> None:
    cmd = build_llm_cli_command(
        "codex",
        "codex",
        "Do the work.",
        LlmToolPolicy(),
        codex_json=True,
        output_last_message="/tmp/codex-last.txt",
    )

    assert cmd[:2] == ["codex", "exec"]
    assert "--json" in cmd
    assert "--output-last-message" in cmd
    assert cmd[cmd.index("--output-last-message") + 1] == "/tmp/codex-last.txt"
    assert cmd[-1].startswith("## Effective Host Tool Policy")
```

- [ ] **Step 2: Run the command-builder test to verify it fails**

Run:

```bash
uv run --extra dev pytest tests/unit/test_llm_tool_policy.py::test_codex_command_can_request_json_and_output_last_message -q
```

Expected: FAIL because `codex_json` and `output_last_message` are not accepted.

- [ ] **Step 3: Extend `build_llm_cli_command()` for Codex JSON mode**

Modify signature in `src/harness/llm_tool_policy.py`:

```python
def build_llm_cli_command(
    cli: str,
    bin_: str,
    prompt: str,
    policy: LlmToolPolicy,
    *,
    stream_json: bool = False,
    disallow_claude_task_tools: bool = False,
    codex_json: bool = False,
    output_last_message: str | None = None,
) -> list[str]:
```

Modify the Codex block:

```python
if cli == "codex":
    cmd = [bin_, "exec"]
    if policy.allow_unsafe_host_execution:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    if codex_json:
        cmd.append("--json")
    if output_last_message:
        cmd += ["--output-last-message", output_last_message]
    cmd.append(effective_prompt)
    return cmd
```

- [ ] **Step 4: Write failing Codex backend parsing tests**

Append to `tests/unit/test_ai_cli_backend.py`:

```python
from harness.ai_cli_backends.codex import CodexCliBackend


def test_codex_backend_parses_jsonl_and_final_message_file(tmp_path) -> None:
    backend = CodexCliBackend(_config("codex"))
    final_message = tmp_path / "last-message.txt"

    class FakeProcess:
        stdout = io.BytesIO(
            (
                json.dumps({"type": "message", "role": "assistant", "content": "working"})
                + "\n"
            ).encode()
        )
        stderr = io.BytesIO(b"")
        returncode = 0

        def kill(self) -> None:
            return None

        def wait(self) -> int:
            final_message.write_text("echelon_result:\n  verdict: PASS\n  state_updates: {}\n")
            return self.returncode

    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Do work.",
        env={},
        timeout_s=10,
    )

    with patch("harness.ai_cli_backends.codex.tempfile.NamedTemporaryFile") as named, patch(
        "harness.ai_cli_backends.codex.subprocess.Popen",
        return_value=FakeProcess(),
    ):
        named.return_value.__enter__.return_value.name = str(final_message)
        result = backend.run_agent(request)

    assert result.exit_code == 0
    assert "working" in result.stdout
    assert "echelon_result:" in result.stdout


def test_codex_backend_falls_back_to_plain_stdout(tmp_path) -> None:
    backend = CodexCliBackend(_config("codex"))

    class FakeProcess:
        stdout = io.BytesIO(b"plain codex output\n")
        stderr = io.BytesIO(b"")
        returncode = 0

        def kill(self) -> None:
            return None

        def wait(self) -> int:
            return self.returncode

    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Do work.",
        env={},
        timeout_s=10,
    )

    with patch("harness.ai_cli_backends.codex.subprocess.Popen", return_value=FakeProcess()):
        result = backend.run_prompt(request)

    assert result.exit_code == 0
    assert "plain codex output" in result.stdout
```

- [ ] **Step 5: Run Codex tests to verify they fail**

Run:

```bash
uv run --extra dev pytest tests/unit/test_ai_cli_backend.py::test_codex_backend_parses_jsonl_and_final_message_file tests/unit/test_ai_cli_backend.py::test_codex_backend_falls_back_to_plain_stdout -q
```

Expected: FAIL because `CodexCliBackend` is not implemented.

- [ ] **Step 6: Implement `CodexCliBackend`**

Replace `src/harness/ai_cli_backends/codex.py` with:

```python
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig
from harness.llm_tool_policy import build_llm_cli_command


class CodexCliBackend:
    name = "codex"

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self._bin = shutil.which("codex") or "codex"

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        return self._run_codex(request, use_final_message=True)

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self._run_codex(request, use_final_message=True)

    def _run_codex(self, request: CliRunRequest, *, use_final_message: bool) -> CliRunResult:
        final_path = ""
        temp_file = None
        if use_final_message:
            temp_file = tempfile.NamedTemporaryFile(prefix="echelon-codex-", suffix=".txt", delete=False)
            final_path = temp_file.name
            temp_file.close()

        cmd = build_llm_cli_command(
            "codex",
            self._bin,
            request.prompt,
            self._config.llm.tool_policy,
            codex_json=True,
            output_last_message=final_path or None,
        )
        proc = subprocess.Popen(
            cmd,
            cwd=request.cwd,
            env=dict(request.env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        timed_out = False

        def kill() -> None:
            nonlocal timed_out
            timed_out = True
            proc.kill()

        timer = threading.Timer(request.timeout_s, kill)
        try:
            timer.start()
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                text = _codex_event_text(line)
                stdout_chunks.append(text)
                print(text, flush=True)
            if proc.stderr is not None:
                stderr_chunks.append(proc.stderr.read().decode("utf-8", errors="replace"))
            proc.wait()
        finally:
            timer.cancel()

        if final_path and os.path.exists(final_path):
            final_text = open(final_path, encoding="utf-8", errors="replace").read()
            if final_text.strip() and final_text not in stdout_chunks:
                stdout_chunks.append(final_text)
            try:
                os.unlink(final_path)
            except OSError:
                pass

        return CliRunResult(
            exit_code=-1 if timed_out else int(proc.returncode),
            stdout="\n".join(chunk for chunk in stdout_chunks if chunk),
            stderr="\n".join(chunk for chunk in stderr_chunks if chunk),
            timed_out=timed_out,
        )


def _codex_event_text(line: str) -> str:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return line

    for key in ("content", "text", "message", "result"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value

    item = event.get("item")
    if isinstance(item, dict):
        for key in ("content", "text", "message"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value

    return line
```

- [ ] **Step 7: Run Codex backend and policy tests**

Run:

```bash
uv run --extra dev pytest tests/unit/test_ai_cli_backend.py tests/unit/test_llm_tool_policy.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/harness/ai_cli_backends/codex.py src/harness/llm_tool_policy.py tests/unit/test_ai_cli_backend.py tests/unit/test_llm_tool_policy.py
git commit -m "feat: add Codex AI CLI backend"
```

---

### Task 5: Route Squad Provider Through Backend Results

**Files:**
- Modify: `src/harness/llm_provider.py`
- Modify: `src/harness/squad_provider.py`
- Test: `tests/unit/test_squad_provider.py`
- Test: `tests/unit/test_llm_provider.py`

**Interfaces:**
- Consumes: `AICodingCliProvider.run_agent_result(project_root, prompt, timeout_ms=None) -> CliRunResult`
- Produces: `SquadCliProvider.exec_agent(...) -> SquadAgentResult`

- [ ] **Step 1: Add failing Codex squad parsing test**

Append to `tests/unit/test_squad_provider.py`:

```python
from harness.ai_cli_backend import CliRunResult
from harness.config import HarnessConfig, LlmConfig
from harness.squad_provider import SquadCliProvider


def test_squad_provider_parses_codex_backend_echelon_result(monkeypatch, tmp_path) -> None:
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="codex"),
    )
    provider = SquadCliProvider(config)

    def fake_run_agent_result(project_root, prompt, timeout_ms=None):
        return CliRunResult(
            exit_code=0,
            stdout="echelon_result:\n  verdict: PASS\n  state_updates: {}\n",
            stderr="",
        )

    monkeypatch.setattr(provider, "run_agent_result", fake_run_agent_result)

    result = provider.exec_agent(str(tmp_path), "prompt")

    assert result.exit_code == 0
    assert result.verdict == "PASS"
    assert result.raw_output.startswith("echelon_result:")
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run --extra dev pytest tests/unit/test_squad_provider.py::test_squad_provider_parses_codex_backend_echelon_result -q
```

Expected: FAIL because `run_agent_result` does not exist or `exec_agent` still branches directly.

- [ ] **Step 3: Add `run_agent_result()` to facade**

In `src/harness/llm_provider.py`, add:

```python
def run_agent_result(
    self,
    project_root: str,
    prompt: str,
    *,
    timeout_ms: int | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> CliRunResult:
    env = self._build_env(extra_env)
    timeout_s = (timeout_ms / 1000.0) if timeout_ms else self._timeout_s
    result = self._backend.run_agent(
        CliRunRequest(
            cwd=project_root,
            prompt=prompt,
            env=env,
            timeout_s=timeout_s,
        )
    )
    self.last_stdout = result.stdout
    self.last_stderr = result.stderr
    self.last_token_usage = result.token_usage
    return result
```

- [ ] **Step 4: Simplify `SquadCliProvider.exec_agent()`**

Replace direct subprocess branching in `src/harness/squad_provider.py` with:

```python
start = time.monotonic()
backend_result = self.run_agent_result(
    project_root,
    prompt,
    timeout_ms=timeout_ms,
)
duration_ms = int((time.monotonic() - start) * 1000)
exit_code = backend_result.exit_code
raw = backend_result.stdout
cost_usd = backend_result.cost_usd
timed_out = backend_result.timed_out
```

Keep existing `_extract_echelon_result()`, `_validate_or_block_echelon_result()`, debug capture, and `SquadAgentResult` construction unchanged.

- [ ] **Step 5: Remove obsolete subprocess helper methods from `SquadCliProvider`**

Delete `_run_streaming_captured()` and `_run_plain_captured()` from `src/harness/squad_provider.py` after tests pass through backend delegation. Keep imports only if still used.

- [ ] **Step 6: Run squad and provider tests**

Run:

```bash
uv run --extra dev pytest tests/unit/test_squad_provider.py tests/unit/test_llm_provider.py tests/unit/test_ai_cli_backend.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/harness/llm_provider.py src/harness/squad_provider.py tests/unit/test_squad_provider.py tests/unit/test_llm_provider.py
git commit -m "refactor: route squad agents through AI CLI backends"
```

---

### Task 6: Route Review Loop Through Backend Facade

**Files:**
- Modify: `src/harness/review_loop.py`
- Test: `tests/unit/test_review_loop.py`

**Interfaces:**
- Consumes: `AICodingCliProvider.run_prompt_result(...)`
- Produces: review skill invocation with backend-consistent command/output behavior

- [ ] **Step 1: Write failing review backend delegation test**

Append to `tests/unit/test_review_loop.py`:

```python
from harness.ai_cli_backend import CliRunResult


def test_review_loop_invokes_ai_cli_provider_facade(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class FakeProvider:
        def __init__(self, config):
            self.config = config

        def run_prompt_result(self, worktree_path, prompt, extra_env=None, timeout_ms=None):
            calls.append((worktree_path, prompt, extra_env, timeout_ms))
            return CliRunResult(exit_code=0, stdout="queued", stderr="")

    monkeypatch.setattr("harness.review_loop.AICodingCliProvider", FakeProvider)
    controller = ReviewLoopController(
        gitops=MagicMock(),
        config=_config(cli="codex"),
        spec_id="005",
        strategy_id="default",
        base_dir=str(tmp_path),
        build_id="build-1",
    )

    controller._invoke_review_skill("https://github.com/org/repo/pull/1", [])

    assert calls
    assert calls[0][0] == str(tmp_path)
    assert "review 005 pr_url=https://github.com/org/repo/pull/1" in calls[0][1]
    assert "HARNESS_BUILD_STATUS_FILE" in calls[0][2]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run --extra dev pytest tests/unit/test_review_loop.py::test_review_loop_invokes_ai_cli_provider_facade -q
```

Expected: FAIL because review loop constructs subprocess commands directly.

- [ ] **Step 3: Modify review loop to use facade**

In `src/harness/review_loop.py`, import:

```python
from harness.llm_provider import AICodingCliProvider
```

Replace local command construction in `_invoke_review_skill()` with:

```python
provider = AICodingCliProvider(self._config)
result = provider.run_prompt_result(
    str(self._base_dir),
    prompt,
    extra_env={"HARNESS_BUILD_STATUS_FILE": str(status_file)},
    timeout_ms=int(self._review_timeout_s * 1000),
)
```

Preserve status file handling and token estimate logic:

```python
if result.timed_out:
    logger.warning("echelon.review timed out after %ss", self._review_timeout_s)
    return 0
if result.exit_code != 0:
    logger.warning("echelon.review exited with %s", result.exit_code)
return max(1, len(result.stdout.encode("utf-8")) // 4)
```

- [ ] **Step 4: Remove review-loop command duplication**

Remove direct use of `build_llm_cli_command()` from `review_loop.py` if no longer used. Keep `resolve_llm_prompt()` logic.

- [ ] **Step 5: Run review loop tests**

Run:

```bash
uv run --extra dev pytest tests/unit/test_review_loop.py -q
```

Expected: PASS after updating older assertions that expected direct `subprocess.run()` calls.

- [ ] **Step 6: Commit**

```bash
git add src/harness/review_loop.py tests/unit/test_review_loop.py
git commit -m "refactor: run review loop through AI CLI provider"
```

---

### Task 7: Align Direct Skill Dispatch With Backend Selection

**Files:**
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_cli_llm_tool_policy.py`

**Interfaces:**
- Consumes: existing `_dispatch_skill_command(command, args)`
- Produces: direct `echelon build/review/bugfix/...` commands use the same Codex backend behavior as workspace/squad paths

- [ ] **Step 1: Write failing direct-dispatch Codex test**

Add to `tests/unit/test_cli_llm_tool_policy.py`:

```python
def test_direct_codex_skill_dispatch_uses_ai_cli_provider(monkeypatch, tmp_path: Path) -> None:
    import echelon.cli as cli

    skill_dir = tmp_path / ".claude" / "skills" / "speckit-echelon-build"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text("build $ARGUMENTS", encoding="utf-8")

    calls = []

    class FakeProvider:
        def __init__(self, config):
            self.config = config

        def exec_prompt(self, worktree_path, prompt):
            calls.append((worktree_path, prompt))
            return 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ECHELON_LLM", "codex")
    monkeypatch.setattr("echelon.cli.AICodingCliProvider", FakeProvider)
    monkeypatch.setattr("echelon.cli.load_config", lambda project_dir, squad_only=True: _config("codex"))

    with pytest.raises(SystemExit) as exc:
        cli._dispatch_skill_command("build", ["005"])

    assert exc.value.code == 0
    assert calls
    assert calls[0][0] == str(tmp_path)
    assert "build 005" in calls[0][1]
```

If this test file does not already import `pytest`, `Path`, or `_config`, add local helpers instead of relying on unrelated fixtures.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run --extra dev pytest tests/unit/test_cli_llm_tool_policy.py::test_direct_codex_skill_dispatch_uses_ai_cli_provider -q
```

Expected: FAIL because direct dispatch currently calls `subprocess.run()` for Codex.

- [ ] **Step 3: Update direct dispatch**

In `src/echelon/cli.py`, import `AICodingCliProvider` where direct dispatch can patch it in tests:

```python
from harness.llm_provider import AICodingCliProvider
from harness.config import load_config
```

For `cli in {"copilot", "codex"}`, replace direct `subprocess.run(cmd, cwd=...)` with:

```python
prompt = _build_prompt(skill_path, arguments)
config = load_config(project_dir, squad_only=True)
result_code = AICodingCliProvider(config).exec_prompt(str(project_dir), prompt)
sys.exit(result_code)
```

Keep `opencode` native command dispatch unchanged for now because it has native `--command speckit...` support.

- [ ] **Step 4: Run direct CLI policy tests**

Run:

```bash
uv run --extra dev pytest tests/unit/test_cli_llm_tool_policy.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/cli.py tests/unit/test_cli_llm_tool_policy.py
git commit -m "refactor: route direct Codex skill dispatch through provider"
```

---

### Task 8: Workspace Init Selection And Documentation

**Files:**
- Modify: `src/harness/init.py`
- Modify: `src/echelon/cli.py`
- Modify: `extension/config-template.yml`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/test_workspace_init_deploy_runtime.py`

**Interfaces:**
- Consumes: `ECHELON_LLM=codex`
- Produces: workspace config with `harness.llm.cli: codex`

- [ ] **Step 1: Write or confirm workspace init test for `ECHELON_LLM=codex`**

Add this test to `tests/unit/test_workspace_init_deploy_runtime.py`:

```python
def test_workspace_init_preserves_echelon_llm_codex(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _write_workspace_config(
        tmp_path,
        "  enabled: false\n  type: http\n  blue_port: 18080\n  green_port: 18081\n",
    )
    monkeypatch.setenv("ECHELON_LLM", "codex")
    monkeypatch.setattr(cli, "_provision_wing", lambda _project_dir, _config: "test-wing")

    cli._cmd_init(tmp_path)

    captured = capsys.readouterr()
    assert "ECHELON INIT" in captured.out
    data = yaml.safe_load((tmp_path / ".echelon" / "config.yml").read_text(encoding="utf-8"))
    assert data["harness"]["llm"]["cli"] == "codex"
```

- [ ] **Step 2: Run the test to verify it fails or already passes**

Run:

```bash
uv run --extra dev pytest tests/unit/test_workspace_init_deploy_runtime.py -q
```

Expected: PASS if workspace init already honors `ECHELON_LLM`; otherwise FAIL until Step 3.

- [ ] **Step 3: Ensure detection order supports explicit Codex**

Confirm `src/harness/init.py` has:

```python
env = os.environ.get("ECHELON_LLM", "").strip()
if env in ("claude", "copilot", "opencode", "codex"):
    return env
```

If workspace init uses a separate detector in `src/echelon/cli.py`, update that detector with the same explicit-env behavior.

- [ ] **Step 4: Update docs/comments only for backend selection**

Ensure `extension/config-template.yml` says:

```yaml
# Options: claude (default) | copilot | opencode | codex
```

Do not add:

```yaml
codex:
  model:
  effort:
  profile:
```

- [ ] **Step 5: Run config and workspace init tests**

Run:

```bash
uv run --extra dev pytest tests/unit/test_config.py tests/unit/test_workspace_init_deploy_runtime.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/init.py src/echelon/cli.py extension/config-template.yml tests/unit/test_config.py tests/unit/test_workspace_init_deploy_runtime.py
git commit -m "test: cover Codex workspace LLM selection"
```

---

### Task 9: Full Verification And Manual Smoke

**Files:**
- No production files unless prior tasks reveal defects.
- Optional docs update: `docs/superpowers/plans/2026-07-05-codex-cli-backend.md` only if plan corrections are needed.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: verified Codex backend implementation.

- [ ] **Step 1: Run focused unit suites**

Run:

```bash
uv run --extra dev pytest \
  tests/unit/test_ai_cli_backend.py \
  tests/unit/test_llm_tool_policy.py \
  tests/unit/test_llm_provider.py \
  tests/unit/test_squad_provider.py \
  tests/unit/test_review_loop.py \
  tests/unit/test_cli_llm_tool_policy.py \
  tests/unit/test_config.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run full unit suite**

Run:

```bash
uv run --extra dev pytest tests/unit -q
```

Expected: PASS.

- [ ] **Step 3: Manual Codex provider smoke**

In a disposable or clean workspace where Codex is authenticated:

```bash
ECHELON_LLM=codex echelon workspace init
```

Then:

```bash
ECHELON_DEBUG_RAW_DIR=/tmp/echelon-codex-raw \
echelon run "smoke test codex provider only; do not modify files" --mode guided --reset
```

Expected:

- SCOUT runs through `codex exec`.
- `/tmp/echelon-codex-raw` contains raw Codex final output.
- `echelon_result:` is present and parseable.
- The run transitions past `phase1-discover`.

- [ ] **Step 4: Inspect git status**

Run:

```bash
git status --short
```

Expected: only intended files are modified or clean after commits.

- [ ] **Step 5: Record any smoke defect as a new focused task**

If Step 3 reveals a defect, stop and add a new task to this plan with the exact failing command, expected output, files to modify, failing test, implementation step, verification command, and commit command. Do not commit an unplanned smoke fix from this catch-all task.

---

## Self-Review

- Spec coverage: The plan covers backend extraction, Codex backend implementation, squad parsing, review loop routing, direct skill dispatch, workspace selection, and verification.
- Placeholder scan: No intentional placeholders remain.
- Type consistency: `CliRunRequest`, `CliRunResult`, `AICodingCliBackend`, `run_prompt_result`, and `run_agent_result` signatures are consistent across tasks.
- Scope check: The plan excludes Codex model/effort/profile config as requested.
