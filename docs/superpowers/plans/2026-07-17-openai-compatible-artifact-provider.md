# OpenAI-Compatible Artifact Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first provider-first unblocker: an OpenAI-compatible API backend that satisfies the existing prompt-result interface and declares artifact-only capability.

**Architecture:** Keep the existing `AICodingCliProvider` facade working while adding an API backend behind the same `run_prompt_result()` / `run_agent_result()` shape. Add provider capability metadata as a small shared enum so command gating can build on it later. Extend `LlmConfig` with OpenAI-compatible endpoint fields, but do not implement PM controller, Aha ingestion, or build/delivery command gating in this slice.

**Tech Stack:** Python 3.11, stdlib `urllib.request` for HTTP, pytest, existing `harness.ai_cli_backend` and `harness.config` modules.

## Global Constraints

- Use TDD: write a failing test, run it, implement minimal code, rerun.
- Do not add third-party dependencies for the provider HTTP client in this slice.
- Support `POST <base_url>/chat/completions` only.
- The OpenAI-compatible provider is artifact-only; it must not add build/file/tool execution behavior.
- Keep existing CLI providers (`claude`, `copilot`, `opencode`, `codex`) behavior-compatible.
- Do not implement Aha ingestion or the PM artifact controller in this plan.

---

## File Structure

- Create `src/harness/provider_capability.py`: shared `ProviderCapability` enum plus immutable capability sets.
- Modify `src/harness/config.py`: allow `llm.cli: openai-compatible`; add endpoint/model fields to `LlmConfig`; parse provider feature flags.
- Create `src/harness/ai_cli_backends/openai_compatible.py`: backend that calls OpenAI-compatible chat completions and returns `CliRunResult`.
- Modify `src/harness/ai_cli_backend.py`: import and return the new backend from the factory.
- Modify `src/harness/llm_provider.py`: expose provider capabilities through the existing facade.
- Modify `extension/config-template.yml`: document the new OpenAI-compatible config.
- Test `tests/unit/test_config.py`: config parsing and validation.
- Test `tests/unit/test_ai_cli_backend.py`: factory and API backend behavior.
- Test `tests/unit/test_llm_provider.py`: facade exposes artifact-only capabilities.

---

### Task 1: Provider Capability Metadata

**Files:**
- Create: `src/harness/provider_capability.py`
- Modify: `src/harness/llm_provider.py`
- Test: `tests/unit/test_llm_provider.py`

