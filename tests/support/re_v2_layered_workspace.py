from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from types import MappingProxyType
from typing import Mapping
from unittest.mock import patch

from harness.ai_cli_backend import CliRunRequest, CliRunResult


_SCENARIOS = frozenset(
    {
        "complete",
        "executor-breach",
        "invalid-domain",
        "large-source",
        "live-codex",
    }
)
_DOMAIN_SURFACES = (
    "responsibilities",
    "entry_points",
    "core_behavior",
    "failure_paths",
    "state_and_data",
    "external_contracts",
    "tests",
    "operational_constraints",
)
_SOURCE_SURFACES = (
    "purpose",
    "runtime_shape",
    "major_entry_points",
    "intra_source_boundaries",
    "domain_relationships",
)


@dataclass(frozen=True, slots=True)
class LayeredWorkspaceFixture:
    root: Path
    source_domains: Mapping[str, tuple[str, ...]]
    provider: ScriptedSharedProvider

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_domains",
            MappingProxyType(dict(sorted(self.source_domains.items()))),
        )

    def run_directories(self) -> tuple[Path, ...]:
        runs = self.root / "runs"
        if not runs.is_dir():
            return ()
        return tuple(
            sorted(
                path
                for path in runs.iterdir()
                if path.is_dir() and path.name.startswith("re-")
            )
        )

@dataclass(frozen=True, slots=True)
class CapturedProviderRequest:
    project_root: Path
    prompt: str
    prompt_metadata: Mapping[str, object]
    provider_name: str
    timeout_ms: int | None
    request_metadata: Mapping[str, object]
    context: Mapping[str, object]

    @property
    def body(self) -> bytes:
        return self.prompt.encode("utf-8")

