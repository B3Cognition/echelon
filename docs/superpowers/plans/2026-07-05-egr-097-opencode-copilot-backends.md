# EGR-097 OpenCode and Copilot CLI Backends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-class OpenCode and GitHub Copilot CLI backends behind `AICodingCliProvider`.

**Architecture:** Replace `PlainCliBackend` routing for supported `opencode` and `copilot` providers with concrete backends. Each backend owns its native command shape, unsafe-permission flag mapping, JSON output parsing, and final assistant/echelon result extraction. Docker remains the harness sandbox provider; `harness.llm.cli` remains the only provider selector.

**Tech Stack:** Python 3.11+, subprocess, JSONL parsing, pytest, existing `harness.ai_cli_backend`, existing `harness.llm_tool_policy`, OpenCode CLI, GitHub Copilot CLI.

## Global Constraints

- EGR-097 source of truth: `docs/findings/echelon-grounded-review-register.md`, GitHub issue #109.
- Keep Docker as the harness sandbox provider; do not add `provider: opencode` or `provider: copilot`.
- Keep `harness.llm.cli` as the only AI coding CLI selector.
- Do not add provider-specific model, effort, or profile config in this EGR.
- Keep unsafe host execution fail-closed behind `harness.llm.tool_policy.allow_unsafe_host_execution` plus `approval_reason`.
- Preserve OpenCode native direct skill dispatch through `opencode run --command ...`.
- Do not rely on `PlainCliBackend` for any supported production provider after this EGR.
- Use TDD: each implementation task starts with a failing test, then minimal implementation.
- Add a `CHANGELOG.md` `[Unreleased]` entry only when implementation is complete.

---

## Research Evidence

- OpenCode CLI docs: `opencode run "..."` is programmatic/non-interactive use; `--format json` emits raw JSON events.
- Local OpenCode CLI evidence on 2026-07-05: `opencode --version` returned `1.17.10`; `opencode run --help` showed `--format default|json`, `--command`, `--model`, `--agent`, `--variant`, and `--dangerously-skip-permissions`.
- GitHub Copilot CLI docs: `-p` / `--prompt` is the programmatic interface and the command exits after completion.
- Local Copilot CLI help on 2026-07-05 showed `-p, --prompt`, `--output-format text|json`, `--stream on|off`, `--silent`, `--allow-all-tools`, `--allow-all`, `--allow-tool`, `--deny-tool`, `--add-dir`, `--no-custom-instructions`, and `--disable-builtin-mcps`.

## File Structure

- Create `src/harness/ai_cli_backends/opencode.py`: OpenCode backend using `opencode run --format json`, OpenCode JSON event parsing, and fallback stdout capture.
- Create `src/harness/ai_cli_backends/copilot.py`: Copilot backend using `copilot -p ... --output-format json --stream off`, Copilot JSONL parsing, and fallback stdout capture.
- Modify `src/harness/ai_cli_backend.py`: factory routes `opencode` and `copilot` to concrete backends.
- Modify `src/harness/llm_tool_policy.py`: provider command builders expose correct OpenCode and Copilot command shapes; Copilot unsafe mode uses Copilot's real approval flags.
- Modify `src/harness/ai_cli_backends/plain.py`: keep only as an unsupported/fallback backend, or make its docstring explicit.
- Modify `tests/unit/test_ai_cli_backend.py`: factory tests and backend parser tests.
- Modify `tests/unit/test_llm_tool_policy.py`: OpenCode and Copilot command-policy tests.
- Modify `tests/unit/test_cli_llm_tool_policy.py`: direct skill dispatch remains provider-facade based for Copilot and native-command based for OpenCode.
- Modify `CHANGELOG.md`: add EGR-097 entry after implementation verification.
- Modify `docs/findings/echelon-grounded-review-register.md`: update EGR-097 status and GitHub issue evidence.

---

### Task 1: Capture Real CLI Output Fixtures

**Files:**
- Create: `tests/fixtures/ai_cli/opencode-run-json.jsonl`
- Create: `tests/fixtures/ai_cli/copilot-prompt-json.jsonl`
- Modify: `docs/superpowers/plans/2026-07-05-egr-097-opencode-copilot-backends.md`

