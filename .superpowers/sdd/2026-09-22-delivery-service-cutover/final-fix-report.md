# Delivery service cutover — final fix wave

Date: 2026-09-23

Workspace: `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-service-cutover`

Branch: `codex/delivery-service-cutover`

## Scope and commits

This wave addresses all four findings in the final review against the approved
Delivery cutover design and implementation plan. No controller decomposition,
RE behavior change, merge, push, or additional reviewer dispatch was performed.

Fix commit: `cdb1a4d310ed7bf39358ee71284ebedf5a8f465a`

Verified candidate tree: `b2b80184eab739396535ae402d800dc8985e8eb2`

Verification baseline: `3abca341ae0d84623d74387e112d9662e8d723f6`

The receipt, refreshed tracking documentation, and this report are committed
separately after verification; that evidence commit does not change executable
code or tests. The receipt identifies the exact tested fix commit above.

## Findings mapped to changes

1. **Explicit project root at the provider capability gate.**
   `_run_delivery` and `_run_delivery_resume` now pass
   `project_dir=project_root`. The latter serves both public recovery entry
   points. The parameterized boundary regression calls `run_delivery`,
   `resume_delivery`, and `continue_delivery` with an API project root after
   changing cwd to another directory. It intercepts the shared capability gate
   before preflight/controller side effects and checks the root, BUILD
   capability, and canonical command name. All service capability calls now
   provide an explicit root; existing target/config-root semantics are preserved.

2. **Polyrepo convergence integration imports.**
   `tests/integration/test_polyrepo_delivery_convergence.py` imports
   `_delivery_provisioning_blockers` from `echelon.delivery_service`. The same
   file also embedded a stale subprocess import of
   `_block_if_delivery_provisioning_incomplete`; this was migrated as part of
   the same ownership fix. The entire affected integration file passed.

3. **Residual Delivery ownership and re-exports.**
   `_print_harness_config_error` moved unchanged from `cli.py` to the service;
   all three production call sites (land, run, recovery) now resolve it there.
   The unused eight-name import/re-export block was deleted from `cli.py`.
   Both remaining `_sync_polyrepo_runtime_extension` test consumers migrated:
   `tests/unit/test_cli_polyrepo_runtime_extension.py` and
   `tests/integration/test_codegraph_delivery_runtime.py`.
   A new boundary guard rejects all nine Delivery-only names in the legacy
   module namespace. Shared helpers remain: `_load_cli_config` still serves
   RE/provider workflows, and `_iter_harness_build_states` still serves the
   shared converged-build lookup. No shared implementation was duplicated.

4. **Measured route totals and S3 status.**
   The executable Typer/Click tree contains 104 public leaf commands, 23 hidden
   leaf commands, 9 public `_legacy_cli()` consumers, and therefore 95 modular
   public commands. The direct hidden `_legacy_cli()` consumer count is 2.
   Both tracking documents use these measurements. `admin commands` was moved
   into the hidden inventory, and already-cut-over general command families
   were included in the modular table. S3 remains **ACTIVE**, with the active
   RE facade next and final; RE protocol consolidation remains assigned to S6.

## RED/GREEN evidence

Before the production edits:

```text
.venv/bin/python -m pytest -q tests/unit/test_delivery_service_boundary.py -k 'execution_capability_gate or does_not_retain_delivery_only_helpers'
4 failed, 13 deselected in 10.28s
```

All three `test_execution_capability_gate_uses_supplied_project_root` cases
failed at the intended assertion: the captured third argument was `None`
instead of the supplied `.../project` root. The run, resume, and continue
command names and BUILD capability already matched. The fourth failure was
the intended ownership assertion: `cli.py` still exposed the nine moved names.
These were assertion failures, not collection/import errors.

After the production and test-import edits, the full affected suite passed:

```text
.venv/bin/python -m pytest -q tests/unit/test_delivery_service_boundary.py tests/integration/test_polyrepo_delivery_convergence.py tests/unit/test_cli_polyrepo_runtime_extension.py tests/integration/test_codegraph_delivery_runtime.py tests/unit/test_controlled_delivery_boundary.py
......................................                                   [100%]
38 passed in 13.66s
```

This includes all 17 service-boundary cases, including the three explicit-root
regressions and the residual-helper ownership guard.

The focused Delivery suite, including init runtime/verification coverage, also
passed:

```text
.venv/bin/python -m pytest -q tests/unit/test_delivery_service_boundary.py tests/unit/test_cli_delivery.py tests/unit/test_cli_delivery_local.py tests/unit/test_cli_delivery_status.py tests/unit/test_cli_harness_init_summary.py tests/unit/test_cli_harness_run.py tests/unit/test_cli_harness_resume.py tests/unit/test_harness_single_repo_unchanged.py tests/unit/test_land_cli.py tests/unit/test_cli_typer_app.py tests/integration/test_egr_151_lifecycle_flow.py tests/unit/test_harness_init_app_runtime.py tests/unit/test_harness_init_verify.py
302 passed in 58.32s
```

The earlier broad CLI regression result remains historical evidence from the
preceding wave: `1 failed, 1672 passed in 274.71s (0:04:34)`. Its failure,
`test_delivery_without_llm_provider_blocks_before_ralph`, was previously
reproduced on design baseline `3abca341`. That broad command was not rerun in
this wave; the required affected, focused Delivery, and full-unit commands
provide this wave's fresh evidence.

## Ownership audit

