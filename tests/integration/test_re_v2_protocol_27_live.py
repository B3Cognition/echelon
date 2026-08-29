from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.integration
@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("ECHELON_RUN_LIVE_CODEX") != "1"
    or shutil.which("codex") is None
    or shutil.which("echelon") is None,
    reason="set ECHELON_RUN_LIVE_CODEX=1 with installed codex and echelon CLIs",
)
def test_installed_codex_deferred_synthesis_pilot(tmp_path: Path) -> None:
    from harness.prosaic_prompt_loader import ProsaicPromptLoader
    workspace = tmp_path / "pilot"
    fixture_script = (
        Path(__file__).resolve().parents[1]
        / "fixtures/create_re_v2_protocol_27_pilot.py"
    )
    _run(
        [
            "python",
            str(fixture_script),
            str(workspace),
        ],
        Path(__file__).resolve().parents[2],
        timeout=300,
    )
    parent_run_id = (workspace / "parent-run-id").read_text(encoding="utf-8").strip()
    environment = {**os.environ, "ECHELON_LLM": "codex"}

    _synthesize(workspace, environment, parent_run_id, 2_000_000, timeout=1800)
    first = _active_run(workspace)
    first_status = _status(workspace, first.name)
    assert first_status["synthesis_status"] == "incomplete"
    assert first_status["stop_reason"] == "synthesis-reservation-exceeds-remaining-budget"
    first_generated = int(first_status["artifact_counts"]["generated"])
    assert 0 < first_generated < int(first_status["artifact_counts"]["required"])

    _synthesize(workspace, environment, parent_run_id, 5_000_000, timeout=1800)
    generated = _active_run(workspace)
    generated_status = _status(workspace, generated.name)
    assert generated_status["synthesis_status"] == "complete"
    assert generated_status["input_quality"] == "partial"
    assert generated_status["publication_status"] == "published_partial"
    assert generated_status["full_quality_claim"] == "unavailable"
    assert generated_status["artifact_counts"]["adopted"] == first_generated
    assert generated_status["avoided_provider_calls"] == first_generated
    assert generated_status["resources"]["provider_attempts"] == (
        generated_status["artifact_counts"]["generated"]
    )
    observations = _capture_observations(generated)
    assert observations
    assert {item["provider_name"] for item in observations} == {"codex"}
    assert all(item["resolved_model_revision"] for item in observations)
    agent = ProsaicPromptLoader(workspace).load_subagent("echelon.re-synthesizer")
    assert agent is not None
    assert agent.frontmatter["model_tier"] == "strong"
    assert agent.frontmatter["effort"] == "high"

    before = _canonical_digests(generated)
    capture_count = len(observations)
    _run(["echelon", "re", "continue", generated.name], workspace, environment, 300)
    assert _canonical_digests(generated) == before
    assert len(_capture_observations(generated)) == capture_count

    hidden_first = workspace / "hidden-first-origin"
    first.rename(hidden_first)
    shutil.rmtree(workspace / ".echelon/re-v2/checkpoints", ignore_errors=True)
    _synthesize(workspace, environment, generated.name, 5_000_001, timeout=300)
    adopted = _active_run(workspace)
    adopted_status = _status(workspace, adopted.name)
    assert adopted_status["artifact_counts"]["adopted"] == adopted_status["artifact_counts"]["required"]
    assert adopted_status["resources"]["provider_attempts"] == 0
    assert _capture_observations(adopted) == []

    hidden_generated = workspace / "hidden-generated-origin"
    generated.rename(hidden_generated)
    adopted_before = _canonical_digests(adopted)
    _run(["echelon", "re", "continue", adopted.name], workspace, environment, 300)
    assert _canonical_digests(adopted) == adopted_before
    _synthesize(workspace, environment, adopted.name, 5_000_002, timeout=300)
    reexported = _active_run(workspace)
    reexported_status = _status(workspace, reexported.name)
    assert reexported_status["artifact_counts"]["adopted"] == reexported_status["artifact_counts"]["required"]
    assert reexported_status["resources"]["provider_attempts"] == 0

    _run(
        ["python", str(fixture_script), "--incremental", str(workspace)],
        Path(__file__).resolve().parents[2],
        timeout=300,
    )
    incremental_parent_id = (
        workspace / "incremental-parent-run-id"
    ).read_text(encoding="utf-8").strip()
    _synthesize(workspace, environment, incremental_parent_id, 5_000_000, timeout=1800)
    incremental = _active_run(workspace)
    incremental_status = _status(workspace, incremental.name)
    assert incremental_status["synthesis_status"] == "complete"
    assert incremental_status["artifact_counts"]["generated"] > 0
    assert incremental_status["artifact_counts"]["adopted"] > 0
    rows = incremental_status["artifacts"]
    assert all(
        row["status"] == "adopted"
        for row in rows
        if row["scope"] == "source" and row["source_id"] == "source-b"
    )
    assert all(
        row["status"] == "generated"
        for row in rows
        if row["scope"] == "source" and row["source_id"] == "source-a"
    )
    assert all(row["status"] == "generated" for row in rows if row["scope"] == "workspace")
    assert _git_status(workspace / "source-a") == ""
    assert _git_status(workspace / "source-b") == ""


def _synthesize(
    workspace: Path,
    environment: dict[str, str],
    parent_run_id: str,
    token_limit: int,
    *,
    timeout: int,
) -> None:
    _run(
        [
            "echelon",
            "re",
            "synthesize",
            "--from-run",
            parent_run_id,
            "--accept-partial",
            "source-b",
            "--token-limit",
            str(token_limit),
            "--active-ms-limit",
            "1800000",
        ],
        workspace,
        environment,
        timeout,
    )


def _run(
    command: list[str],
    cwd: Path,
    environment: dict[str, str] | None = None,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _active_run(workspace: Path) -> Path:
    run_id = (workspace / "runs/.current-re").read_text(encoding="utf-8").strip()
    return workspace / "runs" / run_id


def _status(workspace: Path, run_id: str) -> dict[str, object]:
    result = _run(
        ["echelon", "re", "status", run_id, "--json"],
        workspace,
    )
    loaded = json.loads(result.stdout)
    assert isinstance(loaded, dict)
    return loaded


def _capture_observations(run_dir: Path) -> list[dict[str, object]]:
    from harness.re_v2.ledger import ObjectStore

    root = run_dir / "v2"
    store = ObjectStore(root / "objects")
    observations: list[dict[str, object]] = []
    for path in sorted((root / "captures/committed").glob("*.json")):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        observations.append(json.loads(store.read_blob(receipt["execution_capture_hash"])))
    return observations


def _canonical_digests(run_dir: Path) -> tuple[bytes, bytes, bytes]:
    return tuple(
        run_dir.joinpath("v2", name).read_bytes()
        for name in ("run.json", "events.jsonl", "ledger.jsonl")
    )  # type: ignore[return-value]


def _git_status(source: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