**Interfaces:**
- Produces: `ProviderCapability` enum with values `ARTIFACT = "artifact"` and `BUILD = "build"`.
- Produces: `AICodingCliProvider.capabilities: frozenset[ProviderCapability]`.
- Later tasks rely on `ProviderCapability.ARTIFACT` for OpenAI-compatible providers.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_llm_provider.py`:

```python
def test_provider_exposes_default_cli_build_and_artifact_capabilities() -> None:
    from harness.provider_capability import ProviderCapability

    provider = AICodingCliProvider(_config(cli="claude"))

    assert provider.capabilities == frozenset(
        {ProviderCapability.ARTIFACT, ProviderCapability.BUILD}
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/unit/test_llm_provider.py::test_provider_exposes_default_cli_build_and_artifact_capabilities -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'harness.provider_capability'` or `AttributeError` for `capabilities`.

- [ ] **Step 3: Write minimal implementation**

Create `src/harness/provider_capability.py`:

```python
from __future__ import annotations

from enum import StrEnum


class ProviderCapability(StrEnum):
    ARTIFACT = "artifact"
    BUILD = "build"


CLI_PROVIDER_CAPABILITIES = frozenset(
    {ProviderCapability.ARTIFACT, ProviderCapability.BUILD}
)
ARTIFACT_PROVIDER_CAPABILITIES = frozenset({ProviderCapability.ARTIFACT})
```

Modify `src/harness/llm_provider.py` imports:

```python
from harness.provider_capability import CLI_PROVIDER_CAPABILITIES, ProviderCapability
```

Add inside `AICodingCliProvider`:

```python
    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        return CLI_PROVIDER_CAPABILITIES
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/unit/test_llm_provider.py::test_provider_exposes_default_cli_build_and_artifact_capabilities -q
```

Expected: PASS.

---

### Task 2: Parse OpenAI-Compatible LLM Config

**Files:**
- Modify: `src/harness/config.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: existing `LlmConfig`.
- Produces: `LlmConfig` fields `base_url`, `model`, `api_key_env`, `temperature`, `max_tokens`, `features`.
- Produces: `VALID_LLM_CLIS` includes `"openai-compatible"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_config.py` near the LlmConfig tests:

```python
def test_llm_openai_compatible_config_parsed() -> None:
    config = _parse_config({
        "provider": "docker",
        "llm": {
            "cli": "openai-compatible",
            "base_url": "http://127.0.0.1:8000/v1",
            "model": "local-model",
            "api_key_env": "LOCAL_LLM_API_KEY",
            "temperature": 0.2,
            "max_tokens": 8192,
            "features": {
                "streaming": False,
                "json_mode": True,
                "structured_outputs": False,
                "tool_calls": False,
            },
        },
    })

    assert config.llm.cli == "openai-compatible"
    assert config.llm.base_url == "http://127.0.0.1:8000/v1"
    assert config.llm.model == "local-model"
    assert config.llm.api_key_env == "LOCAL_LLM_API_KEY"
    assert config.llm.temperature == 0.2
    assert config.llm.max_tokens == 8192
    assert config.llm.features == {
        "streaming": False,
        "json_mode": True,
        "structured_outputs": False,
        "tool_calls": False,
    }


def test_llm_openai_compatible_requires_base_url() -> None:
    with pytest.raises(ValidationError, match="base_url"):
        _parse_config({
            "provider": "docker",
            "llm": {
                "cli": "openai-compatible",
                "model": "local-model",
            },
        })


def test_llm_openai_compatible_requires_model() -> None:
    with pytest.raises(ValidationError, match="model"):
        _parse_config({
            "provider": "docker",
            "llm": {
                "cli": "openai-compatible",
                "base_url": "http://127.0.0.1:8000/v1",
            },
        })
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/unit/test_config.py::test_llm_openai_compatible_config_parsed tests/unit/test_config.py::test_llm_openai_compatible_requires_base_url tests/unit/test_config.py::test_llm_openai_compatible_requires_model -q
```

Expected: FAIL because `openai-compatible` is invalid or fields do not exist.

- [ ] **Step 3: Write minimal implementation**

Modify `src/harness/config.py`:

```python
VALID_LLM_CLIS = {"claude", "copilot", "opencode", "codex", "openai-compatible"}
```

Extend `LlmConfig`:

```python
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key_env: Optional[str] = None
    temperature: float = 0.2
    max_tokens: Optional[int] = None
    features: Dict[str, bool] = field(default_factory=dict)
```

Add helper:

```python
def _parse_llm_features(raw: Dict[str, Any]) -> Dict[str, bool]:
    features = raw.get("features", {})
    if not isinstance(features, dict):
        return {}
    return {str(key): bool(value) for key, value in features.items()}
```

Update `_parse_llm`:

```python
    cli = _validate_llm_cli(str(raw.get("cli", "claude")))
    base_url = str(raw["base_url"]).rstrip("/") if raw.get("base_url") else None
    model = str(raw["model"]) if raw.get("model") else None
    if cli == "openai-compatible":
        if not base_url:
            raise ValidationError(
                "llm.base_url is required for openai-compatible provider",
                field_path="llm.base_url",
            )
        if not model:
            raise ValidationError(
                "llm.model is required for openai-compatible provider",
                field_path="llm.model",
            )
```

Return:

```python
        cli=cli,
        base_url=base_url,
        model=model,
        api_key_env=str(raw["api_key_env"]) if raw.get("api_key_env") else None,
        temperature=float(raw.get("temperature", 0.2)),
        max_tokens=int(raw["max_tokens"]) if raw.get("max_tokens") else None,
        features=_parse_llm_features(raw),
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/unit/test_config.py::test_llm_openai_compatible_config_parsed tests/unit/test_config.py::test_llm_openai_compatible_requires_base_url tests/unit/test_config.py::test_llm_openai_compatible_requires_model -q
```

Expected: PASS.

---

### Task 3: OpenAI-Compatible API Backend

**Files:**
- Create: `src/harness/ai_cli_backends/openai_compatible.py`
- Modify: `src/harness/ai_cli_backend.py`
- Test: `tests/unit/test_ai_cli_backend.py`

**Interfaces:**
- Consumes: `LlmConfig.base_url`, `model`, `api_key_env`, `temperature`, `max_tokens`.
- Produces: `OpenAICompatibleBackend.run_prompt(request: CliRunRequest) -> CliRunResult`.
- Produces: factory support for `cli == "openai-compatible"`.

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_ai_cli_backend.py`:

```python
def _openai_config() -> HarnessConfig:
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(
            cli="openai-compatible",
            base_url="http://127.0.0.1:8000/v1",
            model="local-model",
            api_key_env="LOCAL_LLM_API_KEY",
            temperature=0.2,
            max_tokens=256,
        ),
    )


