# Authoritative Host Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Ralph autonomously verify and fulfill a candidate when the coding provider can implement it but cannot execute host-bound verification.

**Architecture:** The coding provider emits a typed verification-environment deferral. Ralph checkpoints the exact candidate, runs the configured or detected verifier, persists an immutable redacted receipt, and passes a validated read-only evidence reference into fulfillment. Fulfillment caching uses stable semantic evidence rather than volatile receipt metadata.

**Tech Stack:** Python 3.11+, pytest, Git worktrees, JSON receipts, SHA-256, Echelon Ralph/FulfillmentRunner, Prosaic/runtime Markdown contracts.

**Spec:** `docs/superpowers/specs/2026-08-31-authoritative-host-verification-design.md`

## Global Constraints

- Configured `verify_command` remains authoritative and takes priority over detection.
- Node detection prefers a non-placeholder `scripts.verify` over `scripts.test`.
- Only `blocker_kind=verification_environment` is recoverable; every other blocker remains terminal.
- Only deterministic Ralph code may create verification receipts.
- Fulfillment receives the exact receipt read-only and never receives write access to the delivery evidence tree.
- A verifier that mutates candidate product content fails verification.
- Persisted command and output text must be redacted; environment values must never be serialized.
- Requirement fulfillment still judges coverage; a green receipt does not automatically satisfy every requirement.

---

### Task 1: Prefer Comprehensive Node Verification

**Files:**
- Modify: `src/harness/verify_detection.py`
- Test: `tests/unit/test_verify_detection.py`

**Interfaces:**
- Consumes: `detect_verify_command(repo_path: Path) -> VerifyDetectionResult`.
- Produces: Node candidates with `command` set to `pnpm verify`, `yarn verify`, or `npm run verify` when `scripts.verify` is usable; existing `test` fallback otherwise.

- [ ] **Step 1: Write the failing detection tests**

```python
def test_prefers_pnpm_verify_over_test(self, tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run", "verify": "pnpm lint && pnpm test:e2e"}}),
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

    result = detect_verify_command(tmp_path)

    assert result.command == "pnpm verify"
    assert result.evidence == ["package.json scripts.verify"]


def test_falls_back_when_verify_is_placeholder(self, tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"verify": "echo no test specified && exit 1", "test": "vitest run"}}),
        encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")

    assert detect_verify_command(tmp_path).command == "npm test"
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/unit/test_verify_detection.py::TestVerifyCommandDetection::test_prefers_pnpm_verify_over_test tests/unit/test_verify_detection.py::TestVerifyCommandDetection::test_falls_back_when_verify_is_placeholder`

Expected: first test fails with `pnpm test`; second establishes the fallback contract.

- [ ] **Step 3: Implement the selection rule**

```python
verify_script = scripts.get("verify")
test_script = scripts.get("test")
script_name, script = (
    ("verify", verify_script)
    if _usable_node_script(verify_script)
    else ("test", test_script)
)
if not _usable_node_script(script):
    return None

if (repo / "pnpm-lock.yaml").exists():
    command = f"pnpm {script_name}"
elif (repo / "yarn.lock").exists():
    command = f"yarn {script_name}"
else:
    command = "npm test" if script_name == "test" else "npm run verify"
return _Candidate(command=command, evidence=f"package.json scripts.{script_name}")
```

- [ ] **Step 4: Verify GREEN and existing fallbacks**

Run: `uv run pytest -q tests/unit/test_verify_detection.py`

Expected: all verify-detection tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/verify_detection.py tests/unit/test_verify_detection.py
git commit -m "fix: prefer comprehensive node verification"
```

---

### Task 2: Add the Typed Verification-Deferral Contract

**Files:**
- Modify: `src/harness/build_result.py`
- Modify: `src/harness/ralph.py`
- Modify: `prosaic/commands/echelon.build.md`
- Modify: `runtime/workflow/phases/build-8-finalize.md`
- Test: `tests/unit/test_build_result.py`
- Test: `tests/unit/test_ralph_outer.py`

**Interfaces:**
- Consumes: build-status JSON and `BuildResult` normalization.
- Produces: `BuildResult.blocker_kind: str | None` and `_is_verification_environment_deferral(build_result: Mapping[str, object]) -> bool`.

- [ ] **Step 1: Write failing parsing and classification tests**

```python
def test_from_status_file_preserves_verification_environment_blocker(self, tmp_path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({
        "status": "blocked",
        "reason": "Chromium unavailable",
        "blocker_kind": "verification_environment",
    }))

    result = BuildResult.from_status_file(
        path, exit_code=0, stdout="", stderr="", duration_ms=10
    )

    assert result.status == "blocked"
    assert result.blocker_kind == "verification_environment"


