# Terminal Handoff Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render one compact Phase A lifecycle banner with a grounded paragraph-style handoff, an integrated next action, and an explicit secondary provider-limit line when a limit caused the authoritative controller contract failure.

**Architecture:** Preserve controller authority while carrying a bounded provider-limit observation beside the authoritative stop reason. Extend the existing bounded `WorkedOnEvidence` packet, deterministically build four-to-eight grounded narrative candidates, and let SUMMARIZER select/order only opaque candidate IDs. Refactor next-step analysis into a reusable presentation object so lifecycle banners can embed it while standalone commands retain the existing `NEXT STEP` card.

**Tech Stack:** Python 3, Click-style Echelon CLI functions, pytest, Prosaic agent prompt artifacts, JSON run state, existing `echelon.ui.banner` renderer.

## Global Constraints

- Phase A `run`, `continue`, and `resume` exits render exactly one lifecycle banner.
- The authoritative stop reason remains `controller_state_contract_validation_failed` when required provider output is missing or invalid.
- A provider limit is a secondary bounded observation and cannot change recovery authority, exit codes, or result-contract validation.
- SUMMARIZER remains a separate `fast` model with `low` effort and normal provider tool availability.
- Selected and fallback handoffs contain four-to-eight short, unbulleted, controller-owned evidence-grounded lines.
- No free-form model-authored string is rendered; SUMMARIZER only selects and orders known candidate IDs.
- The displayed task is the first non-empty cleaned line, truncated to 160 characters with an ellipsis.
- Standalone commands without a lifecycle summary retain actionable `NEXT STEP` output.
- Raw provider transcripts and raw SUMMARIZER JSON never reach terminal handoff output.
- Existing unrelated worktree changes must be preserved.

---

### Task 1: Preserve and Render Dual-Cause Provider Limits

**Files:**
- Modify: `src/harness/squad.py:8821-8848, 9050-9130`
- Modify: `src/harness/squad_state.py:2793-2840`
- Modify: `src/echelon/cli.py:4498-4615`
- Test: `tests/integration/test_squad_controller.py:2123-2167`
- Test: `tests/unit/test_cli_worked_on_summary.py`

**Interfaces:**
- Consumes: canonical `SquadAgentResult.provider_limit_message: str` produced by `detach_squad_agent_result`.
- Produces: `SquadStateStore.merge_advance_failure_diagnostic(..., removals: frozenset[str] = frozenset()) -> bool` and current-dispatch `state["provider_limit_message"]` evidence.
- Produces: `_print_squad_summary(...)` renders `("provider", message)` for any blocked current dispatch carrying a non-empty provider limit, even when `stopped` is a controller contract reason.

- [ ] **Step 1: Change the controller preparation regression to require both causes**

Update `test_provider_limit_without_result_fails_closed_at_preparation` so it keeps these authoritative assertions:

```python
assert state["blocked_reason"] == "controller_state_contract_validation_failed"
assert state["controller_contract_error"]["json_path"] == "$.echelon_result"
```

and replaces the discarded-message assertions with:

```python
assert state["provider_limit_message"] == (
    "You've hit your session limit · resets 4am (Europe/Prague)"
)
assert "session limit" not in json.dumps(state["controller_contract_error"])
```

- [ ] **Step 2: Add failing stale-state and banner tests**

Add a store/controller regression that starts with a historical
`provider_limit_message`, records a non-provider preparation failure, and asserts
the key is removed. Add a CLI regression using state with both
`blocked_reason="controller_state_contract_validation_failed"` and a provider
message:

```python
_print_squad_summary(
    tmp_path,
    squad_dir,
    SimpleNamespace(status="blocked", phase="phase3-plan"),
    mode="semi",
    message="Implement provider model resolution",
)
output = capsys.readouterr().out
assert "stopped    controller_state_contract_validation_failed" in output
assert "provider   You've hit your session limit" in output
```

- [ ] **Step 3: Run the new tests and confirm RED**

Run:

```bash
pytest tests/integration/test_squad_controller.py::TestAgentResultIntegrity::test_provider_limit_without_result_fails_closed_at_preparation tests/unit/test_cli_worked_on_summary.py -q
```

Expected: FAIL because preparation diagnostics discard the provider message and the banner only renders it for `stopped == "provider_session_limit"`.

- [ ] **Step 4: Add exact diagnostic removals to the state store**

Extend the state-store method without changing existing callers:

```python
def merge_advance_failure_diagnostic(
    self,
    *,
    from_phase: str,
    expected_state_revision: int,
    expected_previous_dispatch_sha256: str | None,
    updates: dict[str, Any],
    removals: frozenset[str] = frozenset(),
    token_usage_delta: int = 0,
) -> bool:
    ...
    next_state = deepcopy(state)
    for key in removals:
        next_state.pop(key, None)
    next_state.update(deepcopy(updates))
```

Keep the existing lock, phase/revision/dispatch compare-and-swap checks, token
accounting, and authority audit unchanged.

- [ ] **Step 5: Carry only a canonically detached provider observation into preparation failure**

In `_prepare_phase_result_or_block`, derive the message through
`detach_squad_agent_result(result)` inside the existing preparation boundary.
Pass the cleaned canonical message into `_block_after_state_advance_failure`.
Extend that method with `provider_limit_message: str = ""` and build diagnostic
updates/removals as follows:

```python
diagnostic_updates = {
    "status": "blocked",
    "blocked_reason": "controller_state_contract_validation_failed",
    "controller_contract_error": {...},
    "recovery_instruction": recovery.to_dict(),
}
diagnostic_removals = frozenset({"provider_limit_message"})
if provider_limit_message:
    diagnostic_updates["provider_limit_message"] = provider_limit_message
```

This keeps the provider message outside `controller_contract_error`, replaces a
current observation atomically, and deletes a stale one for non-provider failures.

- [ ] **Step 6: Render the current provider observation independently of the stop reason**

Replace the stop-reason equality guard in `_print_squad_summary` with:

```python
if status == "blocked":
    provider_message = str(state.get("provider_limit_message") or "").strip()
    if provider_message:
        fields.append(("provider", provider_message))
```

Do not alter `_classify_run_recovery`, `stopped`, the recovery instruction, or the
process exit status.

- [ ] **Step 7: Run focused controller and CLI tests**

Run:

```bash
pytest tests/integration/test_squad_controller.py -k 'provider_limit_without_result or preparation' -q
pytest tests/unit/test_cli_worked_on_summary.py tests/unit/test_cli_continue.py -q
```

Expected: PASS, including stale-message removal.

- [ ] **Step 8: Commit the dual-cause behavior**

```bash
git add src/harness/squad.py src/harness/squad_state.py src/echelon/cli.py tests/integration/test_squad_controller.py tests/unit/test_cli_worked_on_summary.py tests/unit/test_cli_continue.py
git commit -m "fix: surface provider limits beside controller failures"
```

---

### Task 2: Produce Rich Paragraph-Style Worked-On Handoffs

> **Approved protocol revision:** The original free-prose validator reached its
> five-round review breaker. Replace it with the closed candidate-selection
> protocol below. This revision supersedes Steps 2 and 5 wherever they refer to
> generated `lines` or semantic prose validation.

**Files:**
- Modify: `src/harness/worked_on_summary.py`
- Modify: `prosaic/subagents/echelon.summarizer.md`
- Modify: `tests/unit/test_worked_on_summary.py`
- Modify: `tests/unit/test_cli_worked_on_summary.py`
- Modify: `docs/agent-role-catalog.md`

**Interfaces:**
- Consumes: durable Phase A/delivery state and canonical result facts.
- Produces: extended `WorkedOnEvidence` fields `duration: str`, `outcomes: tuple[str, ...]`, `commits: tuple[str, ...]`, `provider_limit_message: str`, and `next_note: str`.
- Produces: frozen `NarrativeCandidate(id: str, text: str, priority: int, required: bool = False)` and `narrative_candidates(evidence: WorkedOnEvidence) -> tuple[NarrativeCandidate, ...]`.
- Produces: `_selected_candidate_ids(raw: str, candidates: Sequence[NarrativeCandidate]) -> tuple[str, ...] | None` accepting exactly `{"line_ids": [...]}` with four-to-eight unique known IDs and every required ID.
- Produces: `format_worked_on(lines: Sequence[str]) -> str` joining plain lines without glyphs.

- [ ] **Step 1: Add failing evidence serialization and formatting tests**

Cover round-trip/deferred evidence for the five new fields, byte-budget retention
of blocker/provider/verification/next facts, and plain formatting:

```python
assert format_worked_on(("Implemented the resolver.", "Verification passed.")) == (
    "Implemented the resolver.\nVerification passed."
)
assert "•" not in format_worked_on(("Implemented the resolver.",))
```

Add a task-display regression proving a multi-line request renders only the first
non-empty line and never exceeds 160 characters including the ellipsis.

- [ ] **Step 2: Add failing candidate-selection contract tests**

