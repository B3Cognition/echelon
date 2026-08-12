# Cartographer Perfectionist Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `echelon spec run --perfectionist` as a persisted exhaustive operating mode for the existing Cartographer agent.

**Architecture:** A focused `echelon.spec_authoring` module owns the two mode values and CLI-resolution semantics. The CLI persists the resolved mode before controller execution, state machinery protects and preserves it, and the existing WHAT executor injects one trusted mode block into the unchanged Cartographer dispatch.

**Tech Stack:** Python 3.11, pytest, JSON Schema, Markdown Prosaic prompts, YAML workflow definitions.

## Global Constraints

- `echelon.cartographer` remains the only `phase1-what` agent.
- Accepted modes are exactly `proportional` and `perfectionist`.
- Existing and legacy runs default to `proportional`.
- The mode must not change provider, model tier, effort, tools, templates, quality thresholds, or downstream artifact schemas.
- `spec_authoring_mode` is controller-owned and agents cannot update it.
- TDD is required for every behavioral change.

---

### Task 1: Authoring Mode Domain And State Contract

**Files:**
- Create: `src/echelon/spec_authoring.py`
- Modify: `src/harness/squad_state.py`
- Modify: `src/harness/state_transaction_namespace.py`
- Modify: `templates/state-schema.json`
- Test: `tests/unit/test_spec_authoring.py`
- Test: `tests/kernel/test_squad_state.py`
- Test: `tests/kernel/test_prepared_phase_result.py`

**Interfaces:**
- Produces: `PROPORTIONAL_MODE`, `PERFECTIONIST_MODE`, `SpecAuthoringModeError`, `normalize_spec_authoring_mode(value)`, and `resolve_spec_authoring_mode(state, is_fresh, perfectionist_requested)`.
- Produces: `SquadStateStore.initialize(..., spec_authoring_mode="proportional")` persisted state behavior.
- Consumes: existing store-owned transaction namespace and state schema.

- [ ] **Step 1: Write failing domain and state tests**

```python
def test_resolve_fresh_perfectionist_request() -> None:
    assert resolve_spec_authoring_mode(
        {}, is_fresh=True, perfectionist_requested=True
    ) == "perfectionist"

def test_active_legacy_state_rejects_late_perfectionist_switch() -> None:
    with pytest.raises(SpecAuthoringModeError):
        resolve_spec_authoring_mode(
            {}, is_fresh=False, perfectionist_requested=True
        )

def test_squad_state_defaults_to_proportional(tmp_path: Path) -> None:
    store = SquadStateStore(tmp_path / "run")
    store.initialize("r", "greenfield", "msg", 0, "init")
    assert store.load()["spec_authoring_mode"] == "proportional"
```

Also assert that `spec_authoring_mode` belongs to
`STORE_OWNED_TRANSACTION_KEYS` and that the canonical state schema rejects any
value other than the two accepted values.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_spec_authoring.py \
  tests/kernel/test_squad_state.py \
  tests/kernel/test_prepared_phase_result.py
```

Expected: failures because the module, initializer field, schema enum, and
reserved state key do not yet exist.

- [ ] **Step 3: Implement the minimal domain and state contract**

Implement the mode module with strict normalization and these resolution rules:

```python
PROPORTIONAL_MODE = "proportional"
PERFECTIONIST_MODE = "perfectionist"
SPEC_AUTHORING_MODES = frozenset({PROPORTIONAL_MODE, PERFECTIONIST_MODE})


class SpecAuthoringModeError(ValueError):
    pass


def normalize_spec_authoring_mode(value: object) -> str:
    if value is None or value == "":
        return PROPORTIONAL_MODE
    if type(value) is not str or value not in SPEC_AUTHORING_MODES:
        raise SpecAuthoringModeError(
            "spec authoring mode must be proportional or perfectionist"
        )
    return value