class ScriptedSharedProvider:
    """Script the backend seam while preserving shared-provider behavior."""

    def __init__(self, scenario: str, *, provider_name: str) -> None:
        self.scenario = scenario
        self.name = provider_name
        self.requests: list[CapturedProviderRequest] = []
        self._patcher = None

    def __enter__(self) -> ScriptedSharedProvider:
        self._patcher = patch(
            "harness.llm_provider.create_ai_cli_backend",
            return_value=self,
        )
        self._patcher.start()
        return self

    def __exit__(self, *exc: object) -> None:
        del exc
        if self._patcher is not None:
            self._patcher.stop()
            self._patcher = None

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        return self.run_agent(request)

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        context = _prompt_context(request.prompt)
        raw_prompt_metadata = request.metadata.get("prompt_metadata", {})
        prompt_metadata = (
            dict(raw_prompt_metadata)
            if isinstance(raw_prompt_metadata, Mapping)
            else {}
        )
        captured = CapturedProviderRequest(
            project_root=Path(request.cwd),
            prompt=request.prompt,
            prompt_metadata=MappingProxyType(prompt_metadata),
            provider_name=self.name,
            timeout_ms=max(1, int(request.timeout_s * 1000)),
            request_metadata=MappingProxyType(dict(request.metadata)),
            context=MappingProxyType(context),
        )
        self.requests.append(captured)

        invalid = self.scenario == "invalid-domain" and any(
            str(excerpt.get("source_relative_path", "")).startswith("src/broken/")
            for excerpt in context.get("evidence", [])
            if isinstance(excerpt, dict)
        )
        candidate = _candidate(context, useful=not invalid)
        captured.project_root.joinpath("baseline.json").write_text(
            json.dumps(candidate, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        stdout = (
            "malformed result contract\n"
            if self.scenario == "large-source"
            else "echelon_result:\n  verdict: DONE\n  state_updates: {}\n"
        )
        if self.scenario == "executor-breach":
            token_usage = 300_001
            token_usage_details = {
                "input_tokens": 300_000,
                "output_tokens": 1,
            }
        elif self.scenario == "large-source":
            token_usage = 0
            token_usage_details = {}
        else:
            token_usage = 15
            token_usage_details = {"input_tokens": 10, "output_tokens": 5}
        return CliRunResult(
            exit_code=0,
            stdout=stdout,
            stderr="",
            token_usage=token_usage,
            metadata={
                "response_model": "fixture-shared-model",
                "token_usage_details": token_usage_details,
            },
        )


def create_layered_workspace(
    tmp_path: Path,
    scenario: str,
) -> LayeredWorkspaceFixture:
    return build_and_commit_fixture(tmp_path, scenario)


def build_and_commit_fixture(
    tmp_path: Path,
    scenario: str,
) -> LayeredWorkspaceFixture:
    if scenario not in _SCENARIOS:
        raise ValueError(f"unknown fixture scenario: {scenario}")
    root = tmp_path / "layered-workspace"
    root.mkdir(parents=True)
    cli_name = "codex" if scenario == "live-codex" else "opencode"
    provider = ScriptedSharedProvider(scenario, provider_name=cli_name)
    source_domains = _source_layout(scenario)
    for source_id, domains in source_domains.items():
        source = root / "sources" / source_id
        source.mkdir(parents=True)
        _git(source, "init")
        _write_text(
            source / "pyproject.toml",
            f"[project]\nname = '{source_id}-fixture'\nversion = '0.1.0'\n",
        )
        _write_text(
            source / "README.md",
            f"# {source_id}\n\nRuntime fixture for {source_id}.\n",
        )
        for domain in domains:
            name = domain.rsplit("/", 1)[-1]
            _write_text(
                source / domain / "service.py",
                f"def run_{name}():\n    return '{source_id}:{name}'\n",
            )
            _write_text(
                source / domain / "model.py",
                f"class {name.title()}Record:\n    pass\n",
            )
        if scenario == "large-source" and source_id == "api":
            _write_large_source_files(source / "src" / "huge")
        _git(source, "add", ".")
        _git(source, "commit", "-m", f"build {source_id} fixture")

    _write_text(
        root / ".echelon" / "config.yml",
        _config(
            source_domains,
            timeout_ms=120_000 if scenario == "live-codex" else 30_000,
            cli_name=cli_name,
        ),
    )
    if scenario != "live-codex":
        agent_source = (
            Path(__file__).resolve().parents[2]
            / "prosaic"
            / "subagents"
            / "echelon.re-baseliner.md"
        )
        agent_target = (
            root
            / ".echelon"
            / "prosaic"
            / "subagents"
            / "echelon.re-baseliner.md"
        )
        agent_target.parent.mkdir(parents=True, exist_ok=True)
        agent_target.write_bytes(agent_source.read_bytes())
    return LayeredWorkspaceFixture(root, source_domains, provider)


def _source_layout(scenario: str) -> dict[str, tuple[str, ...]]:
    if scenario == "live-codex":
        return {"api": ("src/orders",)}
    if scenario == "invalid-domain":
        return {
            "api": ("src/broken", "src/orders"),
            "web": ("src/ui",),
        }
    if scenario == "large-source":
        return {"api": ("src/huge",)}
    return {
        "api": ("src/orders", "src/users"),
        "web": ("src/search", "src/ui"),
    }


def _config(
    source_domains: Mapping[str, tuple[str, ...]],
    *,
    timeout_ms: int,
    cli_name: str,
) -> str:
    source_lines = "".join(
        f"    - id: {source_id}\n      path: sources/{source_id}\n"
        for source_id in sorted(source_domains)
    )
    return (
        "workspace:\n"
        "  git_role: orchestration\n"
        "  sources:\n"
        f"{source_lines}"
        "harness:\n"
        "  provider: docker\n"
        "  llm:\n"
        f"    cli: {cli_name}\n"
        "    model: fixture-shared-model\n"
        f"    timeout_ms: {timeout_ms}\n"
    )


def _prompt_context(prompt: str) -> dict[str, object]:
    marker = "## Bounded context (canonical JSON)\n"
    schema_marker = "\n\n## Authorial response schema (canonical JSON)\n"
    if marker not in prompt or schema_marker not in prompt:
        raise ValueError("shared-provider fixture prompt has no bounded context")
    raw = prompt.split(marker, 1)[1].split(schema_marker, 1)[0]
    context = json.loads(raw)
    if not isinstance(context, dict):
        raise ValueError("shared-provider fixture context is not an object")
    return context


def _candidate(context: Mapping[str, object], *, useful: bool) -> dict[str, object]:
    kind = str(context["target_artifact_kind"])
    names = _DOMAIN_SURFACES if kind == "domain-baseline" else _SOURCE_SURFACES
    surfaces = {name: _not_established() for name in names}
    if useful:
        excerpts = [
            excerpt
            for excerpt in context.get("evidence", [])
            if isinstance(excerpt, dict)
        ]
        for projection in context.get("domain_projections", []):
            if isinstance(projection, dict):
                excerpts.extend(
                    excerpt
                    for excerpt in projection.get("evidence", [])
                    if isinstance(excerpt, dict)
                )
        if not excerpts:
            raise ValueError("bounded fixture context has no citable evidence")
        reference = _reference(excerpts[0])
        if kind == "domain-baseline":
            surfaces["responsibilities"] = _observed(
                "Owns the bounded domain behavior",
                reference,
            )
            surfaces["entry_points"] = _observed(
                "Exposes the bounded domain entry point",
                reference,
            )
        else:
            surfaces["purpose"] = _observed(
                "Coordinates the bounded source runtime",
                reference,
            )
            surfaces["runtime_shape"] = _observed(
                "Runs through the bounded source entry point",
                reference,
            )
            if len(context.get("domain_projections", [])) > 1:
                surfaces["domain_relationships"] = _observed(
                    "Relates the bounded source domains",
                    reference,
                )
    return {"schema_version": 1, "surfaces": surfaces, "unknowns": []}


def _reference(excerpt: Mapping[str, object]) -> dict[str, object]:
    return {
        "evidence_authority_id": excerpt["evidence_authority_id"],
        "path": excerpt["source_relative_path"],
        "start_line": excerpt["start_line"],
        "end_line": excerpt["end_line"],
    }


def _observed(statement: str, reference: Mapping[str, object]) -> dict[str, object]:
    return {
        "status": "observed",
        "items": [{"statement": statement, "evidence": [dict(reference)]}],
        "not_established_reason_code": None,
    }


def _not_established() -> dict[str, object]:
    return {
        "status": "not_established",
        "items": [],
        "not_established_reason_code": "not_in_bounded_context",
    }


def _write_large_source_files(domain: Path) -> None:
    domain.mkdir(parents=True, exist_ok=True)
    (domain / "binary.bin").write_bytes(b"\x00\x01\x02\xff\x00")
    (domain / "invalid-utf8.py").write_bytes(b"value = '\xff'\n")
    (domain / "crlf.py").write_bytes(b"def crlf():\r\n    return True\r\n")
    (domain / "unterminated.py").write_bytes(b"value = 1")
    (domain / "long-line.py").write_bytes(
        b"payload = b'" + b"x" * 200_000 + b"'\n"
    )


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Layered Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.test",
            "GIT_COMMITTER_NAME": "Layered Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.test",
        },
    )


__all__ = (
    "CapturedProviderRequest",
    "LayeredWorkspaceFixture",
    "ScriptedSharedProvider",
    "build_and_commit_fixture",
    "create_layered_workspace",
)
