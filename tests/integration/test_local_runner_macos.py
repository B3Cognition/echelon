"""Explicit real-engine acceptance for the supported macOS local runner."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def _require_enabled_macos_engine() -> str:
    if sys.platform != "darwin" or os.environ.get("ECHELON_RUN_LOCAL_ENGINE") != "1":
        pytest.skip("set ECHELON_RUN_LOCAL_ENGINE=1 on a maintained macOS runner")
    engine = os.environ.get("ECHELON_LOCAL_ENGINE", "")
    if engine not in {"docker", "podman"}:
        pytest.skip("set ECHELON_LOCAL_ENGINE to docker or podman")
    return engine


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> None:
    _git(path, "init", "--initial-branch=main")
    _git(path, "config", "user.email", "local-runner@example.invalid")
    _git(path, "config", "user.name", "Local runner acceptance")


def _prepare_fixture(workspace: Path):
    from harness.coverage_contract import parse_coverage_obligations
    from harness.coverage_observation import write_coverage_observation
    from harness.local_runner_candidate import LocalCandidateRequest
    from harness.product_inventory import product_evidence_fingerprint
    from harness.runnability_contract import load_runnability_contract, runnability_contract_sha256
    from harness.test_execution_evidence import ObservedTestExecution
    from harness.verification_evidence import VerificationStage, write_verification_receipt

    fixture_root = Path(__file__).parents[1] / "fixtures" / "local-runner-browser-postgres"
    target = workspace / "sources" / "browser-game"
    target.parent.mkdir(parents=True)
    shutil.copytree(fixture_root, target)
    _init_repo(target)
    (target / "tests").mkdir()
    (target / "tests" / "journey.spec.ts").write_text(
        "test('persisted marker [echelon:E2E-001]', () => {});\n",
        encoding="utf-8",
    )
    _git(target, "add", ".")
    _git(target, "commit", "-m", "fixture candidate")
    candidate_commit = _git(target, "rev-parse", "HEAD")
    fingerprint = product_evidence_fingerprint(target)
    contract = load_runnability_contract(target)
    assert contract is not None

    stage = VerificationStage(
        name="sandbox-verify",
        command=("pnpm", "verify"),
        exit_code=0,
        duration_ms=1,
        stdout=b"passed\n",
        stderr=b"",
    )
    standard = write_verification_receipt(
        evidence_dir=workspace / "evidence" / "standard",
        spec_id="001-local-runner",
        strategy_id="default",
        build_id="build-local-runner",
        candidate_commit=candidate_commit,
        fingerprint_before=fingerprint,
        fingerprint_after=fingerprint,
        verifier_source="sandbox",
        stages=(stage,),
        attempt_sequence=1,
        sensitive_environment={},
    )
    observer = write_verification_receipt(
        evidence_dir=workspace / "evidence" / "observer",
        spec_id="001-local-runner",
        strategy_id="default",
        build_id="build-local-runner",
        candidate_commit=candidate_commit,
        fingerprint_before=fingerprint,
        fingerprint_after=fingerprint,
        verifier_source="sandbox",
        stages=(stage,),
        attempt_sequence=1,
        sensitive_environment={},
    )
    stack_hash = "a" * 64
    observer_hash = "b" * 64
    observation = write_coverage_observation(
        evidence_dir=workspace / "evidence" / "coverage",
        candidate_commit=candidate_commit,
        candidate_fingerprint=fingerprint,
        coverage_map_hash="acceptance-coverage-map",
        resolved_stack_hash=stack_hash,
        observer_plan_hash=observer_hash,
        runnability_contract_hash=runnability_contract_sha256(contract),
        verification_receipt=standard,
        observer_receipts={"playwright": observer},
        obligations=parse_coverage_obligations(
            "FR-001", "E2E-001", "e2e", "deferred-automation", "deferred-automation",
            "browser journey", "keep browser test", {"FR-001"},
        ),
        executions=(
            ObservedTestExecution(
                observer_id="playwright", test_type="e2e", file="tests/journey.spec.ts",
                title="persisted marker [echelon:E2E-001]", project="chromium",
                status="passed", retry_count=0,
            ),
        ),
        candidate_worktree=target,
        attempt_sequence=1,
        sensitive_environment={},
    )
    spec_dir = workspace / "specs" / "001-local-runner"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\ntargets:\n  - sources/browser-game\n---\n# Local runner acceptance\n",
        encoding="utf-8",
    )
    harness_root = workspace / "runs" / "targets" / "browser-game"
    build_id = "build-local-runner"
    build_root = harness_root / "runs" / build_id
    (build_root / "state").mkdir(parents=True)
    (harness_root / "runs" / ".current-build-001-local-runner").write_text(build_id + "\n")
    snapshot = {
        "schema_version": 1,
        "resolved_stack_hash": stack_hash,
        "observer_plan_hash": observer_hash,
        "resolved": {"runnability": {"local_runner": {
            "profiles": ["macos-compose-v1"],
            "allowed_services": ["postgres"],
            "environment_bindings": {
                "DATABASE_URL": "postgres_url",
                "TEST_DATABASE_URL": "postgres_url",
            },
        }}},
    }
    (build_root / "state" / "default.json").write_text(json.dumps({
        "spec_id": "001-local-runner", "strategy_id": "default", "status": "converged",
        "verified_commit": candidate_commit, "delivery_stack_snapshot": snapshot,
        "coverage_observation": {"status": "passed", "ref": observation.ref.as_mapping()},
    }))
    mirror = harness_root / "runs" / "mirror.git"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--bare", str(target), str(mirror)], check=True)
    return LocalCandidateRequest(
        workspace_root=workspace,
        target_root=target,
        spec_id="001-local-runner",
        target_id="browser-game",
        build_id=build_id,
    )


@pytest.mark.integration
@pytest.mark.macos_engine
@pytest.mark.slow
def test_macos_local_runner_browser_postgres(tmp_path: Path) -> None:
    engine = _require_enabled_macos_engine()
    from harness.local_runner import LocalRunnabilityRunner, LocalRunnerOptions, LocalVerificationRequest
    from harness.local_runner_candidate import resolve_effective_local_candidate

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _init_repo(workspace)
    request = _prepare_fixture(workspace)
    candidate = resolve_effective_local_candidate(request)
    result = LocalRunnabilityRunner().verify(
        LocalVerificationRequest(
            workspace_root=workspace,
            target_root=request.target_root,
            spec_id=request.spec_id,
            target_id=request.target_id,
            candidate_request=request,
            local_run_root=candidate.mirror_path.parent / candidate.build_id / "local-runs",
        ),
        LocalRunnerOptions(engine=engine, action_confirmed=True, keep_on_failure=False),
    )

    assert result.status == "passed", result.summary
    assert result.cleanup_complete is True
    assert result.attestation_path is not None
    artifact_root = os.environ.get("ECHELON_LOCAL_RUN_ARTIFACT_ROOT")
    if artifact_root:
        destination = Path(artifact_root)
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result.attestation_path, destination / result.attestation_path.name)
        markdown = result.attestation_path.with_suffix(".md")
        shutil.copy2(markdown, destination / markdown.name)
