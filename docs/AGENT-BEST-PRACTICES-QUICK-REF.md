# Agent Best Practices: Quick Reference

**Date:** May 28, 2026
**Purpose:** Compact checklist for maintaining token-efficient, well-motivated agent prompts.

## ALWAYS / NEVER Pairing

Use positive motivation first, then the boundary:

```markdown
### Rule X - Rule Name
ALWAYS do/prefer the desired behaviour.
NEVER do/prefer the forbidden behaviour.
```

Keep rule pairs adjacent. Avoid negative-only lists unless the surrounding line already provides the positive instruction.

## Token Economy

Prefer extraction when a prompt embeds long examples, static tables, or output skeletons.

Current extracted prompt support:

| Area | Extracted files |
|------|-----------------|
| Cartographer outputs | `agents/exploration/templates/cartographer-*.md` |
| Sage outputs | `agents/exploration/templates/sage-*` |
| Scorekeeper references | `agents/control/appendices/scorekeeper-*` |
| Internalizer references | `agents/learning/appendices/internalizer-*` |

Current largest prompt files:

| File | Lines | Characters | Notes |
|------|------:|-----------:|-------|
| `agents/exploration/sage.md` | 780 | 42,248 | Still largest; mode split is possible but riskier |
| `workflow/phases/build-8-finalize.md` | 693 | 31,968 | Procedural workflow; split cautiously |
| `agents/learning/auditor.md` | 589 | 27,173 | Next safe target: templates/appendices |
| `agents/exploration/cartographer.md` | 538 | 28,198 | Output templates already extracted |
| `commands/echelon.harness-run.md` | 454 | 20,204 | Ordered command flow; postpone broad split |
| `agents/learning/internalizer.md` | 423 | 24,059 | Output/tier appendices extracted |
| `agents/control/scorekeeper.md` | 296 | 11,666 | Scoring appendices extracted |

## Safe Extraction Rules

Always keep operational decision logic inline.
Never extract steps that determine routing, pass/fail verdicts, state mutation, or safety gates without also updating dispatch/loading behavior.

Best extraction candidates:

- Output templates
- Example YAML/Markdown structures
- Static scoring tables
- Long reference definitions
- Optional appendix material read only when needed

Riskier candidates:

- Mode splits
- Workflow phase splits
- Harness command flow splits
- Anything that changes which file a dispatcher reads

## Review Checklist

- ALWAYS/NEVER rules are paired and positive-first.
- Extracted references point to real files under `extension/`.
- The main prompt still states when to read each appendix/template.
- No stale line counts or obsolete findings remain in docs.
- Run `pytest tests/kernel/test_prompt_references.py` after adding or moving prompt references.
