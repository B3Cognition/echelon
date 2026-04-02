# Plan A — Golddigger Single-Pass (Remove Mode 2)

**Status:** Draft — under evaluation  
**Date:** 2026-04-02

## Summary

Remove Mode 2 (on-demand deep dive) entirely. Mode 1 becomes the only extraction pass,
running at full depth with high quality thresholds. SCOUT and downstream agents receive
complete brownfield data upfront — no mid-pipeline re-dispatches.

## Config Changes

### Mode 1 — Survey (single-repo)

```yaml
depth:
  level: full                  # was: signatures
workflow:
  coverage_threshold: 99       # was: 60
  resolution_threshold: 99     # was: 60
  max_validate_iterations: 5   # was: 1
  git_history_limit: 2500      # new
  max_lines_per_file: 5000     # new
output:
  generate_spec: true          # was: false
  generate_plan: false
  generate_tasks: false
```

### Mode 1 — Survey (polyrepo)

Same as above. Adaptive depth / auto-promotion logic (Step 1b) is removed — all repos
run at full depth. The polyrepo per-repo override section in the config is dropped.

### Mode 2 — Deep Dive

**Removed entirely.**

## Agent Changes Required

### golddigger.md — Moderate scope, Low risk
- Update both Mode 1 config profiles (single-repo + polyrepo) with new values above
- Remove adaptive depth python script (Step 1b) — auto-promotion no longer needed
- Remove "Mode 2 — Deep Dive" config profile block
- Remove entire "Mode 2 — Deep Dive (single domain)" section (Steps 1–5 + completion signal)
- Remove NEVER rules #2 and #4 (reference `golddigger_completed_domains` / `golddigger_requests`)
- Update role description line (remove "Mode 2 with a specific domain and optional repo")
- Remove Mode 2 completion signal block

### commander.md — Medium scope, Medium risk
- Remove Section 4 entirely: "GOLDDIGGER Mode 2 Queue (Phase 1 agents)"
- Remove state.json fields: `golddigger_requests`, `golddigger_completed_domains`
- Remove `"deep-dive"` as a valid `golddigger_mode` value

### scout.md — Small scope, Low risk
- Remove Step 6 entirely: "Evaluate Domain Depth for Deep Dive Requests" (incl. python snippet)
- Update Step 1 single-repo mode: domain specs now always exist (Mode 1 generates them),
  remove conditional wording "if domain specs exist"
- Remove beliefs SCT-006 and SCT-007

### synthesizer.md — Small scope, Low risk
- Remove Step 3b: "Request Deep Dives for Unresolvable Contradictions"

### cartographer.md — Small scope, Low risk
- Remove "GOLDDIGGER Mode 2 Deep Dive Requests" section
- Remove belief CAR-008

### config-template.yml — Trivial, Very low risk
- Add under `discovery:`:
  ```yaml
  git_history_limit: 2500
  max_lines_per_file: 5000
  ```

### echelon-config.yml — Trivial, Very low risk
- Add matching entries under `discovery:`

## Change Surface Summary

| File | Change type | Scope | Risk |
|------|-------------|-------|------|
| golddigger.md | Update configs + remove Mode 2 section | ~150 lines removed/changed | Low |
| commander.md | Remove queue section + state field cleanup | ~20 lines removed | Medium |
| scout.md | Remove Step 6 + 2 beliefs | ~40 lines removed | Low |
| synthesizer.md | Remove Step 3b | ~25 lines removed | Low |
| cartographer.md | Remove Mode 2 section + 1 belief | ~30 lines removed | Low |
| config-template.yml | Add 2 params | 2 lines added | Very low |
| echelon-config.yml | Add 2 params | 2 lines added | Very low |

## Trade-offs

**Pros:**
- Simplifies the pipeline significantly — no queue management, no cache, no mid-pipeline surprises
- SCOUT gets complete data upfront — no unknown unknowns from partial coverage
- Removes the "SCOUT must know what it doesn't know" problem inherent in on-demand Mode 2
- Deterministic cost — single extraction pass, predictable token spend

**Cons:**
- Mode 1 will be significantly slower and more expensive (full AST at 99% vs signatures at 60%)
- If gatekeeper kills the spec in Phase 2, the full extraction was wasted
- Large codebases with many irrelevant modules still get fully analyzed
- No surgical targeting — domains the spec doesn't touch still get full extraction
