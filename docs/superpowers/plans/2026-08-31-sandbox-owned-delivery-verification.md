# Sandbox-Owned Delivery Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run all normal delivery verification inside a Docker sandbox with harness-owned service sidecars, never silently on the host.

**Architecture:** A verification plan resolves target image, dependency bootstrap, browser requirements, and target-local stack services before Ralph retries. `DockerWorktreeProvider` owns the internal network and sidecars; Ralph executes verification through the provider and writes mode-aware evidence. Host verification is explicit fallback only. Manual Compose remains a reproduction aid.

**Tech Stack:** Python 3.11, Docker/Podman-compatible CLI, `SandboxProvider`, Playwright images, PostgreSQL, pytest.

**Spec:** `docs/superpowers/specs/2026-08-31-sandbox-owned-delivery-verification-design.md`

## Global Constraints

- `harness.verification.execution` defaults to `sandbox`; host is explicit only.
- No Docker socket, host browser path, host package cache, or credential store enters the sandbox.
- Sidecars share the provider-created internal network and publish no host port.
- Credentials are per-attempt, redacted in evidence, and deleted with the sidecar.
- Setup failures block before LLM repair retries and are not product-test failures.
- `echelon stack provision` is manual reproduction only.
- Preserve schema 1.0 stacks and target-local stack selection.

---

### Task 1: Verification policy and target-derived plan

**Files:**
- Create: `src/harness/verification_plan.py`
- Modify: `src/harness/config.py`, `runtime/config-template.yml`, `src/harness/fingerprint.py`
- Test: `tests/unit/test_verification_plan.py`, `tests/unit/test_config.py`, `tests/unit/test_fingerprint.py`

**Interfaces:** Produces immutable `VerificationPlan(execution, image, bootstrap_commands, browser_requirement, services)` plus the provider-neutral `SandboxServiceSpec` type. `build_verification_plan(worktree, config, services=())` accepts resolved service specs later supplied by Task 3. Tasks 2 and 4 consume these types.

- [ ] **Step 1: Write failing tests**

```python
def test_default_verification_execution_is_sandbox() -> None:
    assert load_config_from_mapping({}).verification.execution == "sandbox"

def test_playwright_plan_uses_pinned_package_version(tmp_path: Path) -> None:
    write_package_json(tmp_path, {"devDependencies": {"@playwright/test": "1.62.1"}})
    plan = build_verification_plan(tmp_path, config())
    assert plan.image == "mcr.microsoft.com/playwright:v1.62.1-noble"
    assert plan.browser_requirement == "chromium"
```

- [ ] **Step 2: Run the tests red**

Run `.echelon/venv/bin/python -m pytest tests/unit/test_verification_plan.py tests/unit/test_config.py tests/unit/test_fingerprint.py -q`.

Expected: FAIL because verification policy and plan types do not exist.

- [ ] **Step 3: Implement the plan**

Add `VerificationConfig(execution="sandbox")` and reject unknown values. Parse pinned Playwright versions to select a compatible official image. Unpinned/ranged versions retain the selected sandbox image and add `pnpm exec playwright install --with-deps chromium` as a sandbox bootstrap stage. Never consult host Playwright cache.

- [ ] **Step 4: Run green and commit**

Run the Step 2 command and `git diff --check`; expect PASS. Commit `feat: plan sandbox-owned verification`.

### Task 2: Provider-owned sidecar lifecycle

**Files:**
- Modify: `src/harness/provider.py`, `src/harness/docker_provider.py`
- Create: `src/harness/sandbox_services.py`
- Test: `tests/unit/test_docker_provider.py`, `tests/unit/test_sandbox_services.py`

**Interfaces:** Consumes `SandboxServiceSpec` from Task 1. Produces `SandboxServiceHandle`, `start_services(handle, services)`, `service_logs(handle)`, and cleanup integrated into `destroy(handle)`.

- [ ] **Step 1: Write failing tests**

```python
def test_postgres_sidecar_uses_sandbox_network_without_host_port(monkeypatch) -> None:
    handle = provider.create(spec)
    service = provider.start_services(handle, (postgres_service(),))[0]
    assert "--network" in docker_args_for(service)
    assert "-p" not in docker_args_for(service)

def test_destroy_removes_services_before_internal_network(monkeypatch) -> None:
    handle = provider.create(spec)
    provider.start_services(handle, (postgres_service(),))
    provider.destroy(handle)
    assert docker_calls_are_ordered("rm", "network rm")
```

