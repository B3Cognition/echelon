"""Tests for content-authoritative local-verification candidates."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness.coverage_contract import parse_coverage_obligations
from harness.coverage_observation import write_coverage_observation
from harness.local_runner_candidate import (
    LocalCandidateError,
    LocalCandidateRequest,
    materialize_local_candidate,
    resolve_effective_local_candidate,
)
from harness.product_inventory import product_evidence_fingerprint
from harness.runnability_contract import (
    load_runnability_contract,
    runnability_contract_sha256,
)
from harness.test_execution_evidence import ObservedTestExecution
from harness.verification_evidence import VerificationStage, write_verification_receipt


_STACK_HASH = "a" * 64
_OBSERVER_PLAN_HASH = "b" * 64


_CONTRACT = """\
schema_version: 1
enabled: true
install_commands: []
bootstrap_commands: []
start_commands: ["pnpm start"]
readiness:
  url: http://127.0.0.1:4173/health
  timeout_ms: 30000
primary_journey:
  kind: browser
  url: http://127.0.0.1:4173/
  requirements: [FR-001]
  real_services_required: [web]
  steps:
    - action: goto
      path: /
  observations:
    - id: scene-visible
      kind: browser_dom
      selector: "#scene"
      expectation: visible
stop_commands: ["pnpm stop"]
"""


@dataclass(frozen=True)
class _Fixture:
    workspace: Path
    target: Path
    mirror: Path
    build_id: str
    build_commit: str
    landed_commit: str

    def request(self) -> LocalCandidateRequest:
        return LocalCandidateRequest(
            workspace_root=self.workspace,
            target_root=self.target,
            spec_id="003-local-demo",
            target_id="browser-3d-game",
        )


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
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "--initial-branch=main")
    _git(path, "config", "user.email", "test@example.invalid")
    _git(path, "config", "user.name", "Test")


def _commit(path: Path, message: str) -> str:
    _git(path, "add", ".")
    _git(path, "commit", "-m", message)
    return _git(path, "rev-parse", "HEAD")


def _write_fixture(
    tmp_path: Path,
    *,
    changed_landed_product: bool = False,
    observer_plan_hash: str = _OBSERVER_PLAN_HASH,
) -> _Fixture:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "sources" / "browser-3d-game"
    _init_repo(target)
    spec_dir = workspace / "specs" / "003-local-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: landed\ntargets:\n  - sources/browser-3d-game\n---\n# Demo\n",
        encoding="utf-8",
    )
    (target / ".echelon").mkdir()
    (target / ".echelon" / "runnability.yml").write_text(_CONTRACT, encoding="utf-8")
    (target / "README.md").write_text("# Browser game\n", encoding="utf-8")
    test_path = target / "tests" / "journey.spec.ts"
    test_path.parent.mkdir()
    test_path.write_text(
        "test('persisted world [echelon:E2E-001]', () => {});\n",
        encoding="utf-8",
    )
    build_commit = _commit(target, "verified candidate")
    fingerprint = product_evidence_fingerprint(target)
    contract = load_runnability_contract(target)
    assert contract is not None
    stage = VerificationStage(
        name="verify",
        command=("pnpm", "verify"),
        exit_code=0,
        duration_ms=1,
        stdout=b"passed\n",
        stderr=b"",
    )
    standard = write_verification_receipt(
        evidence_dir=tmp_path / "evidence" / "standard",
        spec_id="003-local-demo",
        strategy_id="default",
        build_id="build-local-demo",
        candidate_commit=build_commit,
        fingerprint_before=fingerprint,
        fingerprint_after=fingerprint,
        verifier_source="sandbox",
        stages=(stage,),
        attempt_sequence=1,
        sensitive_environment={},
    )
    observer = write_verification_receipt(
        evidence_dir=tmp_path / "evidence" / "observer",
        spec_id="003-local-demo",
        strategy_id="default",
        build_id="build-local-demo",
        candidate_commit=build_commit,
        fingerprint_before=fingerprint,
        fingerprint_after=fingerprint,
        verifier_source="sandbox",
        stages=(stage,),
        attempt_sequence=1,
        sensitive_environment={},
    )
    observation = write_coverage_observation(
        evidence_dir=tmp_path / "evidence" / "coverage",
        candidate_commit=build_commit,
        candidate_fingerprint=fingerprint,
        coverage_map_hash="coverage-map",
        resolved_stack_hash=_STACK_HASH,
        observer_plan_hash=_OBSERVER_PLAN_HASH,
        runnability_contract_hash=runnability_contract_sha256(contract),
        verification_receipt=standard,
        observer_receipts={"playwright": observer},
        obligations=parse_coverage_obligations(
            "FR-001",
            "E2E-001",
            "e2e",
            "deferred-automation",
            "deferred-automation",
            "browser journey",
            "keep browser test",
            {"FR-001"},
        ),
        executions=(
            ObservedTestExecution(
                observer_id="playwright",
                test_type="e2e",
                file="tests/journey.spec.ts",
                title="persisted world [echelon:E2E-001]",
                project="chromium",
                status="passed",
                retry_count=0,
            ),
        ),
        candidate_worktree=target,
        attempt_sequence=1,
        sensitive_environment={},
    )
    if changed_landed_product:
        (target / "README.md").write_text("# Changed product\n", encoding="utf-8")
        landed_commit = _commit(target, "changed landing")
    else:
        _git(target, "commit", "--allow-empty", "-m", "merge-only landing")
        landed_commit = _git(target, "rev-parse", "HEAD")

    harness_root = workspace / "runs" / "targets" / "browser-3d-game"
    build_id = "build-local-demo"
    build_root = harness_root / "runs" / build_id
    state_dir = build_root / "state"
    state_dir.mkdir(parents=True)
    (harness_root / "runs" / ".current-build-003-local-demo").write_text(
        build_id + "\n", encoding="utf-8"
    )
    snapshot = {
        "schema_version": 1,
        "resolved": {"runnability": {"local_runner": {"profiles": ["macos-compose-v1"]}}},
        "resolved_stack_hash": _STACK_HASH,
        "observer_plan_hash": observer_plan_hash,
    }
    (state_dir / "default.json").write_text(
        json.dumps(
            {
                "spec_id": "003-local-demo",
                "strategy_id": "default",
                "status": "converged",
                "verified_commit": build_commit,
                "delivery_stack_snapshot": snapshot,
                "coverage_observation": {
                    "status": "passed",
                    "ref": observation.ref.as_mapping(),
                },
            }
        ),
        encoding="utf-8",
    )
    mirror = harness_root / "runs" / "mirror.git"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", str(target), str(mirror)],
        check=True,
        capture_output=True,
        text=True,
    )
    return _Fixture(workspace, target, mirror, build_id, build_commit, landed_commit)


@pytest.mark.unit
def test_resolve_effective_candidate_uses_landed_merge_commit_when_content_matches(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path)

    candidate = resolve_effective_local_candidate(fixture.request())

    assert candidate.sandbox_candidate_commit == fixture.build_commit
    assert candidate.effective_candidate_commit == fixture.landed_commit
    assert candidate.product_fingerprint == product_evidence_fingerprint(fixture.target)

    destination = (
        fixture.mirror.parent / fixture.build_id / "local-runs" / "test" / "candidate"
    )
    try:
        materialize_local_candidate(candidate, destination)
        assert _git(destination, "rev-parse", "HEAD") == fixture.landed_commit
    finally:
        _git(fixture.mirror, "worktree", "remove", "--force", str(destination))


@pytest.mark.unit
def test_resolve_effective_candidate_rejects_changed_landed_product(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path, changed_landed_product=True)

    with pytest.raises(LocalCandidateError, match="product fingerprint is stale"):
        resolve_effective_local_candidate(fixture.request())


@pytest.mark.unit
def test_resolve_effective_candidate_rejects_changed_landed_observer_plan(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path, observer_plan_hash="c" * 64)

    with pytest.raises(LocalCandidateError, match="observer plan hash mismatch"):
        resolve_effective_local_candidate(fixture.request())
