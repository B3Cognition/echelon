# SUE Auto — Autonomic Pipeline Orchestrator Design

**Date:** 2026-07-20
**Status:** approved (session decisions: diagnose-only · named profiles · measured model split)
**Scope:** `scripts/sue_auto.py` — a sixth standalone stdlib-only script that runs the
existing five SUE tools as one robotic pipeline and produces a single consolidated
dossier. No changes to the five tools.

## Decisions (from brainstorming)

1. **Diagnose only.** The robot runs tiers, auto-selects dialectic drills, and writes
   a fix-ready dossier. It never edits specs and never dispatches `echelon spec change`.
2. **Named profiles.** `--profile lite|deep|forensic` with predictable per-profile cost.
3. **Measured model split.** Dialogue tiers (v1, v2, drills, j-graph) default to
   Sonnet 5 (`claude --model claude-sonnet-5`) — proven adequate 2026-07-20. The v3
   measurement defaults to the CLI's default model (Fable/Opus tier) — Sonnet proven
   not measurement-grade (SR 0.163 vs 0.454, 77/78 units flagged).

## Architecture

In-process orchestrator: `importlib`-loads the five sibling scripts (the same
mechanism v2–v5 use to load v1) and invokes each tool's `main(argv)` in sequence.
Tools keep writing their own reports beside the spec; sue_auto reads their artifacts
(JSON sidecars where they exist; v2's markdown via anchored regexes matching its
renderer's exact format) and builds `sue-dossier.md` + `sue-dossier.json` beside the
spec. Same conventions as the five tools: stdlib-only, exit codes 0/1/2/3,
report-collision guard, `--timeout` pass-through, replay-stub testability.

## CLI

```
python3 scripts/sue_auto.py <spec.md> [--profile lite|deep|forensic]
    [--model-cmd CMD] [--measure-model-cmd CMD] [--max-drills N]
    [--timeout SECS] [--json]
```

- `--model-cmd` overrides the dialogue-tier model (default `claude --model claude-sonnet-5`).
- `--measure-model-cmd` overrides the v3 reader model (default: CLI default resolution).
- `--max-drills` overrides the profile's drill cap.
- Prints the planned tiers and call estimate before running; no interactive prompts.

## Profiles

| Profile | Tiers | Drill cap | Est. calls |
|---|---|---|---|
| `lite` | v1 | 0 | 2 |
| `deep` (default) | v2 (3 readers) → v3 (`--passes 2`) → drills | 3 | ~59 |
| `forensic` | v2 → v3 (`--passes 2`) → j-graph (3 readers) → drills | 8 | ~100 |

Estimates are computed from the spec's unit count (v3 = readers × ceil(units/20) × passes)
and printed, not hard limits.

## Auto-drill selection (deterministic, zero model calls)

Drill slots are filled in order:

1. **v2 stable findings** (parsed from `socratic-consensus.md`): lens by verdict and
   question shape — CONTRADICTED → `parmenides`; UNANSWERABLE with "what is/define/
   mean" → `euthyphro`, "verify/recognize/criterion" → `meno`, "who/may/role/
   permitted" → `republic`, "how many/how long/at most/limit/bound" → `philebus`,
   otherwise → `theaetetus`. Seed = the finding's question text; target = its Target
   unit.
2. **v3 stable-low units** not already targeted, worst-first: lens by family —
   NFR → `philebus`, ERR → `sophist`, AC → `theaetetus`, FR/REQ → `euthyphro`.
   Seed = "the exact meaning and obligations of <unit-id>"; target = unit id.

Each drill runs `sue_dialectic.main` with the dialogue model. Since every drill
overwrites `socratic-dialogue.{md,json}`, the orchestrator reads the JSON after each
drill and embeds the trace summary in the dossier; the last drill's files remain on
disk.

## Dossier

`sue-dossier.md` (+ `.json` mirror): header (profile, models, calls estimated,
tier outcomes incl. failures), per-tier sections (v2 stable findings table, v3
measurement vector + stable-low, drill outcomes with terminal states, j-graph
consensus conflicts), and a **fix-ready summary** ranked by severity class:

1. drill `APORIA_*` terminals (lens, target, one-line failure)
2. v2 stable CONTRADICTED
3. v2 stable UNANSWERABLE
4. v3 stable-low units not covered above

Each entry carries evidence pointers (unit id, report file). The section is written
to be pasteable into an `echelon spec change` description.

## Degradation

A tier whose `main()` returns nonzero (including quota trips) is recorded as a
warning in the dossier; the pipeline continues to tiers that don't depend on it
(v3 runs even if v2 failed; drills run from whichever sources succeeded). Exit 0
iff the dossier was written and ≥1 tier succeeded; otherwise the first failing
tier's exit code propagates.

## Testing

`tests/unit/test_sue_auto.py`, offline throughout:
- Pure units: lens-selection table (verdict/question-shape/unit-family), profile
  planning + call estimates, v2 stable-finding parsing (snippet matching v2's
  renderer format), dossier rendering (fix-ready ordering), collision guard.
- Orchestration: monkeypatched tool mains (fake artifacts, forced failures) for
  sequencing and degradation; one true end-to-end `lite` run via the replay stub
  using v1's real payload shapes.

## Non-goals

Closed-loop fixing, echelon dispatch, adaptive budgets, changes to the five tools.
