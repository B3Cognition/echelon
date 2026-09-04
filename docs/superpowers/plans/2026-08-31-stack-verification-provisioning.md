# Stack Verification Provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let stacks declare verification services, generate target-local manual Compose artifacts, and block delivery before an LLM run when required services are unavailable.

**Architecture:** Stack YAML gains validated provisioner declarations that resolve with owner attribution. A pure provisioning module evaluates environment/Compose satisfaction and renders fixed verification files. Preflight and `stack provision` consume that result; delivery reuses it as a target-scoped no-LLM gate.

**Tech Stack:** Python 3.11+, dataclasses, PyYAML, Typer/legacy CLI adapter, pytest.

**Spec:** `docs/superpowers/specs/2026-08-31-stack-verification-provisioning-design.md`

## Global Constraints

- Provisioning is verification-only; no production deployment, cloud resources, CI/CD execution, or credentials.
- `stack provision` never starts/stops Docker or executes generated files.
- Output is target-root-relative: `docker-compose.echelon-verify.yml` and `.env.echelon-verify.example`.
- Refuse overwrite without `--force`.
- A non-empty required external environment value is ready; generated files are prepared, never ready.
- Delivery blocks before LLM invocation when a selected target has missing verification provisioning.

---

### Task 1: Stack provisioning schema and resolution

**Files:**
- Modify: `src/harness/stacks/schema.py`
- Modify: `src/harness/stacks/resolver.py`
- Modify: `src/harness/stacks/__init__.py`
- Modify: `runtime/stacks/game-persistence-postgres/stack.yml`
- Test: `tests/unit/test_stacks_schema.py`
- Test: `tests/unit/test_stacks_resolver.py`

**Interfaces:**
- Produces `StackProvisioner(id, scope, services, required_environment, readiness_command, satisfiers)`.
- Produces `StackProvisionerSatisfier(kind, variable=None, output=None, env_example=None)`.
- Extends `StackDefinition.provisioners` and `ResolvedStacks.provisioners`.
- `ResolvedStackProvisioner(owner_stack_id, provisioner)` preserves the declaring stack.

- [ ] **Step 1: Write failing schema tests**

```python
def test_stack_schema_parses_postgres_verification_provisioner(tmp_path: Path) -> None:
    definition = parse_stack_definition(_postgres_stack_raw(), tmp_path / "stack.yml")
    provisioner = definition.provisioners[0]
    assert provisioner.id == "postgres-verify"
    assert provisioner.required_environment == ["DATABASE_URL"]
    assert provisioner.satisfiers[1].output == "docker-compose.echelon-verify.yml"

def test_stack_schema_rejects_output_outside_target(tmp_path: Path) -> None:
    raw = _postgres_stack_raw()
    raw["provisioning"][0]["satisfiers"][1]["output"] = "../compose.yml"
    with pytest.raises(StackValidationError, match="target-relative"):
        parse_stack_definition(raw, tmp_path / "stack.yml")
```

- [ ] **Step 2: Verify red**

Run: `pytest tests/unit/test_stacks_schema.py -k provisioner -v`  
Expected: FAIL because `StackDefinition` has no `provisioners`.

- [ ] **Step 3: Implement strict immutable schema types**

```python
@dataclass(frozen=True)
class StackProvisionerSatisfier:
    kind: str
    variable: str | None = None
    output: str | None = None
    env_example: str | None = None
```

Validate `scope == "verification"`, unique ids, safe one-file relative output, at least one satisfier, and known keys. Keep stacks without `provisioning` unchanged.

- [ ] **Step 4: Resolve provisioners with owner ids**

Append each resolved stack’s provisioners in resolution order; reject incompatible duplicate ids from different stacks.

- [ ] **Step 5: Declare PostgreSQL provisioner**

Add `postgres-verify` to `game-persistence-postgres`, requiring `DATABASE_URL`, `pg_isready`, external-environment satisfaction, and Compose-template outputs.

- [ ] **Step 6: Verify green and commit**

Run: `pytest tests/unit/test_stacks_schema.py tests/unit/test_stacks_resolver.py -q`  
Expected: PASS.

```bash
git add src/harness/stacks/schema.py src/harness/stacks/resolver.py src/harness/stacks/__init__.py runtime/stacks/game-persistence-postgres/stack.yml tests/unit/test_stacks_schema.py tests/unit/test_stacks_resolver.py
git commit -m "feat: declare stack verification provisioners"
```

### Task 2: Pure provisioning evaluation and artifact rendering

**Files:**
- Create: `src/harness/stacks/provisioning.py`
- Test: `tests/unit/test_stack_provisioning.py`

**Interfaces:**
- Produces `ProvisioningStatus(state, provisioner_id, owner_stack_id, message, path=None)` where state is `ready`, `prepared`, or `missing`.
- Produces `provisioning_statuses(resolved, target_root, environment) -> list[ProvisioningStatus]`.
- Produces `render_provisioner(provisioner, target_root, force=False) -> list[Path]`.

- [ ] **Step 1: Write failing provisioning tests**

```python
def test_external_database_url_marks_postgres_ready(tmp_path: Path) -> None:
    statuses = provisioning_statuses(_resolved_postgres(), tmp_path, {"DATABASE_URL": "postgresql://isolated"})
    assert statuses[0].state == "ready"

def test_render_compose_writes_only_fixed_target_files(tmp_path: Path) -> None:
    written = render_provisioner(_resolved_postgres().provisioners[0], tmp_path)
    assert written == [tmp_path / "docker-compose.echelon-verify.yml", tmp_path / ".env.echelon-verify.example"]
    assert "postgres" in written[0].read_text(encoding="utf-8")

def test_render_refuses_existing_file_without_force(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.echelon-verify.yml").write_text("keep", encoding="utf-8")
    with pytest.raises(ProvisioningError, match="already exists"):
        render_provisioner(_resolved_postgres().provisioners[0], tmp_path)
```

