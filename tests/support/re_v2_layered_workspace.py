from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from types import MappingProxyType
from typing import Callable, Mapping

from tests.support.re_v2_bounded_api import (
    CapturedRequest,
    ScriptedBoundedApi,
    ScriptedResponse,
    valid_response,
)


_SCENARIOS = frozenset(
    {"complete", "invalid-domain", "executor-breach", "large-source"}
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
    api: ScriptedBoundedApi

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
    api = ScriptedBoundedApi(
        default_response=ScriptedResponse(body=_response_factory(scenario))
    )
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

    _write_text(root / ".echelon" / "config.yml", _config(api, source_domains))
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
    return LayeredWorkspaceFixture(root, source_domains, api)


def _source_layout(scenario: str) -> dict[str, tuple[str, ...]]:
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
    api: ScriptedBoundedApi,
    source_domains: Mapping[str, tuple[str, ...]],
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
        "    cli: openai-compatible\n"
        f"    base_url: {api.base_url}\n"
        "    model: gpt-example\n"
        "    api_key_env: ECHELON_TEST_API_KEY\n"
        "    max_tokens: 2048\n"
        "    timeout_ms: 30000\n"
        "    re_v2_baseline:\n"
        "      model_revision: gpt-example-2026-08-01\n"
        "      revision_authority: provider_resolved_revision\n"
        "      provider_context_tokens: 262144\n"
        "      request_path: /chat/completions\n"
        "      api_protocol_version: '1'\n"
        "      fixed_framing_byte_upper_bound: 4096\n"
    )


def _response_factory(scenario: str) -> Callable[[CapturedRequest], object]:
    def respond(request: CapturedRequest) -> object:
        context = _request_context(request)
        invalid = scenario == "invalid-domain" and any(
            str(excerpt.get("source_relative_path", "")).startswith("src/broken/")
            for excerpt in context.get("evidence", [])
            if isinstance(excerpt, dict)
        )
        candidate = _candidate(context, useful=not invalid)
        content = json.dumps(candidate, sort_keys=True, separators=(",", ":"))
        if scenario == "executor-breach":
            usage: object = {
                "prompt_tokens": 300_000,
                "completion_tokens": 1,
                "total_tokens": 300_001,
            }
            return valid_response(content=content, usage=usage)
        response = valid_response(content=content)
        if scenario == "large-source":
            response.pop("usage", None)
        return response

    return respond


def _request_context(request: CapturedRequest) -> dict[str, object]:
    raw = request.json
    messages = raw.get("messages", []) if isinstance(raw, dict) else []
    user = next(
        (
            message.get("content")
            for message in messages
            if isinstance(message, dict) and message.get("role") == "user"
        ),
        None,
    )
    if not isinstance(user, str):
        raise ValueError("bounded fixture request has no user context")
    context = json.loads(user)
    if not isinstance(context, dict):
        raise ValueError("bounded fixture user context is not an object")
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
    "LayeredWorkspaceFixture",
    "build_and_commit_fixture",
    "create_layered_workspace",
)
