# Context Pack Assembly Guide

## Purpose
MANAGER uses this template to compile context packs per agent.
Each agent receives ONLY what it needs — not everything.

## Per-Agent Context Packs

### DISCOVER
- User input (description or repo path)
- knowledge-base/calibration-profile.yaml
- Previous run's evolution-report.md (if re-run)

### WHAT
- glossary.md + mental-model.md + boundaries.md
- assumptions.md + unknowns.md
- reference-architectures.md (if greenfield)
- reasoning-journal.jsonl (filtered: DISCOVER + WHY1 entries)

### WHY (assumption-challenge mode)
- glossary.md + mental-model.md + boundaries.md
- assumptions.md + unknowns.md
- calibration-profile.yaml
- reasoning-journal.jsonl

### WHY (spec-validation mode)
- All current artifacts
- Understanding CLI access
- calibration-profile.yaml
- reasoning-journal.jsonl

### ASSESS
- spec.md + glossary.md + assumptions.md
- issues.md (from WHY2)
- calibration-profile.yaml + estimates-log.yaml
- reasoning-journal.jsonl

### HOW
- spec.md + feasibility.md + prioritization.md
- constitution.md (if exists)
- All specialist outputs
- reasoning-journal.jsonl

### TEST ARCHITECT
- plan.md + data-model.md
- spec.md (acceptance criteria)
- contracts/
- reasoning-journal.jsonl

### PLAN
- plan.md + research.md + data-model.md
- contracts/ + test-strategy.md
- risk data from specialists
- reasoning-journal.jsonl

### ASSESS2 (consensus)
- plan.md + data-model.md + contracts/
- tasks.md + original estimates.md
- constitution (team constraints)
- reasoning-journal.jsonl

### PLAN2 (consensus)
- Updated plan.md + test-strategy.md
- Specialist outputs + implementability-report.md
- reasoning-journal.jsonl

### SCIENTIST
- Specific question from requesting agent
- Relevant artifacts (MANAGER selects)
- Web search access + git worktree access
- reasoning-journal.jsonl

### SPECIALISTS (all others)
- Domain-relevant artifacts only
- reasoning-journal.jsonl

### LEARNING LAYER
- All artifacts
- Prior run data (if re-run)
- Feedback history from knowledge-base/feedback/
