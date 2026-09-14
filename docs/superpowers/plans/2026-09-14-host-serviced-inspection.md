# Host-serviced Inspection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution or superpowers:subagent-driven-development if the user chooses delegation. Steps use checkbox (`- [x]`) syntax for tracking. These shared-file tasks should execute sequentially.

**Goal:** Expose the existing no-tools provider turns and bounded host reader for fulfillment to consume without activating fulfillment or altering triage.

**Architecture:** Add a neutral optional inspection operation to the existing facade/adapters, delegating to their established no-tools machinery. Extract the descriptor reader into a shared owner with caller-named roots and denied paths; retain the triage wrapper. Workflow sequencing and semantic schemas stay with future fulfillment callers.

**Tech Stack:** Python, pytest, existing Claude/Codex CLI adapters and scripted process fixtures.

**Spec:** `docs/superpowers/specs/2026-09-14-host-serviced-inspection-design.md`; approved reuse-based design. This is a prerequisite checkpoint for Phase 2 of `docs/superpowers/specs/2026-09-13-controlled-fulfillment-ownership-design.md`, not all of Phase 2.

## Global Constraints

- No model-accessible shell, tests, web/network tools, writes or delegation are available.
- Provider authentication and model API transport necessarily retain network access; this is not a claim that the entire CLI process is offline.
- No fallback to `run_agent_result`, generic prompt execution, another provider or COMMANDER is permitted.
- Keep existing `run_review_triage_turn` and generic constrained capability contracts unchanged.
- No semantic fulfillment roles, controller loop, full/scoped refresh, durable recovery, publication, mode/default change, native entry migration, installation, live model call, push or merge belongs to this checkpoint.
- No AGENTS.md/CLAUDE.md or provider-specific Prosaic changes.
- Preserve 1 MiB source-file/input bounds, 200 lines per read, 64 KiB encoded read/list output, 500 directory entries and 256 KiB provider capture. Existing triage retains its 32-read limit.

Worktree: `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`.
Python: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python`.
Baseline runtime: `bfd722cb`. Check status and signatures before editing; use
`apply_patch`. Prior read-only baseline: 97 triage provider/IO tests passed.

## Task 1: Neutral optional no-tools inspection operation

**Files:** Modify `src/harness/ai_cli_backend.py`, `src/harness/llm_provider.py`,
`src/harness/ai_cli_backends/claude.py`, `src/harness/ai_cli_backends/codex.py`.
Create `src/harness/inspection_turn.py`, `tests/unit/test_inspection_turn.py`.

**Consumes:** `CliRunRequest`, `CliRunResult`, existing backend
`run_review_triage_turn(request)` methods, and
`host_workspace_synthesis_boundary_available()` from the Claude adapter.
The existing no-tools backend operations have no PR-specific semantic parser;
their triage naming does not require passing a triage role or schema.

**Produces:**

```python
@runtime_checkable
class InspectionTurnBackend(Protocol):
    def run_inspection_turn(self, request: CliRunRequest) -> CliRunResult: ...

# inspection_turn.py: narrow validation, no provider selection or process launch.
def inspection_request_failure(request: CliRunRequest) -> CliRunResult | None: ...

# AICodingCliProvider
@property
def supports_inspection_turn(self) -> bool: ...
def run_inspection_turn(self, private_cwd: str, prompt: str, *,
                        frontmatter: Mapping[str, object], timeout_ms: int
                        ) -> CliRunResult: ...
```

- [x] **1. Write direct/facade RED tests.** Unsupported backend and unavailable
  macOS host boundary must return exit 125 without either a generic or inspection
  backend launch. Cover invalid private cwd (missing, nonempty, symlink), timeout
  (bool, zero, negative, nonfinite at backend), empty/non-string prompt, unknown
  frontmatter fields, native model/provider fields and tool/profile/scope overrides.

```python
def test_unsupported_inspection_never_falls_back(tmp_path):
    from unittest.mock import patch
    from tests.unit.test_review_triage_provider import _config
    from harness.llm_provider import AICodingCliProvider
    provider = AICodingCliProvider(_config("copilot", unsafe=True))
    with patch.object(provider._backend, "run_prompt") as prompt, \
         patch.object(provider._backend, "run_agent") as agent:
        result = provider.run_inspection_turn(str(tmp_path), "inspect evidence",
            frontmatter={"model_tier": "strong", "effort": "medium"}, timeout_ms=1000)
    assert result.exit_code == 125
    assert result.metadata["failure_reason"] == "inspection-unsupported"
    prompt.assert_not_called()
    agent.assert_not_called()