Build candidate fixtures with stable IDs and use the fake provider to return:

```json
{"line_ids":["outcome","changes","verification","readiness"]}
```

Assert the four controller-owned candidate texts render without bullets. Add
invalid cases for two IDs, nine IDs, unknown IDs, duplicate IDs, raw JSON
commentary, and omission of a required blocker, provider-limit, or next-action ID.
Assert model-provided text fields are rejected and never rendered.

- [ ] **Step 3: Run the worked-on tests and confirm RED**

Run:

```bash
pytest tests/unit/test_worked_on_summary.py tests/unit/test_cli_worked_on_summary.py -q
```

Expected: FAIL because the current contract does not expose the closed candidate
selection protocol.

- [ ] **Step 4: Extend the bounded evidence packet**

Add the five fields to `WorkedOnEvidence`, include tuple fields in normalization
and deferred round trips, and revise truncation priority so these fields survive
before artifact/task/phase inventories. Populate:

- duration from recorded result/state timing when present;
- outcomes and exact verification facts only from durable state/result fields;
- commits only from lifecycle-attributed commit records, formatted as bounded
  `short SHA — subject` strings;
- provider limit from `state["provider_limit_message"]` or the selected delivery
  result's canonical state;
- next note from recovery classification or persisted delivery guidance.

Do not call `git log` to infer run ownership.

- [ ] **Step 5: Implement candidate construction, selection, and fallback**

Create candidates deterministically from evidence. Stable candidate families are
`outcome`, `progress`, `outcome-*`, `decision-*`, `verification`, `commit-*`,
`blocker`, `provider-limit`, `readiness`, and `next-action`. Mark `blocker`,
`provider-limit`, and `next-action` required when their evidence is present for an
unfinished run. Candidate text must preserve exact durable commands and commit
facts without parsing or rewriting shell syntax.

Validate only the closed external contract:

```python
def _selected_candidate_ids(
    raw: str,
    candidates: Sequence[NarrativeCandidate],
) -> tuple[str, ...] | None:
    payload = json.loads(raw)
    if not isinstance(payload, dict) or set(payload) != {"line_ids"}:
        return None
    ids = payload["line_ids"]
    if not isinstance(ids, list) or not 4 <= len(ids) <= 8:
        return None
    # require strings, uniqueness, known IDs, and every required candidate ID
```

Look up selected text exclusively from the candidate map. Rewrite
`fallback_summary` as deterministic candidate ordering using priority and required
IDs. Never inspect or render model-authored text. Sparse evidence still produces
four factual candidates from attempted command, recorded lack of progress, stop
status, and recovery action.

- [ ] **Step 6: Render plain lines and bound the task field**

Change:

```python
def format_worked_on(lines: Sequence[str]) -> str:
    return "\n".join(lines)
```

Add a CLI helper `_terminal_task_summary(message: str, limit: int = 160) -> str`
that selects the first non-empty line, collapses whitespace, and truncates with
an ellipsis. Use it for the `task` field in `_print_squad_summary`.

- [ ] **Step 7: Update the SUMMARIZER prompt and agent catalog**

Change the exact response rule to `{"line_ids": [...]}` with four-to-eight unique
IDs copied from the supplied candidate list. Require all IDs marked `required`,
outcome-first ordering, and no unknown IDs or text fields. State explicitly that
SUMMARIZER selects and orders but never authors terminal prose. Preserve
untrusted-input rules, normal tool availability, `model_tier: fast`, and
`effort: low`.

- [ ] **Step 8: Run focused summary tests**

Run:

```bash
pytest tests/unit/test_worked_on_summary.py tests/unit/test_cli_worked_on_summary.py tests/unit/test_run_skill.py -q
```

Expected: PASS with unbulleted generated and fallback handoffs.

- [ ] **Step 9: Commit the richer handoff**

```bash
git add src/harness/worked_on_summary.py prosaic/subagents/echelon.summarizer.md tests/unit/test_worked_on_summary.py tests/unit/test_cli_worked_on_summary.py docs/agent-role-catalog.md
git commit -m "feat: render evidence-rich worked-on handoffs"
```

---

### Task 3: Integrate Next-Step Guidance into Lifecycle Banners

**Files:**
- Modify: `src/echelon/cli.py:4498-4615, 5204-5648, 6570-6585, 9240-9330`
- Modify: `tests/unit/test_cli_status.py`
- Modify: `tests/unit/test_cli_next_step_escalation.py`
- Modify: `tests/unit/test_cli_worked_on_summary.py`
- Modify: `tests/unit/test_cli_continue.py`
- Modify: `tests/unit/test_cli_harness_resume.py`