def test_plain_blocker_is_not_verification_deferral():
    assert _is_verification_environment_deferral({
        "completion_marker_explicit": True,
        "build_status": "blocked",
        "blocker_kind": None,
    }) is False
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/unit/test_build_result.py::TestBuildResult::test_from_status_file_preserves_verification_environment_blocker tests/unit/test_ralph_outer.py -k verification_deferral`

Expected: missing `blocker_kind` field/helper failures.

- [ ] **Step 3: Implement typed parsing and Ralph propagation**

```python
@dataclass
class BuildResult:
    # existing fields...
    blocker_kind: Optional[str] = None


def _blocker_kind(data: dict[str, object]) -> str | None:
    raw = data.get("blocker_kind")
    if raw is None and isinstance(data.get("state_updates"), dict):
        raw = data["state_updates"].get("blocker_kind")
    value = str(raw or "").strip()
    return value or None


def _is_verification_environment_deferral(result: Mapping[str, object]) -> bool:
    return (
        result.get("completion_marker_explicit") is True
        and str(result.get("build_status") or "") == "blocked"
        and str(result.get("blocker_kind") or "") == "verification_environment"
    )
```

Add `blocker_kind` to both `_exec_build()` and `_exec_feedback()` result dictionaries. Update the build/finalize prose with the approved ALWAYS/NEVER pair and the exact JSON field.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest -q tests/unit/test_build_result.py tests/unit/test_ralph_outer.py -k 'verification_deferral or build_blocked'`

Expected: typed parsing passes and existing ordinary-blocker tests remain green.

- [ ] **Step 5: Commit**

```bash
git add src/harness/build_result.py src/harness/ralph.py prosaic/commands/echelon.build.md runtime/workflow/phases/build-8-finalize.md tests/unit/test_build_result.py tests/unit/test_ralph_outer.py
git commit -m "feat: classify verification environment deferrals"
```

---

### Task 3: Implement Immutable Verification Evidence

**Files:**
- Create: `src/harness/verification_evidence.py`
- Create: `tests/unit/test_verification_evidence.py`
- Modify: `src/harness/verify_result.py`
- Test: `tests/unit/test_verify_result.py`

**Interfaces:**
- Produces: `VerificationStage`, `VerificationEvidenceRef`, `write_verification_receipt(...)`, `validate_verification_receipt(...)`, and `redact_verification_text(...)`.
- Produces: `VerifyResult.verification_evidence: Dict[str, Any]` for transport through existing gates.

- [ ] **Step 1: Write failing receipt, immutability, validation, and redaction tests**

