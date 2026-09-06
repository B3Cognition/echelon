# Banzai Protocol-Upgrade Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow one bounded Banzai WHY2 reassessment after a legacy run's deployed candidate protocol is refreshed, while preserving the human gate for every other case.

**Architecture:** A pure helper fingerprints the three deployed workspace artifacts that define candidate behavior. The state store converts a legacy v1 reassessment record to a v2 audit ledger in the same compare-and-swap transaction that clears the eligible decision. Controller and CLI consult the helper only for that exact v1 legacy state; all other recovery paths retain their present behavior.

**Tech Stack:** Python 3.12, pathlib, hashlib, existing SquadStateStore file-lock/CAS transactions, pytest.

**Spec:** docs/superpowers/specs/2026-09-06-banzai-protocol-upgrade-retry-design.md

## Global Constraints

- Fingerprint exactly .echelon/runtime/workflow/definition.yaml, .echelon/runtime/workflow/phases/phase1-why2.md, and .echelon/prosaic/subagents/echelon.sage.md in sorted path order.
- Accept only readable regular files no larger than 1 MiB; unavailable evidence must fail closed without state mutation or agent dispatch.
- Allow exactly one migration recovery: v1 reassessment record to v2 ledger; never retry a v2 record.
- Restrict the route to intact Banzai phase1-why2 provider-escalation decisions governed by the existing policy checks.
- Do not auto-refresh a workspace, change candidate eligibility, alter prompts, or modify semi/guided recovery behavior.

---

## File Structure

| File | Responsibility |
| --- | --- |
| src/harness/banzai_protocol.py | Pure, fail-closed deployed-artifact fingerprint and diagnostic result. |
| src/harness/squad_state.py | Strict v1/v2 reassessment-ledger validation and atomic v1-to-v2 retry transition. |
| src/harness/squad.py | Controller eligibility check, active-workspace fingerprint lookup, and transition invocation. |
| src/echelon/cli.py | Recovery presentation for available, unavailable, and consumed upgrade retry states. |
| tests/unit/test_banzai_protocol.py | Byte-level fingerprint and fail-closed filesystem tests. |
| tests/kernel/test_squad_state.py | Ledger schema, atomic transition, and no-second-retry state tests. |
| tests/integration/test_human_input_routing.py | Controller routing and ordinary-flow non-regression tests. |
| tests/unit/test_cli_continue.py | User-facing recovery command classification tests. |

### Task 1: Deployed candidate-protocol fingerprint

**Files:**
- Create: src/harness/banzai_protocol.py
- Create: tests/unit/test_banzai_protocol.py

**Interfaces:**
- Produces: BanzaiProtocolFingerprint with fingerprint: str | None and diagnostic: str.
- Produces: active_banzai_default_protocol_fingerprint(project_root: Path) -> BanzaiProtocolFingerprint.
- Consumes: a workspace root; does not read or mutate squad state.

- [ ] **Step 1: Write the failing tests**

~~~python
def test_active_protocol_fingerprint_is_stable_and_path_bound(tmp_path: Path) -> None:
    _write_protocol_bundle(tmp_path, why2="first")
    first = active_banzai_default_protocol_fingerprint(tmp_path)
    _write_protocol_bundle(tmp_path, why2="second")
    second = active_banzai_default_protocol_fingerprint(tmp_path)

    assert first.fingerprint is not None
    assert first.fingerprint != second.fingerprint
    assert second.diagnostic == ""


@pytest.mark.parametrize("kind", ["missing", "directory", "oversized"])
def test_active_protocol_fingerprint_fails_closed(tmp_path: Path, kind: str) -> None:
    _write_protocol_bundle(tmp_path)
    _break_protocol_bundle(tmp_path, kind)

    result = active_banzai_default_protocol_fingerprint(tmp_path)

    assert result.fingerprint is None
    assert "phase1-why2.md" in result.diagnostic
~~~

- [ ] **Step 2: Run the new tests to verify failure**

Run: `uv run --extra dev pytest tests/unit/test_banzai_protocol.py -q`

Expected: FAIL because `harness.banzai_protocol` does not exist.

- [ ] **Step 3: Write the minimal helper**

~~~python
@dataclass(frozen=True)
class BanzaiProtocolFingerprint:
    fingerprint: str | None
    diagnostic: str = ""


def active_banzai_default_protocol_fingerprint(
    project_root: Path,
) -> BanzaiProtocolFingerprint:
    digest = hashlib.sha256()
    for relative_path in _PROTOCOL_PATHS:
        path = project_root / relative_path
        try:
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_BYTES:
                return BanzaiProtocolFingerprint(None, f"{relative_path}: not a readable regular file")
            payload = path.read_bytes()
        except OSError as exc:
            return BanzaiProtocolFingerprint(None, f"{relative_path}: {exc.strerror or 'unreadable'}")
        if len(payload) > _MAX_BYTES:
            return BanzaiProtocolFingerprint(None, f"{relative_path}: exceeds 1 MiB")
        digest.update(relative_path.encode("utf-8") + b"\\0")
        digest.update(len(payload).to_bytes(8, "big") + payload)
    return BanzaiProtocolFingerprint(f"sha256:{digest.hexdigest()}")