def test_backend_factory_returns_openai_compatible_backend() -> None:
    backend = create_ai_cli_backend(_openai_config())

    assert backend.__class__.__name__ == "OpenAICompatibleBackend"
    assert backend.name == "openai-compatible"


def test_openai_compatible_backend_posts_chat_completion(tmp_path, monkeypatch) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured = {}
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "secret-token")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "choices": [
                    {"message": {"content": "echelon_result:\n  verdict: DONE\n"}}
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 5},
            }).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode())
        return FakeResponse()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )
    backend = OpenAICompatibleBackend(_openai_config())
    result = backend.run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "echelon_result:\n  verdict: DONE\n"
    assert result.token_usage == 12
    assert captured["url"] == "http://127.0.0.1:8000/v1/chat/completions"
    assert captured["timeout"] == 12.5
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["payload"]["model"] == "local-model"
    assert captured["payload"]["messages"] == [
        {"role": "user", "content": "Return a result."}
    ]
    assert captured["payload"]["temperature"] == 0.2
    assert captured["payload"]["max_tokens"] == 256
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/unit/test_ai_cli_backend.py::test_backend_factory_returns_openai_compatible_backend tests/unit/test_ai_cli_backend.py::test_openai_compatible_backend_posts_chat_completion -q
```

Expected: FAIL because backend module/factory support is missing.

- [ ] **Step 3: Write minimal implementation**

Create `src/harness/ai_cli_backends/openai_compatible.py`:

```python
from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig


class OpenAICompatibleBackend:
    name = "openai-compatible"

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        llm = self._config.llm
        assert llm.base_url is not None
        assert llm.model is not None
        payload = {
            "model": llm.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "temperature": llm.temperature,
        }
        if llm.max_tokens is not None:
            payload["max_tokens"] = llm.max_tokens
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        token = _api_key(llm.api_key_env)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        http_request = urllib.request.Request(
            f"{llm.base_url.rstrip('/')}/chat/completions",
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=request.timeout_s) as response:
                body = response.read().decode("utf-8", errors="replace")
        except TimeoutError as exc:
            return CliRunResult(
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                timed_out=True,
                metadata={"provider": self.name},
            )
        except socket.timeout as exc:
            return CliRunResult(
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                timed_out=True,
                metadata={"provider": self.name},
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return CliRunResult(
                exit_code=int(exc.code),
                stdout="",
                stderr=body or str(exc),
                metadata={"provider": self.name, "http_status": int(exc.code)},
            )
        except urllib.error.URLError as exc:
            return CliRunResult(
                exit_code=1,
                stdout="",
                stderr=str(exc.reason),
                metadata={"provider": self.name},
            )
        except OSError as exc:
            return CliRunResult(
                exit_code=1,
                stdout="",
                stderr=str(exc),
                metadata={"provider": self.name},
            )
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return CliRunResult(
                exit_code=1,
                stdout="",
                stderr=f"Malformed OpenAI-compatible response: {body}",
                metadata={"provider": self.name},
            )
        text = _assistant_text(parsed)
        if text:
            print(text, flush=True)
        return CliRunResult(
            exit_code=0,
            stdout=text,
            stderr="",
            token_usage=_token_usage(parsed),
            metadata={"provider": self.name},
        )

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self.run_prompt(request)


def _api_key(api_key_env: str | None) -> str:
    if not api_key_env:
        return ""
    return os.environ.get(api_key_env, "")


def _assistant_text(parsed: object) -> str:
    if not isinstance(parsed, dict):
        return ""
    choices = parsed.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    text = first.get("text")
    return text if isinstance(text, str) else ""


def _token_usage(parsed: object) -> int:
    if not isinstance(parsed, dict):
        return 0
    usage = parsed.get("usage")
    if not isinstance(usage, dict):
        return 0
    total = usage.get("total_tokens")
    if isinstance(total, int):
        return total
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    total_tokens = 0
    if isinstance(prompt, int):
        total_tokens += prompt
    if isinstance(completion, int):
        total_tokens += completion
    return total_tokens
```

Modify `src/harness/ai_cli_backend.py` factory:

```python
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend
```

```python
    if cli == "openai-compatible":
        return OpenAICompatibleBackend(config)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/unit/test_ai_cli_backend.py::test_backend_factory_returns_openai_compatible_backend tests/unit/test_ai_cli_backend.py::test_openai_compatible_backend_posts_chat_completion -q
```

Expected: PASS.

---

### Task 4: Artifact-Only Capabilities For OpenAI-Compatible Provider

**Files:**
- Modify: `src/harness/llm_provider.py`
- Test: `tests/unit/test_llm_provider.py`

**Interfaces:**
- Consumes: `ARTIFACT_PROVIDER_CAPABILITIES`.
- Produces: `AICodingCliProvider.capabilities` returns artifact-only when `self._cli == "openai-compatible"`.

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_llm_provider.py`:

```python
def test_openai_compatible_provider_is_artifact_only() -> None:
    from harness.provider_capability import ProviderCapability

    provider = AICodingCliProvider(
        _config(
            cli="openai-compatible",
            timeout_ms=600_000,
        )
    )

    assert provider.capabilities == frozenset({ProviderCapability.ARTIFACT})
```

Then update `_config` in `tests/unit/test_llm_provider.py` so `openai-compatible` receives required fields:

```python
def _config(config_dir=None, timeout_ms=1_200_000, cli="claude", tool_policy=None):
    llm_kwargs = {}
    if cli == "openai-compatible":
        llm_kwargs.update(
            base_url="http://127.0.0.1:8000/v1",
            model="local-model",
        )
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(
            config_dir=config_dir,
            timeout_ms=timeout_ms,
            cli=cli,
            tool_policy=tool_policy or LlmToolPolicy(),
            **llm_kwargs,
        ),
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/unit/test_llm_provider.py::test_openai_compatible_provider_is_artifact_only -q
```

Expected: FAIL because `capabilities` still returns both capabilities.

- [ ] **Step 3: Write minimal implementation**

Modify `src/harness/llm_provider.py` imports:

```python
from harness.provider_capability import (
    ARTIFACT_PROVIDER_CAPABILITIES,
    CLI_PROVIDER_CAPABILITIES,
    ProviderCapability,
)
```

Update the property:

```python
    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        if self._cli == "openai-compatible":
            return ARTIFACT_PROVIDER_CAPABILITIES
        return CLI_PROVIDER_CAPABILITIES
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/unit/test_llm_provider.py::test_openai_compatible_provider_is_artifact_only tests/unit/test_llm_provider.py::test_provider_exposes_default_cli_build_and_artifact_capabilities -q
```

Expected: PASS.

---

### Task 5: Config Template Documentation

**Files:**
- Modify: `extension/config-template.yml`
- Test: no automated test; verify via grep.

**Interfaces:**
- Consumes: config fields added in Task 2.
- Produces: commented template for `llm.cli: openai-compatible`.

- [ ] **Step 1: Patch the config template**

Replace the LLM provider comment block with content including:

```yaml
  # LLM provider used by Echelon commands.
  # Build-capable CLIs: claude (default) | copilot | opencode | codex
  # Artifact-only API provider: openai-compatible
  # llm:
  #   cli: claude
  #   config_dir: ~/.claude-personal   # sets CLAUDE_CONFIG_DIR (claude only)
  #   timeout_ms: 1200000              # 20 minutes
  #
  #   # OpenAI-compatible artifact-only provider example:
  #   # cli: openai-compatible
  #   # base_url: http://127.0.0.1:8000/v1
  #   # model: local-model
  #   # api_key_env: LOCAL_LLM_API_KEY
  #   # temperature: 0.2
  #   # max_tokens: 8192
  #   # features:
  #   #   streaming: false
  #   #   json_mode: false
  #   #   structured_outputs: false
  #   #   tool_calls: false
```

- [ ] **Step 2: Verify documentation text**

Run:

```bash
rg -n "openai-compatible|base_url|artifact-only" extension/config-template.yml
```

Expected: output includes the new template lines.

---

### Task 6: Focused Verification

**Files:**
- No additional source changes.

**Interfaces:**
- Consumes: all tasks above.
- Produces: verified provider-first slice.

- [ ] **Step 1: Run focused provider/config tests**

Run:

```bash
pytest tests/unit/test_config.py tests/unit/test_ai_cli_backend.py tests/unit/test_llm_provider.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run status and diff review**

Run:

```bash
git status --short
git diff -- src/harness tests/unit extension/config-template.yml
```

Expected: only files from this plan are modified, and no unrelated changes appear.

- [ ] **Step 3: Commit**

Run:

```bash
git add src/harness/provider_capability.py src/harness/config.py src/harness/ai_cli_backend.py src/harness/ai_cli_backends/openai_compatible.py src/harness/llm_provider.py tests/unit/test_config.py tests/unit/test_ai_cli_backend.py tests/unit/test_llm_provider.py extension/config-template.yml docs/superpowers/plans/2026-07-17-openai-compatible-artifact-provider.md
git commit -m "feat: add openai-compatible artifact provider"
```