```python
def test_writes_immutable_redacted_receipt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://user:secret@localhost/db")
    ref = write_verification_receipt(
        evidence_dir=tmp_path,
        spec_id="003-demo",
        strategy_id="default",
        build_id="build-1",
        candidate_commit="a" * 40,
        fingerprint_before="b" * 64,
        fingerprint_after="b" * 64,
        verifier_source="configured",
        stages=[VerificationStage(
            name="verify",
            command=("pnpm", "verify"),
            exit_code=0,
            duration_ms=12,
            stdout=b"connected postgres://user:secret@localhost/db\n4 passed",
            stderr=b"Authorization: Bearer abc.def.ghi",
        )],
        attempt_sequence=1,
        sensitive_environment=os.environ,
    )

    payload = json.loads(ref.path.read_text())
    serialized = json.dumps(payload)
    assert "user:secret" not in serialized
    assert "abc.def.ghi" not in serialized
    assert payload["status"] == "passed"
    assert validate_verification_receipt(ref, candidate_commit="a" * 40,
        candidate_fingerprint="b" * 64).valid is True


def test_candidate_mutation_produces_failed_receipt(tmp_path: Path) -> None:
    ref = _write_fixture_receipt(tmp_path, before="a" * 64, after="b" * 64)
    assert ref.passed is False
    assert json.loads(ref.path.read_text())["failure_id"] == "candidate_mutated_during_verification"


def test_timestamp_only_changes_keep_stable_evidence_digest(tmp_path: Path) -> None:
    first = _write_fixture_receipt(tmp_path, sequence=1, started_at="2026-08-31T00:00:00Z")
    second = _write_fixture_receipt(tmp_path, sequence=2, started_at="2026-08-31T00:01:00Z")
    assert first.receipt_sha256 != second.receipt_sha256
    assert first.evidence_sha256 == second.evidence_sha256


def _write_fixture_receipt(
    root: Path,
    *,
    before: str = "b" * 64,
    after: str = "b" * 64,
    sequence: int = 1,
    started_at: str = "2026-08-31T00:00:00Z",
) -> VerificationEvidenceRef:
    return write_verification_receipt(
        evidence_dir=root,
        spec_id="003-demo",
        strategy_id="default",
        build_id="build-1",
        candidate_commit="a" * 40,
        fingerprint_before=before,
        fingerprint_after=after,
        verifier_source="configured",
        stages=[VerificationStage(
            name="verify",
            command=("python", "-c", "print('passed')"),
            exit_code=0,
            duration_ms=12,
            stdout=b"passed\n",
            stderr=b"",
        )],
        attempt_sequence=sequence,
        sensitive_environment={},
        started_at=started_at,
    )
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/unit/test_verification_evidence.py tests/unit/test_verify_result.py`

Expected: module/types do not exist.

- [ ] **Step 3: Implement the evidence model and atomic writer**

```python
@dataclass(frozen=True)
class VerificationStage:
    name: str
    command: tuple[str, ...]
    exit_code: int
    duration_ms: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class VerificationEvidenceRef:
    path: Path
    receipt_sha256: str
    evidence_sha256: str
    candidate_commit: str
    candidate_fingerprint: str
    passed: bool


def validate_verification_receipt(
    ref: VerificationEvidenceRef,
    *,
    candidate_commit: str,
    candidate_fingerprint: str,
) -> VerificationReceiptValidation:
    # Reject symlinks/path escape, verify canonical receipt digest, authority,
    # pass status, candidate identity, and latest-pointer target/digest.
```

Use `hmac.compare_digest` for digest comparisons, `harness.durable_json.write_json_atomic()` for `latest.json`, a 64 KiB tail limit, and per-attempt `O_EXCL` creation so an existing attempt cannot be overwritten. Accept an optional `started_at` injection for deterministic tests. Extend `VerifyResult.from_dict()` to preserve the optional evidence mapping, and give `VerificationEvidenceRef` an `as_mapping()` serializer containing the exact path and both digests.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest -q tests/unit/test_verification_evidence.py tests/unit/test_verify_result.py`

Expected: receipt, redaction, mutation, pointer, tamper, and stable-digest tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/verification_evidence.py src/harness/verify_result.py tests/unit/test_verification_evidence.py tests/unit/test_verify_result.py
git commit -m "feat: persist authoritative verification evidence"
```

---

### Task 4: Make Ralph Execute, Bind, and Repair from Host Evidence

**Files:**
- Modify: `src/harness/ralph.py`
- Test: `tests/unit/test_ralph_outer.py`

**Interfaces:**
- Consumes: `VerificationStage`, `write_verification_receipt()`, typed deferrals.
- Produces: `_checkpoint_verification_deferred_candidate(...) -> str`, receipt-bearing `VerifyResult`, and identical outer/inner deferral behavior.

- [ ] **Step 1: Write failing outer-loop, repair-loop, checkpoint, and mutation tests**

