# Agent/Skill Best Practices Review

**Date:** May 28, 2026
**Scope:** Markdown prompts under `extension/agents`, `extension/commands`, and `extension/workflow/phases`.

## Current State

Recent remediation completed:

- Paired high-priority ALWAYS/NEVER rules across agents, commands, and workflow phases.
- Scoped Bash exploration guidance so it no longer conflicts with generated shell snippets.
- Extracted bulky output/reference content from Cartographer, Sage, Scorekeeper, and Internalizer.
- Added prompt reference validation for extracted appendix/template paths.

## Current Large Files

| File | Lines | Characters | Current recommendation |
|------|------:|-----------:|------------------------|
| `agents/exploration/sage.md` | 780 | 42,248 | Consider mode split only after dispatcher impact review |
| `workflow/phases/build-8-finalize.md` | 693 | 31,968 | Avoid broad split until workflow loader supports it clearly |
| `agents/learning/auditor.md` | 589 | 27,173 | Safest next target: analytics/feedback templates |
| `agents/exploration/cartographer.md` | 538 | 28,198 | Template extraction done; further split is optional |
| `commands/echelon.harness-run.md` | 454 | 20,204 | Keep ordered command flow intact for now |
| `agents/learning/internalizer.md` | 423 | 24,059 | Output/tier appendices extracted; formulas remain inline |
| `agents/control/scorekeeper.md` | 296 | 11,666 | No longer a priority for token reduction |

## Extracted References

| Prompt | Extracted support files |
|--------|-------------------------|
| `agents/exploration/cartographer.md` | `agents/exploration/templates/cartographer-spec-template.md`, `cartographer-overview-template.md` |
| `agents/exploration/sage.md` | `agents/exploration/templates/sage-assumption-review-template.md`, `sage-quality-gates-template.md`, `sage-issues-template.md`, `sage-decision-entry-template.yaml` |
| `agents/control/scorekeeper.md` | `agents/control/appendices/scorekeeper-scoring-reference.md`, `scorekeeper-output-template.md` |
| `agents/learning/internalizer.md` | `agents/learning/appendices/internalizer-tier-definitions.md`, `internalizer-output-formats.md` |

## Remaining Options

### Option A: Auditor Template Extraction

Lowest-risk remaining work.

Move only:

- Analytics notebook template
- `auto-feedback.yaml` example
- feedback report skeleton

Keep inline:

- Mode process steps
- calibration formulas
- ECC computation rules
- routing and escalation rules

### Option B: Sage Mode Split

Higher token win, higher risk.

Potential split:

- `sage-core.md`
- `sage-why1.md`
- `sage-why2-why3.md`

Do this only after confirming all phase prompts can load the correct mode-specific file reliably.

### Option C: Build Finalize Subphase Extraction

Potentially useful, but risky because `build-8-finalize.md` is an ordered workflow phase.

Do not split unless the phase loader has an explicit include/subphase pattern.

## Guardrails

- Always keep safety gates, routing decisions, and state mutation instructions inline unless the loader is changed and tested.
- Never extract a section if the main prompt no longer says when the agent must read it.
- Add or update tests when introducing referenced files.

## Verification

Run:

```bash
pytest tests/kernel/test_prompt_references.py
```

For broader confidence, run:

```bash
pytest
```