**Interfaces:**
- Consumes: local `opencode` and `copilot` CLIs when available.
- Produces: stable fixture files used by parser tests in later tasks.

- [x] **Step 1: Capture OpenCode JSON output**

Run from the repo root:

```bash
opencode run --format json "Say hello in one short sentence. Do not modify files." > /tmp/egr097-opencode.jsonl
```

Expected: exit code `0`, JSONL output containing at least one assistant/content/result event.

- [x] **Step 2: Sanitize and save the OpenCode fixture**

Inspect:

```bash
head -20 /tmp/egr097-opencode.jsonl
```

Create `tests/fixtures/ai_cli/opencode-run-json.jsonl` with a minimal representative subset. Keep real event keys, but replace volatile ids/timestamps/session paths with deterministic values such as `"fixture-session"`.

- [x] **Step 3: Capture Copilot JSON output**

Run from the repo root:

```bash
copilot -p "Say hello in one short sentence. Do not modify files." --output-format json --stream off --silent > /tmp/egr097-copilot.jsonl
```

Expected: exit code `0`, JSONL output containing a final assistant response or completion event.

- [x] **Step 4: Sanitize and save the Copilot fixture**

Inspect:

```bash
head -40 /tmp/egr097-copilot.jsonl
```

Create `tests/fixtures/ai_cli/copilot-prompt-json.jsonl` with a minimal representative subset. Keep real event keys, but replace volatile ids/timestamps/session paths with deterministic values.

- [x] **Step 5: Commit the fixtures**

```bash
git add tests/fixtures/ai_cli/opencode-run-json.jsonl tests/fixtures/ai_cli/copilot-prompt-json.jsonl docs/superpowers/plans/2026-07-05-egr-097-opencode-copilot-backends.md
git commit -m "test: capture OpenCode and Copilot CLI output fixtures"
```

---

### Task 2: Correct Provider Command Policy

**Files:**
- Modify: `src/harness/llm_tool_policy.py`
- Test: `tests/unit/test_llm_tool_policy.py`

**Interfaces:**
- Consumes: `build_llm_cli_command(cli, bin_, prompt, policy, ...)`
- Produces: correct command lists for `opencode` and `copilot`.

- [x] **Step 1: Write failing OpenCode and Copilot policy tests**

Add to `tests/unit/test_llm_tool_policy.py`:

```python
def test_opencode_prompt_command_can_request_json() -> None:
    cmd = build_llm_cli_command(
        "opencode",
        "opencode",
        "Do the work.",
        LlmToolPolicy(),
        opencode_json=True,
    )

    assert cmd[:2] == ["opencode", "run"]
    assert "--format" in cmd
    assert cmd[cmd.index("--format") + 1] == "json"
    assert cmd[-1].startswith("## Effective Host Tool Policy")


def test_copilot_prompt_command_uses_json_non_streaming_mode() -> None:
    cmd = build_llm_cli_command(
        "copilot",
        "copilot",
        "Do the work.",
        LlmToolPolicy(),
        copilot_json=True,
    )

    assert cmd[:2] == ["copilot", "-p"]
    assert "--output-format" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert "--stream" in cmd
    assert cmd[cmd.index("--stream") + 1] == "off"
    assert "--dangerously-skip-permissions" not in cmd


def test_copilot_approved_unsafe_mode_uses_copilot_permission_flags() -> None:
    policy = LlmToolPolicy(
        allow_unsafe_host_execution=True,
        approval_reason="Operator approved disposable local worktree.",
    )

    cmd = build_llm_cli_command(
        "copilot",
        "copilot",
        "Do the work.",
        policy,
        copilot_json=True,
    )

    assert "--allow-all-tools" in cmd
    assert "--dangerously-skip-permissions" not in cmd
```

- [x] **Step 2: Run tests to verify failure**

Run:

```bash
uv run --extra dev pytest tests/unit/test_llm_tool_policy.py -q
```

Expected: FAIL because `opencode_json` and `copilot_json` keyword arguments do not exist yet, and Copilot unsafe mode currently uses the wrong generic flag.

- [x] **Step 3: Implement command builder arguments**

