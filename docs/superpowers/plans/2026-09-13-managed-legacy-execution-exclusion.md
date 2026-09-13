# Managed identity legacy execution exclusion implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refuse the existing legacy controller paths when a managed identity declaration or retained ownership is already present, before recovery, cleanup or decision writes.

**Architecture:** Add a query-only exclusion check to the existing identity authority and a small filesystem/state admission adapter. Call it at existing controller entry boundaries; it deliberately rejects managed execution until the full managed producer/publication protocol is integrated. It creates no managed runs and is not the eventual managed execution admission proof.

**Tech Stack:** Existing SQLite authority/indexes, existing Phase A/SpecRun execution locks and state/completion owners, isolated native fixtures and simulated controller tests.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- Existing graph keys remain valid.
- Historical evidence is retained, not relabeled as proof of the new content.
- A pending publication blocks conflicting writes until reconciled.
- Identity failures cannot become quality debt or banzai waivers.
- This task excludes existing managed ownership from legacy execution; it does not enable managed authoring, enrollment, migration, publication recovery or any producer.
- Failed admission must not save a blocker into the rejected state, mutate the ledger, drain/discard retained completion/publication stages, claim a decision or dispatch a provider.
- An absent legacy authority is never initialized or reconstructed from Markdown. No schema, wire format, default feature snapshot, CLI, prose or provider implementation changes.

---

### Task 1: exclude managed ownership before legacy controller effects

**Files:** Modify `src/harness/element_identity_store.py` and `src/harness/squad.py`; create `src/harness/element_identity_legacy_guard.py`, `tests/unit/test_element_identity_legacy_guard.py` and `tests/unit/test_squad_identity_exclusion.py`; document the bounded exclusion in `docs/element-identity-storage.md`. No existing tests or other production files may change without root escalation. Root owns plan/brief/progress. No subagents.

**Authority interface:** Add this thin query-only method to the existing store; no new authority object or JSON result:

```python
def require_unmanaged_execution(
    self, *, spec_id: str | None, run_ids: tuple[str, ...],
) -> None:
    # Validate/detach identifiers, then use one query-only transaction.
    # Reject any retained managed owner matching spec_id or one of run_ids.
    # Also reject orphan managed registration operations via the existing index.
    # Return None only when no such retained owner was observed.
```

Require exact tuple, at least one run identifier, exact strings through native lifecycle.text (no integer coercion or normalization), and unique run IDs. `spec_id=None` means no claimed spec; any supplied value must pass the same native text validation. All inputs validate before transaction entry. Use the existing unique managed run/spec indexes and `managed_identity_operations` partial index for the orphan check (managed operations whose registration row is missing). This is at most a scan of managed registration operations, never reservations/entities/revisions/reference/occurrence history or all general operations. Check matching rows even if their request/source payload is damaged: presence is sufficient to refuse legacy execution, not to certify managed validity. A query-only read cannot certify all nonselected authority history; do not call full audit or claim a full audit was performed. Schema/marker/ordinary query failure rejects. Preserve one transaction with PRAGMA query_only=ON, no writes/repair, bounded `IdentityStoreError` raised outside handlers with neither nested cause nor context. BaseException propagates.

**Admission adapter:** The new focused module exports one function and fixed message:

```python
LEGACY_IDENTITY_EXECUTION_BLOCKED = "identity authority does not permit legacy execution"

def require_legacy_identity_execution(
    *, project_root: Path, run_dir: Path, state: dict,
) -> None:
    # A present managed_identity key always refuses this legacy path.
    # Otherwise inspect presence (including broken symlinks) of .echelon/identity.
    # Truly absent authority returns without initializing or reading Markdown.
    # Existing authority opens with IdentityStore.open and invokes the method above.
```

The constant is the exact bounded IdentityStoreError message for this adapter's ordinary failures and managed refusal. Reject a present `managed_identity` key regardless of its value; this is an exclusion, not an authentication attempt. Require an exact dict for supplied state. When neither that key nor the authority path exists, preserve the legacy no-authority route without adding validation of unrelated legacy state fields. Presence detection must not use Path.exists alone because it treats a dangling symlink as absent. First lstat the explicit `.echelon` parent: an absent parent permits the no-authority route, but a present symlink or non-directory parent refuses. Then lstat the identity leaf; only FileNotFoundError with that real-directory parent may represent leaf absence. This prevents a dangling parent link from masquerading as an absent leaf. Do not add broad project-root ancestor/symlink validation to the no-authority legacy fast path. Never create/open-as-new the authority. Existing directory/file/symlink/incomplete/malformed authority is passed through native open validation and fails rather than falling back.