```python
def test_outer_verification_deferral_runs_host_verify_and_fulfillment(tmp_path: Path):
    build_runner = MagicMock(spec=LlmBuildRunner)
    fulfillment = MagicMock(spec=FulfillmentRunner)
    controller, _provider, gitops, _state = _make_controller(
        tmp_path,
        mode="banzai",
        llm_build_runner=build_runner,
        fulfillment_runner=fulfillment,
    )
    worktree = tmp_path / "worktree"
    _init_git_repo(worktree)
    (worktree / "README.md").write_text("candidate\n", encoding="utf-8")
    _commit_all(worktree)
    gitops.base_dir = worktree
    gitops.create_worktree.return_value = str(worktree)
    build_runner.exec_build.return_value = BuildResult(
        exit_code=0, status="blocked", blocker_kind="verification_environment",
        reason="Chromium unavailable", impasse_file=None,
        stdout="", stderr="", duration_ms=1,
    )
    receipt = _write_passing_test_receipt(tmp_path, worktree)
    controller._exec_verify_locally = MagicMock(return_value=VerifyResult(
        passed=True,
        failures=[],
        verification_evidence=receipt.as_mapping(),
    ))

    result = controller.run_loop(max_outer=1)

    controller._exec_verify_locally.assert_called_once()
    fulfillment.refresh.assert_called_once()
    assert result.termination_reason != "build_blocked"


def test_plain_blocker_still_stops_before_host_verify(tmp_path: Path):
    build_runner = MagicMock(spec=LlmBuildRunner)
    controller, _provider, gitops, _state = _make_controller(
        tmp_path, mode="banzai", llm_build_runner=build_runner
    )
    worktree = tmp_path / "worktree"
    _init_git_repo(worktree)
    (worktree / "README.md").write_text("candidate\n", encoding="utf-8")
    _commit_all(worktree)
    gitops.base_dir = worktree
    gitops.create_worktree.return_value = str(worktree)
    build_runner.exec_build.return_value = BuildResult(
        exit_code=0, status="blocked", blocker_kind=None,
        reason="requirements ambiguous", impasse_file=None,
        stdout="", stderr="", duration_ms=1,
    )
    controller._exec_verify_locally = MagicMock()

    result = controller.run_loop(max_outer=1)

    assert result.termination_reason == "build_blocked"
    controller._exec_verify_locally.assert_not_called()


def test_feedback_verification_deferral_returns_to_host_verify(tmp_path: Path):
    controller, build_runner, fulfillment, worktree = _prepared_deferral_controller(
        tmp_path
    )
    build_runner.exec_build.return_value = BuildResult(
        exit_code=0, status="done", impasse_file=None,
        stdout="", stderr="", duration_ms=1,
    )
    build_runner.exec_feedback.return_value = BuildResult(
        exit_code=0, status="blocked", blocker_kind="verification_environment",
        reason="Postgres unavailable", impasse_file=None,
        stdout="", stderr="", duration_ms=1,
    )
    controller._exec_verify_locally.side_effect = [
        VerifyResult(passed=False, failures=[FailureEntry(
            FailureCategory.TEST, "journey", "journey failed"
        )]),
        VerifyResult(passed=True, failures=[]),
    ]

    result = controller.run_loop(max_outer=1, max_inner=1)

    assert controller._exec_verify_locally.call_count == 2
    assert result.termination_reason != "inner_build_blocked"


def _write_passing_test_receipt(
    root: Path, worktree: Path
) -> VerificationEvidenceRef:
    fingerprint = _safe_product_evidence_fingerprint(worktree)
    return write_verification_receipt(
        evidence_dir=root / "evidence" / "default",
        spec_id="spec-001",
        strategy_id="default",
        build_id="run-1",
        candidate_commit=_current_git_commit(worktree) or "",
        fingerprint_before=fingerprint,
        fingerprint_after=fingerprint,
        verifier_source="configured",
        stages=[VerificationStage(
            name="verify", command=(sys.executable, "-c", "pass"),
            exit_code=0, duration_ms=1, stdout=b"", stderr=b"",
        )],
        attempt_sequence=1,
        sensitive_environment={},
    )


def _prepared_deferral_controller(tmp_path: Path):
    build_runner = MagicMock(spec=LlmBuildRunner)
    fulfillment = MagicMock(spec=FulfillmentRunner)
    controller, _provider, gitops, _state = _make_controller(
        tmp_path,
        mode="banzai",
        llm_build_runner=build_runner,
        fulfillment_runner=fulfillment,
    )
    worktree = tmp_path / "worktree"
    _init_git_repo(worktree)
    (worktree / "README.md").write_text("candidate\n", encoding="utf-8")
    _commit_all(worktree)
    gitops.base_dir = worktree
    gitops.create_worktree.return_value = str(worktree)
    receipt = _write_passing_test_receipt(tmp_path, worktree)
    controller._exec_verify_locally = MagicMock(return_value=VerifyResult(
        passed=True, failures=[], verification_evidence=receipt.as_mapping()
    ))
    return controller, build_runner, fulfillment, worktree
```

