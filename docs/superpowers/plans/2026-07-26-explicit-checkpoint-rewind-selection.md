# Explicit Checkpoint Rewind Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make historical duplicate-phase checkpoints explicitly selectable by commit while exposing authoritative ledger order and diagnostic timestamps.

**Architecture:** Extend the shared checkpoint resolver with an optional commit prefix so CLI preflight and rewind execution use one selection rule. Thread the selector through both CLI surfaces without changing checkpoint persistence, and improve list rendering from the same immutable ledger records.

**Tech Stack:** Python 3, Typer, pytest, Git-backed Phase A checkpoint ledgers.

## Global Constraints

- Preserve phase-only selection as the last matching record in durable ledger order.
- Do not change checkpoint IDs, ledger schema, or persisted checkpoint order.
- Treat `created_at` as display-only metadata, never routing authority.
- Fail before Git, ledger, artifact, or run-state mutation when selection fails.
- Do not add compatibility switches, timestamp selectors, or numeric occurrence selectors.

---

### Task 1: Commit-aware checkpoint resolution

**Files:**
- Modify: `src/harness/phase_checkpoints.py`
- Test: `tests/unit/test_phase_checkpoints.py`

**Interfaces:**
- Consumes: `CheckpointLedger`, `PhaseCheckpoint`, existing phase-or-ID target string.
- Produces: `resolve_checkpoint(ledger: CheckpointLedger, target: str, commit: str = "") -> PhaseCheckpoint`.

- [ ] **Step 1: Write failing resolver tests**

Add tests that construct duplicate `phase1-what` records and assert:

```python
assert resolve_checkpoint(ledger, "phase1-what").commit == newest_commit
assert (
    resolve_checkpoint(ledger, "phase1-what", commit=older_commit[:8]).commit
    == older_commit
)
```

Add failure cases:

```python
with pytest.raises(KeyError, match="commit .* not found"):
    resolve_checkpoint(ledger, "phase1-what", commit="deadbeef")

with pytest.raises(ValueError, match="ambiguous checkpoint commit prefix"):
    resolve_checkpoint(ledger, "phase1-what", commit="abc")
```

The ambiguous fixture must use two different commits sharing the prefix. A
duplicate record with the same phase and exact commit must select the last
ledger record.

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_phase_checkpoints.py -k "resolve_checkpoint"
```

Expected: commit-selector calls fail because `resolve_checkpoint` does not
accept `commit`.

- [ ] **Step 3: Implement minimal shared resolution**

Change the resolver signature and filter only the existing target matches:

```python
def resolve_checkpoint(
    ledger: CheckpointLedger,
    target: str,
    commit: str = "",
) -> PhaseCheckpoint:
    matches = _target_matches(ledger, target)
    if not matches:
        raise KeyError(...)
    prefix = commit.strip().lower()
    if not prefix:
        return matches[-1]
    commit_matches = [item for item in matches if item.commit.startswith(prefix)]
    if not commit_matches:
        raise KeyError(...)
    distinct_commits = {item.commit for item in commit_matches}
    if len(distinct_commits) > 1:
        raise ValueError(...)
    return commit_matches[-1]
```

Reject non-hex selectors before prefix matching. Error text must include the
target and selector without mutating the ledger.

- [ ] **Step 4: Verify GREEN**

Run the focused command from Step 2 and then:

```bash
.venv/bin/pytest -q tests/unit/test_phase_checkpoints.py
```

Expected: all checkpoint resolver and ledger tests pass.

---

### Task 2: Thread `--commit` through preview and confirmed rewind

**Files:**
- Modify: `src/echelon/rewind.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/cli_app.py`
- Test: `tests/unit/test_rewind.py`
- Test: `tests/unit/test_cli_rewind.py`
- Test: `tests/unit/test_cli_typer_app.py`

**Interfaces:**
- Consumes: `resolve_checkpoint(..., commit=...)`.
- Produces: `prepare_rewind(..., target: str, checkpoint_commit: str = "")`.
- Produces CLI syntax `echelon spec rewind <phase-or-id> [--commit <sha>] [--confirm]`.

- [ ] **Step 1: Write failing rewind and CLI tests**

Cover these behaviors:

```python
result = prepare_rewind(
    project_root=repo,
    spec="001",
    target="phase1-what",
    checkpoint_commit=older_commit[:8],
    confirm=False,
)
assert result.to_commit == older_commit
assert f"--commit {older_commit[:8]} --confirm" in result.message
```

For `_cmd_rewind`, record three duplicate phase checkpoints, select the middle
one with `--commit`, and assert the retained ledger ends at that exact object
and the reset state targets `phase1-what`.

Add Typer coverage asserting `--commit` is accepted and forwarded to the legacy
argument list. Add a malformed `--commit` test that exits before
`prepare_rewind`.

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_rewind.py \
  tests/unit/test_cli_rewind.py \
  tests/unit/test_cli_typer_app.py -k "rewind"
```

