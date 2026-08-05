# Bounded Dispatch-Cap Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make dispatch-cap recovery accept valid long issue content without exceeding human-input transport limits or misreporting controller option failures as malformed evidence.

**Architecture:** Keep the existing bounded `issues.md` parser as evidence authority. New recovery options carry a UTF-8-safe compact label and a versioned `{issue_id, evidence_sha256}` reference; resolution rereads the authoritative issues artifact and verifies the digest before applying the exact candidate. Legacy self-contained option descriptions remain readable for already-sealed decisions.

**Tech Stack:** Python 3, dataclasses, `hashlib.sha256`, JSON canonicalization, pytest.

## Global Constraints

- Keep `HUMAN_INPUT_OPTION_LABEL_MAX_BYTES = 256` and `HUMAN_INPUT_OPTION_DESCRIPTION_MAX_BYTES = 1_024` unchanged.
- Never truncate evidence-bearing candidate fields.
- Never split a UTF-8 code point when shortening presentation labels.
- Fail closed when referenced evidence is missing or changes after sealing.
- Preserve legacy full-candidate option descriptions during migration.
- Do not edit `state.json` or `reasoning-journal.jsonl` directly.

---

### Task 1: Compact, evidence-bound dispatch-cap options

**Files:**
- Modify: `src/harness/squad.py`
- Test: `tests/integration/test_human_input_routing.py`

**Interfaces:**
- Produces: `SquadController._dispatch_cap_options(candidates) -> tuple[HumanInputOption, ...]` with bounded labels and compact descriptions.
- Produces: private canonical-candidate digest and UTF-8 label-shortening helpers in `src/harness/squad.py`.
- Consumes: existing `HUMAN_INPUT_OPTION_LABEL_MAX_BYTES`, `HumanInputOption`, and parsed candidate mappings.

- [ ] **Step 1: Write failing tests for long and Unicode titles**

Add focused tests that call `_dispatch_cap_options` with a title exceeding 256 UTF-8 bytes and assert:

```python
options = SquadController._dispatch_cap_options([
    _dispatch_cap_candidate(title="ž" * 200),
])
assert len(options[0].label.encode("utf-8")) <= 256
options[0].label.encode("utf-8").decode("utf-8")
assert options[0].label.startswith("ISS-001: ")
assert options[0].label.endswith("…")
```

Add a second candidate whose `suggested_option` exceeds 1,024 bytes and assert the generated description remains within `HUMAN_INPUT_OPTION_DESCRIPTION_MAX_BYTES` and contains only `schema_version`, `issue_id`, and `evidence_sha256`.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/integration/test_human_input_routing.py -q -k 'dispatch_cap_options_bound_long_title or dispatch_cap_options_reference_large_evidence'
```

Expected: FAIL because the current label exceeds 256 bytes and the current description serializes the complete candidate.

- [ ] **Step 3: Implement canonical digest and UTF-8-safe label shortening**

In `src/harness/squad.py`, import the existing label/description bounds from `harness.human_input` and add private helpers equivalent to:

```python
def _canonical_dispatch_cap_candidate(candidate: Mapping[str, str]) -> str:
    return json.dumps(candidate, sort_keys=True, separators=(",", ":"))


def _dispatch_cap_candidate_digest(candidate: Mapping[str, str]) -> str:
    return hashlib.sha256(
        _canonical_dispatch_cap_candidate(candidate).encode("utf-8")
    ).hexdigest()


def _bounded_utf8_label(prefix: str, text: str, max_bytes: int) -> str:
    full = f"{prefix}{text}"
    if len(full.encode("utf-8")) <= max_bytes:
        return full
    suffix = "…"
    budget = max_bytes - len(prefix.encode("utf-8")) - len(suffix.encode("utf-8"))
    kept: list[str] = []
    used = 0
    for character in text:
        width = len(character.encode("utf-8"))
        if used + width > budget:
            break
        kept.append(character)
        used += width
    return f"{prefix}{''.join(kept)}{suffix}"
```

Generate new descriptions as compact schema-version-1 references and validate each constructed `HumanInputOption` through the existing closed contract.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: both tests PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/harness/squad.py tests/integration/test_human_input_routing.py
git commit -m "fix: bound dispatch cap recovery options"
```

---

### Task 2: Rehydrate references and preserve legacy decisions

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `tests/integration/test_human_input_routing.py`

**Interfaces:**
- Consumes: selected `HumanInputOption`, current controller state, and authoritative candidates from `_banzai_issue_resolution_candidates(state)`.
- Produces: exact full candidate only after issue-ID and SHA-256 reference verification.
- Compatibility: accepts the existing legacy five-field candidate JSON description.

- [ ] **Step 1: Write failing rehydration and drift tests**

Update the dispatch-cap lifecycle test to seal a new compact option and assert unchanged `issues.md` resolves to the exact existing issue-resolution state updates.

Replace the old “sealed option survives evidence drift” expectation with a fail-closed assertion:

```python
before = store.load()
with pytest.raises(HumanInputPolicyError, match="evidence.*changed"):
    controller.apply_human_input_resolution(
        decision_id,
        expected_state_revision=revision,
        resolution=HumanInputResolution(
            selected_option_id="ISS-001",
            answer_text=None,
            resolved_by="user",
        ),
    )
assert store.load() == before
```