**Interfaces:**
- Produces: frozen `_NextStepPresentation` with `subtitle: str` and `fields: tuple[tuple[str, str], ...]`.
- Produces: `_next_step_presentation(project_root: Path, result_status: str) -> _NextStepPresentation | None` containing the existing analysis without printing.
- Produces: `_format_embedded_next_step(presentation: _NextStepPresentation) -> str` for one `next` section.
- Preserves: `_print_next_steps(project_root, result_status) -> None` as the standalone rendering wrapper.

- [ ] **Step 1: Add failing pure-planner compatibility tests**

For ready, retry-phase, human-resume, manual-recovery, harness-converged, and
provider-limited fixtures, assert `_next_step_presentation` returns the same
subtitle and ordered fields currently asserted from `_print_next_steps` output.
Keep one wrapper test proving `_print_next_steps` still renders `NEXT STEP`.

- [ ] **Step 2: Add failing exactly-one-banner lifecycle tests**

Patch lifecycle dependencies and assert for `run`, `continue`, direct `resume`,
and nested resume-to-continue:

```python
assert output.count("SQUAD SUMMARY") == 1
assert output.count("Worked on") == 1
assert "echelon · NEXT STEP" not in output
assert "\n  next\n  ────\n" in output
```

For a completed run, assert the embedded section retains the delivery command.
For a blocked run, assert it retains reason, recovery note, and resume/continue
command.

- [ ] **Step 3: Run lifecycle and next-step tests and confirm RED**

Run:

```bash
pytest tests/unit/test_cli_status.py tests/unit/test_cli_next_step_escalation.py tests/unit/test_cli_worked_on_summary.py tests/unit/test_cli_continue.py tests/unit/test_cli_harness_resume.py -q
```

Expected: FAIL because `_print_next_steps` prints directly and lifecycle handlers
emit a second banner or a separate `SQUAD RESUMED` card.

- [ ] **Step 4: Separate next-step analysis from rendering**

Introduce:

```python
@dataclass(frozen=True)
class _NextStepPresentation:
    subtitle: str
    fields: tuple[tuple[str, str], ...]

def _print_next_steps(project_root: Path, result_status: str) -> None:
    presentation = _next_step_presentation(project_root, result_status)
    if presentation is not None:
        _banner(
            "NEXT STEP",
            list(presentation.fields),
            subtitle=presentation.subtitle,
        )
```

Move each early `_banner(...); return` branch in the existing function to return
`_NextStepPresentation(subtitle, tuple(fields))`. Return `None` for statuses that
currently print nothing. Preserve field order and every specialized readiness,
decision, rewind, manual-recovery, delivery, and provider-reset branch.

- [ ] **Step 5: Format one embedded next section**

Implement a bounded formatter that places the primary command first and preserves
the remaining labels as readable lines:

```python
def _format_embedded_next_step(presentation: _NextStepPresentation) -> str:
    command = next((value for key, value in presentation.fields if key == "next"), "")
    details = [
        f"{key}: {value}"
        for key, value in presentation.fields
        if key != "next" and value
    ]
    return "\n".join(item for item in (command, *details) if item)
```

Preserve multi-line field values and do not repeat the presentation subtitle as a
second banner-like heading.

- [ ] **Step 6: Embed guidance in `_print_squad_summary`**

Compute `_next_step_presentation(project_root, status)` once. Remove the existing
ad hoc `continue`/`note` fields when the planner supplies guidance, pass the same
command/note into `phase_a_evidence`, and append:

```python
if presentation is not None:
    embedded = _format_embedded_next_step(presentation)
    if embedded:
        fields.append(("next", embedded))
```

Place `next` after `worked on`. This requires attaching the worked-on field before
the embedded next field rather than appending it last.

- [ ] **Step 7: Route run, continue, and resume through one final summary**

Remove `_print_next_steps` immediately following `_print_squad_summary` in the run
path. Replace the terminal direct-resume `SQUAD RESUMED` card plus next-step card
with `_print_squad_summary` using persisted mode, task, targets, and the controller
result. For terminal-blocked resume delegation, do not print the preliminary
`SQUAD RESUMED` card; let the nested continue path own the single final handoff.

Keep standalone `_cmd_status` and other non-lifecycle callers on
`_print_next_steps`.

- [ ] **Step 8: Run focused lifecycle and next-step tests**

Run:

