# Spec Service Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every active 'spec' command and shared Phase A replay helper behind a typed application service, deleting legacy ownership from 'cli.py' without changing behavior.

**Architecture:** 'cli_app.py' keeps Typer parsing and calls typed functions in a new 'spec_service.py'. The existing Phase A kernel moves mechanically into that service, generic Prosaic skill execution moves to 'skill_command_service.py', and 'phase_service.py' consumes shared recovery helpers from the new spec owner. Controller decomposition remains deferred to S5.

**Tech Stack:** Python 3.11+, Typer/Click, pytest, existing Echelon Phase A controller and persisted-state contracts.

**Spec:** 'docs/superpowers/specs/2026-09-22-spec-service-cutover-design.md'

## Global Constraints

- Preserve Phase A schemas, locks, checkpoints, publication, console output, and exit codes.
- Do not redesign the Phase A kernel, change delivery/RE behavior, or add a new public dispatch layer.
- Do not leave forwarding aliases or duplicate active spec handlers in 'cli.py'.
- Typer passes typed declared values; only undeclared compatibility arguments may remain 'tuple[str, ...]'.
- Run focused tests after each production commit and repository verification once after both.

## File Structure

- Create 'src/echelon/spec_service.py': typed API and mechanically relocated Phase A/spec kernel.
- Create 'src/echelon/skill_command_service.py': shared Prosaic skill dispatch.
- Modify 'src/echelon/cli_app.py': route active spec commands to typed services.
- Modify 'src/echelon/phase_service.py': consume replay/recovery helpers from 'spec_service'.
- Modify 'src/echelon/cli.py': delete moved handlers, spec-only helpers, skill dispatch, and '_cmd_spec'.
- Create 'tests/unit/test_spec_service_boundary.py': typed routing and structural ownership guards.
- Modify focused tests that import moved private functions so they import the new owner.
- Update the route inventory and simplification control only after verification.

---

### Task 1: Cut Over Leaf Spec Workflows and Skill Dispatch

**Files:**

- Create: 'src/echelon/spec_service.py'
- Create: 'src/echelon/skill_command_service.py'
- Create: 'tests/unit/test_spec_service_boundary.py'
- Modify: 'src/echelon/cli_app.py:1698-1711, 2886-2930, 3073-3085, 4083-4120, 4307-4323, 4487-4536'
- Modify: 'src/echelon/cli.py:5379-5551, 11460-11627, 12100-12238, 19620-19664, 19746-19797, 19999-20165'
- Modify: 'tests/unit/test_cli_add_input.py'
- Modify: 'tests/unit/test_cli_artifacts.py'
- Modify: 'tests/unit/test_cli_drop_target.py'
- Modify: 'tests/unit/test_cli_llm_tool_policy.py'
- Modify: 'tests/unit/test_cli_spec_target.py'
- Modify: 'tests/unit/test_cli_spec_targets.py'
- Modify: 'tests/unit/test_cli_spec_switch.py'
- Modify: 'tests/unit/test_cli_typer_app.py'
- Modify: 'tests/unit/test_spec_amendment.py'
- Modify: 'tests/integration/test_spec_retarget_workflow.py'

**Interfaces:**

- Produces: 'dispatch_skill(command: str, arguments: Sequence[str], *, project_root: Path) -> NoReturn'.
- Produces: 'add_input(project_root: Path, *, input_values: Sequence[str]) -> None'.
- Produces: 'resolve_issue(project_root: Path, *, issue_id: str, decision: str | None, extra_args: Sequence[str] = ()) -> None'.
- Produces: 'drop_target(project_root: Path, *, spec_id: str, target: str, confirm: bool) -> None'.
- Produces: 'show_targets(project_root: Path, *, spec_id: str) -> None'.
- Produces: 'write_artifacts(project_root: Path, *, spec_id: str, extra_args: Sequence[str] = ()) -> None'.
- Produces: 'prepare_amendment(project_root: Path, *, spec_id: str, description: str, input_values: Sequence[str], dry_run: bool, extra_args: Sequence[str] = ()) -> None'.
- Produces: 'reject_target_mutation() -> NoReturn'.
- Consumes: existing spec domain modules and current console/error contracts.