Add a checkpoint test that makes one tracked file dirty, calls `_checkpoint_verification_deferred_candidate()`, asserts `gitops.commit()` was invoked, and asserts the state store's completed-task count is unchanged.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/unit/test_ralph_outer.py -k 'verification_deferral or ordinary_blocker'`

Expected: typed deferral still terminates as `build_blocked`.

- [ ] **Step 3: Implement the shared deferral path**

```python
def _checkpoint_verification_deferred_candidate(
    self, worktree_path: str, *, outer_iter: int, inner_iter: int, phase: str
) -> str:
    if self._has_non_verify_worktree_changes(worktree_path):
        commit = self._gitops.commit(
            worktree_path,
            build_echelon_commit_message(
                f"harness-checkpoint: {self._spec_id}/{self._strategy_id} "
                f"iter-{outer_iter} {phase} verification-deferred",
                EchelonCommitMetadata(
                    origin="delivery", action="checkpoint", spec_id=self._spec_id,
                    run_id=self._build_id, phase=phase, strategy=self._strategy_id,
                ),
            ),
        )
        return commit
    return _current_git_commit(Path(worktree_path)) or ""
```

Refactor outer and inner blocker branches to call one helper. If typed, checkpoint then continue to `_exec_verify`; if ordinary, preserve the existing terminal behavior. Refactor `_exec_verify_locally()` so every configured/detected stage produces `VerificationStage`, compares product fingerprints before/after, writes the receipt under `self._state_store.state_dir.parent / "evidence" / self._strategy_id`, and attaches the reference mapping to `VerifyResult.verification_evidence`.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest -q tests/unit/test_ralph_outer.py -k 'verification_deferral or build_blocked or verify_locally or candidate_mutated'`

Expected: typed outer/inner deferrals reach host verification; ordinary blockers stop; mutations fail.

- [ ] **Step 5: Commit**

```bash
git add src/harness/ralph.py tests/unit/test_ralph_outer.py
git commit -m "feat: recover provider verification deferrals"
```

---

### Task 5: Feed Trusted Evidence into Fulfillment with Narrow Writes

**Files:**
- Modify: `src/harness/fulfillment_runner.py`
- Modify: `src/harness/ralph.py`
- Test: `tests/unit/test_fulfillment_runner.py`
- Test: `tests/unit/test_ralph_outer.py`

**Interfaces:**
- Consumes: `VerifyResult.verification_evidence`.
- Produces: `FulfillmentRunner.refresh(..., verification_evidence: Mapping[str, object] | None = None)` and receipt-aware cache/ledger inputs.

- [ ] **Step 1: Write failing validation, permissions, and cache tests**

```python
def test_target_scoped_refresh_grants_receipt_read_only(tmp_path: Path):
    receipt = _write_passing_fulfillment_receipt(tmp_path)
    provider = object.__new__(AICodingCliProvider)
    provider._cli = "codex"
    provider.last_stdout = ""
    provider.last_stderr = ""
    provider.run_prompt_result = MagicMock(return_value=MagicMock(exit_code=0))

    FulfillmentRunner(provider).refresh(
        str(tmp_path / "worktree"), "spec-001",
        spec_dir=tmp_path / "specs" / "spec-001-demo",
        orchestration_root=tmp_path,
        verification_evidence=receipt.as_mapping(),
    )

    metadata = provider.run_prompt_result.call_args.kwargs["request_metadata"]["prompt_metadata"]
    assert str(receipt.path.parent) in metadata["tool_read_roots"]
    assert str(receipt.path.parent) not in metadata["tool_write_paths"]
    assert str((tmp_path / "runs").resolve()) not in metadata["tool_write_paths"]


