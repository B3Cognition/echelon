"""Tests for the Phase B delivery status CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_delivery_state(
    project_root: Path,
    *,
    strategy: str = "default",
    user_runnability: dict | None = None,
) -> Path:
    state_dir = project_root / "runs" / "build-20260710-101500-000000" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / f"{strategy}.json"
    payload = {
                "spec_id": "001",
                "strategy_id": strategy,
                "status": "blocked",
                "mode": "banzai",
                "outer_iter": 2,
                "inner_iter": 1,
                "tokens_used": 1200,
                "token_budget": 4000,
                "termination_reason": "blocker_escalation",
                "build_status": "needs_answer",
                "build_reason": "Pick a provider.",
                "salvage_commit": "abcdef1234567890",
                "salvage_branch": "harness/001-salvage",
                "checkpoint_commits": [{"commit": "1234567890abcdef", "phase": "build"}],
                "escalation_file": "runs/build-20260710-101500-000000/escalation.md",
            }
    if user_runnability is not None:
        payload["user_runnability"] = user_runnability
    state_file.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    return state_file


def _write_spec(project_root: Path) -> Path:
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: ready_to_land\n---\n# Demo\n",
        encoding="utf-8",
    )
    (spec_dir / "harness-run-history.json").write_text(
        json.dumps({"runs": [{"status": "blocked", "finished_at": "2026-07-10T10:20:00Z"}]}),
        encoding="utf-8",
    )
    return spec_dir


def _write_target_delivery_state(project_root: Path) -> Path:
    state_dir = (
        project_root
        / "runs"
        / "targets"
        / "browser-3d-game"
        / "runs"
        / "build-20260711-101500-000000"
        / "state"
    )
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "default.json"
    state_file.write_text(
        json.dumps(
            {
                "spec_id": "001",
                "strategy_id": "default",
                "status": "blocked",
                "target_repo": "browser-3d-game",
                "implementation_target": "sources/browser-3d-game",
                "outer_iter": 3,
                "inner_iter": 2,
                "tokens_used": 3939746,
                "termination_reason": "blocker_escalation",
                "build_status": "blocked",
                "build_reason": "same_failure_repeat",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return state_file


def _write_escalation(project_root: Path) -> Path:
    path = project_root / "runs" / "build-20260710-101500-000000" / "escalation.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Escalation: same_failure_repeat\n\n"
        "## Question\n\n"
        "Which database should verification use?\n\n"
        "## Context\n\n"
        "DATABASE_URL is missing from the isolated verification environment.\n\n"
        "## Decision Metadata\n\n"
        "```json\n"
        "{\n"
        "  \"suggested_answers\": [\n"
        "    {\n"
        "      \"label\": \"Retry with the recorded context\",\n"
        "      \"answer\": \"Continue with the isolated verification database.\",\n"
        "      \"consequence\": \"The delivery loop retries.\",\n"
        "      \"recommended\": true\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "```\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.unit
def test_build_blocked_status_matches_executable_fresh_run_recovery() -> None:
    from echelon.cli import _delivery_status_next_step

    next_step = _delivery_status_next_step(
        {
            "status": "blocked",
            "termination_reason": "build_blocked",
            "build_reason": "candidate contract path was denied",
        },
        "001",
    )

    assert next_step == "resolve the reported blocker, then echelon delivery run 001"
    assert "continue" not in next_step


@pytest.mark.unit
@pytest.mark.parametrize("status", ["initialized", "running", "interrupted"])
def test_non_blocked_status_matches_delivery_run_dispatch(status: str) -> None:
    from echelon.cli import _delivery_status_next_step

    next_step = _delivery_status_next_step({"status": status}, "001")

    assert next_step == "echelon delivery run 001"


@pytest.mark.unit
def test_delivery_status_shows_failed_runnability_action(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_delivery_status

    _write_delivery_state(
        tmp_path,
        user_runnability={
            "status": "not_runnable",
            "failed_stage": "primary_journey",
            "failure_class": "missing_local_auth_bootstrap",
            "summary": "No local player session could be created.",
            "report": "/runs/report.md",
            "candidate_fingerprint": "product-1",
            "contract_hash": "contract-1",
            "stack_hash": "stack-1",
            "user_commands": {},
        },
    )

    _cmd_delivery_status([], project_root=tmp_path)

    output = capsys.readouterr().out
    assert "user runnable" in output
    assert "primary journey" in output
    assert "missing_local_auth_bootstrap" in output
    assert "/runs/report.md" in output
    assert "delivery will repair this current-spec product gap" in output


@pytest.mark.unit
def test_delivery_status_runnability_shows_passing_local_run_commands(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_delivery_status

    commands = {
        "prerequisites": ["Docker 27", "pnpm 10"],
        "provision": ["echelon stack provision --target browser-game"],
        "start": ["pnpm start:local"],
        "open": ["http://127.0.0.1:5173"],
        "stop": ["pnpm stop:local", "docker compose down"],
    }
    _write_delivery_state(
        tmp_path,
        user_runnability={
            "status": "runnable",
            "failed_stage": None,
            "failure_class": "",
            "summary": "The composed journey passed.",
            "report": "/runs/report.md",
            "candidate_fingerprint": "product-1",
            "contract_hash": "contract-1",
            "stack_hash": "stack-1",
            "user_commands": commands,
        },
    )

    _cmd_delivery_status(["--json"], project_root=tmp_path)
    json_payload = json.loads(capsys.readouterr().out)
    assert json_payload["latest"]["user_runnability"]["user_commands"] == commands

    _cmd_delivery_status([], project_root=tmp_path)
    output = capsys.readouterr().out
    assert "pnpm start:local" in output
    assert "echelon stack provision --target browser-game" in output
    assert "http://127.0.0.1:5173" in output


@pytest.mark.unit
def test_delivery_status_surfaces_separate_unverified_local_journey(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_delivery_status

    local_journey = {
        "status": "unverified",
        "reason": "No compatible local runner executed these commands.",
        "commands": {
            "prerequisites": ["Docker with Compose v2"],
            "provision": ["docker compose up -d postgres"],
            "readiness": ["docker compose exec -T postgres pg_isready"],
            "prepare": ["pnpm db:prepare-local-test"],
            "verify": ["pnpm verify:local"],
            "start": ["pnpm start"],
            "open": ["http://127.0.0.1:3000"],
            "stop": ["pnpm stop"],
            "cleanup": ["docker compose down -v"],
        },
    }
    _write_delivery_state(
        tmp_path,
        user_runnability={
            "status": "runnable",
            "failed_stage": None,
            "failure_class": "",
            "summary": "The sandbox journey passed.",
            "report": "/runs/report.md",
            "candidate_fingerprint": "product-1",
            "contract_hash": "contract-1",
            "stack_hash": "stack-1",
            "user_commands": {"start": ["pnpm start:sandbox"]},
            "local_journey": local_journey,
        },
    )

    _cmd_delivery_status(["--json"], project_root=tmp_path)
    json_payload = json.loads(capsys.readouterr().out)
    assert json_payload["latest"]["user_runnability"]["local_journey"] == local_journey

    _cmd_delivery_status([], project_root=tmp_path)
    output = capsys.readouterr().out
    assert "local journey" in output
    assert "unverified" in output
    assert "local provision" in output
    assert "docker compose up -d postgres" in output
    assert "local verify" in output
    assert "pnpm verify:local" in output
    assert "local cleanup" in output
    assert "docker compose down -v" in output


@pytest.mark.unit
def test_delivery_status_prints_latest_state(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from echelon.cli import _cmd_delivery_status

    state_file = _write_delivery_state(tmp_path)
    _write_spec(tmp_path)

    _cmd_delivery_status(["001"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "DELIVERY STATUS" in out
    assert "Phase B delivery" in out
    assert "001" in out
    assert "blocked" in out
    assert "blocker_escalation" in out
    assert "ready_to_land" in out
    assert "echelon delivery resume 001" in out
    assert str(state_file) in out


@pytest.mark.unit
def test_delivery_status_does_not_recommend_landing_an_already_landed_spec(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_delivery_status

    state_file = _write_delivery_state(tmp_path)
    state = json.loads(state_file.read_text(encoding="utf-8"))
    state["status"] = "converged"
    state["termination_reason"] = "converged"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    spec_dir = _write_spec(tmp_path)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: landed\n---\n# Demo\n",
        encoding="utf-8",
    )

    _cmd_delivery_status(["001", "--json"], project_root=tmp_path)

    payload = json.loads(capsys.readouterr().out)
    assert payload["latest"]["spec_status"] == "landed"
    assert payload["latest"]["next"] == "No action required; delivery is already landed."


@pytest.mark.unit
def test_delivery_status_prints_publication_failure_cause(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_delivery_status

    state_file = _write_delivery_state(tmp_path)
    state = json.loads(state_file.read_text(encoding="utf-8"))
    state["termination_reason"] = "publish_failed"
    state["publication_failure"] = {
        "stage": "dirty_adjudication",
        "error": "Dirty worktree adjudication blocked commit",
    }
    state_file.write_text(json.dumps(state), encoding="utf-8")

    _cmd_delivery_status(["001"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "publish stage" in out
    assert "dirty_adjudication" in out
    assert "publish error" in out
    assert "Dirty worktree adjudication blocked commit" in out


@pytest.mark.unit
def test_delivery_status_json_filters_strategy(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from echelon.cli import _cmd_delivery_status

    _write_delivery_state(tmp_path, strategy="default")
    _write_delivery_state(tmp_path, strategy="codegen")

    _cmd_delivery_status(["001", "--strategy", "codegen", "--json"], project_root=tmp_path)

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert payload["latest"]["spec_id"] == "001"
    assert payload["latest"]["strategy"] == "codegen"
    assert payload["latest"]["next"] == 'echelon delivery resume 001 "<answer>"'
    assert len(payload["states"]) == 1


@pytest.mark.unit
def test_delivery_status_without_state_points_to_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_delivery_status

    _cmd_delivery_status(["001"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "No delivery runs found" in out
    assert "echelon delivery run 001" in out


@pytest.mark.unit
def test_delivery_status_discovers_target_delivery_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_delivery_status

    state_file = _write_target_delivery_state(tmp_path)
    _write_spec(tmp_path)

    _cmd_delivery_status(["001"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "browser-3d-game" in out
    assert "blocker_escalation" in out
    assert str(state_file) in out


@pytest.mark.unit
def test_delivery_status_renders_escalation_question_and_recommended_command(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_delivery_status

    _write_delivery_state(tmp_path)
    escalation_path = _write_escalation(tmp_path)

    _cmd_delivery_status(["001"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "Which database should verification use?" in out
    assert "DATABASE_URL is missing" in out
    assert "Retry with the recorded context" in out
    assert "Continue with the isolated verification database." in out
    assert str(escalation_path) in out
    assert "echelon delivery resume 001 'Continue with the isolated verification database.'" in out


@pytest.mark.unit
def test_delivery_status_outer_cap_ignores_stale_escalation_and_starts_new_budget(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An exhausted loop cannot advertise an answer-based resume it rejects."""
    state_file = _write_delivery_state(tmp_path)
    state = json.loads(state_file.read_text(encoding="utf-8"))
    state["termination_reason"] = "outer_cap"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    _write_escalation(tmp_path)

    from echelon.cli import _cmd_delivery_status

    _cmd_delivery_status(["001"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "echelon delivery run 001" in out
    assert "fresh outer-loop budget" in out
    assert "echelon delivery resume 001" not in out
    assert "Which database should verification use?" not in out

    _cmd_delivery_status(["001", "--json"], project_root=tmp_path)

    payload = json.loads(capsys.readouterr().out)
    assert payload["latest"]["next"].startswith("echelon delivery run 001")
    assert "escalation" not in payload["latest"]
