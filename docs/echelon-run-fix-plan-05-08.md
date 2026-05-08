# Fix Plan: Remaining Issues from Echelon Run Analysis (2026-05-08)

**Source:** [echelon-run-analysis-05-08.md](echelon-run-analysis-05-08.md)
**Low-risk batch already shipped:** commit `be1241c` (23 issues, all Low severity)
**Remaining:** 24 issues — 5 High, 19 Medium

---

## Risk split

Issues are grouped into three implementation batches, lowest risk first.

| Batch | Issues | Type | Risk |
| --- | --- | --- | --- |
| M1 — Medium doc-only | #14, #15, #16, #18, #22, #27, #31, #32, #33, #39–42, #43, #44, #45, #47, #50 | Prompt/phase MD edits only | Low–Medium |
| M2 — Medium script/code | #3, #4, #5, #6 | Bash script + frontmatter + command file changes | Medium |
| H — High behavioral | #1, #2, #17, #30, #38 | Routing, dispatch ordering, append-not-overwrite | High |

---

## Batch M1 — Medium doc-only (16 issues)

Same approach as the low-risk batch: strengthen wording, add MANDATORY labels, add NEVER rules. No bash/Python changes.

### #14 — Constitution created without UNDERSTAND context

**File:** `extension/workflow/phases/phase1-constitution.md`

Add a "Context Extraction (MANDATORY)" step before the `speckit.constitution` call. COMMANDER must extract key domain concepts from `glossary.md`, `mental-model.md`, `boundaries.md`, and `assumptions.md` and pass a structured summary to the skill. Without this, the constitution is a generic template, not domain-specific.

Concrete addition: numbered checklist of 4 extractions + the exact text to prepend to the `speckit.constitution` invocation.

---

### #15 — `00-overview.md` never produced

**Files:** `extension/workflow/phases/phase1-what.md`, `extension/agents/exploration/cartographer.md`

`phase1-what.md` already lists `00-overview.md` in Expected Outputs — it's not getting produced.
- Add `00-overview.md` to the CARTOGRAPHER agent's Outputs section and to its echelon_result `output_files[]`.
- Add a post-dispatch verification bash one-liner: `[ -f "${spec_dir}/00-overview.md" ]`.

---

### #16 — Staging artifacts not moved to spec directory

**Files:** `extension/workflow/phases/phase1-what.md`, `extension/agents/exploration/cartographer.md`

CARTOGRAPHER's instructions say "move staging artifacts" but never specify which files or how. Make it concrete:
- Add a numbered "Step N: Move Staging Artifacts" to the CARTOGRAPHER agent protocol with an explicit file list and a `cp` + `rm` bash block.
- Add a verification step in `phase1-what.md` post-CARTOGRAPHER that checks at least one expected artifact (e.g., `glossary.md`) is present in `spec_dir`.

---

### #18 — Fallback path inverted (CARTOGRAPHER handles COMMANDER's role)

**File:** `extension/workflow/phases/phase1-what.md`

The fallback section §4.2 is correct but CARTOGRAPHER re-invoked `speckit.specify` itself instead of signalling BLOCKED. Add a NEVER rule directly in CARTOGRAPHER's agent file prohibiting self-re-invocation of `speckit.specify` on failure.

**File:** `extension/agents/exploration/cartographer.md`
- Add NEVER rule: "NEVER re-invoke `speckit.specify` if the spec directory is absent after the first call. Signal `CARTOGRAPHER BLOCKED — speckit.specify returned empty spec_dir` and let COMMANDER handle the fallback."

---

### #22 — `understanding-diagram` crashes with `disable-model-invocation`

**File:** `extension/agents/exploration/sage.md`

The agent calls `speckit.echelon.understanding-diagram` via the Skill tool, but this command has `disable-model-invocation: true`. It cannot be invoked via Skill. Fix: replace the Skill invocation with the equivalent bash command.

The understanding CLI exposes diagram generation as a direct CLI call (same binary as `understanding validate`). Replace:
```
Skill: speckit.echelon.understanding-diagram
```
with:
```bash
understanding diagram <spec.md> --diagram <spec_dir>/spec-diagram.svg
```
And update the surrounding prose to match.

---

### #27 — `phase-timing.sh` never called at any phase boundary (systematic)

**Files:** `extension/workflow/phases/phase2-decide.md`, `phase2-strategic-overview.md`, `phase3-specialists.md`, `phase3-sentinel.md`, `phase3-plan.md`, `phase3-consensus.md`

