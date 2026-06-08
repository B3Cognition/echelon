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

## Deterministic Planning Gate

Before mutating `tasks.md`, run the deterministic planner:

```bash
python -m harness plan-reopen-gaps "{gaps_file}" "{spec_dir}/tasks.md" "{spec_dir}/reopen-plan" {existing_reopen_files}
```

Where `{existing_reopen_files}` is the space-separated list of existing
`{spec_dir}/reopen-*.md` files, if any.

Read `{spec_dir}/reopen-plan/reopen-plan.json`. Treat it as authoritative:

- If `status` is `noop`, do not append tasks. Write `reopen-{n}.md` from the
  plan summary and proceed to `DONE`.
- If `status` is `manual_review`, do not append tasks. Write `reopen-{n}.md`
  listing `manual_followups`, skipped rows, and the planner reason, then
  proceed to `DONE`.
- If `status` is `ready`, append only the exact `proposed_tasks[*].row` rows
  and their `title` values from the JSON. Do not invent extra tasks, split
  clusters further, renumber rows differently, or convert skipped/manual rows
  into executable tasks.

## Duplicate Prevention

Before appending anything, read:

- `{spec_dir}/tasks.md`
- all existing `{spec_dir}/reopen-*.md`
- the selected fulfillment gaps source

Build a coverage index of existing fulfillment-gap work from canonical task rows
with `phase=fulfillment-gap`, existing `FG-T*` labels, and existing
`reopen-*.md` summaries.

STOP without mutating `tasks.md` when existing `reopen-*.md` summaries or
existing `phase=fulfillment-gap` task rows already cover the selected
fulfillment gaps and there are no new actionable root-cause clusters. In that
case, write `reopen-{n}.md` as a no-op/manual-review summary listing:

- source gaps file
- existing reopen file(s) covering the gaps
- why no tasks were appended
- next command or manual decision needed

## Gap Clustering Rules

NEVER create one task sequence per fulfillment-report row.

Cluster rows by root cause before generating tasks. Multiple checklist rows
that point to the same missing source module, same deviated behavior, same
spec/code decision, or same test gap are one root-cause cluster. Cross-reference
rows such as "also resolves US*-AC*" must be folded into the controlling
cluster, not emitted as separate tasks.

Treat planned work already present in the base task list as existing coverage.
For example, future planned-phase missing work is not a fulfillment-gap task
when canonical tasks for that feature already exist and are still pending.
Only reopen it when the existing task is wrong, missing, obsolete, or not
traceable to the verified gap.

Manual/product decisions are not implementation tasks. If a gap requires a
spec-vs-code decision (for example event names or tolerance constants), emit a
manual follow-up in `reopen-{n}.md` and do not append implementation tasks until
the decision is reflected in `spec.md`, `plan.md`, or source/tests.

## Append Safety Cap

A reopen pass may append a maximum of 20 new root-cause sequences and a
maximum of 60 executable task rows. If clustering produces more than either limit,
write `reopen-{n}.md` as a no-op/manual-review summary and STOP without mutating
`tasks.md`. The summary must show the proposed clusters and ask for a narrower
`from=<path>` report or a human-selected subset.

Append a `## Fulfillment Gap Tasks` section to `{spec_dir}/tasks.md` using
`extension/templates/fulfillment-gap-task-fragment.md`. Add only deterministic
planner-approved rows from `proposed_tasks`:

```markdown
- [ ] {task_id} complexity=standard phase=fulfillment-gap req={req} depends={depends}

  **Title:** {title}
```

Write `{spec_dir}/reopen-{n}.md` summarizing:
- source gaps file
- gaps converted
- tasks appended
- next command: `echelon harness run {spec_id}`

## Output

Proceed to `DONE`.
