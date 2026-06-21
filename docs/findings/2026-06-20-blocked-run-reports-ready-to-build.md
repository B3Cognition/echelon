# Finding: a blocked / incomplete Phase-A run reports "READY TO BUILD"

**Date:** 2026-06-20
**Severity:** High (correctness / trust — the run pipeline declares success on a failed run)
**Found during:** live `echelon run "build echelon frontend"` (headless CLI path) in an external project, while validating the lexicon tasks-grammar gate.
**Status:** open — write-up only, no fix applied.

## Symptom

A headless `echelon run` blocked in `phase1-what` (CARTOGRAPHER could not invoke the
`speckit.specify` skill — absent from that environment — and correctly refused to
hand-author `spec.md`). At that point **only `constitution.md` existed**: no `spec.md`,
no `plan.md`, no `tasks.md`, and WHY2 never ran.

The CLI nonetheless printed:

```
╭─ ✈ echelon · NEXT STEP ─────────────────╮
│  READY TO BUILD                         │
ready   ✓ constitution.md ✓
next    echelon harness run <spec-id>
warnings
  ⚠ WHY2 not yet run — spec validation pending
  ⚠ Run blocked
```

A follow-up `echelon continue` then reported **"Build is ready — nothing left to do in
Phase A."** Both surfaces told the operator to proceed to `echelon harness run` on a run
that had produced no specification at all.

## Mechanism (root cause)

`src/echelon/cli.py:1720-1739` (the NEXT STEP banner):

```python
subtitle = "BUILD BLOCKED — fix blockers before running" if blockers else ""
if not blockers:
    if ready_items:
        fields.append(("ready", "\n".join(f"✓ {item}" for item in ready_items)))
    fields.append(("next", harness_cmd))
    if warnings:
        fields.append(("warnings", "\n".join(f"⚠ {w}" for w in warnings)))
    subtitle = "READY TO BUILD"          # <-- fires whenever `blockers` is empty
```

The readiness subtitle keys **only** on the `blockers` list being empty. But the
terminal blocked state — and "WHY2 not yet run" — are pushed onto `warnings`
(`cli.py:1714-1718`, `1698-1708`), **not** `blockers`. So a run that ended blocked,
with no `spec.md`/`tasks.md`, has an empty `blockers` list and is rendered
**READY TO BUILD** with the failure demoted to a warning.

This also **contradicts the strict readiness predicate** that already exists in the
same file:

```python
# src/echelon/cli.py:2331-2349
def _phase_a_ready_to_build(project_root, current_state) -> bool:
    ...
    return all((spec_dir / name).exists()
               for name in ("plan.md", "research.md", "data-model.md", "tasks.md"))
```

`_phase_a_ready_to_build` correctly requires the build-input artifacts. The banner does
not reuse it — it invents a weaker, second definition of "ready." The two disagree, and
the user-facing banner is the wrong one.

## Why it matters

"Ready to build" is an instruction the operator (or an automation wrapper) acts on.
Following it here runs `echelon harness run` against a spec directory with **no spec and
no tasks** — at best a wasted build, at worst a downstream agent inventing scope from an
empty contract. A pipeline that reports *ready/success* on a *blocked/incomplete* run is
a bug class, not a one-off: the failure is silent and looks identical to a healthy run.

## Recommended fix

1. **One readiness definition.** The banner must gate "READY TO BUILD" on the same
   predicate the build actually needs — at minimum `spec.md` **and** `tasks.md` present
   (reuse / extend `_phase_a_ready_to_build`, or factor a shared
   `_build_inputs_present(spec_dir)`), AND `run_status != "blocked"`.
2. **Blocked status is a blocker, not a warning.** When `run_status == "blocked"` (or a
   terminal-block reason is set), add it to `blockers` so the subtitle renders
   `BUILD BLOCKED` / `RUN INCOMPLETE`, not `READY TO BUILD`.
3. **Missing core artifacts are blockers.** "WHY2 not yet run" / "spec.md absent" should
   block readiness, not merely warn, since the harness consumes them.
4. **Regression test.** A unit test that builds a state with only `constitution.md` +
   `run_status="blocked"` and asserts the banner subtitle is NOT `READY TO BUILD` and the
   `next` action is a remediation, not `echelon harness run`.

## Scope note

This is independent of the lexicon tasks-grammar feature (the gate itself behaved
correctly in this run — it was the host run-state reporting that misled). Tracked
separately so it does not ride on the lexicon PR.