- [ ] **Step 2: Run red**

Run `.echelon/venv/bin/python -m pytest tests/unit/test_docker_provider.py tests/unit/test_sandbox_services.py -q`.

Expected: FAIL because sidecar APIs do not exist.

- [ ] **Step 3: Implement sidecar management**

Use the provider’s container CLI, session labels, and existing internal network. Generate service credentials in memory; pass only service-local and sandbox-local values. Health-poll with a bounded timeout. On partial failure remove services before the network. Do not run Docker within the sandbox.

- [ ] **Step 4: Run green and commit**

Run the Step 2 command and `git diff --check`; expect PASS. Commit `feat: manage verification services in sandbox network`.

### Task 3: Stack service contracts and target-aware discovery

**Files:**
- Modify: `src/harness/stacks/schema.py`, `src/harness/stacks/resolver.py`, `src/harness/stacks/provisioning.py`, `src/harness/stacks/preflight.py`
- Modify: `src/echelon/cli.py`, `src/echelon/cli_app.py`, `runtime/stacks/game-persistence-postgres/stack.yml`
- Test: `tests/unit/test_stacks_schema.py`, `tests/unit/test_stack_provisioning.py`, `tests/unit/test_stacks_preflight.py`, `tests/unit/test_cli_stack.py`

**Interfaces:** Produces `ResolvedStackService` for Task 1. Adds read-only `echelon stack preflight --target <path>`. Keeps manual renderer separate.

- [ ] **Step 1: Write failing tests**

```python
def test_postgres_stack_resolves_internal_sandbox_service() -> None:
    resolved = resolve_stacks(["game-persistence-postgres"], definitions())
    assert resolved.services[0].service_name == "postgres"
    assert resolved.services[0].environment_names == ("TEST_DATABASE_URL",)

def test_stack_preflight_target_reports_sandbox_bootstrap(tmp_path, runner) -> None:
    result = runner.invoke(app, ["stack", "preflight", "--target", str(tmp_path)])
    assert "sandbox-bootstrap-required" in result.output
```

- [ ] **Step 2: Run red**

Run `.echelon/venv/bin/python -m pytest tests/unit/test_stacks_schema.py tests/unit/test_stack_provisioning.py tests/unit/test_stacks_preflight.py tests/unit/test_cli_stack.py -q`.

Expected: FAIL because sandbox-service declarations and target preflight are absent.

- [ ] **Step 3: Implement safe contracts**

Accept only the bundled PostgreSQL 16 service shape in this iteration: internal 5432, fixed health command, and declared test environment name. Reject arbitrary service commands, volume mounts, host ports, and unknown service kinds during schema load. Keep local Compose fixed-path rendering but label it local reproduction, never delivery setup.

- [ ] **Step 4: Run green and commit**

Run the Step 2 command and `git diff --check`; expect PASS. Commit `feat: resolve sandbox verification services from stacks`.

### Task 4: Ralph sandbox execution and authoritative evidence

**Files:**
- Modify: `src/harness/ralph.py`, `src/harness/verification_evidence.py`, `src/harness/verify_result.py`, `src/harness/fulfillment_runner.py`
- Test: `tests/unit/test_ralph_outer.py`, `tests/unit/test_verification_evidence.py`, `tests/unit/test_fulfillment_runner.py`

**Interfaces:** Consumes Task 1 plan and Task 2 sidecars. Produces a receipt with `execution_mode`, image, bootstrap stages, redacted service metadata, candidate commit, and candidate fingerprint.

- [ ] **Step 1: Write failing tests**

```python
def test_configured_verify_command_uses_sandbox_provider(tmp_path, controller, provider) -> None:
    controller._config.verify_command = "pnpm verify"
    controller._verify_build(tmp_path)
    assert provider.executed_commands[-1] == "pnpm verify"
    assert no_host_subprocess_was_called()

def test_service_setup_failure_blocks_without_inner_retry(tmp_path, controller, provider) -> None:
    provider.start_services.side_effect = SandboxSetupError("image pull failed")
    result = controller.run()
    assert result.termination_reason == "sandbox_verification_unavailable"
    assert controller.llm_call_count == 0
```