```

- [x] **2. Run RED:** `python -m pytest tests/unit/test_inspection_turn.py -xq`
  using the absolute Python above. Record the missing operation failure.
- [x] **3. Implement validation and the optional operation.** Metadata is exactly
  `{"prompt_metadata":{"model_tier":tier,"effort":effort}}`. Accepted tiers are
  `fast`, `balanced`, `strong`; effort is `low`, `medium`, `high`. Reject extra
  fields rather than silently stripping unsafe options. The facade constructs
  the request using `_build_env()`, bounds timeout by its configured maximum,
  and records every result through `_record_result`, including admission failure.
  Preserve the existing last-call field reset semantics. Validate before backend
  dispatch; each adapter also validates direct calls. Check host availability
  lazily to avoid an import cycle between the shared validator and adapters.

```python
# Both adapters: reuse, do not duplicate native controls or capture/parsing.
def run_inspection_turn(self, request):
    from harness.inspection_turn import inspection_request_failure
    failure = inspection_request_failure(request)
    if failure is not None:
        return failure
    return self.run_review_triage_turn(request)
```

  The new helper returns `None` only for an admitted request; otherwise return
  exit 125 with `failure_reason=invalid_request` or `isolation_unavailable`.
  Unsupported facade backends use `inspection-unsupported`. Do not modify existing
  triage metadata admission, model mappings, native profile defaults, constrained
  RE capability or the general `supports_read_only_review` property. An explicit
  small facade helper may share result bookkeeping if needed; no dynamic registry.
- [x] **4. Verify both real adapter paths.** Reuse `_codex_wire`, `_claude_wire`
  and scripted subprocess patterns from `test_review_triage_provider.py`. Assert
  no-tools command settings, isolated configuration, neutral model/effort mapping,
  input/capture limits, timeout cleanup, final text normalization, rejection of
  tool events and preservation of failed-turn usage through the new facade.
  No actual CLI model call. Run the new file plus `test_review_triage_provider.py`,
  `test_llm_provider.py`, `test_ai_cli_backend.py` and `test_codex_screened_capture.py`.
- [x] **5. Check diff and commit** only Task 1 files:
  `feat: expose neutral tool-disabled inspection turns`.

## Task 2: Shared bounded host reader with triage compatibility

**Files:** Create `src/harness/inspection_io.py`,
`tests/unit/test_inspection_io.py`; modify `src/harness/review_triage_io.py`.
Adjust existing IO tests only when their patch target moves with extracted code;
do not weaken their assertions or change triage behavior.

**Consumes:** The current descriptor reader and helpers in `review_triage_io.py`.
Keep prose loading, source capture and Prosaic-specific validation in that module.

**Produces:**

```python
class InspectionReadError(ValueError): pass
class BoundedReadChannel:
    def __init__(self, roots: Mapping[str, Path], *,
                 forbidden_paths: tuple[Path, ...] = ()): ...
    def __enter__(self) -> BoundedReadChannel: ...
    def __exit__(self, *args: object) -> None: ...
    def request(self, value: object) -> dict[str, object]: ...
```

  Root aliases must be nonempty strings, supplied only by the host. Require a
  nonempty mapping; copy it so caller mutation cannot change admission. Preserve
  no-follow root opening and descriptor cleanup. Closed request schemas and
  result formats remain exactly those in existing `ReviewReadChannel.request`.
  There are no new model operations. The old error import remains a compatible
  alias (`ReviewTriageError = InspectionReadError`); the old constructor becomes:

```python
class ReviewReadChannel(BoundedReadChannel):
    def __init__(self, worktree: Path, spec_dir: Path) -> None:
        super().__init__({"worktree": worktree, "spec": spec_dir})