For existing authority, independently include the physical `run_dir.name` and the declared state `run_id` when present and nonempty, retaining exact strings and deduplicating before calling the strict authority method. Reject a present non-string/nonempty-invalid declared run value; absent/None/empty string supplies no additional identifier. For state `spec_id`, absent/None/empty string means None; any other value must satisfy exact native text validation. Do not derive ownership from a subject, Markdown maximum, current-directory name other than the explicit run argument, or the managed record's own claimed IDs. The claimed spec is checked in addition to physical/declared run ownership, so a later run of an already managed spec is also refused. No tuple/string width cap. No new generic discovery API, enrollment, namespace selection or positive managed-admission result.

**Controller integration:** Add one small private `_legacy_identity_execution_blocked(state)` method that calls the adapter with existing project/run fields and returns bool only by catching its bounded IdentityStoreError. It performs no logging of untrusted state, no persistence and no fallback initialization. The no-error path returns False; the exclusion returns True. Do not catch process-control exceptions.

1. In `_run_with_execution_lease`, after acquiring the existing PhaseA and SpecRun leases but BEFORE `_drain_pending_controller_completion`, `_emit_pending_retarget_comparison`, orphan cleanup or `execute()`, load state and check exclusion. If blocked, return `SquadResult(status="blocked", phase=<existing string phase or "unknown">, run_id=self._squad_dir.name, summary=LEGACY_IDENTITY_EXECUTION_BLOCKED)`. Do not save this synthetic result. This covers public run and run_single_phase before early recovery/budget/manual claim writes. Preserve existing busy/lock behavior and release locks normally.
2. At the existing state load in `handle_human_input`, `apply_human_input_resolution`, `resume_pending_human_input`, and `resume_with_human_input`, check before any decision/recovery writes or completion draining. On exclusion raise `HumanInputPolicyError(LEGACY_IDENTITY_EXECUTION_BLOCKED)` outside the identity error handler, rather than merely returning False. Keep existing read-only argument/policy validation ordering otherwise. The CLI catches this existing exception; its current unconditional submission banner after a returned False must not be reached. No CLI edit is needed.

This intentionally refuses even a completely valid managed record: legacy publishing still lacks the managed protocol. It does not replace the future positive context/source/semantic/graph admission. The read observes existing ownership at that instant and is not a long-lived registration lease; do not claim it serializes a concurrent explicit enrollment. Missing both all managed declarations and all durable ownership witnesses is not detectable from current Markdown; this adapter neither reconstructs them nor claims such recovery. Other legacy runs with a valid authority but no matching managed ownership remain legacy. Malformed/incomplete authority, a matching damaged managed row or any orphan managed registration operation refuses entry rather than guessing legacy.

**First RED:** Create a real resolved temporary identity authority, actual empty selected run-local tree captured through native source inspection, real source context/genesis registration and real SquadStateStore initialization retaining that managed record. Use public `SquadController.run` with existing terminal graph/no-provider fixture setup. Narrow spies on recovery, retarget, cleanup and phase callback may make ordering observable without running unrelated workflow; they are not the identity authority or mutation oracle. Before this change the entry reaches those legacy callbacks/returns their legacy result. Assert the synthetic blocked result and zero callback/provider activity, plus complete original state bytes and SQL dump unchanged. This must fail on actual existing behavior before any production edit, not on an invented missing helper. Report its actual outcome before implementation.

```python
before_state = state_path.read_bytes()
before_sql = sql_state(project_root)
result = controller.run(user_message="Retain the managed spec")
assert result.status == "blocked"
assert result.summary == "identity authority does not permit legacy execution"
assert calls == []
assert state_path.read_bytes() == before_state
assert sql_state(project_root) == before_sql
```