- [ ] **Step 2: Run red**

Run `.echelon/venv/bin/python -m pytest tests/unit/test_ralph_outer.py tests/unit/test_verification_evidence.py tests/unit/test_fulfillment_runner.py -k 'sandbox or verification' -q`.

Expected: FAIL because Ralph runs configured verification through host `subprocess.run`.

- [ ] **Step 3: Implement sandbox verification**

Create one verification sandbox after the LLM has produced the candidate. Execute bootstrap and configured/detected verifier through `provider.exec`; capture bounded test artifacts and service logs before teardown. Host verification is permitted only by explicit configuration and receipt wording is `host-fallback`. Translate image, sidecar, and network setup faults into non-retryable environment setup results.

- [ ] **Step 4: Run green and commit**

Run the Step 2 command and `git diff --check`; expect PASS. Commit `fix: run delivery verification inside sandbox`.

### Task 5: Accurate delivery outcomes and end-to-end coverage

**Files:**
- Modify: `src/echelon/cli.py`, `src/echelon/orchestrator.py`, `README.md`
- Create: `tests/integration/test_sandbox_verification.py`
- Modify: `tests/unit/test_cli_delivery.py`, `tests/unit/test_orchestrator.py`, `tests/integration/test_polyrepo_delivery_convergence.py`

**Interfaces:** Consumes Task 4 setup outcomes. Produces `converged`, `blocked`, `failed`, or `skipped` target facts and non-zero aggregate result for any blocked target.

- [ ] **Step 1: Write failing tests**

```python
def test_sandbox_unavailable_blocks_before_provider_retry(capsys, configured_delivery) -> None:
    assert run_delivery(configured_delivery).returncode == 1
    assert "SANDBOX_VERIFICATION_UNAVAILABLE" in capsys.readouterr().err

def test_multi_target_summary_never_calls_blocked_target_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(orchestrator, "run_worker", blocked_worker)
    assert run_multi_target(...) == 1
    assert "completed successfully" not in capsys.readouterr().out
```

- [ ] **Step 2: Run red**

Run `.echelon/venv/bin/python -m pytest tests/unit/test_cli_delivery.py tests/unit/test_orchestrator.py tests/integration/test_polyrepo_delivery_convergence.py -k 'sandbox or blocked or provisioning' -q`.

Expected: FAIL because setup faults become repeated verification failures and summaries trust an incorrect worker success status.

- [ ] **Step 3: Implement status, docs, and Docker integration fixture**

Persist target outcome separately from worker process result, preserve independent-target continuation and dependency skips, and build parent summary from outcome. Document Docker as the only default host prerequisite. Add an opt-in Docker fixture running pnpm/Playwright plus PostgreSQL sidecar; assert service DNS URI, no host port, labelled cleanup, and no host browser/node_modules dependency.

- [ ] **Step 4: Run complete scoped verification**

Run `.echelon/venv/bin/python -m pytest tests/unit/test_verification_plan.py tests/unit/test_docker_provider.py tests/unit/test_sandbox_services.py tests/unit/test_stacks_schema.py tests/unit/test_stack_provisioning.py tests/unit/test_stacks_preflight.py tests/unit/test_cli_stack.py tests/unit/test_ralph_outer.py tests/unit/test_verification_evidence.py tests/unit/test_fulfillment_runner.py tests/unit/test_cli_delivery.py tests/unit/test_orchestrator.py tests/integration/test_polyrepo_delivery_convergence.py tests/integration/test_sandbox_verification.py -q` and `git diff --check`.

Expected: PASS; Docker integration can skip only when Docker is unavailable.

- [ ] **Step 5: Commit**

Commit `fix: report sandbox delivery outcomes accurately`.

## Plan self-review

- Tasks 1–4 cover sandbox policy, browser assets, services, execution, and evidence.
- Task 3 preserves manual reproduction without making it delivery infrastructure.
- Task 5 covers environment failure classification and the false-success CLI regression.
- Each task has file paths, interfaces, red/green tests, and a commit boundary.