Modify `build_llm_cli_command()` signature in `src/harness/llm_tool_policy.py`:

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
    opencode_json: bool = False,
    copilot_json: bool = False,
) -> list[str]:
```

Replace the `opencode` branch with:

```python
    if cli == "opencode":
        cmd = [bin_, "run"]
        if unsafe:
            cmd.append("--dangerously-skip-permissions")
        if opencode_json:
            cmd += ["--format", "json"]
        cmd.append(effective_prompt)
        return cmd
```

Replace the generic Copilot behavior with a dedicated branch before the final fallback:

```python
    if cli == "copilot":
        cmd = [bin_, "-p", effective_prompt]
        if copilot_json:
            cmd += ["--output-format", "json", "--stream", "off"]
        if unsafe:
            cmd.append("--allow-all-tools")
        return cmd
```

Leave the final fallback for unsupported CLIs only:

```python
    cmd = [bin_, "-p", effective_prompt]
    if unsafe:
        cmd.append("--dangerously-skip-permissions")
    return cmd
```

- [x] **Step 4: Run policy tests**

Run:

```bash
uv run --extra dev pytest tests/unit/test_llm_tool_policy.py -q
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/harness/llm_tool_policy.py tests/unit/test_llm_tool_policy.py
git commit -m "fix: map OpenCode and Copilot CLI command policy"
```

---

### Task 3: Add OpenCode Backend

**Files:**
- Create: `src/harness/ai_cli_backends/opencode.py`
- Modify: `src/harness/ai_cli_backend.py`
- Test: `tests/unit/test_ai_cli_backend.py`

**Interfaces:**
- Consumes: `CliRunRequest`, `CliRunResult`, `build_llm_cli_command(..., opencode_json=True)`
- Produces: `OpenCodeCliBackend.run_prompt()` and `.run_agent()`.

- [x] **Step 1: Write failing factory and parser tests**

Modify `tests/unit/test_ai_cli_backend.py` imports:

```python
from harness.ai_cli_backends.opencode import OpenCodeCliBackend
```

Change the factory parameter for `opencode`:

```python
("opencode", "OpenCodeCliBackend"),
```

Add parser test:

```python
def test_opencode_backend_parses_json_events(tmp_path) -> None:
    backend = OpenCodeCliBackend(_config("opencode"))

    class FakeProcess:
        stdout = io.BytesIO(
            (
                json.dumps({"type": "message", "role": "assistant", "content": "working"})
                + "\n"
                + json.dumps({"type": "result", "output": "echelon_result:\\n  verdict: PASS\\n"})
                + "\n"
            ).encode()
        )
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

    with patch("harness.ai_cli_backends.opencode.subprocess.Popen", return_value=FakeProcess()):
        result = backend.run_agent(request)

    assert result.exit_code == 0
    assert "working" in result.stdout
    assert "echelon_result:" in result.stdout
```

- [x] **Step 2: Run tests to verify failure**

Run:

```bash
uv run --extra dev pytest tests/unit/test_ai_cli_backend.py::test_backend_factory_returns_concrete_backend tests/unit/test_ai_cli_backend.py::test_opencode_backend_parses_json_events -q
```

Expected: FAIL because `OpenCodeCliBackend` does not exist and factory still returns `PlainCliBackend`.

- [x] **Step 3: Implement OpenCode backend**

Create `src/harness/ai_cli_backends/opencode.py`:

```python
from __future__ import annotations

import json
import shutil
import subprocess

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig
from harness.llm_tool_policy import build_llm_cli_command


class OpenCodeCliBackend:
    name = "opencode"

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self._bin = shutil.which(self.name) or self.name

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        cmd = build_llm_cli_command(
            self.name,
            self._bin,
            request.prompt,
            self._config.llm.tool_policy,
            opencode_json=True,
        )
        return self._run(cmd, request)

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self.run_prompt(request)

    def _run(self, cmd: list[str], request: CliRunRequest) -> CliRunResult:
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=request.cwd,
                env=dict(request.env),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                stdout_parts.append(_extract_opencode_text(line))
            stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            if stderr:
                stderr_parts.append(stderr)
            exit_code = proc.wait()
        except subprocess.TimeoutExpired as exc:
            return CliRunResult(
                exit_code=-1,
                stdout=(exc.stdout or b"").decode("utf-8", errors="replace"),
                stderr=(exc.stderr or b"").decode("utf-8", errors="replace"),
                timed_out=True,
            )
        stdout = "\n".join(part for part in stdout_parts if part)
        stderr = "\n".join(part for part in stderr_parts if part)
        if stdout:
            print(stdout, flush=True)
        if stderr:
            print(stderr, flush=True)
        return CliRunResult(exit_code=int(exit_code), stdout=stdout, stderr=stderr)