This residual search returned no matches in `cli.py`:

```bash
rg -n '_print_harness_config_error|HarnessWorkspaceTarget|_apply_target_verify_command_detection|_block_if_spec_task_targets_mismatch|_format_missing_verify_command_resume_message|_resolve_harness_workspace_target|_source_dispatch_metadata|_sync_polyrepo_runtime_extension|_workspace_target_dispatch_metadata' src/echelon/cli.py
```

A repository-wide AST audit collected every top-level function/class defined in
`delivery_service.py` and compared those names against test imports from
`echelon.cli` and string patch/subprocess references to those names. Output:

```text
Remaining direct moved-helper test imports/patches: []
```

Remaining Delivery-test references to `echelon.cli` use the shared capability
gate, banner, or public `main` entry point. The service remains the sole owner
of the relocated helpers. `_print_harness_config_error` appears only in its
service definition/calls and the ownership regression's forbidden-name set.

A further AST comparison against the pre-wave commit `c5c83355` confirmed:

```text
Renderer AST identical after move: True
Service capability calls: 7
Calls without project_dir: []
```

## Route recount method and results

The recount ran against the executable command tree, not decorator counts or
the old Markdown totals:

```python
import inspect
import click
from typer.main import get_command
from echelon.cli_app import app

routes = []
def visit(command, path=(), hidden=False):
    hidden = hidden or command.hidden
    if isinstance(command, click.Group):
        for name, child in command.commands.items():
            visit(child, (*path, name), hidden)
    else:
        callback = inspect.unwrap(command.callback)
        legacy = '_legacy_cli(' in inspect.getsource(callback)
        routes.append((' '.join(path), hidden, legacy))
visit(get_command(app))
```

Measured results: **104 public, 23 hidden, 9 public direct legacy consumers,
95 public modular, 2 hidden direct legacy consumers**.

The nine public legacy consumers are `re run`, `re refresh`, `re deepen`,
`re status`, `re continue`, `re resume`, `re publish`, `re finalize`, and
`re synthesize`. The two direct hidden consumers are `re execute-run` and
`re check-domain`. All four `harness` leaves and `admin commands` inherit their
parent group's hidden flag. Compatibility forwarding may reach legacy code
indirectly; the reported legacy counts measure direct `_legacy_cli()` usage.

## Full repository gate

The required `plan --base 3abca341` and `run --base 3abca341` commands were each
started exactly once after committing all code/tests/route corrections. The
planner selected `full-unit`, requiring `pytest -q -m unit`, against the clean
candidate commit/tree above. The original running process was retained.

Both commands completed with exit code 0. Exact final run output:

```text
9822 passed, 11438 deselected in 1773.29s (0:29:33)
receipt: /Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-service-cutover/tests/reports/merge-verification/receipt-cdb1a4d310ed-88781f07aeae4d69a0049ac35bed75fb.json
scope: full-unit
```

Totals: **9,822 passed, 0 skipped, 11,438 deselected, 0 failed**. Pytest elapsed
time was **1,773.29s (29m33.29s)**. The generated receipt records the complete
pytest subprocess as **1,775,535ms (29m35.535s)**, exit code **0**, and status
**passed**. These are distinct timer scopes; neither value is rounded to the
other. The four new boundary cases follow the existing file's unmarked
convention, so `-m unit` deselects them; all four passed in the separately run
38-test affected suite and again in the 302-test focused suite.

Receipt:
`tests/reports/merge-verification/receipt-cdb1a4d310ed-88781f07aeae4d69a0049ac35bed75fb.json`.
The receipt's baseline, candidate, and tree match the immutable IDs above.
The superseded tracked Delivery receipt
`receipt-0741dd4c9f62-d59ac9b2a44647fa8e97504443ecff94.json` was removed and is
recoverable from Git history (`c5c83355`). The earlier Spec receipt was retained.

Complete, verbatim generated command output is committed alongside this report:

- `final-merge-plan.log`: full planner JSON, including command, paths, and IDs.
- `final-merge-run.log`: every pytest progress line and the final output above.

## Files changed

- `src/echelon/cli.py`
- `src/echelon/delivery_service.py`
- `tests/unit/test_delivery_service_boundary.py`
- `tests/unit/test_cli_polyrepo_runtime_extension.py`
- `tests/integration/test_polyrepo_delivery_convergence.py`
- `tests/integration/test_codegraph_delivery_runtime.py`
- `docs/findings/2026-09-21-typer-route-inventory.md`
- `docs/simplification-control.md`
- Replacement passing merge-verification receipt, this report, and gate logs.

## Self-review and concerns

Reviewed the complete fix diff before the candidate commit. The renderer body
is unchanged; capability-gate ordering is unchanged; the only execution
change is selecting the supplied API root. No schema, controller, lifecycle,
state write, provider rule, output text, or exit-code behavior was changed.
The root regression catches either kernel reverting to ambient cwd; continue
is independently exercised even though it shares the recovery kernel.
Ownership searches and migrated real runtime/provisioning tests cover the
removal of old import locations. `git diff --check` passed before the candidate
commit. The final evidence diff was checked separately; no executable code or
test changes were made after the verified candidate commit.

The receipt is bound to the code/test candidate commit, not the subsequent
documentation/evidence commit. Exact-HEAD fast-forward receipt reuse requires
matching that recorded candidate commit/tree; no broader reuse is claimed.
No outstanding implementation concern identified in self-review.