def test_tampered_or_stale_receipt_fails_before_provider(tmp_path: Path):
    receipt = _write_passing_fulfillment_receipt(tmp_path)
    receipt.path.write_text("{}", encoding="utf-8")
    provider = object.__new__(AICodingCliProvider)
    provider._cli = "codex"
    provider.last_stdout = ""
    provider.last_stderr = ""
    provider.run_prompt_result = MagicMock()

    result = FulfillmentRunner(provider).refresh(
        str(tmp_path), "spec-001", verification_evidence=receipt.as_mapping()
    )

    assert result.status == "failed"
    assert "verification evidence" in result.reason
    provider.run_prompt_result.assert_not_called()


def _write_passing_fulfillment_receipt(root: Path) -> VerificationEvidenceRef:
    return write_verification_receipt(
        evidence_dir=root / "runs" / "build-1" / "evidence" / "default",
        spec_id="spec-001",
        strategy_id="default",
        build_id="build-1",
        candidate_commit="a" * 40,
        fingerprint_before="b" * 64,
        fingerprint_after="b" * 64,
        verifier_source="configured",
        stages=[VerificationStage(
            name="verify", command=("pnpm", "verify"), exit_code=0,
            duration_ms=1, stdout=b"passed\n", stderr=b"",
        )],
        attempt_sequence=1,
        sensitive_environment={},
        started_at="2026-08-31T00:00:00Z",
    )
```

Add a cache-key test that writes sequence 1 and sequence 2 receipts with different `started_at` values, asserts the second refresh is a cache hit, then changes stage exit/output content and asserts a provider call occurs.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/unit/test_fulfillment_runner.py -k 'verification_evidence or receipt_read_only or stable_evidence'`

Expected: `refresh()` rejects the new keyword or broad `runs` write permission remains visible.

- [ ] **Step 3: Implement receipt validation and preallocated write scope**

```python
def refresh(
    self,
    worktree_path: str,
    spec_id: str,
    *,
    verification_evidence: Mapping[str, object] | None = None,
    # existing keyword arguments...
) -> FulfillmentRefreshResult:
    evidence = _validated_verification_evidence(
        verification_evidence,
        worktree=Path(worktree_path),
    )
    if verification_evidence is not None and evidence is None:
        return FulfillmentRefreshResult(
            status="failed", exit_code=2,
            reason="verification evidence is invalid or stale",
        )
```

Allocate the verify-spec run directory deterministically before provider dispatch. Change `_exec_verify_spec_prompt()` to grant that exact directory rather than `workspace_root / "runs"`. Add the receipt parent only to read roots. Append the exact receipt path/digest to the prompt arguments and incorporate `evidence.evidence_sha256` into `_verify_cache_key()` and verified-ledger construction.

