# Phase: reopen-1-apply-gaps
# Read by: speckit-echelon-commander (COMMANDER)
# Type: commander_internal

## Objective

Convert verified fulfillment gaps into harness-ready follow-up tasks.

## Instructions

Parse `spec_id` and optional `from=<path>`. Locate `specs/{spec_id}-*/`.
When `from` is absent, use `{spec_dir}/fulfillment-gaps.md`.

ALWAYS require an existing fulfillment gaps file before mutating artifacts.
NEVER reopen from a stale report without recording the source path.

Set spec frontmatter/status to `In Progress`.

Append a `## Fulfillment Gap Tasks` section to `{spec_dir}/tasks.md` using
`extension/templates/fulfillment-gap-task-fragment.md`. Add one small
test-first sequence per actionable gap, preserving canonical `T-###` executable
task rows:

```markdown
- [ ] T-{next} complexity=standard phase=fulfillment-gap req={FR-id} depends=none

  **Title:** FG-T{n}.1 - Add failing test for {gap_id}

- [ ] T-{next+1} complexity=standard phase=fulfillment-gap req={FR-id} depends=T-{next}

  **Title:** FG-T{n}.2 - Implement missing or deviated behavior for {gap_id}

- [ ] T-{next+2} complexity=standard phase=fulfillment-gap req={FR-id} depends=T-{next+1}

  **Title:** FG-T{n}.3 - Rerun verify-spec and update fulfillment evidence
```

Write `{spec_dir}/reopen-{n}.md` summarizing:
- source gaps file
- gaps converted
- tasks appended
- next command: `echelon harness run {spec_id}`

## Output

Proceed to `DONE`.