```bash
pytest tests/unit/test_cli_status.py tests/unit/test_cli_next_step_escalation.py tests/unit/test_cli_worked_on_summary.py tests/unit/test_cli_continue.py tests/unit/test_cli_harness_resume.py tests/unit/test_cli_mode_args.py -q
```

Expected: PASS; standalone next-step output survives and lifecycle exits contain
one banner with embedded guidance.

- [ ] **Step 9: Commit integrated terminal presentation**

```bash
git add src/echelon/cli.py tests/unit/test_cli_status.py tests/unit/test_cli_next_step_escalation.py tests/unit/test_cli_worked_on_summary.py tests/unit/test_cli_continue.py tests/unit/test_cli_harness_resume.py tests/unit/test_cli_mode_args.py
git commit -m "refactor: unify Phase A terminal handoffs"
```

---

### Task 4: Cross-Lifecycle Verification and Documentation

**Files:**
- Modify: `README.md:600-610`
- Modify: `docs/agent-role-catalog.md` if Task 2 did not fully describe the final contract
- Test: `tests/unit/test_worked_on_summary.py`
- Test: `tests/unit/test_cli_worked_on_summary.py`
- Test: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Consumes: completed dual-cause, SUMMARIZER, and integrated-next interfaces from Tasks 1–3.
- Produces: documented terminal contract and final verified feature branch.

- [ ] **Step 1: Add one representative transcript regression**

Create a blocked Phase A fixture matching the reported failure: a long multi-line
task, `controller_state_contract_validation_failed`, a provider reset message,
22 completed phases, and continue recovery. Assert:

```python
assert output.count("echelon · SQUAD SUMMARY") == 1
assert "echelon · NEXT STEP" not in output
assert "You've hit your session limit" in output
assert full_multiline_task not in output
assert output.count("worked on") == 1
assert "echelon spec continue" in output
```

- [ ] **Step 2: Run the representative regression and confirm it passes**

Run:

```bash
pytest tests/unit/test_cli_worked_on_summary.py -k 'provider or transcript or lifecycle' -q
```

Expected: PASS.

- [ ] **Step 3: Update user-facing documentation**

Document that Phase A terminal handoffs:

- use one lifecycle banner;
- show the authoritative stop plus a provider limit when both apply;
- contain four-to-eight plain evidence-grounded `worked on` lines;
- integrate the next action;
- truncate display-only task text while retaining the full request in artifacts.

- [ ] **Step 4: Run formatting and focused verification**

Run:

```bash
ruff check src/harness/worked_on_summary.py src/harness/squad.py src/harness/squad_state.py src/echelon/cli.py tests/unit/test_worked_on_summary.py tests/unit/test_cli_worked_on_summary.py tests/integration/test_squad_controller.py
pytest tests/unit/test_worked_on_summary.py tests/unit/test_cli_worked_on_summary.py tests/unit/test_cli_status.py tests/unit/test_cli_next_step_escalation.py tests/unit/test_cli_continue.py tests/unit/test_cli_harness_resume.py tests/unit/test_cli_mode_args.py tests/unit/test_run_skill.py -q
pytest tests/integration/test_squad_controller.py -k 'provider or preparation or advance_failure' -q
```

Expected: all selected checks PASS.

- [ ] **Step 5: Run bundle checks and the broader relevant suite**

Run the repository's documented bundle validation command, then the broader
relevant suite:

```bash
./scripts/bash/dry-run.sh
pytest tests/unit tests/integration/test_squad_controller.py -q
```

Record any pre-existing baseline failures by reproducing them on the main
worktree; do not alter unrelated capability-policy behavior.

- [ ] **Step 6: Live-test in a disposable workspace**

Use a new temporary Hello World repository and the feature worktree's Echelon
entry point. Exercise proportional CARTOGRAPHER spec authoring and a lifecycle
exit. Confirm one banner, an unbulleted narrative, integrated next guidance, no
raw JSON/provider progress, and the real separate SUMMARIZER path when provider
capacity is available. If a provider limit occurs, confirm the dual-cause line.

- [ ] **Step 7: Commit documentation and final regression coverage**

```bash
git add README.md docs/agent-role-catalog.md tests/unit/test_worked_on_summary.py tests/unit/test_cli_worked_on_summary.py tests/integration/test_squad_controller.py
git commit -m "docs: explain unified terminal handoffs"
```

- [ ] **Step 8: Review the complete diff**

Run:

```bash
git diff --check
git status --short
git log --oneline --decorate -8
```

Confirm the worktree contains only intentional changes and all plan tasks have a
corresponding test or verification result.
