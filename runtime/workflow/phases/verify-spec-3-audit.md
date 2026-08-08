# Phase: verify-spec-3-audit
# Read by: echelon.commander (COMMANDER)
# Type: commander_internal

## Deterministic Audit

Run:

```bash
python -m harness write-canonical-requirements "{spec_dir}" "{verify_run_dir}"
```

This writes `{verify_run_dir}/canonical-requirements.json` and
`{verify_run_dir}/canonical-requirements.md`. These files are the Python-owned
canonical requirement inventory for this verify-spec run. The command also
stamps `canonical_requirements: ready` and `canonical_requirements_count` in
`{verify_run_dir}/state.json`.
If `{verify_run_dir}/state.json` is missing, hard stop with BLOCKED and report
the command stderr. Do not create a replacement state file by hand; verify-spec
init owns state creation.

Then run:

```bash
python -m harness write-requirement-audit "{verify_run_dir}"
```

This writes `{verify_run_dir}/requirement-audit.md` from the canonical inventory
and stamps `requirement_audit: ready` and `requirement_audit_count` in
`{verify_run_dir}/state.json`.
If `{verify_run_dir}/state.json` is missing, hard stop with BLOCKED and report
the command stderr.
Do not dispatch SPEC-FULFILLMENT-AUDITOR for row-set extraction, do not hand-edit
`requirement-audit.md`, and do not ask an LLM to infer or repair the audit table.
Python owns the canonical audit row set.

Task-progress integrity is bookkeeping evidence, not implementation evidence:
it can reveal stale or inconsistent task tracking, but it does not decide
whether source code fulfills a requirement.

NEVER instruct downstream agents to downgrade source-backed implementation
evidence solely because the corresponding task checkbox is still pending.
If task progress and code evidence disagree, preserve the requirement checklist
as extracted from the spec and record the disagreement as a task-progress
integrity note.

## Expected Output

- `{verify_run_dir}/requirement-audit.md` with exactly the IDs from
  `{verify_run_dir}/canonical-requirements.json`.
- task-progress integrity notes with any mismatch that could make the spec look
  implemented when task tracking says otherwise.

Proceed to `verify-spec-4-map`.