def _extract_opencode_text(line: str) -> str:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return line
    for key in ("content", "output", "result", "text", "message"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    return line
```

- [x] **Step 4: Wire the factory**

Modify `src/harness/ai_cli_backend.py`:

```python
def create_ai_cli_backend(config: HarnessConfig) -> AICodingCliBackend:
    from harness.ai_cli_backends.claude import ClaudeCliBackend
    from harness.ai_cli_backends.codex import CodexCliBackend
    from harness.ai_cli_backends.opencode import OpenCodeCliBackend
    from harness.ai_cli_backends.plain import PlainCliBackend

    cli = config.llm.cli
    if cli == "claude":
        return ClaudeCliBackend(config)
    if cli == "codex":
        return CodexCliBackend(config)
    if cli == "opencode":
        return OpenCodeCliBackend(config)
    return PlainCliBackend(config)
```

- [x] **Step 5: Run OpenCode tests**

Run:

```bash
uv run --extra dev pytest tests/unit/test_ai_cli_backend.py::test_opencode_backend_parses_json_events -q
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add src/harness/ai_cli_backends/opencode.py src/harness/ai_cli_backend.py tests/unit/test_ai_cli_backend.py
git commit -m "feat: add OpenCode AI CLI backend"
```

---

### Task 4: Add Copilot Backend

**Files:**
- Create: `src/harness/ai_cli_backends/copilot.py`
- Modify: `src/harness/ai_cli_backend.py`
- Test: `tests/unit/test_ai_cli_backend.py`

**Interfaces:**
- Consumes: `CliRunRequest`, `CliRunResult`, `build_llm_cli_command(..., copilot_json=True)`
- Produces: `CopilotCliBackend.run_prompt()` and `.run_agent()`.

- [x] **Step 1: Write failing factory and parser tests**

Modify `tests/unit/test_ai_cli_backend.py` imports:

```python
from harness.ai_cli_backends.copilot import CopilotCliBackend
```

Change the factory parameter for `copilot`:

```python
("copilot", "CopilotCliBackend"),
```

Add parser test:

```python
def test_copilot_backend_parses_jsonl_response(tmp_path) -> None:
    backend = CopilotCliBackend(_config("copilot"))

    class FakeProcess:
        stdout = io.BytesIO(
            (
                json.dumps({"type": "assistant_message", "content": "working"})
                + "\n"
                + json.dumps({"type": "final", "message": "echelon_result:\\n  verdict: PASS\\n"})
                + "\n"
            ).encode()
        )
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

    with patch("harness.ai_cli_backends.copilot.subprocess.Popen", return_value=FakeProcess()):
        result = backend.run_agent(request)

    assert result.exit_code == 0
    assert "working" in result.stdout
    assert "echelon_result:" in result.stdout
```

- [x] **Step 2: Run tests to verify failure**

Run:

```bash
uv run --extra dev pytest tests/unit/test_ai_cli_backend.py::test_backend_factory_returns_concrete_backend tests/unit/test_ai_cli_backend.py::test_copilot_backend_parses_jsonl_response -q
```

Expected: FAIL because `CopilotCliBackend` does not exist and factory still returns `PlainCliBackend`.

- [x] **Step 3: Implement Copilot backend**

Create `src/harness/ai_cli_backends/copilot.py`:

```python
from __future__ import annotations

import json
import shutil
import subprocess

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig
from harness.llm_tool_policy import build_llm_cli_command


class CopilotCliBackend:
    name = "copilot"

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self._bin = shutil.which(self.name) or self.name

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        cmd = build_llm_cli_command(
            self.name,
            self._bin,
            request.prompt,
            self._config.llm.tool_policy,
            copilot_json=True,
        )
        return self._run(cmd, request)

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self.run_prompt(request)

    def _run(self, cmd: list[str], request: CliRunRequest) -> CliRunResult:
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=request.cwd,
                env=dict(request.env),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                stdout_parts.append(_extract_copilot_text(line))
            stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            if stderr:
                stderr_parts.append(stderr)
            exit_code = proc.wait()
        except subprocess.TimeoutExpired as exc:
            return CliRunResult(
                exit_code=-1,
                stdout=(exc.stdout or b"").decode("utf-8", errors="replace"),
                stderr=(exc.stderr or b"").decode("utf-8", errors="replace"),
                timed_out=True,
            )
        stdout = "\n".join(part for part in stdout_parts if part)
        stderr = "\n".join(part for part in stderr_parts if part)
        if stdout:
            print(stdout, flush=True)
        if stderr:
            print(stderr, flush=True)
        return CliRunResult(exit_code=int(exit_code), stdout=stdout, stderr=stderr)


def _extract_copilot_text(line: str) -> str:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return line
    for key in ("content", "message", "output", "result", "text"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    return line
```

- [x] **Step 4: Wire the factory**

Modify `src/harness/ai_cli_backend.py` so `copilot` returns `CopilotCliBackend` and `opencode` returns `OpenCodeCliBackend`.

- [x] **Step 5: Run Copilot tests**

Run:

```bash
uv run --extra dev pytest tests/unit/test_ai_cli_backend.py::test_copilot_backend_parses_jsonl_response tests/unit/test_ai_cli_backend.py::test_backend_factory_returns_concrete_backend -q
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add src/harness/ai_cli_backends/copilot.py src/harness/ai_cli_backend.py tests/unit/test_ai_cli_backend.py
git commit -m "feat: add Copilot AI CLI backend"
```

---

### Task 5: Tighten Skill Dispatch and Config Coverage

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `tests/unit/test_cli_llm_tool_policy.py`
- Modify: `tests/unit/test_workspace_init_deploy_runtime.py`
- Modify: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: `AICodingCliProvider(config).exec_prompt(worktree_path, prompt)`
- Produces: verified routing for `copilot`, verified native command dispatch for `opencode`, and workspace init persistence for both.

- [ ] **Step 1: Add direct dispatch tests**

Add to `tests/unit/test_cli_llm_tool_policy.py`:

```python
@pytest.mark.unit
def test_dispatch_skill_command_routes_copilot_through_ai_cli_provider(monkeypatch, tmp_path: Path) -> None:
    skill_dir = tmp_path / ".github" / "agents"
    skill_dir.mkdir(parents=True)
    (skill_dir / "speckit.echelon.review.agent.md").write_text(
        "---\nname: speckit.echelon.review\n---\nreview $ARGUMENTS\n",
        encoding="utf-8",
    )
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="copilot"),
    )
    calls = []

    class FakeProvider:
        def __init__(self, loaded_config):
            assert loaded_config is config

        def exec_prompt(self, worktree_path, prompt):
            calls.append((worktree_path, prompt))
            return 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ECHELON_LLM", "copilot")
    monkeypatch.setattr("echelon.cli.load_config", lambda project_dir, squad_only=True: config)
    monkeypatch.setattr("echelon.cli.AICodingCliProvider", FakeProvider)

    with pytest.raises(SystemExit) as exc:
        cli._dispatch_skill_command("review", ["005", "pr_url=https://github.com/org/repo/pull/1"])

    assert exc.value.code == 0
    assert calls
    assert "review 005 pr_url=https://github.com/org/repo/pull/1" in calls[0][1]