Each phase-boundary spec already contains a timing section but it's phrased as an inert description rather than an imperative instruction. For each file: convert the existing timing block from passive narrative to a numbered MANDATORY step with the exact bash invocation:

```bash
bash "${ECHELON_EXT}/scripts/bash/phase-timing.sh" start_phase <phase> <budget_seconds>
bash "${ECHELON_EXT}/scripts/bash/phase-timing.sh" end_phase <phase>
```

One phase file at a time — all phrasing changes, no logic changes.

---

### #31 — Specialists dispatched in parallel (should be sequential)

**File:** `extension/workflow/phases/phase3-specialists.md`

Add a NEVER rule: "NEVER dispatch multiple specialists in parallel using a single multi-Agent batch call (except INVESTIGATOR, which may run in parallel with domain specialists per the existing exemption)."

Add a dispatch loop template showing sequential dispatch with a post-dispatch protocol call between each specialist.

---

### #32 — INNOVATE not dispatched despite WHY2 failing 3×

**File:** `extension/workflow/phases/phase3-specialists.md`

The INNOVATE trigger list already exists but COMMANDER never evaluates it. Add a dedicated pre-dispatch evaluation block that explicitly checks each trigger condition and notes the expected `dispatch_innovate: true|false` decision in a journal entry. Trigger #3 ("WHY rejects spec 2+ times") must be checked against `state.json.quality_scores[]` — add the exact lookup logic.

---

### #33 — ARCHITECT missing `plan.md` and `contracts/`

**Files:** `extension/workflow/phases/phase3-how.md`, `extension/agents/solution/architect.md`

- `phase3-how.md` Expected Outputs already lists these; add post-dispatch verification bash (same pattern as phase3-sentinel.md fix).
- `architect.md` Outputs section: add `plan.md` and `contracts/` with their required content descriptions. Add a NEVER rule: "NEVER complete dispatch without producing `plan.md` and `contracts/`."

---

### #39–42 — REALIST, MIRROR, AUDITOR, SCOREKEEPER all skipped

**File:** `extension/workflow/phases/phase4-document.md`

Steps 12.1–12.7 exist but are structured as optional narrative. Restructure each into a numbered MANDATORY dispatch step with:
- Required context pack per agent
- Expected output files
- A post-dispatch check before proceeding to next step
- A NEVER rule at the top of the section: "NEVER jump to 12.8 (final state) without executing 12.1–12.7 in order."

Agents affected: REALIST (12.1), MIRROR (12.2), AUDITOR (12.4), SCOREKEEPER (12.7).

---

### #43 — `run-history.json` not written

**File:** `extension/workflow/phases/phase4-document.md`

Step 12.8 already has the write instruction but it's soft. Promote it to a MANDATORY step with a verification check:
```bash
python3 -c "import json; r=json.load(open('${spec_dir}/run-history.json')); assert any(e['run_id']=='${run_id}' for e in r['runs'])" || exit 1
```

---

### #44 — Staging not archived or cleaned

**File:** `extension/workflow/phases/phase4-document.md`

Step 12.10 has the archive/cleanup bash. Make it a numbered step with explicit precondition: "Only clean staging AFTER run-history.json is written and state.json.status = 'done'." Add an error-exit if archiving fails.

---

### #45 — Git not returned to default branch

**File:** `extension/workflow/phases/phase4-document.md`

Step 12.11 has the bash. Add NEVER rule: "NEVER end the run on the feature branch." Make the `git checkout` mandatory (not conditional on worktree state).

---

### #47 — ECHELON RUN COMPLETE banner not printed

**File:** `extension/workflow/phases/phase4-document.md`

Step 12.9 has the full banner template but it's not visually separated from surrounding prose. Promote it to a MANDATORY final step with a NEVER rule: "NEVER set status = 'done' or archive staging before printing this banner."

Emphasize the **HUMAN ACTIONS REQUIRED** section: "This section MUST always be present. If there are no human actions, print `None — squad resolved all items autonomously.` Never omit the section even if empty."

---

### #50 — `calibration-dashboard.md` never written; INTERNALIZER never dispatched

**Files:** `extension/agents/control/commander.md`, `extension/workflow/phases/phase4-document.md`