- [ ] Run the first real RED using `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_squad_identity_exclusion.py::test_managed_run_refuses_legacy_recovery_before_any_effect -q` from this worktree. Fix/report genuine fixture failures separately; notify root before production changes.
- [ ] Implement the smallest authority query, adapter and existing-controller entry calls, then rerun that first test to GREEN. No managed initialization/default activation or positive admission capability.
- [ ] Add actual authority query tests: no matching owner returnsNone unchanged; match by spec or either run refuses; unrelated managed spec/run coexistence permits; removed row with retained managed operation rejects; damaged matching payload still refuses; exact malformed IDs/tuples reject before transaction; duplicate tuple IDs reject; fresh reopened authority gives same answers; ordinary failure has bounded no-context/no-cause error and BaseException propagates. Use SQL authorizer/query tracing to prove one query-only transaction and no access to identity child-history tables, rather than seeding/repeating a million-record benchmark.
- [ ] Add adapter tests for no authority/no initialization/no Markdown IO; any present managed key (including None/false/empty dict) blocks; removed key caught by actual retained physical run or claimed run/spec; changed state spec/run cannot hide independently retained physical run; later run of managed spec blocks; genuinely unrelated legacy ownership passes. Test incomplete directory, missing marker/DB, malformed marker/schema, regular-file authority, symlink and dangling symlink refusal; preserve exact filesystem/SQL state except deliberate fixture damage. Separate portable value cases from explicitly requested secure-POSIX fixtures.
- [ ] Parameterize public run and run_single_phase across guided/semi/banzai: same refusal before callback recovery, retarget/orphan cleanup, manual failed-decision claim, budget reset, provider, checkpoint, mining or graph publication. Existing lock-contention behavior must remain busy, with no new effects. Do not write a blocker or remove managed metadata to make tests pass.
- [ ] Include a real retained completion/publication stage fixture and pending marker, then invoke public run after removing managed state metadata by explicit raw test-fixture damage. Retained authority must refuse before recovery/cleanup; exact staged files, state bytes/markers and SQL dump remain unchanged. Use native stage/state construction from existing completion tests; an ordering spy is allowed to trip if drain is reached, but do not claim this implements managed recovery or fabricate a validated completion marker.
- [ ] Exercise all four human-input boundaries with native prepared request/decision/resolution fixtures where their earlier read-only validation requires them. Assert HumanInputPolicyError with the exact constant before claim/answer writes/provider/recovery; no false submitted result, no state changes, no cause/context. Preserve normal unmanaged guided/semi/banzai behavior through the existing integration suite. No banzai bypass or quality-debt exception.
- [ ] Add genuine legacy controls: no-authority controller path still executes; valid authority with no matching managed ownership still executes without registry writes; managed refusal does not consume repair/dispatch counters. Ensure no-authority fast path does not unnecessarily validate unrelated old state fields or change current provider metadata behavior.
- [ ] Document the early exclusion, its per-spec/run matching and indexed registration-orphan check, ordinary authority-error refusal, no persistence on rejection and handled human-input error. Explicitly retain missing positive managed admission, enrollment concurrency, pending recovery and all producer/publication/repair integrations. A successful absence read is not a lease or complete authority audit.
- [ ] Self-review and run once these covering modules with the exact pytest executable/workdir above: `tests/unit/test_element_identity_legacy_guard.py`, `tests/unit/test_squad_identity_exclusion.py`, `tests/unit/test_element_identity_managed.py`, `tests/unit/test_element_identity_managed_context.py`, `tests/unit/test_squad_execution_lock.py`, `tests/unit/test_squad_completion.py`, `tests/integration/test_human_input_routing.py`. The last module uses simulated providers; do not run a real provider/service, bare pytest/full unit, Docker, capacity or global install. Later amendments get named scoped checks and exact tested-tree chronology, no unchanged postcommit reruns.
- [ ] Commit only scoped production/new tests/storage docs; keep root ledger unstaged. Retain complete report separately at the authorized report path (force-add that exact path if ignored). Report all actual failures/fixture corrections/diagnostics/RED/GREEN/covering commands and outputs, exact staged tested tree and later amendments. Root dispatches fresh original-BASE independent review. Escalate any additional owner/API/CLI change required rather than silently broadening.

## Remaining integration

This early negative boundary is not managed execution support. The eventual owner must replace refusal only after authenticating complete run/state/source ownership and coupling every candidate producer, semantic review, identity/source journal, sealed graph, completion/recovery and bounded repair. Fresh managed enrollment and later-run transitions remain unactivated. This task introduces no route that accepts managed content and authorizes no live rollout.