```

Keep the existing OpenCode direct skill dispatch path covered by `test_opencode_skill_command_preserves_native_command_dispatch()` in `tests/unit/test_llm_tool_policy.py`.

- [ ] **Step 2: Add workspace init persistence tests**

Add parameterized test to `tests/unit/test_workspace_init_deploy_runtime.py`:

```python
@pytest.mark.parametrize("llm_cli", ["opencode", "copilot"])
def test_workspace_init_persists_additional_llm_providers(tmp_path, monkeypatch, capsys, llm_cli: str) -> None:
    _write_workspace_config(
        tmp_path,
        "  enabled: false\n  type: http\n  blue_port: 18080\n  green_port: 18081\n",
    )
    monkeypatch.setenv("ECHELON_LLM", llm_cli)
    monkeypatch.setattr(cli, "_provision_wing", lambda _project_dir, _config: "test-wing")

    cli._cmd_init(tmp_path)

    captured = capsys.readouterr()
    assert "ECHELON INIT — COMPLETE" in captured.out
    config = yaml.safe_load((tmp_path / ".echelon" / "config.yml").read_text(encoding="utf-8"))
    assert config["harness"]["llm"]["cli"] == llm_cli
```

- [ ] **Step 3: Run tests**

Run:

```bash
uv run --extra dev pytest tests/unit/test_cli_llm_tool_policy.py tests/unit/test_workspace_init_deploy_runtime.py tests/unit/test_config.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/echelon/cli.py tests/unit/test_cli_llm_tool_policy.py tests/unit/test_workspace_init_deploy_runtime.py tests/unit/test_config.py
git commit -m "test: cover OpenCode and Copilot provider routing"
```

---

### Task 6: Final Verification and EGR Closure

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `docs/superpowers/plans/2026-07-05-egr-097-opencode-copilot-backends.md`

**Interfaces:**
- Consumes: completed backend tasks and GitHub issue number.
- Produces: completed EGR-097 documentation and verification evidence.

- [ ] **Step 1: Add changelog entry**

Add under `CHANGELOG.md` `[Unreleased]` / `Added`:

```markdown
- **EGR-097 / #109 OpenCode and Copilot AI CLI backends** — OpenCode and
  GitHub Copilot CLI now have first-class `AICodingCliProvider` backends with
  provider-specific JSON output parsing and permission flag mapping, replacing
  the generic `PlainCliBackend` path for supported providers.