`commander.md` §"Per-Agent Internalization Data Handoff" already defines the AUDITOR→INTERNALIZER→SCOREKEEPER sequence but it's in a separate section not cross-referenced from `phase4-document.md`. Add an explicit cross-reference at step 12.4 in `phase4-document.md`: "Before dispatching AUDITOR, execute the Per-Agent Internalization Data Handoff protocol in commander.md §12 — INTERNALIZER must run before AUDITOR produces the calibration dashboard."

---

## Batch M2 — Medium script/code (4 issues)

These require changes to bash scripts, frontmatter, or command invocation files.

### #3 — `endocrine.sh` wrong path

**File:** `extension/scripts/bash/endocrine.sh`

The script constructs the state.json path as `${ECHELON_EXT}/.specify/squad/state.json` (incorrectly nesting `.specify/extensions/` before `.specify/squad/`). Fix: read `PROJECT_ROOT` from the first argument or from the calling environment; construct the path as `${PROJECT_ROOT}/.specify/squad/state.json`.

Verify with: `bash endocrine.sh get_full_prompt_modifier speckit-echelon-scout` in a project that has a valid state.json.

---

### #4 — `detect-project.sh` not invoked

**File:** `extension/commands/echelon.run.md`

The frontmatter `scripts.sh` field runs `startup-banner.sh`. `init.md` §1.1 says `detect-project.sh`'s output must be available as `$SH_OUTPUT`. Change the frontmatter `scripts.sh` to run `detect-project.sh` (possibly chaining `startup-banner.sh && detect-project.sh`, or moving banner output to detect-project.sh itself). Ensure `$SH_OUTPUT` captures the greenfield/brownfield verdict.

---

### #5 — `validate-deploy.sh` hard-stop guard skipped

**File:** `extension/workflow/phases/init.md`

The guard exists in §1.0 but COMMANDER never runs it. The issue is that init.md's bash blocks are instructions, but COMMANDER doesn't execute all of them.

Fix: promote the `validate-deploy.sh` check to the `scripts.sh` frontmatter field in `echelon.run.md` (alongside or instead of the banner script), so it runs automatically before the model sees the prompt. Alternatively, make it the first explicit bash block in init.md with a stronger HARD STOP signal COMMANDER must honour.

---

### #6 — Config resolution not called

**File:** `extension/workflow/phases/init.md`

§1.6 describes `specify extension config resolve echelon --format env` but COMMANDER reads `echelon-config.yml` directly. This means project overrides, local-config.yml, and env var layering are bypassed.

Fix: make §1.6 a numbered MANDATORY step with the `eval "$(specify extension config resolve ...)"` bash block and an explicit note: "All threshold values used during the run come from `ECHELON_CFG_*` env vars set here. Reading `echelon-config.yml` directly is incorrect — the raw file does not apply layering."

---

## Batch H — High severity (5 issues)

These change dispatch routing, file handling, or agent ordering. Higher risk of regressions — test each carefully.

### #1 — GUARDIAN not dispatched at initialization

**File:** `extension/agents/control/commander.md`

§"Run Initialization" step 1 prescribes dispatching GUARDIAN before any other agent, but this init-time dispatch is missing in practice. The current run dispatches GUARDIAN only in `phase3-specialists`.

Fix: make the init-time GUARDIAN dispatch a numbered step with a concrete Agent tool call block, clearly separated from the phase3-specialists dispatch. Add a NEVER rule: "NEVER proceed to phase1-discover before GUARDIAN has completed its Minimum Security Checklist on the project root." The init-time dispatch is lightweight (checklist only, not full STRIDE); full STRIDE runs in phase3-specialists if the domain is security-relevant.

---

### #2 — `reasoning-journal.jsonl` overwritten instead of appended

**File:** `extension/agents/control/commander.md`

The Post-Dispatch Protocol Step B says "Append the entry as a single JSON line" but COMMANDER uses the `Write` tool (which overwrites) instead of `Bash: echo '<json>' >> file` or `Edit`.

Fix: in the Post-Dispatch Protocol Step B, replace the current write instruction with an explicit append-only pattern:

```bash
echo '<single-line json entry>' >> .specify/squad/reasoning-journal.jsonl
```

Add a NEVER rule: "NEVER use the `Write` tool on `reasoning-journal.jsonl`. NEVER use `Edit` on it either — it is append-only. The only valid write operation is `echo '<json line>' >>` (shell append)." Clarify that the file does NOT get read back — only appended.