```

- [x] **1. Write consuming RED tests with real files.**

```python
def test_named_preparation_evidence_is_read_without_source_access(tmp_path):
    from harness.inspection_io import BoundedReadChannel
    run = tmp_path / "selected-run"
    run.mkdir()
    (run / "audit.md").write_text("FR-000001\nFR-1000000\n")
    with BoundedReadChannel({"evidence": run}) as channel:
        value = channel.request({"op":"read_file", "root":"evidence",
            "path":"audit.md", "start_line":2, "line_count":1})
    assert value == {"status":"ok", "text":"FR-1000000\n",
                     "start_line":2, "total_lines":2}
```

  Add supplied/unknown alias, caller mapping mutation, parent traversal, absolute
  path, integer booleans, unsafe schemas, symlink/hard-link/FIFO, mutation while
  reading, retained-root behavior and explicit unavailability bounds. Reuse
  existing real-filesystem fixture techniques without copying parser algorithms.
- [x] **2. Run RED:** `python -m pytest tests/unit/test_inspection_io.py -xq`.
- [x] **3. Extract the existing algorithms once.** Move `ReviewReadChannel`'s
  mechanics and filesystem-only helpers into `inspection_io.py`, naming the
  neutral class/error as above. Import shared descriptor helpers into triage's
  prose-capture code instead of leaving duplicate implementations. Preserve
  current exception messages/output payloads for existing operations.
- [x] **4. Add denied-path RED cases before implementing that guard.** Test a
  denied file, denied subtree, false-prefix sibling, alias pointing into a denied
  tree, denied names in listings, and a separately supplied evidence alias that
  attempts to reopen the denied content. All denied read/list requests must fail
  without opening the target; no automatic new triage exclusions.

  Capture absolute lexical root/denied paths without resolving away symlinks;
  reuse the existing no-follow root traversal. Component-wise containment, not
  string prefix, defines denial. Reject an authorized root equal to or below a
  denied path. Check candidate paths before servicing requests. For listings,
  omit directly denied children before reading their metadata; retain existing
  directory-size/output/mutation bounds. Do not build a new containment-policy
  loader: future fulfillment supplies its already-authorized paths.
- [x] **5. Verify and commit.** Run `test_inspection_io.py`,
  `test_review_triage_io.py`, `test_review_triage.py`, `test_review_loop.py` and
  `test_prosaic_prompt_loader.py`; check no duplicate filesystem algorithms or
  changes to triage role loading/limits. Commit only this task's files as
  `refactor: share bounded host inspection reads`.

## Task 3: Composed boundary acceptance and handoff

**Files:** Create `tests/unit/test_host_serviced_inspection.py`; update the design,
this checklist and `docs/element-identity-convergence-boundary.md` with actual
evidence. No new production workflow belongs to this task.

**Consumes:** The new facade and `BoundedReadChannel`, real provider adapters,
the existing scripted external process fixtures. **Produces:** Evidence that
the two boundaries compose without native model tools, not a fulfillment result.

- [x] **1. Add a parametrized Claude/Codex acceptance test.** Create separate
  private invocation directories and actual worktree/spec/evidence roots. The
  first scripted model response is exactly:

```json
{"action":"read","request":{"op":"read_file","root":"evidence","path":"audit.md","start_line":1,"line_count":2}}
```

  The test driver validates this literal test envelope, calls the real channel,
  JSON-frames its actual output into the second prompt, and dispatches a second
  no-tools turn. The scripted process checks that prompt contains the exact
  authored legacy/six-digit/seven-digit IDs and returns a literal final answer.
  Inspect both commands and real capture parsing; assert source/spec/evidence
  bytes unchanged and per-turn usage retained. Keep this test driver in tests;
  Phase 2 will define its own role envelopes, turn budgets and failure policy.
- [x] **2. Cover rejection at the composed boundary.** A forbidden read produces
  no next turn. A native tool event, malformed provider final record, unavailable
  isolation, timeout or overflow cannot become successful inspection. A provider
  failure preserves observed usage and never enters a generic fallback. Use
  native macOS sandbox probes already established by provider tests where
  applicable; distinguish command-shape assertions from executed OS controls.
- [x] **3. Run the final affected batch after final production changes:**

```bash
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_inspection_turn.py tests/unit/test_inspection_io.py tests/unit/test_host_serviced_inspection.py tests/unit/test_review_triage_provider.py tests/unit/test_review_triage_io.py tests/unit/test_review_triage.py tests/unit/test_review_loop.py tests/unit/test_llm_provider.py tests/unit/test_ai_cli_backend.py tests/unit/test_codex_screened_capture.py tests/unit/test_claude_delivery_scope.py tests/unit/test_delivery_slice_runner.py tests/unit/test_delivery_documentation.py tests/unit/test_fulfillment_preparation.py tests/unit/test_fulfillment_preparation_steps.py tests/unit/test_prosaic_prompt_loader.py -q
git diff --check
rg -n 'run_inspection_turn|BoundedReadChannel' src tests
```

  Confirm the only new non-test consumer of the shared reader is the compatible
  triage wrapper; no fulfillment/Ralph activation or Prosaic edits. Record
  pre-existing failures separately and stop on a required scope expansion.
- [x] **4. Request one independent read-only review** using requesting-code-review.
  Review protocol admission, actual no-tools profiles, forbidden-path aliases,
  extraction parity and lack of activation. Reuse fresh test receipts; correct
  demonstrated checkpoint defects with RED tests, not unrelated redesign.
- [x] **5. Record evidence and commit** tests/docs as
  `test: accept host-serviced inspection boundary`. State exact counts, scripted
  boundaries, unchanged legacy behavior and remaining Phase 2 work. Preserve
  this branch/worktree; no push, merge or installation.

## Self-review and execution

The plan covers the approved interface/reader reuse and its acceptance, not
the later fulfillment loop. Native settings and process parsers remain in
their existing adapters; the new interface neither advertises generic RE
capability nor broadens old read-only review claims. All new APIs are defined
above. Denied-path handling is limited to explicit host inputs; old triage
constructors retain their previous policy. Model API connectivity remains
distinct from model-accessible network tools.

Inline execution is recommended for these sequential shared-file changes,
consistent with the user's previous preference. Delegated execution is an
alternative only if the user chooses it. The user selected inline execution;
all three tasks are complete. The branch/worktree is retained without integration.

## Execution receipts (2026-09-14)

- Baseline: 97 existing triage provider/IO tests passed in 1.65s.
- Task 1: missing interface reproduced RED; 63 new tests passed, then 364
  surrounding provider tests passed in 3.19s. Commit `1bf7ec12`.
- Task 2: missing shared module and denied-path API reproduced RED. Six real
  macOS case/Unicode alias cases also failed before the conservative normalized
  component guard. 143 affected reader/triage/loader tests passed in 3.62s.
  Commit `80c67750`; no existing tests changed.
- Task 3: 15 composed cases passed in 0.61s, including the executed Claude
  sandbox probe. The initial affected batch passed 718 tests in 29.06s.
- Independent read-only review found a macOS firmlink denial bypass. Ten new
  cases reproduced it before correction (both path directions, root, descendant,
  read, listing and file). Device/inode-anchored normalized suffix comparisons
  now supplement lexical checks; no native execution controls were changed.
  Focused reader/triage/composed tests passed 111 cases in 1.45s. Commit
  `bcedd7f3`. The same reviewer independently rechecked the original reproduction
  and an absent-then-created denied leaf; no remaining findings.
- Final affected batch after all production corrections: **728 passed in
  29.34s**. `git diff --check` passed. Scope search found no new active workflow
  calls, duplicate filesystem implementations or Prosaic changes. Only the
  compatible triage wrapper is a production consumer of the shared reader.

Model processes were scripted; provider builders/parsers and host reads were
real. Claude's emitted macOS sandbox was executed, while Codex controls were
asserted on its native command. No live model call, installation, workflow
activation, push, merge or branch-wide acceptance is claimed. The next separate
checkpoint is neutral semantic fulfillment mapping/judgment and its host owner.
