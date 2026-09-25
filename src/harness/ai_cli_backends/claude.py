from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Callable

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.ai_cli_backends.claude_constrained import (
    ConstrainedClaudeError,
    failure as constrained_failure,
    prepare_claude_request,
    run_claude_process,
)
from harness.config import HarnessConfig
from harness.llm_tool_policy import build_llm_cli_command
from harness.skill_loader import StreamEventPrinter


_MODEL_TIER_TO_CLAUDE_MODEL = {
    "fast": "haiku",
    "balanced": "sonnet",
    "strong": "opus",
    "ultra": "fable",
}

_REVIEW_TRIAGE_PROFILE = "review_triage_v1"
_REVIEW_TRIAGE_AGENT_NAMES = (
    "echelon-debugger",
    "echelon-sentinel",
    "echelon-spec-guard",
)
_CLAUDE_RULE_PATH_SAFE_CHARACTERS = frozenset("/._- ")


class ClaudeCliBackend:
    name = "claude"
    constrained_execution_contract_id = "claude-constrained-prompt-v1"

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self._bin = shutil.which("claude") or "claude"

    def model_for_tier(self, tier: str) -> str | None:
        """Resolve neutral Prosaic model intent inside the Claude adapter."""
        if not isinstance(tier, str):
            return None
        return _MODEL_TIER_TO_CLAUDE_MODEL.get(tier.strip().lower())

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        review_triage = _execution_profile(request) == _REVIEW_TRIAGE_PROFILE
        exclusive_write_scope = _prompt_metadata_bool(request, "tool_write_scope_exclusive")
        metadata = request.metadata.get("prompt_metadata")
        explicit_write_scope = isinstance(metadata, Mapping) and isinstance(
            metadata.get("tool_write_scope_exclusive"), bool
        )
        if explicit_write_scope:
            scope_paths = (
                str(Path(request.cwd).resolve()),
                *_prompt_scope_paths(request, metadata, "tool_read_roots"),
                *_prompt_scope_paths(request, metadata, "tool_write_paths"),
            )
            if review_triage or not _review_triage_paths_are_representable(scope_paths):
                return CliRunResult(
                    exit_code=125, stdout="", stderr="invalid explicit file scope",
                    metadata={
                        "exclusive_write_scope" if exclusive_write_scope
                        else "workspace_write_scope": "invalid"
                    },
                )
        canonical_task_execution = (
            request.metadata.get("canonical_task_execution") is True
        )
        cmd = build_llm_cli_command(
            "claude",
            self._bin,
            request.prompt,
            (
                replace(
                    self._config.llm.tool_policy,
                    allow_unsafe_host_execution=False,
                    approval_reason=None,
                )
                if review_triage or exclusive_write_scope
                else self._config.llm.tool_policy
            ),
            stream_json=True,
            disallow_claude_task_tools=canonical_task_execution and not review_triage,
        )
        model = _prompt_metadata_str(request, "model") or _claude_model_for_request(
            request
        )
        if model:
            cmd.extend(["--model", model])
        if review_triage:
            profile_args = _review_triage_profile_args(request)
            if profile_args is None:
                return _invalid_review_triage_profile_result()
            cmd.extend(profile_args)
            return self._run_stream_json(cmd, request)
        scope_args = _prompt_file_scope_args(request)
        if scope_args:
            cmd.extend(scope_args)
        raw_prompt_metadata = request.metadata.get("prompt_metadata")
        read_roots = (
            _prompt_scope_paths(request, raw_prompt_metadata, "tool_read_roots")
            if isinstance(raw_prompt_metadata, Mapping)
            else ()
        )
        write_paths = (
            _prompt_scope_paths(request, raw_prompt_metadata, "tool_write_paths")
            if isinstance(raw_prompt_metadata, Mapping)
            else ()
        )
        forbidden_roots = (
            _prompt_scope_paths(
                request,
                raw_prompt_metadata,
                "tool_forbidden_roots",
            )
            if isinstance(raw_prompt_metadata, Mapping)
            else ()
        )
        operational_roots = (
            _prompt_scope_paths(
                request,
                raw_prompt_metadata,
                "tool_operational_roots",
            )
            if isinstance(raw_prompt_metadata, Mapping)
            else ()
        )
        operational_read_paths = (
            _prompt_scope_paths(
                request,
                raw_prompt_metadata,
                "tool_operational_read_paths",
            )
            if isinstance(raw_prompt_metadata, Mapping)
            else ()
        )
        operational_metadata_paths = (
            _prompt_scope_paths(
                request,
                raw_prompt_metadata,
                "tool_operational_metadata_paths",
            )
            if isinstance(raw_prompt_metadata, Mapping)
            else ()
        )
        if forbidden_roots or exclusive_write_scope:
            sandbox_exec = _sandbox_exec_path()
            if sandbox_exec is None and (read_roots or write_paths or exclusive_write_scope):
                return CliRunResult(
                    exit_code=125,
                    stdout="",
                    stderr="workspace synthesis host boundary is unavailable",
                    metadata={"workspace_synthesis_boundary": "unavailable"},
                )
            if sandbox_exec is not None:
                cmd = [
                    sandbox_exec,
                    "-p",
                    _workspace_sandbox_profile(
                        forbidden_roots,
                        read_roots=read_roots,
                        write_paths=write_paths,
                        operational_roots=operational_roots,
                        operational_read_paths=operational_read_paths,
                        operational_metadata_paths=operational_metadata_paths,
                        read_only_roots=(str(Path(request.cwd).resolve()), *read_roots)
                        if exclusive_write_scope else (),
                        preserve_forbidden_children=explicit_write_scope,
                        allow_atomic_writes=exclusive_write_scope,
                    ),
                    *cmd,
                ]
        return self._run_stream_json(cmd, request)

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self.run_prompt(request)

    def run_inspection_turn(self, request: CliRunRequest) -> CliRunResult:
        from harness.inspection_turn import inspection_request_failure

        failure = inspection_request_failure(request)
        if failure is not None:
            return failure
        return self.run_review_triage_turn(request)

    def run_review_triage_turn(self, request: CliRunRequest) -> CliRunResult:
        from harness.ai_cli_backends.claude_triage import run_claude_review_triage

        return run_claude_review_triage(
            self._bin,
            request,
            tool_policy=self._config.llm.tool_policy,
        )

    def run_constrained_prompt(
        self,
        request: CliRunRequest,
        *,
        model: str,
        screen_output: Callable[[bytes], bytes],
        max_input_bytes: int,
        max_capture_bytes: int,
        screen_input: Callable[[bytes], bytes] | None = None,
    ) -> CliRunResult:
        """Run one bounded, tool-free request through native Claude stdin."""
        try:
            prepared = prepare_claude_request(
                self._bin,
                request,
                model=model,
                screen_output=screen_output,
                max_input_bytes=max_input_bytes,
                max_capture_bytes=max_capture_bytes,
                tool_policy=self._config.llm.tool_policy,
                screen_input=screen_input,
            )
        except ConstrainedClaudeError as exc:
            return constrained_failure(exc.reason)
        try:
            proc = subprocess.Popen(
                list(prepared.command),
                cwd=request.cwd,
                env=prepared.env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception:
            return constrained_failure("process_start_error")
        return run_claude_process(
            proc,
            screen_output=screen_output,
            max_capture_bytes=max_capture_bytes,
            timeout_s=float(request.timeout_s),
            model=model,
            input_bytes=prepared.prompt_bytes,
        )

    def _run_stream_json(self, cmd: list[str], request: CliRunRequest) -> CliRunResult:
        quiet = _prompt_metadata_bool(request, "quiet")
        proc = subprocess.Popen(
            cmd,
            cwd=request.cwd,
            env=dict(request.env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if quiet else None,
        )
        captured_lines: list[str] = []
        text_chunks: list[str] = []
        error_chunks: list[str] = []
        timed_out = False
        token_usage = 0
        observed_token_usage = 0
        max_token_usage = _prompt_metadata_positive_int(
            request, "max_token_usage"
        )
        token_budget_exhausted = False
        cost_usd = 0.0
        response_model = ""
        printer = StreamEventPrinter()
        native_stderr: list[str] = []

        def drain_stderr() -> None:
            stream = getattr(proc, "stderr", None)
            if stream is None:
                return
            text = stream.read().decode("utf-8", errors="replace").strip()
            if text:
                native_stderr.append(text)

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
        stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
        try:
            timer.start()
            if quiet:
                stderr_thread.start()
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if not quiet:
                        printer(event)
                    etype = event.get("type")
                    if etype == "assistant":
                        raw_message = event.get("message")
                        message = raw_message if isinstance(raw_message, Mapping) else {}
                        raw_model = message.get("model")
                        if isinstance(raw_model, str) and raw_model.strip():
                            response_model = raw_model.strip()
                        observed_token_usage += _extract_token_usage(message)
                        if (
                            max_token_usage is not None
                            and observed_token_usage >= max_token_usage
                            and not token_budget_exhausted
                        ):
                            token_budget_exhausted = True
                            proc.terminate()
                        for block in message.get("content", []):
                            if block.get("type") == "text":
                                text = block.get("text", "")
                                text_chunks.append(text)
                                capture(text)
                                if event.get("isApiErrorMessage") or event.get("error"):
                                    error_chunks.append(str(text))
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
                            error = str(event.get("result") or "").strip()
                            capture(error)
                            if error:
                                error_chunks.append(error)
                except json.JSONDecodeError:
                    capture(line)
                    text_chunks.append(line)
                    if not quiet:
                        print(line, flush=True)
            proc.stdout.close()
            proc.wait()
        finally:
            timer.cancel()
            if quiet:
                stderr_thread.join(timeout=1.0)

        stdout = "".join(text_chunks).strip() or "\n".join(captured_lines)
        token_usage = max(token_usage, observed_token_usage)
        metadata: dict[str, object] = {}
        if response_model:
            metadata["response_model"] = response_model
        stderr = "\n".join(dict.fromkeys([*error_chunks, *native_stderr]))
        if token_budget_exhausted:
            metadata["token_budget_exhausted"] = True
            budget_message = "RE token budget exhausted during provider invocation"
            stderr = "\n".join(part for part in (stderr, budget_message) if part)
        return CliRunResult(
            exit_code=-1 if timed_out else int(proc.returncode),
            stdout=stdout,
            stderr=stderr,
            token_usage=token_usage,
            cost_usd=cost_usd,
            timed_out=timed_out,
            metadata=metadata,
        )


def _extract_token_usage(event: Mapping[str, object]) -> int:
    usage = event.get("usage")
    if isinstance(usage, Mapping):
        total = 0
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        ):
            try:
                total += int(usage.get(key) or 0)
            except (TypeError, ValueError):
                continue
        if total > 0:
            return total

    total = 0
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        try:
            total += int(event.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return total


def _prompt_metadata_str(request: CliRunRequest, key: str) -> str:
    metadata = request.metadata.get("prompt_metadata")
    if not isinstance(metadata, Mapping):
        return ""
    value = metadata.get(key)
    return value.strip() if isinstance(value, str) else ""


def _prompt_metadata_positive_int(
    request: CliRunRequest, key: str
) -> int | None:
    metadata = request.metadata.get("prompt_metadata")
    if not isinstance(metadata, Mapping):
        return None
    value = metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def _prompt_metadata_bool(request: CliRunRequest, key: str) -> bool:
    metadata = request.metadata.get("prompt_metadata")
    return isinstance(metadata, Mapping) and metadata.get(key) is True


def _execution_profile(request: CliRunRequest) -> str:
    profile = request.metadata.get("execution_profile")
    return profile.strip() if isinstance(profile, str) else ""


def _review_triage_profile_args(request: CliRunRequest) -> list[str] | None:
    raw_metadata = request.metadata.get("prompt_metadata")
    if not isinstance(raw_metadata, Mapping):
        return None
    review_agents = _validated_review_agents(raw_metadata.get("review_agents"))
    if review_agents is None:
        return None
    read_roots = _prompt_scope_paths(request, raw_metadata, "tool_read_roots")
    write_paths = _prompt_scope_paths(request, raw_metadata, "tool_write_paths")
    if not _review_triage_paths_are_representable(read_roots + write_paths):
        return None
    file_rules: list[str] = []
    for root in read_roots:
        file_rules.append(f"Read({_claude_absolute_rule_path(root)}/**)")
    for path in write_paths:
        rule_path = _claude_absolute_rule_path(path)
        file_rules.extend(f"{tool}({rule_path})" for tool in ("Write", "Edit"))
    agent_rules = [f"Agent({name})" for name in _REVIEW_TRIAGE_AGENT_NAMES]
    return [
        "--bare",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--tools",
        "Read,Write,Edit,Agent",
        "--allowedTools",
        ",".join(file_rules + agent_rules),
        "--agents",
        json.dumps(review_agents, sort_keys=True),
    ]


def _validated_review_agents(
    raw_agents: object,
) -> dict[str, dict[str, object]] | None:
    if not isinstance(raw_agents, Mapping):
        return None
    if set(raw_agents) != set(_REVIEW_TRIAGE_AGENT_NAMES):
        return None
    agents: dict[str, dict[str, object]] = {}
    for name in _REVIEW_TRIAGE_AGENT_NAMES:
        definition = raw_agents.get(name)
        if not isinstance(definition, Mapping):
            return None
        if set(definition) != {"description", "prompt", "tools"}:
            return None
        description = definition.get("description")
        prompt = definition.get("prompt")
        if (
            not isinstance(description, str)
            or not description.strip()
            or not isinstance(prompt, str)
            or not prompt.strip()
            or definition.get("tools") != ["Read"]
        ):
            return None
        agents[name] = {
            "description": description,
            "prompt": prompt,
            "tools": ["Read"],
        }
    return agents


def _review_triage_paths_are_representable(paths: tuple[str, ...]) -> bool:
    return all(
        all(
            character.isalnum()
            or character in _CLAUDE_RULE_PATH_SAFE_CHARACTERS
            for character in path
        )
        for path in paths
    )


def _invalid_review_triage_profile_result() -> CliRunResult:
    return CliRunResult(
        exit_code=125,
        stdout="",
        stderr="invalid review_triage_v1 profile configuration",
        metadata={"invalid_execution_profile": _REVIEW_TRIAGE_PROFILE},
    )


def _prompt_file_scope_args(request: CliRunRequest) -> list[str]:
    metadata = request.metadata.get("prompt_metadata")
    if not isinstance(metadata, Mapping):
        return []
    isolation_args = [
        "--safe-mode", "--setting-sources", "", "--strict-mcp-config",
        "--disable-slash-commands",
    ]
    read_roots = _prompt_scope_paths(request, metadata, "tool_read_roots")
    write_paths = _prompt_scope_paths(request, metadata, "tool_write_paths")
    if metadata.get("tool_write_scope_exclusive") is False:
        # Explicit nonexclusive scope adds control-file exceptions to the normal
        # product workspace. It is not an output-only authoring assignment.
        root = str(Path(request.cwd).resolve())
        rules = [f"{tool}({_claude_absolute_rule_path(root)}/**)"
                 for tool in ("Read", "Write", "Edit")]
        rules.extend(f"Read({_claude_absolute_rule_path(path)}/**)"
                     for path in read_roots if path != root)
        for path in write_paths:
            rules.extend(f"{tool}({_claude_absolute_rule_path(path)})"
                         for tool in ("Read", "Write", "Edit"))
        # Do not grant Bash or bypass permissions here: shell execution retains
        # the existing explicitly approved host policy.
        return [*isolation_args, "--allowedTools", ",".join(rules)]
    if metadata.get("tool_write_scope_exclusive") is True:
        rules = ["Glob", "Grep"]
        for root in read_roots or (str(Path(request.cwd).resolve()),):
            rules.append(f"Read({_claude_absolute_rule_path(root)}/**)")
        for path in write_paths:
            rules.extend(f"{tool}({_claude_absolute_rule_path(path)})"
                         for tool in ("Read", "Write", "Edit"))
        return [
            *isolation_args, "--permission-mode", "dontAsk", "--tools",
            "Read,Glob,Grep,Write,Edit" if write_paths else "Read,Glob,Grep",
            "--allowedTools", ",".join(rules),
        ]
    if not read_roots and not write_paths:
        return []

    rules: list[str] = []
    for root in read_roots:
        rules.append(f"Read({_claude_absolute_rule_path(root)}/**)")
    for path in write_paths:
        rule_path = _claude_absolute_rule_path(path)
        rules.extend(
            f"{tool}({rule_path})" for tool in ("Read", "Write", "Edit")
        )
    return [
        "--safe-mode",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--tools",
        "Read,Write,Edit",
        "--allowedTools",
        ",".join(rules),
    ]


def _prompt_scope_paths(
    request: CliRunRequest,
    metadata: Mapping[object, object],
    key: str,
) -> tuple[str, ...]:
    raw = metadata.get(key)
    if not isinstance(raw, list):
        return ()
    cwd = Path(request.cwd).resolve()
    paths: set[str] = set()
    for value in raw:
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = cwd / candidate
        paths.add(str(candidate.resolve(strict=False)))
    return tuple(sorted(paths))


def _claude_absolute_rule_path(path: str) -> str:
    return path if path.startswith("/") else f"/{path}"


def _atomic_write_sibling_regex(path: str) -> str:
    """Match only temp siblings derived from one authorized output name."""
    candidate = Path(path)
    parent = re.escape(str(candidate.parent)).replace(r"\-", "-").replace(r"\ ", " ")
    filename = re.escape(candidate.name).replace(r"\-", "-")
    pattern = rf"^{parent}/[.]?{filename}([.][^/]+)?$"
    # SBPL's #"..." regex form is already raw; JSON-style double escaping
    # changes the pattern and silently prevents the intended match.
    return f'(regex #"{pattern}")'


def host_workspace_synthesis_boundary_available() -> bool:
    return sys.platform == "darwin" and _sandbox_exec_path() is not None


def _sandbox_exec_path() -> str | None:
    return shutil.which("sandbox-exec")


def _workspace_sandbox_profile(
    forbidden_roots: tuple[str, ...],
    *,
    read_roots: tuple[str, ...] = (),
    write_paths: tuple[str, ...] = (),
    operational_roots: tuple[str, ...] = (),
    operational_read_paths: tuple[str, ...] = (),
    operational_metadata_paths: tuple[str, ...] = (),
    read_only_roots: tuple[str, ...] = (),
    preserve_forbidden_children: bool = False,
    allow_atomic_writes: bool = False,
) -> str:
    exclusions: list[str] = []
    for root in forbidden_roots:
        quoted = json.dumps(root)
        exclusions.extend(
            (
                f"(require-not (literal {quoted}))",
                f"(require-not (subpath {quoted}))",
            )
        )
    allowed_files = f"(require-all {' '.join(exclusions)})"
    write_exclusions = list(exclusions)
    for root in read_only_roots:
        quoted = json.dumps(root)
        write_exclusions.extend((
            f"(require-not (literal {quoted}))",
            f"(require-not (subpath {quoted}))",
        ))
    writable_files = f"(require-all {' '.join(write_exclusions)})"
    read_rules = []
    for root in (*read_roots, *operational_roots):
        scope = f"(subpath {json.dumps(root)})"
        # An enclosing scoped read root must not reopen its forbidden children.
        # Keep legacy synthesis's explicit subtree exceptions unchanged.
        if read_only_roots or preserve_forbidden_children:
            nested = [f"(require-not (subpath {json.dumps(path)}))"
                      for path in forbidden_roots if Path(path).is_relative_to(root)]
            if nested:
                scope = f"(require-all {scope} {' '.join(nested)})"
        read_rules.append(f"(allow file-read* {scope})")
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process*)",
        f"(allow file-read* {allowed_files})",
        f"(allow file-write* {writable_files})",
        *read_rules,
        *(
            f"(allow file-read* (literal {json.dumps(path)}))"
            for path in operational_read_paths
        ),
        *(
            f"(allow file-read-metadata (literal {json.dumps(path)}))"
            for path in operational_metadata_paths
        ),
        *(
            rule
            for path in write_paths
            for rule in (
                f"(allow file-read* (literal {json.dumps(path)}))",
                *(
                    (
                        f"(allow file-write* {_atomic_write_sibling_regex(path)})",
                    )
                    if allow_atomic_writes
                    else ()
                ),
                f"(allow file-write* (literal {json.dumps(str(Path(path).parent))}))",
                f"(allow file-write* (literal {json.dumps(path)}))",
            )
        ),
        "(allow network*)",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        "(allow ipc-posix*)",
    ]
    return "\n".join(lines)


def _claude_model_for_request(request: CliRunRequest) -> str:
    tier = _prompt_metadata_str(request, "model_tier").lower()
    return _MODEL_TIER_TO_CLAUDE_MODEL.get(tier, "")