~~~

Use `lstat()` and `stat.S_ISREG` so the helper rejects symlinks. Check size before and after read so a file that changes during inspection cannot bypass the 1 MiB limit.

- [ ] **Step 4: Run the fingerprint tests to verify success**

Run: `uv run --extra dev pytest tests/unit/test_banzai_protocol.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the isolated helper**

~~~bash
git add src/harness/banzai_protocol.py tests/unit/test_banzai_protocol.py
git commit -m "feat: fingerprint deployed Banzai candidate protocol"
~~~

### Task 2: Strict v2 ledger and atomic upgrade transition

**Files:**
- Modify: src/harness/squad_state.py:330-373 and 2637-2721
- Modify: tests/kernel/test_squad_state.py

**Interfaces:**
- Consumes: validated v1 banzai_default_reassessment, active decision ID, expected state revision, and a `sha256:` prefix followed by exactly 64 lower-case hexadecimal characters.
- Produces: SquadStateStore.reassess_awaiting_banzai_why2_after_protocol_upgrade(decision_id: str, *, protocol_fingerprint: str, expected_state_revision: int) -> dict[str, Any].
- Produces: schema-v2 ledger with initial_attempt and upgrade_attempt mappings; generic state updates cannot mutate either version.

- [ ] **Step 1: Write failing state-store tests**

~~~python
def test_protocol_upgrade_reassessment_replaces_v1_with_v2_ledger(
    store: SquadStateStore,
) -> None:
    _write_intact_banzai_why2_state_with_v1_marker(store)
    before = store.load()

    after = store.reassess_awaiting_banzai_why2_after_protocol_upgrade(
        "dec-current",
        protocol_fingerprint="sha256:" + "a" * 64,
        expected_state_revision=before["state_revision"],
    )

    assert after["status"] == "running"
    assert after["banzai_default_reassessment"]["schema_version"] == 2
    assert (
        after["banzai_default_reassessment"]["upgrade_attempt"]["protocol_fingerprint"]
        == "sha256:" + "a" * 64
    )


def test_protocol_upgrade_reassessment_rejects_second_attempt(
    store: SquadStateStore,
) -> None:
    _write_intact_banzai_why2_state_with_v2_marker(store)

    with pytest.raises(StateAdvanceError, match="already consumed"):
        store.reassess_awaiting_banzai_why2_after_protocol_upgrade(
            "dec-current",
            protocol_fingerprint="sha256:" + "a" * 64,
            expected_state_revision=store.load()["state_revision"],
        )
~~~

- [ ] **Step 2: Run the state-store tests to verify failure**

Run: `uv run --extra dev pytest tests/kernel/test_squad_state.py -k "protocol_upgrade_reassessment" -q`

Expected: FAIL because the state-store transition is absent.

- [ ] **Step 3: Implement schema validation and CAS transition**

Split `_banzai_default_reassessment_record` into strict v1 and v2 validators. Preserve v1 return compatibility for the existing legacy transition. Add a v2 validator that accepts exactly the fields declared in the approved design, validates decision IDs, question digests, protocol digests, timestamps, and source phase, and rejects extra keys.

Under the existing exclusive state lock, require the exact intact WHY2 decision fields currently enforced by `reassess_awaiting_banzai_legacy_why2_decision`, require a v1 marker, clear the same controller-owned human-input keys, change blocked to running, set phase1-why2, and write this record before `_commit_human_input_state_unlocked`:

~~~python
desired[BANZAI_DEFAULT_REASSESSMENT_KEY] = {
    "schema_version": 2,
    "source_phase": "phase1-why2",
    "initial_attempt": {
        "decision_id": v1["decision_id"],
        "question_sha256": v1["question_sha256"],
        "protocol_fingerprint": None,
    },
    "upgrade_attempt": {
        "decision_id": str(decision["id"]),
        "question_sha256": hashlib.sha256(
            str(decision["question"]).encode("utf-8")
        ).hexdigest(),
        "protocol_fingerprint": protocol_fingerprint,
        "reassessed_at": datetime.now(timezone.utc).isoformat(),
    },
}
~~~

- [ ] **Step 4: Run the state-store focused suite to verify success**

Run: `uv run --extra dev pytest tests/kernel/test_squad_state.py -k "banzai_default_reassessment or protocol_upgrade_reassessment" -q`

Expected: PASS, including existing v1 behavior.

- [ ] **Step 5: Commit the atomic state transition**

~~~bash
git add src/harness/squad_state.py tests/kernel/test_squad_state.py
git commit -m "feat: record bounded Banzai protocol upgrade retry"
~~~

### Task 3: Controller and CLI recovery routing

**Files:**
- Modify: src/harness/squad.py:5710-5758 and 5925-5940
- Modify: src/echelon/cli.py:4561-4605 and 3843-3929
- Modify: tests/integration/test_human_input_routing.py:1298-1380
- Modify: tests/unit/test_cli_continue.py:242-340

**Interfaces:**
- Consumes: active_banzai_default_protocol_fingerprint(self._project_root), a v1 reassessment marker, and the existing WHY2 policy registry.
- Consumes: the Task 2 state-store transition.
- Produces: at most one `echelon spec continue` action with a specific upgrade-retry note.

- [ ] **Step 1: Write failing controller and CLI tests**

~~~python
def test_banzai_reassesses_one_v1_marker_after_protocol_refresh(
    tmp_path: Path,
) -> None:
    controller, store, provider = _legacy_reassessed_why2_controller(tmp_path)
    _write_protocol_bundle(tmp_path)
    next_decision_id, _ = _seal_awaiting_provider_human(
        controller, store, _why2_policy(), question="Which boundary?"
    )

    assert controller.resume_pending_human_input() is True
    ledger = store.load()["banzai_default_reassessment"]
    assert ledger["schema_version"] == 2
    assert ledger["upgrade_attempt"]["decision_id"] == next_decision_id
    provider.exec_agent.assert_not_called()


def test_cli_requires_workspace_refresh_when_upgrade_bundle_is_missing(
    tmp_path: Path,
) -> None:
    action = _classify_run_recovery(
        _blocked_v1_legacy_reassessment_state(), project_root=tmp_path
    )

    assert action.kind == "manual_recovery"
    assert action.command == "echelon workspace migrate-to-prosaic"
~~~

Add a second controller test that calls `resume_pending_human_input()` after v2 conversion and proves it returns false, leaves the next decision untouched, and never calls the provider.

- [ ] **Step 2: Run the new routing tests to verify failure**

Run: `uv run --extra dev pytest tests/integration/test_human_input_routing.py tests/unit/test_cli_continue.py -k "protocol_refresh or protocol_upgrade" -q`

Expected: FAIL because v1-marker runs have no upgrade route.

- [ ] **Step 3: Implement the controller route and CLI presentation**

Add `_reassess_awaiting_banzai_why2_after_protocol_upgrade(state)` beside the legacy method. It must first require a v1 marker and the same exact decision and policy predicates as the legacy route. It then calls the Task 1 helper. On unavailable fingerprint evidence it returns unchanged state. On a valid fingerprint it calls the Task 2 transition with current revision. Invoke it after the original legacy reassessment check and before `_rearm_awaiting_banzai_recommendation`.

In CLI recovery classification, add a presentation-only predicate for the same v1 state. Use the helper only when project_root exists. Return `resolve_decision` with command `echelon spec continue` and note:

~~~text
will re-evaluate this legacy Banzai WHY2 question once using the refreshed candidate-protocol bundle
~~~

When fingerprinting fails, return `manual_recovery` with command `echelon workspace migrate-to-prosaic` and the helper diagnostic. Preserve the legacy no-marker branch and the ordinary automatic-decision branch.

- [ ] **Step 4: Run focused routing suites to verify success**

Run: `uv run --extra dev pytest tests/integration/test_human_input_routing.py tests/unit/test_cli_continue.py -k "banzai or protocol_upgrade or protocol_refresh" -q`

Expected: PASS. The existing current-run no-loop test remains green.

- [ ] **Step 5: Commit recovery presentation and routing**

~~~bash
git add src/harness/squad.py src/echelon/cli.py tests/integration/test_human_input_routing.py tests/unit/test_cli_continue.py
git commit -m "fix: retry legacy Banzai WHY2 once after protocol refresh"
~~~

### Task 4: Verification and demo-run exercise

**Files:**
- Modify: no files; this task produces verification evidence only.

**Interfaces:**
- Consumes: completed feature branch and refreshed browser-game workspace.
- Produces: test evidence and one attempted demo recovery after installing the branch.

- [ ] **Step 1: Run focused verification**

~~~bash
uv run --extra dev pytest \
  tests/unit/test_banzai_protocol.py \
  tests/kernel/test_squad_state.py \
  tests/integration/test_human_input_routing.py \
  tests/unit/test_cli_continue.py -q
git diff --check
~~~

Expected: PASS and no whitespace errors.

- [ ] **Step 2: Review the implementation diff**

~~~bash
git diff main...HEAD -- \
  src/harness/banzai_protocol.py \
  src/harness/squad_state.py \
  src/harness/squad.py \
  src/echelon/cli.py \
  tests
~~~

Verify that no branch permits v2-to-v3 or repeated v2 upgrade transitions, and no non-Banzai decision calls the new helper.

- [ ] **Step 3: Install and inspect the demo state**

~~~bash
uv tool install --reinstall --editable .
cd /Users/michalbachorik/work/browser-3d-game-stack-smoke
echelon spec status
~~~

Expected: status recommends `echelon spec continue` and identifies one refreshed candidate-protocol reassessment.

- [ ] **Step 4: Attempt the one permitted demo retry**

~~~bash
cd /Users/michalbachorik/work/browser-3d-game-stack-smoke
echelon spec continue
~~~

Expected: state converts to v2 before WHY2 dispatch. A valid typed candidate may continue the Banzai flow; a missing or invalid candidate stops at a normal human-owned decision with no further automatic retry.