```

- [ ] **Step 2: Update EGR-097 row**

Change EGR-097 status from `in-progress` to `fixed`. Ensure evidence includes `GitHub issue #109`. Replace next action with:

```markdown
Fixed: OpenCode and Copilot now use concrete AI CLI backends with provider-native command builders, JSON output parsing, final assistant/echelon result extraction, and correct unsafe-permission flag mapping. `PlainCliBackend` no longer handles supported production providers. Verification: focused provider/policy/CLI/config suites and full unit suite passed.
```

- [ ] **Step 3: Add review note**

Append to Review Notes after retrieving the current short commit:

```bash
SHORT_HEAD="$(git rev-parse --short HEAD)"
printf '| 2026-07-05 | `%s` | EGR-097 implemented: OpenCode and Copilot are now concrete AI CLI backends behind `AICodingCliProvider`; provider-specific permission flags and JSON output parsing are covered by tests. Verification: focused provider/policy/CLI/config suites passed; full unit suite passed. |\n' "$SHORT_HEAD"
```

- [ ] **Step 4: Run focused verification**

Run:

```bash
uv run --extra dev pytest tests/unit/test_ai_cli_backend.py tests/unit/test_llm_tool_policy.py tests/unit/test_llm_provider.py tests/unit/test_squad_provider.py tests/unit/test_review_loop.py tests/unit/test_cli_llm_tool_policy.py tests/unit/test_workspace_init_deploy_runtime.py tests/unit/test_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full unit verification**

Run:

```bash
uv run --extra dev pytest tests/unit -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add CHANGELOG.md docs/findings/echelon-grounded-review-register.md docs/superpowers/plans/2026-07-05-egr-097-opencode-copilot-backends.md
git commit -m "docs: mark EGR-097 fixed"
```

---

## Self-Review

- Spec coverage: the plan covers command policy, concrete backend factory routing, OpenCode backend parsing, Copilot backend parsing, skill/config coverage, fixtures, changelog, register update, and full verification.
- Plan hygiene scan: no task uses deferred-work markers or fill-in language; finalization instructions use GitHub issue #109 and tell the implementer to retrieve the actual short commit with `git rev-parse --short HEAD`.
- Type consistency: all tasks use existing `CliRunRequest`, `CliRunResult`, `AICodingCliProvider`, `build_llm_cli_command`, `LlmToolPolicy`, and pytest patterns already present in the repo.