Add a compatibility test that manually seals `_dispatch_cap_option(candidate)` in the old full-candidate shape and verifies successful resolution.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/integration/test_human_input_routing.py -q -k 'phase_dispatch_limit_reuses_issue_lifecycle or dispatch_cap_rejects_evidence_drift or dispatch_cap_accepts_legacy_candidate'
```

Expected: new-reference lifecycle and drift tests FAIL because `_dispatch_cap_candidate_from_option` only accepts the legacy five-field JSON object.

- [ ] **Step 3: Implement reference validation and legacy fallback**

Change dispatch-cap resolution so it:

1. Parses the description.
2. If it is the exact legacy five-field shape, validates and returns it through the current path.
3. If it is the exact schema-version-1 reference shape, rereads candidates using `_banzai_issue_resolution_candidates(dict(state))`.
4. Selects exactly one matching issue ID.
5. Recomputes and compares the SHA-256 digest with `hmac.compare_digest` or an equivalent constant-time comparison.
6. Raises `HumanInputPolicyError("dispatch-cap evidence changed after decision sealing")` on missing or mismatched evidence.
7. Applies the existing `_validate_banzai_issue_resolution_selection` and state-update path only after verification.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/harness/squad.py tests/integration/test_human_input_routing.py
git commit -m "fix: verify dispatch cap evidence references"
```

---

### Task 3: Report controller option-contract failures accurately

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `tests/integration/test_human_input_routing.py`
- Modify if surfaced by CLI mapping tests: `src/echelon/cli.py`

**Interfaces:**
- Produces: terminal reason code `phase_dispatch_limit_option_contract_failed` only for controller-generated option construction/validation failures.
- Preserves: existing `phase_dispatch_limit_evidence_missing|empty|malformed|oversized|ineligible|too_many_candidates` codes for source-evidence failures.

- [ ] **Step 1: Write a failing classification regression**

Monkeypatch `_dispatch_cap_options` to raise `HumanInputPolicyError` after valid candidate parsing, exceed the dispatch cap, and assert:

```python
assert failed["blocked_reason"] == "phase_dispatch_limit_option_contract_failed"
assert failed["recovery_instruction"]["kind"] == "manual_diagnosis"
```

Keep the existing malformed-evidence test asserting `phase_dispatch_limit_evidence_malformed`.

- [ ] **Step 2: Run the classification tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/integration/test_human_input_routing.py -q -k 'dispatch_cap_option_contract_failure or dispatch_cap_without_resolvable_evidence'
```

Expected: option-contract test FAILS with the current malformed-evidence reason.

- [ ] **Step 3: Split the exception boundary**

In the dispatch-cap branch, keep `_DispatchCapEvidenceError` mapped to its evidence reason. Map `HumanInputPolicyError` from `_dispatch_cap_options` to `phase_dispatch_limit_option_contract_failed`; do not relabel it as evidence malformed.

If CLI recovery classification uses a fixed reason list, add the new reason to the same manual-diagnosis class without adding a free-text resume path.

- [ ] **Step 4: Run focused and adjacent tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/integration/test_human_input_routing.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_human_input.py \
  tests/unit/test_blocked_decision.py \
  tests/unit/test_cli_continue.py \
  tests/unit/test_cli_status.py -q
```

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/harness/squad.py src/echelon/cli.py tests/integration/test_human_input_routing.py
git commit -m "fix: distinguish dispatch option contract failures"
```

---

### Task 4: Install main and continue the recovered run

**Files:**
- Runtime install: `~/.echelon/venv`
- Active project: `/Users/michalbachorik/work/md_distribution`

**Interfaces:**
- Consumes: verified main checkout.
- Produces: installed `echelon` CLI importing main `src/harness/squad.py`.

- [ ] **Step 1: Verify the main worktree and focused suite**

Run:

```bash
git status --short --branch
.venv/bin/python -m pytest \
  tests/integration/test_human_input_routing.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_human_input.py \
  tests/unit/test_blocked_decision.py \
  tests/unit/test_cli_continue.py \
  tests/unit/test_cli_status.py -q
```

Expected: clean committed implementation and all tests PASS.

- [ ] **Step 2: Reinstall the CLI from main**

Run:

```bash
bash scripts/install.sh
```

Expected: installer exits 0.

- [ ] **Step 3: Verify import provenance**

Run:

```bash
/Users/michalbachorik/.echelon/venv/bin/python - <<'PY'
import inspect
import harness.squad
print(inspect.getfile(harness.squad))
PY
```

Expected path starts with `/Users/michalbachorik/work/echelon_r/echelon/src/` and does not contain `.worktrees/source-topology-foundation`.

- [ ] **Step 4: Continue the active spec run**

Run from `/Users/michalbachorik/work/md_distribution`:

```bash
echelon spec status
echelon spec continue
```

Expected: the run advances from the recovered `phase1-why2` state. Follow only controller-reported `continue` or structured `resume` actions; stop at completion or a genuine human/external prerequisite decision.

- [ ] **Step 5: Record final verification**

Report the test counts, installed import path, active run phase/status, and any remaining genuine decision separately from the fixed harness defect.
