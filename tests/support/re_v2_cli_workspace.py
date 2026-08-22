from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess


@dataclass(frozen=True, slots=True)
class CliWorkspaceProbe:
    root: Path

    def active_pointer_bytes(self) -> bytes | None:
        pointer = self.root / "runs" / ".current-re"
        return pointer.read_bytes() if pointer.exists() else None

    def run_directories(self) -> tuple[Path, ...]:
        runs = self.root / "runs"
        if not runs.exists():
            return ()
        return tuple(
            sorted(
                (
                    path
                    for path in runs.iterdir()
                    if path.is_dir() and path.name.startswith("re-")
                ),
                key=lambda path: path.name,
            )
        )


def create_cli_workspace(
    tmp_path: Path,
    llm_cli: str,
    *,
    include_agent: bool = True,
) -> CliWorkspaceProbe:
    root = tmp_path / "workspace"
    root.mkdir(parents=True)
    _write(root / "pyproject.toml", "[project]\nname = 'cli-fixture'\nversion = '0.1.0'\n")
    _write(root / "src" / "orders" / "service.py", "def orders():\n    return []\n")
    _write(root / ".gitignore", "runs/\n")
    _write(root / ".echelon" / "config.yml", _config(llm_cli))
    if include_agent:
        source = (
            Path(__file__).resolve().parents[2]
            / "prosaic"
            / "subagents"
            / "echelon.re-baseliner.md"
        )
        target = (
            root
            / ".echelon"
            / "prosaic"
            / "subagents"
            / "echelon.re-baseliner.md"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    _git(root, "init")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    return CliWorkspaceProbe(root)


def _config(llm_cli: str) -> str:
    workspace = (
        "workspace:\n"
        "  git_role: source\n"
        "  sources:\n"
        "    - id: cli-fixture\n"
        "      path: .\n"
    )
    if llm_cli != "openai-compatible":
        return (
            workspace
            +
            "harness:\n"
            "  provider: docker\n"
            "  llm:\n"
            f"    cli: {llm_cli}\n"
        )
    return (
        workspace
        +
        "harness:\n"
        "  provider: docker\n"
        "  llm:\n"
        "    cli: openai-compatible\n"
        "    base_url: http://127.0.0.1:9/v1\n"
        "    model: fixture-model\n"
        "    max_tokens: 2048\n"
        "    timeout_ms: 300000\n"
        "    re_v2_baseline:\n"
        "      model_revision: fixture-model-2026-08-22\n"
        "      revision_authority: provider_resolved_revision\n"
        "      provider_context_tokens: 32768\n"
        "      request_path: /chat/completions\n"
        "      api_protocol_version: '1'\n"
        "      fixed_framing_byte_upper_bound: 4096\n"
    )


def _write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.test",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.test",
        },
    )
