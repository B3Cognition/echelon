# Agent Best Practices: ALWAYS/NEVER Rule Pairing Guide

**Date:** May 28, 2026
**Purpose:** Standardize positive/negative rule pairs for prompt clarity and token economy.

## Standard Pattern

```markdown
### Rule X - Descriptive Name
ALWAYS do the desired action.
NEVER do the prohibited action.
```

Why this order:

1. The positive behaviour is loaded first.
2. The negative boundary closes the escape route.
3. The pair is easier to scan than separate positive and negative sections.
4. The rule is easier to audit mechanically.

## Good Examples

```markdown
### Rule 1 - Script Execution Evidence
ALWAYS run the required scripts before reporting their results.
NEVER report script results without executing the scripts.
```

```markdown
### Rule 2 - JSON-Safe Scripting
ALWAYS use `sys.stdout.write()` or structured JSON helpers for captured machine output.
NEVER use `print()` where stray stdout can corrupt captured state.
```

```markdown
### Rule 3 - Output Ownership
ALWAYS return journal/state updates through the `echelon_result` block.
NEVER write directly to `reasoning-journal.jsonl`.
```

## Avoid

Avoid negative-only blocks:

```markdown
NEVER skip verification.
NEVER modify specs.
NEVER ignore failures.
```

Prefer paired, named rules:

```markdown
### Rule 1 - Verification Evidence
ALWAYS prove the result with the required verification gate.
NEVER skip verification.

### Rule 2 - Spec Ownership
ALWAYS escalate spec changes to the owning agent.
NEVER modify specs directly.

### Rule 3 - Failure Handling
ALWAYS report blocking failures with exact evidence.
NEVER ignore failures.
```

## Inline Rules

Inline rules should still be positive-first:

```markdown
Always preserve existing deploy fields. Do NOT overwrite dockerfile, port, or app fields.
```

If a sentence has multiple negative clauses, add explicit positive companions where useful:

```markdown
Always write project-root-relative commands. Do NOT write absolute paths.
Always preserve other sections. Do NOT change them.
```

## Bash Guidance Scope

When a prompt bans Bash exploration commands, scope the rule precisely:

```markdown
ALWAYS use Glob, Read, and Grep tools for ad hoc file exploration.
NEVER use Bash `ls`, `find`, `cat`, `echo`, or `grep` for ad hoc exploration.
```

This does not apply to generated shell scripts, project scripts, or literal workflow snippets whose purpose is shell script content.

## Maintenance Checklist

- Pair behavioural rules as ALWAYS then NEVER.
- Keep pairs adjacent.
- Do not count generated examples as prompt behaviour unless the agent is instructed to follow them directly.
- Prefer concise positive phrasing over long negative explanations.
- Re-run prompt reference tests after extracting templates or appendices.