- [x] **Step 1: Write failing typed-routing tests**

In 'tests/unit/test_spec_service_boundary.py', invoke the Typer app and patch the new services. Cover every Task 1 route. Representative tests:

~~~python
from pathlib import Path
from typer.testing import CliRunner


def test_spec_add_input_routes_typed_values(monkeypatch):
    from echelon.cli_app import app

    calls = []
    monkeypatch.setattr(
        "echelon.spec_service.add_input",
        lambda project_root, *, input_values: calls.append(
            (project_root, tuple(input_values))
        ),
    )
    result = CliRunner().invoke(
        app, ["spec", "add-input", "--input", "reference:notes.md"]
    )
    assert result.exit_code == 0
    assert calls == [(Path.cwd(), ("reference:notes.md",))]


def test_spec_drop_target_routes_typed_values(monkeypatch):
    from echelon.cli_app import app

    calls = []
    monkeypatch.setattr(
        "echelon.spec_service.drop_target",
        lambda project_root, *, spec_id, target, confirm: calls.append(
            (project_root, spec_id, target, confirm)
        ),
    )
    result = CliRunner().invoke(
        app,
        ["spec", "drop-target", "001-demo", "sources/api", "--confirm"],
    )
    assert result.exit_code == 0
    assert calls == [(Path.cwd(), "001-demo", "sources/api", True)]
~~~

For 'reopen', 'bugfix', and 'change', patch 'dispatch_skill' and assert the command, tuple of arguments, and 'Path.cwd()'.

- [x] **Step 2: Verify the new boundary is absent**

Run:

~~~bash
.venv/bin/python -m pytest -q tests/unit/test_spec_service_boundary.py
~~~

Expected: collection or monkeypatch resolution fails because the two service modules do not exist.

- [x] **Step 3: Move shared skill dispatch**

Create 'skill_command_service.py' with:

~~~python
def dispatch_skill(
    command: str,
    arguments: Sequence[str],
    *,
    project_root: Path,
) -> NoReturn:
    rendered_arguments = " ".join(arguments)
    if not rendered_arguments:
        from echelon.cli import USAGE

        print(f"echelon {command}: missing arguments\n", file=sys.stderr)
        print(USAGE)
        raise SystemExit(1)

    skill_base = SKILL_MAP[command]
    from echelon import cli as shared

    shared._require_provider_capability(
        f"echelon {command}",
        _skill_required_capability(command),
        project_dir=project_root,
    )
    try:
        config = shared._load_cli_config(project_root)
    except Exception as exc:
        print(f"echelon {command}: invalid LLM tool policy: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    cli = config.llm.cli
    prosaic_command = _load_prosaic_command(
        skill_base, rendered_arguments, project_root
    )
    prompt = prosaic_command.prompt if prosaic_command is not None else None
    skill_path = None
    if prompt is None:
        skill_path = shared._find_skill(skill_base, project_root, cli)
        if skill_path is None:
            print(
                _skill_not_found_msg(skill_base, project_root, cli),
                file=sys.stderr,
            )
            raise SystemExit(1)
    if cli == "opencode" and prompt is None:
        bin_ = shutil.which(cli) or cli
        cmd = build_opencode_skill_command(
            bin_, skill_base, rendered_arguments, config.llm.tool_policy
        )
        result = subprocess.run(cmd, cwd=str(project_root))
        raise SystemExit(result.returncode)
    if prompt is None:
        assert skill_path is not None
        prompt = _build_prompt(skill_path, rendered_arguments)
    metadata = (
        {"prompt_metadata": prosaic_command.frontmatter}
        if prosaic_command is not None
        else None
    )
    result = AICodingCliProvider(config).run_prompt_result(
        str(project_root), prompt, request_metadata=metadata
    )
    raise SystemExit(result.exit_code)
~~~

Move 'SKILL_MAP', '_load_prosaic_command', '_skill_required_capability', '_skill_not_found_msg', and '_build_prompt' with the dispatcher. Keep the provider/config and skill-location helpers in 'cli.py' because delivery and RE still use them; the local import above avoids an import-time cycle. Update '_dispatch_review_compatibility' to call the service. Delete the old dispatcher and only its now-exclusive helpers from 'cli.py'.

- [x] **Step 4: Add typed leaf functions and redirect Typer**

Implement the exact signatures already listed in this task's Interfaces block, with 'project_root' positional and all command values keyword-only. 'resolve_issue', 'write_artifacts', and 'prepare_amendment' additionally accept 'extra_args: Sequence[str] = ()'; 'reject_target_mutation' returns 'NoReturn'.

Move existing handler bodies without changing branches or text. Replace internal 'Path.cwd()' with 'project_root'. Update matching Typer commands to pass typed fields; declared values must not be rebuilt into a complete argument vector.

For 'resolve_issue', move the installed-runtime check and artifact-provider
capability gate currently performed by 'spec_resolve' in 'cli_app.py' into the
service before entering the relocated handler. This preserves validation while
leaving Typer responsible only for parsing.

- [x] **Step 5: Delete legacy leaf definitions and repair imports**

Delete '_cmd_spec_add_input', '_format_product_input_declarations', '_cmd_spec_resolve', '_cmd_drop_target', '_cmd_spec_target', '_cmd_spec_targets', '_cmd_artifacts', '_cmd_spec_amend', '_dispatch_skill_command', and the already-dead '_cmd_spec' dispatcher from 'cli.py'. Deleting '_cmd_spec' here prevents it from retaining references to removed leaf handlers; its direct help/switch tests move to the canonical Typer surface.

Find direct tests with:

~~~bash
rg -n '_cmd_spec_add_input|_cmd_spec_resolve|_cmd_drop_target|_cmd_spec_target|_cmd_spec_targets|_cmd_artifacts|_cmd_spec_amend|_dispatch_skill_command' tests
~~~

Import or patch the new owner in every match. Do not retain test-only aliases.
In 'test_cli_spec_switch.py', remove direct '_cmd_spec' imports and invoke the
Typer app with 'CliRunner' for help and switch coverage.

- [x] **Step 6: Run the leaf focused suite**

~~~bash
.venv/bin/python -m pytest -q \
  tests/unit/test_spec_service_boundary.py \
  tests/unit/test_cli_add_input.py tests/unit/test_cli_artifacts.py \
  tests/unit/test_cli_drop_target.py tests/unit/test_cli_llm_tool_policy.py \
  tests/unit/test_cli_spec_target.py tests/unit/test_cli_spec_targets.py \
  tests/unit/test_cli_spec_switch.py tests/unit/test_cli_typer_app.py \
  tests/unit/test_spec_amendment.py \
  tests/integration/test_spec_retarget_workflow.py
~~~

Expected: all selected tests pass.

- [x] **Step 7: Commit the leaf cutover**

~~~bash
git add src/echelon/spec_service.py src/echelon/skill_command_service.py \
  src/echelon/cli_app.py src/echelon/cli.py \
  tests/unit/test_spec_service_boundary.py tests/unit/test_cli_add_input.py \
  tests/unit/test_cli_artifacts.py tests/unit/test_cli_drop_target.py \
  tests/unit/test_cli_llm_tool_policy.py tests/unit/test_cli_spec_target.py \
  tests/unit/test_cli_spec_targets.py tests/unit/test_cli_spec_switch.py \
  tests/unit/test_cli_typer_app.py \
  tests/unit/test_spec_amendment.py \
  tests/integration/test_spec_retarget_workflow.py
git commit -m "refactor: move leaf spec commands to service"
~~~

---

### Task 2: Cut Over the Phase A Run and Recovery Core

**Files:**

- Modify: 'src/echelon/spec_service.py'
- Modify: 'src/echelon/cli_app.py:2749-2973'
- Modify: 'src/echelon/phase_service.py:90-305'
- Modify: 'src/echelon/cli.py:270-312, 3030-3037, 4434-5376, 5526-6097, 8014-12188, 19477-19743'
- Modify: 'tests/unit/test_spec_service_boundary.py'
- Modify: 'tests/unit/test_cli_config_compatibility.py'
- Modify: 'tests/unit/test_cli_continue.py'
- Modify: 'tests/unit/test_cli_mode_args.py'
- Modify: 'tests/unit/test_cli_next_step_escalation.py'
- Modify: 'tests/unit/test_cli_phase.py'
- Modify: 'tests/unit/test_cli_resume_escalation_options.py'
- Modify: 'tests/unit/test_cli_rewind.py'
- Modify: 'tests/unit/test_cli_run_summary.py'
- Modify: 'tests/unit/test_cli_spec_retarget.py'
- Modify: 'tests/unit/test_cli_spec_switch.py'
- Modify: 'tests/unit/test_cli_status.py'
- Modify: 'tests/unit/test_managed_retarget_rewind_exclusion.py'
- Modify: 'tests/unit/test_phase3_repair_reporting.py'
- Modify: 'tests/unit/test_prosaic_runtime_state_paths.py'
- Modify: 'tests/integration/test_human_input_routing.py'
- Modify: 'tests/integration/test_spec_retarget_workflow.py'
- Modify: 'tests/integration/test_squad_controller.py'

**Interfaces:**

- Produces: immutable 'SpecRunRequest', 'SpecRetargetRequest', and 'SpecRewindRequest'.
- Produces: 'run_spec(project_root: Path, request: SpecRunRequest) -> None'.
- Produces: 'retarget_spec(project_root: Path, request: SpecRetargetRequest) -> None'.
- Produces: 'show_status(project_root: Path) -> None'.
- Produces: 'continue_spec(project_root: Path, *, mode: str | None, extra_args: Sequence[str] = ()) -> None'.
- Produces: 'resume_spec(project_root: Path, *, answer: str | None, extra_args: Sequence[str] = ()) -> None'.
- Produces: 'rewind_spec(project_root: Path, request: SpecRewindRequest) -> None'.
- Produces: 'repair_traceability(project_root: Path, *, confirm: bool) -> None'.
- Produces for 'phase_service': 'find_current_run_dir', 'failed_automatic_phase_replay', 'resolve_phase_target_spec_dir', 'phase_state_updates_for_target', 'phase_context_resolution_rows', 'classify_run_recovery', 'enforce_project_config_compatibility', 'workspace_git_preflight', and 'command_display'.

- [ ] **Step 1: Write failing typed-core and ownership tests**

Add route tests for run, retarget, status, continue, resume, rewind, and repair. The run assertion must compare this value:

~~~python
SpecRunRequest(
    description="build notes",
    extra_args=(),
    mode="banzai",
    reset=False,
    perfectionist=True,
    init=False,
    message=None,
    next_phase=None,
    targets=("sources/api",),
    input_values=("requirement:req.md",),
    ignore_re=False,
    stash=False,
    discard=False,
    confirm=False,
)
~~~

Add an AST guard asserting 'cli_app.py' active spec functions and 'phase_service.py' do not import 'echelon.cli'. Also assert 'cli.py' has no function definitions named '_cmd_spec', '_cmd_spec_run', '_cmd_spec_retarget', '_cmd_spec_continue', '_cmd_spec_resume', '_cmd_status', '_cmd_rewind', or '_cmd_repair_traceability'.

Use the exact active-function set so delivery and RE imports elsewhere in 'cli_app.py' do not produce a false failure:

~~~python
ACTIVE_SPEC_FUNCTIONS = {
    "spec_run", "spec_retarget", "spec_status", "spec_continue", "spec_resume",
    "spec_add_input", "spec_resolve", "spec_rewind",
    "spec_repair_traceability", "spec_drop_target", "spec_targets",
    "spec_artifacts", "spec_reopen", "spec_bugfix", "spec_change", "spec_amend",
}


def test_active_spec_and_phase_surfaces_do_not_import_legacy_cli():
    import inspect
    import textwrap
    import echelon.cli_app as cli_app
    import echelon.phase_service as phase_service

    for name in ACTIVE_SPEC_FUNCTIONS:
        source = textwrap.dedent(inspect.getsource(getattr(cli_app, name)))
        assert "echelon import cli" not in source
        assert "echelon.cli import" not in source
    phase_source = inspect.getsource(phase_service)
    assert "echelon import cli" not in phase_source
    assert "echelon.cli import" not in phase_source
~~~

- [ ] **Step 2: Verify the core boundary tests fail**

~~~bash
.venv/bin/python -m pytest -q tests/unit/test_spec_service_boundary.py \
  -k 'run_routes or retarget or status or continue or resume or rewind or repair or ownership'
~~~

Expected: missing APIs and remaining legacy ownership cause failures.

- [ ] **Step 3: Define typed request objects and public entry points**

Add:

~~~python
@dataclass(frozen=True)
class SpecRunRequest:
    description: str | None = None
    extra_args: tuple[str, ...] = ()
    mode: str | None = None
    reset: bool = False
    perfectionist: bool = False
    init: bool = False
    message: str | None = None
    next_phase: str | None = None
    targets: tuple[str, ...] = ()
    input_values: tuple[str, ...] = ()
    ignore_re: bool = False
    stash: bool = False
    discard: bool = False
    confirm: bool = False


@dataclass(frozen=True)
class SpecRetargetRequest:
    spec_id: str
    targets: tuple[str, ...]
    confirm_count: int = 0


@dataclass(frozen=True)
class SpecRewindRequest:
    phase_id: str
    extra_args: tuple[str, ...] = ()
    checkpoint_commit: str | None = None
    checkpoint_next_phase: str | None = None
    confirm: bool = False
~~~

Public functions accept these types or explicit typed keywords. Only private helpers inside 'spec_service.py' may adapt them to the mechanically moved parser.

- [ ] **Step 4: Move the Phase A kernel mechanically**

Move implementations rooted at '_cmd_run', '_cmd_continue', '_cmd_continue_impl', '_cmd_resume', '_cmd_status', '_cmd_rewind', '_cmd_repair_traceability', and '_cmd_repair_traceability_locked', plus their spec-only reachable helpers. Include summary rendering, recovery classification, rewind selection/reset, active-run selection, phase-target resolution, and spec context preservation.

Preserve bodies before correcting imports. Do not combine branches, rename persisted fields, alter state-write order, or change exceptions. Shared generic helpers still used by delivery/RE may remain in 'cli.py'; use narrow local imports and never dispatch back to a removed spec handler.

- [ ] **Step 5: Redirect Typer and 'phase_service'**

Construct typed requests in 'cli_app.py'. In 'phase_service.py', replace 'from echelon import cli as shared' with explicit imports from 'echelon.spec_service', then call those names directly. Preserve phase replay ordering and authority comparisons.

- [ ] **Step 6: Delete legacy ownership and migrate tests**

Delete the four remaining '_cmd_spec_*' wrappers, moved core handlers, and helpers now exclusive to 'spec_service.py'. Delete '_installed_extension_or_exit' if no caller remains. The dead '_cmd_spec' dispatcher was already removed in Task 1.

Find residual references:

~~~bash
rg -n '_cmd_spec|_cmd_status|_cmd_continue|_cmd_resume|_cmd_rewind|_cmd_repair_traceability|_classify_run_recovery|_find_current_run_dir|_failed_automatic_phase_replay|_resolve_phase_target_spec_dir|_phase_state_updates_for_target|_phase_context_resolution_rows' src tests
~~~

Move Phase A test imports to 'echelon.spec_service'. Retain 'echelon.cli' imports only for definitions that remain generic and are still owned there. Remove obsolete '_cmd_spec' help/dispatch tests; Typer and boundary tests replace them.

- [ ] **Step 7: Run focused Phase A verification**

~~~bash
.venv/bin/python -m pytest -q \
  tests/unit/test_spec_service_boundary.py tests/unit/test_cli_config_compatibility.py \
  tests/unit/test_cli_continue.py tests/unit/test_cli_mode_args.py \
  tests/unit/test_cli_next_step_escalation.py tests/unit/test_cli_phase.py \
  tests/unit/test_cli_resume_escalation_options.py tests/unit/test_cli_rewind.py \
  tests/unit/test_cli_run_summary.py tests/unit/test_cli_spec_retarget.py \
  tests/unit/test_cli_spec_switch.py tests/unit/test_cli_status.py \
  tests/unit/test_managed_retarget_rewind_exclusion.py \
  tests/unit/test_phase3_repair_reporting.py \
  tests/unit/test_prosaic_runtime_state_paths.py tests/unit/test_cli_typer_app.py \
  tests/integration/test_human_input_routing.py \
  tests/integration/test_spec_retarget_workflow.py \
  tests/integration/test_squad_controller.py
~~~

Expected: all selected tests pass. Poll a long-running pytest process instead of restarting it.

- [ ] **Step 8: Run the CLI regression gate**

~~~bash
.venv/bin/python -m pytest -q \
  tests/unit/test_cli_*.py tests/unit/test_spec_*.py tests/unit/test_phase_*.py \
  tests/unit/test_prosaic_runtime_state_paths.py
~~~

Expected: all selected tests pass.

- [ ] **Step 9: Commit the core cutover**

~~~bash
git add src/echelon/spec_service.py src/echelon/cli_app.py \
  src/echelon/phase_service.py src/echelon/cli.py \
  tests/unit/test_spec_service_boundary.py \
  tests/unit/test_cli_config_compatibility.py tests/unit/test_cli_continue.py \
  tests/unit/test_cli_mode_args.py tests/unit/test_cli_next_step_escalation.py \
  tests/unit/test_cli_phase.py tests/unit/test_cli_resume_escalation_options.py \
  tests/unit/test_cli_rewind.py tests/unit/test_cli_run_summary.py \
  tests/unit/test_cli_spec_retarget.py tests/unit/test_cli_spec_switch.py \
  tests/unit/test_cli_status.py \
  tests/unit/test_managed_retarget_rewind_exclusion.py \
  tests/unit/test_phase3_repair_reporting.py \
  tests/unit/test_prosaic_runtime_state_paths.py \
  tests/integration/test_human_input_routing.py \
  tests/integration/test_spec_retarget_workflow.py \
  tests/integration/test_squad_controller.py
git commit -m "refactor: move phase a commands to spec service"
~~~

---

### Task 3: Verify and Record the Completed Spec Slice

**Files:**

- Modify: 'docs/findings/2026-09-21-typer-route-inventory.md'
- Modify: 'docs/simplification-control.md'
- Create: generated receipt under 'tests/reports/merge-verification/'

**Interfaces:**

- Consumes: both production commits.
- Produces: exact verification evidence and makes active delivery workflows the next S3 action; S3 remains 'ACTIVE'.

- [ ] **Step 1: Run structural guards**

~~~bash
rg -n '^def _cmd_spec|^def _cmd_status|^def _cmd_continue|^def _cmd_resume|^def _cmd_rewind|^def _cmd_repair_traceability' \
  src/echelon/cli.py
.venv/bin/python -m pytest -q tests/unit/test_spec_service_boundary.py
~~~

Expected: the search returns no matches and the boundary tests pass, including the AST-scoped checks for active spec functions and 'phase_service.py'.

- [ ] **Step 2: Run repository merge verification**

~~~bash
.venv/bin/python scripts/merge_verification.py plan --base f6a3d2a4
.venv/bin/python scripts/merge_verification.py run --base f6a3d2a4
~~~

Expected: the planned repository gate passes and writes a receipt. Record exact pass, skip, deselection, failure, and duration totals.

- [ ] **Step 3: Update tracking documents**

Move all 16 active spec routes to the modular-service table, name 'echelon.spec_service', isolate hidden 'spec target', and update totals in the route inventory. In the control sheet, check the spec cutover item, record commits/test totals/receipt, keep S3 'ACTIVE', and set active delivery workflows as next.

- [ ] **Step 4: Check and commit evidence**

~~~bash
git diff --check
git status --short
git add docs/findings/2026-09-21-typer-route-inventory.md \
  docs/simplification-control.md tests/reports/merge-verification
git commit -m "docs: record spec service cutover verification"
~~~

Expected before commit: only the two documentation files and generated receipt are uncommitted.

- [ ] **Step 5: Verify final state**

~~~bash
git status --short
git log -4 --oneline
~~~

Expected: clean status and the design, two production, and evidence commits in recent history.