Update `RalphController._refresh_fulfillment_report()` to pass the evidence mapping only after local verification succeeds.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest -q tests/unit/test_fulfillment_runner.py tests/unit/test_ralph_outer.py -k 'verification_evidence or receipt or fulfillment_refresh'`

Expected: stale/tampered evidence fails closed, permissions do not overlap, and semantic cache behavior passes.

- [ ] **Step 5: Commit**

```bash
git add src/harness/fulfillment_runner.py src/harness/ralph.py tests/unit/test_fulfillment_runner.py tests/unit/test_ralph_outer.py
git commit -m "feat: consume trusted host verification evidence"
```

---

### Task 6: Prove Autonomous Convergence End to End

**Files:**
- Modify: `tests/integration/test_polyrepo_delivery_convergence.py`
- Modify: `tests/integration/test_brownfield_fixture_detection.py`
- Modify: `runtime/config-template.yml` only if the existing verification comments inaccurately describe the new authority boundary.

**Interfaces:**
- Consumes: complete typed-deferral, host-receipt, and fulfillment flow.
- Produces: a deterministic smoke fixture that converges without browser, database, Docker, network, or manual debt acceptance.

- [ ] **Step 1: Write the failing convergence test**

```python
def test_provider_verification_environment_deferral_converges_via_ralph(tmp_path: Path):
    target, _initial_commit = _target_checkout(tmp_path)
    target.joinpath("package.json").write_text(json.dumps({
        "scripts": {
            "test": "python -c 'raise SystemExit(9)'",
            "verify": "python scripts/verify_journey.py",
        }
    }), encoding="utf-8")
    target.joinpath("scripts").mkdir()
    target.joinpath("scripts/verify_journey.py").write_text(
        "print('five-stage journey passed')\n", encoding="utf-8"
    )
    _git(target, "add", ".")
    _git(target, "commit", "-m", "add browser journey")

    build_runner = MagicMock(spec=LlmBuildRunner)
    build_runner.exec_build.return_value = BuildResult(
        exit_code=0,
        status="blocked",
        blocker_kind="verification_environment",
        reason="Chromium unavailable in coding sandbox",
        impasse_file=None,
        stdout="",
        stderr="",
        duration_ms=1,
    )
    controller, fulfillment, state_store = _real_ralph_for_target(
        tmp_path, target, build_runner
    )

    result = controller.run_loop(max_outer=1, max_inner=1, build_prompt="finish")

    assert result.status == "verified"
    assert result.termination_reason == "success"
    latest = json.loads(next(
        (state_store.state_dir.parent / "evidence" / "default").glob("*/receipt.json")
    ).read_text(encoding="utf-8"))
    assert latest["status"] == "passed"
    assert fulfillment.refresh.call_args.kwargs["verification_evidence"]["passed"] is True
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/integration/test_polyrepo_delivery_convergence.py -k verification_environment_deferral`

Expected: delivery stops as `build_blocked` or lacks receipt evidence.

- [ ] **Step 3: Complete fixture wiring and runtime documentation**

Add `_real_ralph_for_target()` directly to this integration module. It must instantiate the real `RalphController`, `StateStore`, `ModeController("banzai")`, and `EscalationHandler`; configure `gitops.create_worktree`/`base_dir` to the initialized target; and use a `FulfillmentRunner` whose `AICodingCliProvider.run_prompt_result` is faked only to write the matching report and return exit code 0. Do not mock `_exec_verify_locally()`, receipt writing/validation, verification detection, blocker branching, checkpointing, or fulfillment permission construction. Keep the deliberately failing `test` script so the assertion can only pass when `verify` was selected.

- [ ] **Step 4: Run focused and affected regression suites**

Run:

```bash
uv run pytest -q \
  tests/unit/test_verify_detection.py \
  tests/unit/test_build_result.py \
  tests/unit/test_verify_result.py \
  tests/unit/test_verification_evidence.py \
  tests/unit/test_fulfillment_runner.py \
  tests/unit/test_ralph_outer.py \
  tests/integration/test_polyrepo_delivery_convergence.py \
  tests/integration/test_brownfield_fixture_detection.py
```

Expected: all selected tests pass with zero failures.

- [ ] **Step 5: Run repository verification appropriate to the changed surfaces**

Run: `uv run pytest -q -m 'unit or integration'`

Expected: zero failures. If unrelated pre-existing failures remain on the merged baseline, record their exact test IDs and rerun every directly affected file successfully; do not claim the whole suite is green.

- [ ] **Step 6: Install the edited CLI and replay the browser smoke delivery**

Run:

```bash
bash scripts/install.sh
cd /Users/michalbachorik/work/browser-3d-game-stack-smoke
echelon workspace migrate-to-prosaic
echelon delivery run 003-create-browser-first-3d --mode banzai
```

Expected: Ralph selects `pnpm verify`, a provider-local Chromium limitation defers to Ralph, a passing host receipt reaches fulfillment, and delivery no longer stops solely on `verification_environment`. Any real verifier failure remains actionable and must not be reclassified as success.

- [ ] **Step 7: Commit final integration coverage**

```bash
git add tests/integration/test_polyrepo_delivery_convergence.py tests/integration/test_brownfield_fixture_detection.py runtime/config-template.yml
git commit -m "test: prove autonomous host verification convergence"
```