Expected: failures show the missing `checkpoint_commit` parameter and unknown
`--commit` parsing.

- [ ] **Step 3: Implement selector plumbing**

In `prepare_rewind`, resolve with:

```python
checkpoint = resolve_checkpoint(
    ledger,
    target,
    commit=checkpoint_commit,
)
```

Build the preview confirmation command from the exact selector:

```python
selector_arg = (
    f" --commit {checkpoint_commit}"
    if checkpoint_commit
    else ""
)
confirm_command = (
    f"echelon spec rewind {checkpoint.phase}{selector_arg} --confirm"
)
```

In `_cmd_rewind`, parse exactly one optional `--commit <sha>` pair plus
`--confirm`, reject missing/repeated values, pass the selector to both
pre-validation and `prepare_rewind`, and keep ledger truncation based on
`ledger.checkpoints.index(checkpoint)`.

Add the typed option:

```python
checkpoint_commit: Optional[str] = typer.Option(
    None,
    "--commit",
    help="Full checkpoint commit or unique abbreviated prefix.",
)
```

Forward it as `["--commit", checkpoint_commit]`.

- [ ] **Step 4: Verify GREEN**

Run the focused command from Step 2.

Expected: preview, confirmation, truncation, malformed-input, and Typer tests
all pass.

---

### Task 3: Make checkpoint list order and recency explicit

**Files:**
- Modify: `src/echelon/checkpoint_cli.py`
- Test: `tests/unit/test_cli_checkpoint.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `CheckpointLedger.checkpoints` in persisted order.
- Produces: human-readable oldest-to-newest table with UTC timestamps and
  per-phase latest markers.

- [ ] **Step 1: Write failing list-rendering tests**

Create a ledger whose timestamps and insertion order deliberately differ.
Assert output preserves insertion order and contains:

```python
assert "Order: oldest -> newest (ledger order)" in out
assert "CREATED UTC" in out
assert "LATEST" in out
assert "2026-07-23 18:40:12" in out
```

Assert only the final ledger occurrence of each phase is marked `yes`, even
when an earlier record has a later `created_at`.

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_cli_checkpoint.py
```

Expected: the order note, timestamp column, and latest marker are absent.

- [ ] **Step 3: Implement deterministic rendering**

Precompute the final index for every phase:

```python
latest_by_phase = {
    checkpoint.phase: index
    for index, checkpoint in enumerate(ledger.checkpoints)
}
```

Iterate `ledger.checkpoints` unchanged. Parse valid ISO timestamps for compact
UTC display; for malformed legacy metadata, display the stored value rather
than reordering or failing the list command.

Document both forms:

```text
echelon spec rewind phase1-what
echelon spec rewind phase1-what --commit 98152f1
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_cli_checkpoint.py
```

Expected: all checkpoint list tests pass.

---

### Task 4: Cross-path verification and completion

**Files:**
- Verify only; modify a task file only if a failing assertion reveals a direct
  contract mismatch.

**Interfaces:**
- Consumes: completed resolver, rewind, CLI, and list behavior.
- Produces: verified repository state ready for one implementation commit.

- [ ] **Step 1: Run the checkpoint/rewind matrix**

```bash
.venv/bin/pytest -q \
  tests/unit/test_phase_checkpoints.py \
  tests/unit/test_rewind.py \
  tests/unit/test_cli_rewind.py \
  tests/unit/test_cli_checkpoint.py \
  tests/unit/test_cli_typer_app.py \
  tests/unit/test_cli_continue.py
```

Expected: all tests pass.

- [ ] **Step 2: Run static checks**

```bash
python3 -m py_compile \
  src/harness/phase_checkpoints.py \
  src/echelon/rewind.py \
  src/echelon/cli.py \
  src/echelon/cli_app.py \
  src/echelon/checkpoint_cli.py
git diff --check
```

Expected: both commands exit zero.

- [ ] **Step 3: Run the full repository suite**

```bash
bash tests/run-all.sh
```

Expected: `OVERALL: PASS`.

- [ ] **Step 4: Commit the implementation**

```bash
git add \
  README.md \
  src/harness/phase_checkpoints.py \
  src/echelon/rewind.py \
  src/echelon/cli.py \
  src/echelon/cli_app.py \
  src/echelon/checkpoint_cli.py \
  tests/unit/test_phase_checkpoints.py \
  tests/unit/test_rewind.py \
  tests/unit/test_cli_rewind.py \
  tests/unit/test_cli_checkpoint.py \
  tests/unit/test_cli_typer_app.py
git commit -m "fix: select rewind checkpoints by commit"
```