- [ ] **Step 2: Verify red**

Run: `pytest tests/unit/test_stack_provisioning.py -q`  
Expected: FAIL because the provisioning module does not exist.

- [ ] **Step 3: Implement statuses and rendering**

Treat non-empty required environment values as ready; both generated files as prepared; otherwise missing. Resolve all outputs and reject escapes from target root. Render a pinned PostgreSQL service, healthcheck, named volume, disabled host port, env example, and manual Compose commands. Do not call subprocess.

- [ ] **Step 4: Verify green and commit**

Run: `pytest tests/unit/test_stack_provisioning.py -q`  
Expected: PASS.

```bash
git add src/harness/stacks/provisioning.py tests/unit/test_stack_provisioning.py
git commit -m "feat: render stack verification provisioners"
```

### Task 3: Provision-aware preflight and `stack provision`

**Files:**
- Modify: `src/harness/stacks/preflight.py`
- Modify: `src/harness/stacks/__init__.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/cli_app.py`
- Test: `tests/unit/test_stacks_preflight.py`
- Test: `tests/unit/test_cli_stack.py`

**Interfaces:**
- Extends `run_stack_preflight(..., target_root=None, environment=None)`.
- Adds `STACK_PROVISIONING_MISSING` and `STACK_PROVISIONING_PREPARED` findings.
- Adds `echelon stack provision [--stack <id>] [--target <path>] [--force] [--json]`.

- [ ] **Step 1: Write failing preflight and CLI tests**

```python
def test_preflight_reports_missing_postgres_provisioner(tmp_path: Path) -> None:
    result = run_stack_preflight(_resolved_postgres(), target_root=tmp_path, environment={})
    assert any(f.code == "STACK_PROVISIONING_MISSING" for f in result.findings)

def test_stack_provision_writes_target_local_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _cmd_stack(["provision", "--stack", "game-persistence-postgres", "--target", str(tmp_path)], project_root=tmp_path)
    assert (tmp_path / "docker-compose.echelon-verify.yml").is_file()
    assert "docker compose -f docker-compose.echelon-verify.yml up -d" in capsys.readouterr().out
```

- [ ] **Step 2: Verify red**

Run: `pytest tests/unit/test_stacks_preflight.py tests/unit/test_cli_stack.py -k provision -v`  
Expected: FAIL because preflight has no provisioning findings and the subcommand is unknown.

- [ ] **Step 3: Implement preflight and both CLI adapters**

Missing is an error; prepared is a warning explaining Echelon did not start Docker; ready has no finding. Parse repeatable `--stack`, `--target`, `--force`, and `--json`. Generate only missing templates, print paths plus manual setup/cleanup commands, and expose provisioners in stack JSON. Text stack list stays concise.

- [ ] **Step 4: Verify green and commit**

Run: `pytest tests/unit/test_stacks_preflight.py tests/unit/test_cli_stack.py -q`  
Expected: PASS.

```bash
git add src/harness/stacks/preflight.py src/harness/stacks/__init__.py src/echelon/cli.py src/echelon/cli_app.py tests/unit/test_stacks_preflight.py tests/unit/test_cli_stack.py
git commit -m "feat: preflight stack verification provisioning"
```

### Task 4: Target-scoped delivery gate

**Files:**
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_cli_delivery.py`
- Test: `tests/integration/test_polyrepo_delivery_convergence.py`

**Interfaces:**
- Adds `_delivery_provisioning_blockers(project_root, target_root) -> list[str]`.
- Calls it before target worktree/LLM construction for delivery run, continue, and resume.

- [ ] **Step 1: Write failing gate tests**

```python
def test_delivery_does_not_invoke_provider_when_postgres_provisioning_is_missing(...):
    with patch("echelon.cli._run_harness") as run_harness:
        _cmd_harness_run(["001"], command_prefix="echelon delivery run")
    run_harness.assert_not_called()
    assert "STACK_PROVISIONING_MISSING" in capsys.readouterr().err

def test_delivery_allows_external_database_url(..., monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://isolated")
    # Existing provider-invocation fixture reaches the normal harness boundary.
```

- [ ] **Step 2: Verify red**

Run: `pytest tests/unit/test_cli_delivery.py tests/integration/test_polyrepo_delivery_convergence.py -k provisioning -v`  
Expected: FAIL because delivery does not evaluate provisioners.

- [ ] **Step 3: Implement the gate**

Resolve effective stacks once per target. For missing services print stable remediation (`echelon stack provision --target <target>`); for prepared services require manual startup or an external URL. Do not create a worktree or invoke the LLM before the gate passes.

- [ ] **Step 4: Verify full scope and commit**

Run: `pytest tests/unit/test_stacks_schema.py tests/unit/test_stacks_resolver.py tests/unit/test_stack_provisioning.py tests/unit/test_stacks_preflight.py tests/unit/test_cli_stack.py tests/unit/test_cli_delivery.py tests/integration/test_polyrepo_delivery_convergence.py -q`  
Expected: PASS.

```bash
git add src/echelon/cli.py tests/unit/test_cli_delivery.py tests/integration/test_polyrepo_delivery_convergence.py
git commit -m "feat: gate delivery on stack provisioning"
```
