#!/usr/bin/env python3
"""Create a disposable clean two-source protocol-2.7 Codex pilot workspace."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.prosaic_prompt_loader import ProsaicPromptLoader
from harness.re_v2.publication import EMPTY_INDEX_HASH
from harness.re_registry import load_published_index
from harness.re_v2.publication import current_index_hash
from harness.re_v2.protocol_27.controller import Protocol27Controller
from harness.re_v2.protocol_27.inputs import (
    create_protocol_27_run_store,
    load_protocol_27_inputs,
)
from tests.unit.test_re_v2_protocol_27_controller import _ScriptedProvider
from tests.unit.test_re_v2_protocol_27_inputs import _input_set


def create_pilot(root: Path) -> str:
    root = root.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"pilot root must be empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    for source_id in ("source-a", "source-b"):
        source = root / source_id
        source.mkdir()
        _git(source, "init")
        _write(
            source / "pyproject.toml",
            f"[project]\nname = \"{source_id}\"\nversion = \"0.1.0\"\n",
        )
        _write(
            source / "src" / source_id.replace("-", "_") / "service.py",
            (
                f'"""{source_id} pilot service."""\n\n'
                f"def identity(value: str) -> str:\n    return \"{source_id}:\" + value\n"
            ),
        )
        _write(
            source / "tests" / "test_service.py",
            (
                f"from {source_id.replace('-', '_')}.service import identity\n\n"
                f"def test_identity():\n    assert identity(\"x\") == \"{source_id}:x\"\n"
            ),
        )
        _git(source, "add", ".")
        _git(source, "commit", "-m", f"build {source_id} pilot")

    _write(
        root / ".echelon" / "config.yml",
        (
            "workspace:\n"
            "  git_role: orchestration\n"
            "  sources:\n"
            "    - id: source-a\n"
            "      path: source-a\n"
            "    - id: source-b\n"
            "      path: source-b\n"
            "harness:\n"
            "  provider: docker\n"
            "  llm:\n"
            "    cli: codex\n"
            "    model: gpt-5.4\n"
            "    timeout_ms: 300000\n"
        ),
    )
    subprocess.run(
        ["echelon", "workspace", "migrate-to-prosaic"],
        cwd=root,
        check=True,
    )
    artifact = ProsaicPromptLoader(root).load_subagent("echelon.re-synthesizer")
    if artifact is None:
        raise RuntimeError("installed pilot has no echelon.re-synthesizer")

    run_id = "re-protocol-27-pilot-parent"
    run_dir = root / "runs" / run_id
    inputs = _input_set(
        run_id,
        partial_sources=frozenset({"source-b"}),
        source_ids=("source-a", "source-b"),
        prosaic_artifact=artifact,
        expected_v2_index_hash=EMPTY_INDEX_HASH,
        expected_compatibility_generation=0,
        token_limit=100_000_000,
        active_ms_limit=100_000_000,
    )
    create_protocol_27_run_store(run_dir, inputs)
    result = Protocol27Controller(
        load_protocol_27_inputs(run_dir),
        provider_factory=lambda: _ScriptedProvider(),  # type: ignore[arg-type]
    ).run_to_closure()
    if not result.synthesis_closure_complete:
        raise RuntimeError("pilot parent synthesis did not close")

    # Keep the terminal accepted-source authority and publication, but remove
    # synthesis checkpoints so the first real child must exercise Codex.
    (run_dir / "v2" / "ledger.jsonl").unlink()
    (root / "runs" / ".current-re").write_text(run_id + "\n", encoding="utf-8")
    (root / "parent-run-id").write_text(run_id + "\n", encoding="utf-8")
    (root / "pilot-metadata.json").write_text(
        json.dumps(
            {
                "parent_run_id": run_id,
                "complete_sources": ["source-a"],
                "partial_sources": ["source-b"],
                "provider": "codex",
                "model_tier": "strong",
                "effort": "high",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    for source_id in ("source-a", "source-b"):
        if _git(root / source_id, "status", "--porcelain").stdout:
            raise RuntimeError(f"pilot source is dirty after creation: {source_id}")
    return run_id


def create_incremental_parent(root: Path) -> str:
    """Publish a synthetic accepted parent where only source-a authority changed."""
    root = root.resolve()
    published = load_published_index(root)
    if published is None:
        raise RuntimeError("incremental pilot requires an existing publication")
    artifact = ProsaicPromptLoader(root).load_subagent("echelon.re-synthesizer")
    if artifact is None:
        raise RuntimeError("installed pilot has no echelon.re-synthesizer")
    run_id = "re-protocol-27-incremental-parent"
    run_dir = root / "runs" / run_id
    inputs = _input_set(
        run_id,
        partial_sources=frozenset({"source-b"}),
        source_ids=("source-a", "source-b"),
        prosaic_artifact=artifact,
        expected_v2_index_hash=current_index_hash(root),
        expected_compatibility_generation=published.generation,
        token_limit=100_000_000,
        active_ms_limit=100_000_000,
        source_root_suffixes={"source-a": "incremental-v2"},
    )
    create_protocol_27_run_store(run_dir, inputs)
    result = Protocol27Controller(
        load_protocol_27_inputs(run_dir),
        provider_factory=lambda: _ScriptedProvider(),  # type: ignore[arg-type]
    ).run_to_closure()
    if not result.synthesis_closure_complete:
        raise RuntimeError("incremental pilot parent synthesis did not close")
    (run_dir / "v2" / "ledger.jsonl").unlink()
    (root / "incremental-parent-run-id").write_text(run_id + "\n", encoding="utf-8")
    return run_id


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "--incremental":
        print(create_incremental_parent(Path(argv[2])))
        return 0
    if len(argv) != 2:
        print(
            "usage: create_re_v2_protocol_27_pilot.py [--incremental] <pilot-root>",
            file=sys.stderr,
        )
        return 2
    run_id = create_pilot(Path(argv[1]))
    print(run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