This is the highest-impact fix: without it, the journal is always a single-entry file after the second write.

---

### #17 — CARTOGRAPHER spec enhancement not executed

**Files:** `extension/agents/exploration/cartographer.md`, `extension/workflow/phases/phase1-what.md`

CARTOGRAPHER calls `speckit.specify` and returns without doing the second pass (domain insight injection, Given/When/Then acceptance criteria, glossary cross-reference). The agent prompt doesn't make clear that `speckit.specify` is only step 1 of 3.

Fix:
- In `cartographer.md`, restructure the process into three explicit numbered steps:
  1. Call `speckit.specify` to create the spec skeleton
  2. Move staging artifacts into `spec_dir` (links to #16 fix)
  3. Enhance `spec.md` with domain insights, GWT acceptance criteria, glossary cross-reference — this is the majority of CARTOGRAPHER's value
- In `phase1-what.md`, add a post-dispatch verification: the spec must contain at least one `WHEN … THEN` acceptance criterion or COMMANDER re-dispatches CARTOGRAPHER with explicit enhancement instructions.

---

### #30 — Specialists run AFTER ARCHITECT (ordering inversion)

**File:** `extension/agents/control/commander.md`

COMMANDER misread the state machine: it dispatches ARCHITECT (`phase3-how`) before specialists (`phase3-specialists`), but `phase3-specialists.md` transitions to `phase3-how` — meaning specialists run first, then ARCHITECT uses their outputs.

Fix in `commander.md`:
- Add an explicit routing reminder before the phase3 dispatch sequence: "ORDER IS: phase3-specialists → phase3-how → phase3-sentinel → phase3-plan → phase3-consensus. Specialists feed ARCHITECT; ARCHITECT does not feed backwards to specialists."
- Add a NEVER rule: "NEVER dispatch ARCHITECT before all phase3-specialists agents have completed."

This is a routing-only fix — no logic changes in phase files needed.

---

### #38 — PLAN2 dispatched without ASSESS2's `implementability-report.md`

**File:** `extension/workflow/phases/phase3-consensus.md`

The file already states dispatch order: WHY3+ASSESS2 in parallel, then PLAN2 after. In practice all three are dispatched simultaneously.

Fix:
- Convert the consensus dispatch section from a "parallel" description into a two-step sequence: `{WHY3, ASSESS2}` together, then wait for both to complete, then `{PLAN2}` with ASSESS2's `implementability-report.md` in context.
- Add a NEVER rule: "NEVER dispatch PLAN2 simultaneously with ASSESS2. PLAN2 is a sequential follow-on, not a parallel peer."
- Add a post-ASSESS2 verification: `[ -f "${spec_dir}/implementability-report.md" ]` before PLAN2 dispatch.

---

## Implementation order

```
M1 (16 issues, doc-only)  →  M2 (4 issues, scripts)  →  H (5 issues, behavioral)
```

Within M1, suggested file grouping to minimize context-switching:

1. `phase4-document.md` — #39–42, #43, #44, #45, #47, #50 (6 items, one file)
2. `phase3-specialists.md` — #31, #32 (2 items, one file)
3. `phase3-how.md` + `architect.md` — #33 (1 item, 2 files)
4. `phase1-what.md` + `cartographer.md` — #15, #16, #18 (3 items, 2 files)
5. `phase1-constitution.md` — #14 (1 item)
6. `sage.md` — #22 (1 item)
7. Six phase MDs (phase2–phase3 boundaries) — #27 (1 item, 6 files)
8. `tracker.md` cross-ref — #50 (commander.md half)

M2 can be a single focused commit (4 script/frontmatter changes).
H should be committed one issue at a time with a test run between each.

## Verification gates

**After M1:** `python3 -m pytest tests/unit/ -q` must remain green. `prompt_lint.py` delta should be ≤ +20 occurrences.

**After M2:** manually run `bash extension/scripts/bash/endocrine.sh get_full_prompt_modifier speckit-echelon-scout` against a test project; confirm `$SH_OUTPUT` is greenfield/brownfield. Run unit tests.

**After each H issue:** run a mini `echelon run` on a trivial spec (single-sentence request) and verify the specific behaviour changed. For #2 (append), check `.specify/squad/reasoning-journal.jsonl` has multiple lines after the run. For #30 (ordering), verify GUARDIAN runs before ARCHITECT in the tool-call sequence.