```

`resolve_spec_authoring_mode` must preserve a persisted valid value, reject a
late active-run switch from proportional to perfectionist, and otherwise apply
the fresh-run default. Add the state initializer field, JSON Schema property,
and reserved transaction key.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/spec_authoring.py src/harness/squad_state.py \
  src/harness/state_transaction_namespace.py templates/state-schema.json \
  tests/unit/test_spec_authoring.py tests/kernel/test_squad_state.py \
  tests/kernel/test_prepared_phase_result.py
git commit -m "feat: add spec authoring mode state contract"
```

### Task 2: CLI Selection And Lifecycle Preservation

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `src/harness/squad.py`
- Modify: `src/echelon/phase_a_start.py`
- Test: `tests/unit/test_cli_mode_args.py`
- Test: `tests/unit/test_phase_a_start.py`
- Test: `tests/unit/test_cli_continue.py`

**Interfaces:**
- Consumes: `resolve_spec_authoring_mode(...)` from Task 1.
- Produces: parsed `--perfectionist`, persisted state before controller run,
  `SquadController` prepared-identity preservation, and retarget inheritance.

- [ ] **Step 1: Write failing CLI and lifecycle tests**

Add tests proving:

```python
def test_cmd_run_passes_perfectionist_mode_to_prepared_state(...):
    _cmd_run(["build notes", "--perfectionist"], ...)
    assert json.loads((squad_dir / "state.json").read_text())[
        "spec_authoring_mode"
    ] == "perfectionist"

def test_cmd_run_rejects_switching_active_proportional_run(...):
    # Existing state contains spec_authoring_mode=proportional.
    with pytest.raises(SystemExit) as exc:
        _cmd_run(["build notes", "--perfectionist"], ...)
    assert exc.value.code == 2

def test_retarget_preserves_perfectionist_mode(...):
    # Baseline state contains spec_authoring_mode=perfectionist.
    outcome = start_retarget_phase_a_spec(...)
    assert load_state(outcome.run_dir)["spec_authoring_mode"] == "perfectionist"
```

Also prove that a prepared Perfectionist retry without the flag preserves the
mode and that continue-generated run arguments do not need to repeat the flag.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_cli_mode_args.py \
  tests/unit/test_cli_continue.py \
  tests/unit/test_phase_a_start.py
```

Expected: failures because the CLI does not parse or persist the option and
retarget preparation does not copy the field.

- [ ] **Step 3: Implement CLI resolution and persistence**

In `_cmd_run`, parse `--perfectionist` separately from the user message. After
`_select_squad_dir`, load prepared or active state, resolve the mode through the
Task 1 helper, print a concise error for conflicts, and save the resolved value
before creating `SquadController`.

Add `spec_authoring_mode` to `SquadController`'s prepared identity preservation.
In `_expected_retarget_prepared_state`, copy
`normalize_spec_authoring_mode(baseline_state.get("spec_authoring_mode"))`.
Add `Spec authoring` to the run banner.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/cli.py src/harness/squad.py src/echelon/phase_a_start.py \
  tests/unit/test_cli_mode_args.py tests/unit/test_cli_continue.py \
  tests/unit/test_phase_a_start.py
git commit -m "feat: persist perfectionist spec runs"
```

### Task 3: Trusted WHAT Context And Cartographer Modes

**Files:**
- Modify: `src/harness/squad_executors.py`
- Modify: `prosaic/subagents/echelon.cartographer.md`
- Modify: `runtime/workflow/phases/phase1-what.md`
- Test: `tests/kernel/test_squad_executors_journal.py`
- Test: `tests/unit/test_cartographer_templates.py`

**Interfaces:**
- Consumes: normalized `spec_authoring_mode` state from Tasks 1 and 2.
- Produces: `_render_spec_authoring_mode_context(state, phase_id)` and the two
  Cartographer operating-mode contracts.

- [ ] **Step 1: Write failing prompt and prose tests**

Add tests proving:

```python
def test_what_prompt_injects_perfectionist_authoring_mode(...):
    prompt = executor._assemble_prompt(
        what_node, {"spec_authoring_mode": "perfectionist", ...}
    )
    assert "## Specification Authoring Mode" in prompt
    assert "Mode: perfectionist" in prompt

def test_non_what_prompt_omits_spec_authoring_mode(...):
    prompt = executor._assemble_prompt(
        sage_node, {"spec_authoring_mode": "perfectionist", ...}
    )
    assert "## Specification Authoring Mode" not in prompt
```

Static prose tests must assert that Cartographer defines both modes, defaults to
proportional when context is absent, performs the complete applicability review
in Perfectionist mode, and retains one canonical obligation plus
evidence-grounding rules. Assert that `definition.yaml` still contains
`agent: echelon.cartographer` and no `echelon.perfectionist`.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/kernel/test_squad_executors_journal.py \
  tests/unit/test_cartographer_templates.py
```

Expected: failures because the trusted mode block and operating-mode prose are
absent.

- [ ] **Step 3: Implement trusted context and prose behavior**

Add a pure renderer that returns an empty string outside `phase1-what`. For
WHAT, render the normalized mode and concise instructions distinguishing the
two strategies while repeating that evidence, atomicity, testability, and
one-obligation rules are invariant.

Add an `Operating Modes` section to Cartographer. Replace the static
proportional-only paragraph in `phase1-what.md` with an instruction to follow
the controller-injected authoring mode. Do not modify `definition.yaml`, SAGE,
Understanding, templates, or Prosaic frontmatter.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/squad_executors.py \
  prosaic/subagents/echelon.cartographer.md \
  runtime/workflow/phases/phase1-what.md \
  tests/kernel/test_squad_executors_journal.py \
  tests/unit/test_cartographer_templates.py
git commit -m "feat: add Cartographer perfectionist mode"
```

### Task 4: Public Documentation And Regression Verification

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `README.md`
- Test: `tests/unit/test_cli_spec_switch.py`
- Test: `tests/unit/test_prosaic_package_install.py`
- Test: `tests/unit/test_workspace_init_deploy_runtime.py`

**Interfaces:**
- Consumes: completed CLI and prose behavior from Tasks 1 through 3.
- Produces: accurate public help and full regression evidence.

- [ ] **Step 1: Write failing help assertions**

Assert that top-level and `echelon spec --help` output include
`--perfectionist`, and that README describes it as exhaustive Cartographer
authoring rather than a model, provider, or autonomy option.

- [ ] **Step 2: Run help tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_cli_spec_switch.py
```

Expected: failure because help does not expose the option.

- [ ] **Step 3: Update help and README**

Add `[--perfectionist]` to both CLI help surfaces and the README command table.
Add one short explanatory paragraph near Phase A usage:

```markdown
Pass `--perfectionist` to ask the existing Cartographer agent for exhaustive,
evidence-backed coverage. The default remains proportional authoring.
```

- [ ] **Step 4: Run focused and regression suites**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_spec_authoring.py \
  tests/unit/test_cli_mode_args.py \
  tests/unit/test_cli_continue.py \
  tests/unit/test_phase_a_start.py \
  tests/kernel/test_squad_state.py \
  tests/kernel/test_prepared_phase_result.py \
  tests/kernel/test_squad_executors_journal.py \
  tests/unit/test_cartographer_templates.py \
  tests/unit/test_cli_spec_switch.py \
  tests/unit/test_prosaic_package_install.py \
  tests/unit/test_workspace_init_deploy_runtime.py
```

Expected: PASS.

- [ ] **Step 5: Run repository checks**

Run:

```bash
git diff --check
.venv/bin/python -m pytest -q tests/unit/test_phase_graph.py tests/unit/test_prompt_references.py
```

If `tests/unit/test_prompt_references.py` is not present in this checkout, run
the existing equivalent `tests/kernel/test_prompt_references.py`. Expected:
PASS with no whitespace errors.

- [ ] **Step 6: Commit**

```bash
git add src/echelon/cli.py README.md tests/unit/test_cli_spec_switch.py
git commit -m "docs: expose perfectionist spec authoring"
```
