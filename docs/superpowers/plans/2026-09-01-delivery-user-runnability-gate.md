# Delivery User-Runnability Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent Echelon from converging or landing a required user-facing target until a fresh sandbox proves its real composed user journey, required service observations, persistence behavior, documentation, and evidence provenance.

**Architecture:** Resolved stacks declare the runnability policy and runner. The candidate worktree declares concrete commands and a harness-driven journey in `.echelon/runnability.yml`. A new deterministic runner provisions a fresh sandbox and sidecars, drives the journey through typed adapters, persists content-addressed evidence, feeds failures into Ralph's existing repair loop, and exposes the result to documentation, status, deferral, and landing gates.

**Tech Stack:** Python 3 dataclasses and PyYAML, existing `SandboxProvider`/Docker sidecars, Node.js Playwright helper for browser journeys, pytest, Typer CLI, YAML/JSON/Markdown evidence.

**Spec:** `docs/superpowers/specs/2026-09-01-delivery-user-runnability-gate-design.md`

## Global Constraints

- Only deterministic sandbox execution may produce `status: runnable`.
- Build, browser, service, database, and teardown commands run inside the delivery sandbox boundary; never on the host.
- The candidate contract is `.echelon/runnability.yml` in the candidate worktree and is loaded after every build/fix.
- Product source cannot disable a stack-required gate or select follow-up scope.
- Evidence authority is the product content fingerprint plus candidate-contract hash plus resolved-stack hash; commit SHA is informational.
- A project command's exit code is not sufficient journey evidence; harness-owned observations are mandatory.
- Browser 3D and browser WASM use `linux_container` in the first release. iOS records `macos_simulator` but is not enforced until that runner exists.
- Existing projects with neither a required user-facing stack nor an explicit enabled contract remain unaffected.
- Every command/output artifact is bounded and secret-redacted using the existing verification-evidence policy.
- Preserve all unrelated uncommitted changes already present in the worktree.

---

### Task 1: Stack Runnability Schema And Resolution

**Files:**
- Modify: `src/harness/stacks/schema.py`
- Modify: `src/harness/stacks/resolver.py`
- Modify: `src/harness/stacks/renderer.py`
- Modify: `src/harness/stacks/__init__.py`
- Test: `tests/unit/test_stacks_schema.py`
- Test: `tests/unit/test_stacks_resolver.py`

**Interfaces:**
- Produces: `StackRunnability`, parsed on every `StackDefinition`.
- Produces: `ResolvedRunnability`, exposed as `ResolvedStacks.runnability`.
- Produces: `resolved_stack_contract_sha256(resolved: ResolvedStacks) -> str`.
- Consumes later: candidate-contract requirement decisions, runner selection, required observation IDs, and stable stack hashing.

- [ ] **Step 1: Write failing schema tests**

Add tests proving schema version `1.2` accepts runnability, older versions reject it, and invalid policies/runners/capabilities fail closed:

```python
@pytest.mark.unit
def test_stack_schema_parses_required_linux_runnability() -> None:
    raw = {
        **VALID_STACK,
        "schema_version": "1.2",
        "runnability": {
            "classification": "user_facing",
            "policy": "required",
            "runner": "linux_container",
            "capabilities": ["install", "start", "primary_journey", "stop"],
            "required_observations": ["browser_dom"],
        },
    }

    parsed = parse_stack_definition(raw, Path("stack.yml"))

    assert parsed.runnability.policy == "required"
    assert parsed.runnability.runner == "linux_container"
    assert parsed.runnability.required_observations == ("browser_dom",)


@pytest.mark.unit
def test_stack_schema_rejects_runnability_before_schema_1_2() -> None:
    raw = {**VALID_STACK, "runnability": {"policy": "required"}}

    with pytest.raises(StackValidationError, match="runnability requires stack schema_version 1.2"):
        parse_stack_definition(raw, Path("stack.yml"))
```

- [ ] **Step 2: Run schema tests and verify RED**

Run:

```bash
pytest -q tests/unit/test_stacks_schema.py -k runnability
```

Expected: FAIL because `StackDefinition` has no `runnability` field and schema `1.2` is unsupported.

- [ ] **Step 3: Implement the stack schema**

Add exact typed contracts and parser validation:

```python
VALID_RUNNABILITY_CLASSIFICATIONS = {"user_facing", "non_runnable"}
VALID_RUNNABILITY_POLICIES = {"required", "advisory", "not_applicable"}
VALID_RUNNABILITY_RUNNERS = {"linux_container", "macos_simulator"}
VALID_RUNNABILITY_CAPABILITIES = {
    "install", "provision", "start", "readiness", "primary_journey", "stop"
}
VALID_RUNNABILITY_OBSERVATIONS = {"browser_dom", "http", "exec", "postgres_query"}


@dataclass(frozen=True)
class StackRunnability:
    classification: str = "non_runnable"
    policy: str = "not_applicable"
    runner: str | None = None
    capabilities: tuple[str, ...] = ()
    required_observations: tuple[str, ...] = ()
```

Parse only declared keys, reject duplicates and unknown values, and require `schema_version: "1.2"` whenever `runnability` is present.

- [ ] **Step 4: Write failing resolution tests**

Extend `_stack()` with `runnability: StackRunnability | None = None`, then add:

```python
@pytest.mark.unit
def test_resolve_runnability_unions_capabilities_and_uses_strongest_policy() -> None:
    web = _stack(
        "web",
        provides={"web_app.framework": "vite-react"},
        runnability=StackRunnability(
            classification="user_facing",
            policy="required",
            runner="linux_container",
            capabilities=("start", "primary_journey"),
            required_observations=("browser_dom",),
        ),
    )
    persistence = _stack(
        "persistence",
        provides={"data.database": "postgres"},
        runnability=StackRunnability(
            classification="non_runnable",
            policy="advisory",
            runner="linux_container",
            capabilities=("provision",),
            required_observations=("postgres_query",),
        ),
    )

    resolved = resolve_stacks(["web", "persistence"], {"web": web, "persistence": persistence})

    assert resolved.runnability.policy == "required"
    assert resolved.runnability.capabilities == (
        "start", "primary_journey", "provision"
    )
    assert resolved.runnability.required_observations == (
        "browser_dom", "postgres_query"
    )


@pytest.mark.unit
def test_resolve_runnability_rejects_incompatible_runners() -> None:
    linux = _stack("linux", provides={}, runnability=StackRunnability(runner="linux_container"))
    mac = _stack("mac", provides={}, runnability=StackRunnability(runner="macos_simulator"))

    with pytest.raises(StackConflictError, match="runnability runner"):
        resolve_stacks(["linux", "mac"], {"linux": linux, "mac": mac})


@pytest.mark.unit
def test_resolved_stack_contract_hash_is_order_stable() -> None:
    first = resolve_stacks(["web", "persistence"], STACK_REGISTRY)
    second = resolve_stacks(["persistence", "web"], STACK_REGISTRY)

    assert resolved_stack_contract_sha256(first) == resolved_stack_contract_sha256(second)
```

- [ ] **Step 5: Run resolution tests and verify RED**

Run:

```bash
pytest -q tests/unit/test_stacks_resolver.py -k runnability
```

Expected: FAIL because `ResolvedStacks` does not aggregate runnability.

- [ ] **Step 6: Implement deterministic resolution and rendering**

Add:

```python
@dataclass(frozen=True)
class ResolvedRunnability:
    classification: str = "non_runnable"
    policy: str = "not_applicable"
    runner: str | None = None
    capabilities: tuple[str, ...] = ()
    required_observations: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
```

Use policy rank `not_applicable=0`, `advisory=1`, `required=2`, preserve first-seen list order, reject incompatible non-empty runners, and expose all fields in `resolved_to_dict()`/Markdown so stack status explains why the gate is required.
Hash a canonical sorted JSON representation containing selected stack IDs, resolved
runnability, and materialized service contracts; do not include filesystem paths or
selection order.

- [ ] **Step 7: Run the complete stack regression slice**

Run:

```bash
pytest -q tests/unit/test_stacks_schema.py tests/unit/test_stacks_resolver.py tests/unit/test_stacks_integration.py tests/unit/test_cli_stack.py
```

Expected: PASS.

- [ ] **Step 8: Commit Task 1**

```bash
git add src/harness/stacks/schema.py src/harness/stacks/resolver.py src/harness/stacks/renderer.py src/harness/stacks/__init__.py tests/unit/test_stacks_schema.py tests/unit/test_stacks_resolver.py
git commit -m "feat: resolve stack runnability obligations"
```

### Task 2: Candidate Runnability Contract

**Files:**
- Create: `src/harness/runnability_contract.py`
- Create: `tests/unit/test_runnability_contract.py`
- Modify: `src/harness/product_inventory.py`
- Test: `tests/unit/test_product_inventory.py`

**Interfaces:**
- Produces: `load_runnability_contract(worktree: Path) -> RunnabilityContract | None`.
- Produces: `runnability_contract_sha256(contract) -> str`.
- Produces: typed `JourneyStep` and `Observation` values consumed only by the runner.
- Keeps `.echelon/runnability.yml` outside the product fingerprint while binding it through its separate canonical hash.

- [ ] **Step 1: Write failing parser and validation tests**

Create fixtures with literal expected values:

```python
@pytest.mark.unit
def test_loads_candidate_owned_browser_contract(tmp_path: Path) -> None:
    path = tmp_path / ".echelon" / "runnability.yml"
    path.parent.mkdir()
    path.write_text(BROWSER_CONTRACT, encoding="utf-8")

    contract = load_runnability_contract(tmp_path)

    assert contract is not None
    assert contract.primary_journey.kind == "browser"
    assert contract.primary_journey.steps[0].action == "goto"
    assert [item.kind for item in contract.primary_journey.observations] == [
        "browser_dom", "postgres_query"
    ]


@pytest.mark.unit
def test_contract_rejects_product_policy_override(tmp_path: Path) -> None:
    _write_contract(tmp_path, BROWSER_CONTRACT + "\nscope: follow_up\n")

    with pytest.raises(RunnabilityContractError, match="unknown field.*scope"):
        load_runnability_contract(tmp_path)


@pytest.mark.unit
def test_contract_requires_non_exit_observation(tmp_path: Path) -> None:
    _write_contract(tmp_path, EXEC_ONLY_CONTRACT)

    with pytest.raises(RunnabilityContractError, match="observable assertion"):
        load_runnability_contract(tmp_path)
```

- [ ] **Step 2: Run parser tests and verify RED**

Run:

```bash
pytest -q tests/unit/test_runnability_contract.py
```

Expected: ERROR importing the missing module.

- [ ] **Step 3: Implement typed parsing with fail-closed unknown fields**

Define focused immutable types:

```python
CONTRACT_PATH = Path(".echelon/runnability.yml")
ALLOWED_VARIABLES = {
    "ECHELON_PORT", "ECHELON_BASE_URL", "ECHELON_MARKER", "ECHELON_SESSION_TOKEN"
}


@dataclass(frozen=True)
class JourneyStep:
    action: str
    path: str | None = None
    selector: str | None = None
    state: str | None = None
    key: str | None = None
    repeat: int = 1


@dataclass(frozen=True)
class Observation:
    id: str
    kind: str
    expectation: str
    selector: str | None = None
    statement: str | None = None
    parameters: tuple[str, ...] = ()


@dataclass(frozen=True)
class PrimaryJourney:
    kind: str
    url: str
    requirements: tuple[str, ...]
    real_services_required: tuple[str, ...]
    session_storage: tuple[tuple[str, str], ...]
    steps: tuple[JourneyStep, ...]
    observations: tuple[Observation, ...]


@dataclass(frozen=True)
class RunnabilityContract:
    schema_version: int
    enabled: bool
    install_commands: tuple[str, ...]
    bootstrap_commands: tuple[str, ...]
    start_commands: tuple[str, ...]
    stop_commands: tuple[str, ...]
    restart_commands: tuple[str, ...]
    readiness_url: str
    readiness_timeout_ms: int
    identity_command: str | None
    identity_exports: tuple[tuple[str, str], ...]
    primary_journey: PrimaryJourney
    persistence_observation_ids: tuple[str, ...]
```

Reject absolute paths, YAML aliases with non-scalar surprises, empty required commands, unsupported `${...}` variables, duplicate observation IDs, missing required observation references, empty `requirements` or `real_services_required`, browser journeys without `goto`/DOM assertion, and SQL observations without positional parameters.

- [ ] **Step 4: Write digest and inventory-boundary tests**

```python
@pytest.mark.unit
def test_contract_digest_is_key_order_independent(tmp_path: Path) -> None:
    first = load_runnability_contract(_write_contract(tmp_path / "a", BROWSER_CONTRACT))
    second = load_runnability_contract(_write_contract(tmp_path / "b", REORDERED_BROWSER_CONTRACT))

    assert runnability_contract_sha256(first) == runnability_contract_sha256(second)


@pytest.mark.unit
def test_product_fingerprint_excludes_contract_but_contract_hash_changes(tmp_path: Path) -> None:
    _init_git_product(tmp_path)
    first_product = product_evidence_fingerprint(tmp_path)
    first_contract = runnability_contract_sha256(load_runnability_contract(tmp_path))
    _replace_selector(tmp_path, "[data-checkpoint-state=missing]")

    assert product_evidence_fingerprint(tmp_path) == first_product
    assert runnability_contract_sha256(load_runnability_contract(tmp_path)) != first_contract
```

- [ ] **Step 5: Run tests and verify RED, then implement canonical hashing**

Run:

```bash
pytest -q tests/unit/test_runnability_contract.py tests/unit/test_product_inventory.py -k 'contract or fingerprint'
```

Expected before implementation: FAIL on digest and boundary assertions. Serialize dataclasses to sorted compact JSON and SHA-256 that representation. Keep `.echelon` excluded from `product_evidence_fingerprint()`.

- [ ] **Step 6: Run Task 2 tests and commit**

```bash
pytest -q tests/unit/test_runnability_contract.py tests/unit/test_product_inventory.py
git add src/harness/runnability_contract.py src/harness/product_inventory.py tests/unit/test_runnability_contract.py tests/unit/test_product_inventory.py
git commit -m "feat: parse candidate runnability contracts"
```

Expected: PASS.

### Task 3: Content-Addressed Runnability Evidence

**Files:**
- Create: `src/harness/runnability_evidence.py`
- Create: `tests/unit/test_runnability_evidence.py`
- Reuse: `src/harness/verification_evidence.py`

**Interfaces:**
- Produces: `write_runnability_report(...) -> RunnabilityEvidenceRef`.
- Produces: `validate_runnability_report(ref, candidate_fingerprint, contract_hash, stack_hash) -> RunnabilityEvidenceValidation`.
- Consumes: redaction and atomic-write behavior from verification evidence without sharing its exact-commit validation rule.

- [ ] **Step 1: Write failing evidence tests**

```python
@pytest.mark.unit
def test_passing_report_survives_commit_only_change(tmp_path: Path) -> None:
    ref = _write_report(
        tmp_path,
        status="runnable",
        candidate_commit="a" * 40,
        candidate_fingerprint="product-1",
        contract_hash="contract-1",
        stack_hash="stack-1",
    )

    result = validate_runnability_report(
        ref,
        candidate_commit="b" * 40,
        candidate_fingerprint="product-1",
        contract_hash="contract-1",
        stack_hash="stack-1",
    )

    assert result.valid is True


@pytest.mark.unit
@pytest.mark.parametrize("field", ["candidate_fingerprint", "contract_hash", "stack_hash"])
def test_report_rejects_changed_authoritative_hash(tmp_path: Path, field: str) -> None:
    ref = _write_report(tmp_path, status="runnable")
    inputs = _matching_validation_inputs()
    inputs[field] = "changed"

    assert validate_runnability_report(ref, **inputs).valid is False


@pytest.mark.unit
def test_report_redacts_generated_credentials_and_bounds_output(tmp_path: Path) -> None:
    ref = _write_report(tmp_path, stdout="secret-token\n" + "x" * 100_000)
    payload = json.loads(ref.path.read_text(encoding="utf-8"))

    assert "secret-token" not in json.dumps(payload)
    assert len(payload["stages"][0]["stdout_tail"]) <= OUTPUT_TAIL_BYTES
```

- [ ] **Step 2: Run evidence tests and verify RED**

```bash
pytest -q tests/unit/test_runnability_evidence.py
```

Expected: ERROR importing the missing module.

- [ ] **Step 3: Implement immutable report receipts**

Use these core types:

```python
@dataclass(frozen=True)
class RunnabilityStage:
    name: str
    status: str
    command: tuple[str, ...] = ()
    exit_code: int | None = None
    duration_ms: int = 0
    stdout: bytes = b""
    stderr: bytes = b""


@dataclass(frozen=True)
class RunnabilityEvidenceRef:
    path: Path
    receipt_sha256: str
    evidence_sha256: str
    candidate_commit: str
    candidate_fingerprint: str
    contract_hash: str
    stack_hash: str
    status: str
```

Accept only `runnable`, `not_runnable`, `blocked`, `deferred`, and `not_applicable`. A `runnable` report requires all required stages and observations to pass. Persist immutable attempt files plus `latest.json`, reject symlinks/path traversal, redact with `redact_verification_text()`, and make validation ignore commit mismatch while still checking receipt/evidence digests and all three authoritative hashes.

- [ ] **Step 4: Add Markdown rendering and failure classification tests**

Assert the Markdown report names the failed stage, diagnostic code, exact candidate contract path, and suggested repair action without printing secrets.

- [ ] **Step 5: Run and commit Task 3**

```bash
pytest -q tests/unit/test_runnability_evidence.py tests/unit/test_verification_evidence.py
git add src/harness/runnability_evidence.py tests/unit/test_runnability_evidence.py
git commit -m "feat: record authoritative runnability evidence"
```

Expected: PASS.

### Task 4: Fresh-Sandbox Runner And Harness-Owned Observations

**Files:**
- Modify: `src/harness/provider.py`
- Modify: `src/harness/docker_provider.py`
- Modify: `src/harness/verification_plan.py`
- Create: `src/harness/runnability_runner.py`
- Create: `runtime/scripts/user-runnability-browser.mjs`
- Create: `tests/unit/test_runnability_runner.py`
- Create: `tests/unit/test_docker_provider.py`
- Modify: `tests/integration/test_docker_provider.py`
- Create: `tests/integration/test_user_runnability_browser.py`

**Interfaces:**
- Adds optional `SandboxProvider.exec_service(handle, service_name, argv, timeout_ms)` for harness-owned sidecar observations.
- Produces: `RunnabilityRunner.run(...) -> RunnabilityRunResult`.
- Consumes: `RunnabilityContract`, `ResolvedRunnability`, `SandboxServiceSpec`, and evidence writer.

- [ ] **Step 1: Write failing provider sidecar-exec tests**

```python
@pytest.mark.unit
def test_exec_service_targets_only_attempt_owned_named_sidecar(provider, handle, monkeypatch) -> None:
    provider.start_services(handle, (POSTGRES_SERVICE,))

    result = provider.exec_service(
        handle,
        "postgres",
        ("psql", "-Atqc", "SELECT 1"),
        timeout_ms=30_000,
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "1"


@pytest.mark.unit
def test_exec_service_rejects_unknown_service(provider, handle) -> None:
    with pytest.raises(NotSupportedError, match="service.*not active"):
        provider.exec_service(handle, "postgres", ("true",))
```

- [ ] **Step 2: Run provider tests and verify RED**

```bash
pytest -q tests/unit/test_docker_provider.py -k exec_service
```

Expected: FAIL because the provider has no sidecar exec surface or name-to-container mapping.

- [ ] **Step 3: Implement bounded sidecar execution**

Add an optional provider method that defaults to `NotSupportedError`. In Docker, store `service_name -> container_id` under the active session and invoke the container CLI with an argv list, timeout, bounded capture, and no shell interpolation. Return an `ExecResult`; remove mappings during destroy.

- [ ] **Step 4: Write failing runner stage-order and cleanup tests**

Use a real fake provider that records observable calls and returns literal results:

```python
@pytest.mark.unit
def test_runner_uses_fresh_sandbox_and_executes_required_stages(tmp_path: Path) -> None:
    provider = RecordingProvider(browser_observation="present", postgres_rows="player-123\n")
    result = _runner(provider, tmp_path).run(
        worktree=tmp_path,
        contract=BROWSER_CONTRACT_OBJECT,
        stack=REQUIRED_BROWSER_POSTGRES,
    )

    assert result.status == "runnable"
    assert provider.calls == [
        "create", "start_services", "install", "bootstrap", "identity",
        "start", "readiness", "browser_journey", "postgres_before",
        "restart", "browser_after", "postgres_after", "stop", "destroy",
    ]


@pytest.mark.unit
@pytest.mark.parametrize("failure", ["install", "start", "readiness", "browser_journey", "postgres_after"])
def test_runner_always_stops_and_destroys_after_failure(tmp_path: Path, failure: str) -> None:
    provider = RecordingProvider(fail_at=failure)

    result = _runner(provider, tmp_path).run(
        worktree=tmp_path,
        contract=BROWSER_CONTRACT_OBJECT,
        resolved=REQUIRED_BROWSER_POSTGRES,
        candidate_commit="a" * 40,
        evidence_dir=tmp_path / "evidence",
    )

    assert result.status == "not_runnable"
    assert provider.calls[-2:] == ["stop", "destroy"]
```

- [ ] **Step 5: Run runner tests and verify RED**

```bash
pytest -q tests/unit/test_runnability_runner.py
```

Expected: ERROR importing the missing runner.

- [ ] **Step 6: Implement the runnability planner and lifecycle**

The runner must:

```python
class RunnabilityRunner:
    def run(
        self,
        *,
        worktree: Path,
        contract: RunnabilityContract,
        resolved: ResolvedStacks,
        candidate_commit: str,
        evidence_dir: Path,
    ) -> RunnabilityRunResult:
        handle = self._provider.create(self._sandbox_spec(worktree, resolved))
        try:
            services = materialize_services(tuple(resolved.services), session_id=handle.session_id)
            self._start_services(handle, services)
            return self._execute_contract(
                handle=handle,
                contract=contract,
                resolved=resolved,
                candidate_commit=candidate_commit,
                evidence_dir=evidence_dir,
            )
        finally:
            self._stop_processes_best_effort(handle)
            self._provider.destroy(handle)
```

Create a new handle for every invocation. Never accept an existing handle. Use provisioner-declared environment names, including `DATABASE_URL`; preserve `TEST_DATABASE_URL` for the existing verification suite. Generate a UUID marker after bootstrap. Background processes use PID/log files and are killed on every exit path.

- [ ] **Step 7: Implement harness-owned adapters**

The browser helper consumes a generated JSON plan and emits JSON observations. It creates its own Playwright context, rejects unsupported actions, exposes only `goto`, `click`, `fill`, `press`, and `expect`, and never exposes request interception APIs to candidate code.

Postgres observations execute inside the sidecar with parameter values passed through `psql --set` variables; never concatenate the marker into SQL. Compare literal normalized rows to the declared expectation. HTTP and exec adapters require an explicit response/output assertion in addition to exit status.
Before declaring the primary journey passed, require one successful harness-owned
observation for every `real_services_required` entry. Map `web` to the browser origin,
`api` to a declared HTTP observation, and `postgres` to a direct sidecar query. Reject
an unknown service name at contract-validation time and classify a live UI with a failed
required service observation as `mocked_dependency_detected`.

- [ ] **Step 8: Add the Docker browser integration fixture**

Create a tiny HTTP fixture whose page changes DOM only after a real API request writes the marker to Postgres. Assert the full runner passes. Add a second fixture that serves a static shell and assert `primary_journey_failed` despite HTTP 200. Add a third fixture whose UI satisfies the DOM assertion while the declared API boundary is unavailable; assert `mocked_dependency_detected` and prove no passing report is written. Keep the Postgres sidecar alive while restarting only the declared application processes, then require the same marker through both browser and direct Postgres observations after restart.

Run:

```bash
pytest -q tests/unit/test_runnability_runner.py tests/unit/test_docker_provider.py -k 'runnability or exec_service'
pytest -q -m docker tests/integration/test_user_runnability_browser.py
```

Expected: PASS when Docker is available; the Docker-marked test may skip only under the repository's existing Docker-unavailable convention.

- [ ] **Step 9: Commit Task 4**

```bash
git add src/harness/provider.py src/harness/docker_provider.py src/harness/verification_plan.py src/harness/runnability_runner.py runtime/scripts/user-runnability-browser.mjs tests/unit/test_runnability_runner.py tests/unit/test_docker_provider.py tests/integration/test_docker_provider.py tests/integration/test_user_runnability_browser.py
git commit -m "feat: verify user journeys in fresh sandboxes"
```

### Task 5: Owner-Controlled Deferral And Follow-Up Proposal

**Files:**
- Create: `src/harness/runnability_disposition.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `src/echelon/cli.py`
- Create: `tests/unit/test_runnability_disposition.py`
- Create: `tests/unit/test_cli_runnability_disposition.py`

**Interfaces:**
- Produces: `read_runnability_disposition(spec_dir) -> RunnabilityDisposition`.
- Produces: `defer_runnability(...)` and `plan_runnability(...)` history-preserving mutations.
- Produces: owner command surfaces `echelon spec defer-runnability` and `echelon spec plan-runnability`.

- [ ] **Step 1: Write failing ledger tests**

```python
@pytest.mark.unit
def test_defer_records_owner_reason_and_follow_up_without_erasing_history(tmp_path: Path) -> None:
    report = _failed_report(tmp_path, failure_class="primary_journey_failed")

    deferred = defer_runnability(
        spec_dir=tmp_path,
        target="sources/game",
        reason="Local deployment is explicitly scheduled as a separate deliverable.",
        evidence_report=report,
        approved_at="2026-09-01T12:00:00+00:00",
    )
    planned = plan_runnability(tmp_path, planned_at="2026-09-01T13:00:00+00:00")

    assert deferred.status == "deferred"
    assert planned.status == "planned"
    assert len(read_runnability_history(tmp_path)) == 2
    assert (tmp_path / "runnability-follow-up.md").exists()


@pytest.mark.unit
def test_product_contract_cannot_create_owner_disposition(tmp_path: Path) -> None:
    _write_candidate_contract(tmp_path, extra="scope: follow_up")

    with pytest.raises(RunnabilityContractError):
        load_runnability_contract(tmp_path)
```

- [ ] **Step 2: Run ledger tests and verify RED**

```bash
pytest -q tests/unit/test_runnability_disposition.py
```

Expected: ERROR importing the missing module.

- [ ] **Step 3: Implement atomic owner disposition and proposal rendering**

Use `runnability-disposition.json` schema version 1 with append-only events:

```json
{
  "schema_version": 1,
  "events": [
    {
      "status": "deferred",
      "target": "sources/game",
      "reason": "Local deployment is explicitly scheduled as a separate deliverable.",
      "at": "2026-09-01T12:00:00+00:00",
      "evidence_report": "/absolute/run/evidence/report.json",
      "follow_up_proposal": "runnability-follow-up.md"
    }
  ]
}
```

Require a non-empty reason and an existing failed current report. Render a deterministic proposal with the failed capabilities, report evidence, title `Make <target> locally runnable`, acceptance criteria for each failed stage, and the existing command `echelon spec run "<intent>" --target <target>`. Never invoke an LLM or create a spec.

- [ ] **Step 4: Write and run failing CLI tests**

Use Typer's existing CLI runner pattern to prove dry failure, applied deferral, inverse planning, and missing-report rejection. Then add the two commands in `cli_app.py` and usage text in `cli.py`.

```bash
pytest -q tests/unit/test_cli_runnability_disposition.py tests/unit/test_runnability_disposition.py
```

Expected after implementation: PASS.

- [ ] **Step 5: Commit Task 5**

```bash
git add src/harness/runnability_disposition.py src/echelon/cli_app.py src/echelon/cli.py tests/unit/test_runnability_disposition.py tests/unit/test_cli_runnability_disposition.py
git commit -m "feat: add owner runnability deferral lifecycle"
```

### Task 6: Ralph Gate, Repair Loop, And State

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `src/harness/config.py`
- Modify: `src/harness/ralph.py`
- Modify: `src/harness/coordinator.py`
- Test: `tests/unit/test_ralph_outer.py`
- Test: `tests/unit/test_ralph_inner.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Attaches the resolved stack object/policy to runtime config without reading candidate policy from `.echelon/config.yml`.
- Adds `RalphController._apply_user_runnability_gate(...) -> VerifyResult`.
- Persists a compact `user_runnability` summary in strategy state and the full immutable report under the build evidence directory.

- [ ] **Step 1: Write failing outer-loop gate tests**

Add tests at the observable convergence boundary:

```python
def test_required_user_facing_stack_cannot_converge_without_candidate_contract(harness):
    harness.config.resolved_runnability = REQUIRED_BROWSER_RUNNABILITY
    harness.verify_result = VerifyResult(passed=True)

    result = harness.run()

    assert result.status != "verified"
    assert result.final_verify.failures[0].id == "user-runnability-contract-missing"
    assert result.final_verify.failures[0].details["contract"] == ".echelon/runnability.yml"


def test_runnability_failure_enters_existing_fix_loop_with_report_context(harness):
    harness.runnability_result = _failed_runnability("primary_journey_failed")

    harness.run()

    assert "primary_journey_failed" in harness.fix_prompts[-1]
    assert "report.md" in harness.fix_prompts[-1]


def test_non_runnable_stack_without_contract_preserves_existing_convergence(harness):
    harness.config.resolved_runnability = NOT_APPLICABLE_RUNNABILITY

    assert harness.run().status == "verified"


def test_candidate_disabled_contract_cannot_downgrade_required_stack(harness):
    harness.config.resolved_runnability = REQUIRED_BROWSER_RUNNABILITY
    harness.write_candidate_contract(enabled=False)

    result = harness.run()

    assert result.status != "verified"
    assert result.final_verify.failures[0].id == "user-runnability-contract-disabled"
```

- [ ] **Step 2: Run outer-loop tests and verify RED**

```bash
pytest -q tests/unit/test_ralph_outer.py -k user_runnability
```

Expected: FAIL because Ralph has no runnability gate.

- [ ] **Step 3: Resolve stack runtime data once without changing config ownership**

Extend `_resolve_delivery_verification_services()` to attach `resolved.services` and `resolved.runnability` as runtime-only fields on `HarnessConfig`. Do not load candidate `.echelon/config.yml`. Candidate contracts are loaded later from each build worktree.

- [ ] **Step 4: Insert the gate in both outer and inner verification paths**

Use this exact ordering in both locations: `_exec_verify`, incomplete-task progress gate,
fulfillment refresh, fulfillment gate, user-runnability gate, documentation gate, and
finally the completion-required task-progress gate. Preserve the current argument sets
at each call site and pass the current candidate worktree, commit, and evidence directory
only to `_apply_user_runnability_gate`.

Load `.echelon/runnability.yml` from the current candidate worktree inside every gate
invocation, never from an earlier config snapshot. The gate no-ops only when the resolved
policy is not required and no explicit enabled contract exists. A missing, disabled, or
invalid required contract becomes a product-repair failure. Sandbox/provider unavailability
becomes `user-runnability-sandbox-prerequisite` and blocks without repeatedly dispatching
the product agent.

- [ ] **Step 5: Persist state and provider context**

Store only:

```python
state["user_runnability"] = {
    "status": result.status,
    "failed_stage": result.failed_stage,
    "failure_class": result.failure_class,
    "summary": result.summary,
    "report": str(result.report_path),
    "candidate_fingerprint": result.candidate_fingerprint,
    "contract_hash": result.contract_hash,
    "stack_hash": result.stack_hash,
    "user_commands": result.user_commands,
}
```

Put the redacted report path, failed stage, evidence summary, and required repair into `FailureEntry.details` so `_build_slice_last_verify_failures()` and the fix prompt expose actionable context. Do not embed raw command logs in state.

- [ ] **Step 6: Add inner-loop and infrastructure classification tests**

Prove a repaired contract is reloaded in the same delivery run, a passing rerun converges, an unchanged product+contract failure triggers existing no-progress protection, and a sandbox prerequisite blocks immediately.

- [ ] **Step 7: Run and commit Task 6**

```bash
pytest -q tests/unit/test_ralph_outer.py tests/unit/test_ralph_inner.py tests/unit/test_config.py tests/unit/test_cli_harness_run.py
git add src/echelon/cli.py src/harness/config.py src/harness/ralph.py src/harness/coordinator.py tests/unit/test_ralph_outer.py tests/unit/test_ralph_inner.py tests/unit/test_config.py
git commit -m "feat: gate delivery convergence on user runnability"
```

Expected: PASS.

### Task 7: Documentation, Status, And Landing Enforcement

**Files:**
- Modify: `src/harness/docs_verifier.py`
- Modify: `src/harness/documentation_gate.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/harness/land.py`
- Modify: `tests/unit/test_documentation_gate.py`
- Modify: `tests/unit/test_cli_delivery_status.py`
- Modify: `tests/unit/test_land.py`

**Interfaces:**
- Documentation consumes the current passing runnability report and verifies exact first-run commands.
- Delivery status renders both failure repair context and passing local-run commands.
- Landing validates the current report against target product/contract/stack hashes before mutation.

- [ ] **Step 1: Write failing documentation evidence tests**

```python
@pytest.mark.unit
def test_docs_gate_rejects_readme_that_omits_observed_start_command(tmp_path: Path) -> None:
    report = _passing_report(tmp_path, user_commands={"start": ["pnpm start:local"]})
    _write_readme(tmp_path, "pnpm dev:web\n")

    result = verify_docs(tmp_path, _spec_dir(tmp_path), runnability_report=report)

    assert result.verdict == "FAIL"
    assert "pnpm start:local" in result.findings[0].required_repair


@pytest.mark.unit
def test_docs_gate_accepts_exact_observed_first_run(tmp_path: Path) -> None:
    report = _passing_report(tmp_path, user_commands=COMPLETE_USER_COMMANDS)
    _write_complete_readme(tmp_path, COMPLETE_USER_COMMANDS)

    assert verify_docs(tmp_path, _spec_dir(tmp_path), runnability_report=report).verdict == "PASS"
```

- [ ] **Step 2: Run docs tests and verify RED**

```bash
pytest -q tests/unit/test_documentation_gate.py -k runnability
```

Expected: FAIL because documentation verification does not consume runnability evidence.

- [ ] **Step 3: Implement deterministic README-to-evidence checks**

Require the README to contain normalized prerequisites and install, provision, bootstrap, start, open, and stop commands from the report. Add `runnability_evidence_sha256` and `runnability_commands_current` to docs report frontmatter. A provisional report lacking current evidence cannot pass final convergence.

- [ ] **Step 4: Write failing status tests**

```python
def test_delivery_status_shows_failed_runnability_action(tmp_path: Path, capsys) -> None:
    _write_state(tmp_path, user_runnability={
        "status": "not_runnable",
        "failed_stage": "primary_journey",
        "failure_class": "missing_local_auth_bootstrap",
        "report": "/runs/report.md",
    })

    _cmd_delivery_status([], project_root=tmp_path)

    output = capsys.readouterr().out
    assert "user runnable" in output
    assert "missing_local_auth_bootstrap" in output
    assert "/runs/report.md" in output


def test_delivery_status_shows_passing_local_run_commands(tmp_path: Path, capsys) -> None:
    _write_state(tmp_path, user_runnability=_passing_status(COMPLETE_USER_COMMANDS))

    _cmd_delivery_status([], project_root=tmp_path)

    assert "pnpm start:local" in capsys.readouterr().out
```

- [ ] **Step 5: Implement status summary and JSON output**

Add a normalized `user_runnability` object to `_delivery_status_summary()` and render fields before `next`. Keep the report path and commands untruncated; keep diagnostic summary bounded. JSON output must expose the same object.

- [ ] **Step 6: Write failing landing provenance tests**

```python
def test_land_blocks_missing_required_runnability_evidence(tmp_path: Path) -> None:
    project, spec = _ready_required_browser_project(tmp_path)

    assert land(spec.name, project, FakeGitOps(project)) is False


def test_land_accepts_merge_only_commit_when_three_hashes_match(tmp_path: Path) -> None:
    project, spec, ref = _ready_project_with_passing_runnability(tmp_path)
    _create_merge_only_commit(project)

    validation = _runnability_warning(spec.name, project, harness_root=project / "runs")

    assert validation is None


def test_land_blocks_changed_candidate_contract(tmp_path: Path) -> None:
    project, spec, ref = _ready_project_with_passing_runnability(tmp_path)
    _change_contract(project)

    assert "stale" in _runnability_warning(spec.name, project, harness_root=project / "runs")
```

- [ ] **Step 7: Implement landing check before any merge/push mutation**

Resolve the current build's recorded report from state, recompute product/contract/stack hashes for the selected target/ref, and call `validate_runnability_report()`. Required missing/failed/stale evidence blocks. An active owner disposition permits landing with a visible deferred summary and proposal path; `--allow-fulfillment-gaps` does not override runnability.

- [ ] **Step 8: Run and commit Task 7**

```bash
pytest -q tests/unit/test_documentation_gate.py tests/unit/test_cli_delivery_status.py tests/unit/test_land.py
git add src/harness/docs_verifier.py src/harness/documentation_gate.py src/echelon/cli.py src/harness/land.py tests/unit/test_documentation_gate.py tests/unit/test_cli_delivery_status.py tests/unit/test_land.py
git commit -m "feat: report and enforce runnable deliveries"
```

Expected: PASS.

### Task 8: Bundle Contracts, Agent Guidance, And Browser Stack Rollout

**Files:**
- Modify: `runtime/stacks/browser-3d-game/stack.yml`
- Modify: `runtime/stacks/browser-wasm-game/stack.yml`
- Modify: `runtime/stacks/ios-ar-game/stack.yml`
- Modify: `runtime/stacks/game-persistence-postgres/stack.yml`
- Modify: `runtime/stacks/browser-3d-game/context.md`
- Modify: `runtime/stacks/browser-wasm-game/context.md`
- Modify: `runtime/stacks/ios-ar-game/context.md`
- Modify: `runtime/stacks/game-persistence-postgres/context.md`
- Modify: `runtime/config-template.yml`
- Modify: `runtime/workflow/phases/build-8-finalize.md`
- Modify: `runtime/workflow/phases/build-8-documentation.md`
- Modify: `runtime/workflow/phases/build-8-verify-docs.md`
- Modify: `prosaic/subagents/echelon.tech-writer.md`
- Modify: `prosaic/subagents/echelon.docs-verifier.md`
- Modify: `tests/unit/test_stacks_integration.py`
- Modify: `tests/unit/test_stack_context_prompt.py`
- Modify: `tests/unit/test_tech_writer_contract.py`
- Modify: `tests/kernel/test_prompt_references.py`

**Interfaces:**
- Browser stacks require the Linux-container gate and browser DOM observation.
- Postgres persistence contributes the direct pre/post-restart database observation and declared `DATABASE_URL` environment.
- iOS records its future runner without enabling enforcement.
- Build/documentation agents receive the exact contract/report paths and cannot claim runnability themselves.

- [ ] **Step 1: Write failing bundled-stack integration tests**

```python
def test_browser_3d_with_persistence_requires_browser_and_postgres_observations() -> None:
    resolved = _resolve_bundled("browser-3d-game", "game-persistence-postgres")

    assert resolved.runnability.policy == "required"
    assert resolved.runnability.runner == "linux_container"
    assert resolved.runnability.required_observations == (
        "browser_dom", "postgres_query"
    )
    assert "DATABASE_URL" in resolved.services[0].environment_names


def test_ios_records_future_macos_runner_without_required_policy() -> None:
    resolved = _resolve_bundled("ios-ar-game")

    assert resolved.runnability.runner == "macos_simulator"
    assert resolved.runnability.policy == "advisory"
```

- [ ] **Step 2: Run tests and verify RED**

```bash
pytest -q tests/unit/test_stacks_integration.py -k runnability
```

Expected: FAIL because bundled stacks have no runnability sections.

- [ ] **Step 3: Upgrade bundled stack YAML to schema 1.2**

Set:

```yaml
# browser stacks
runnability:
  classification: user_facing
  policy: required
  runner: linux_container
  capabilities: [install, provision, start, readiness, primary_journey, stop]
  required_observations: [browser_dom]
```

Add `postgres_query` to the persistence capability. Set iOS to `policy: advisory`, `runner: macos_simulator`, and document that absence of the runner cannot be represented as a pass.

- [ ] **Step 4: Update neutral agent/workflow guidance**

TECH WRITER must document the exact commands from current runnability evidence. DOCS VERIFIER must cite the evidence digest. ENGINEERING MANAGER must not finalize when a required report is missing, failed, stale, or provisional. Preserve the dispatcher/protocol split and ALWAYS/NEVER pairs required by `AGENTS.md`.

- [ ] **Step 5: Update template and user guidance**

Document `.echelon/runnability.yml`, supported journey/observation kinds, stack-required behavior, owner deferral commands, evidence location, and successful `delivery status` run commands in `runtime/config-template.yml` comments and the relevant stack contexts. Do not add candidate commands to `.echelon/config.yml`.

- [ ] **Step 6: Run workflow/bundle regressions and commit**

```bash
pytest -q tests/unit/test_stacks_integration.py tests/unit/test_stack_context_prompt.py tests/unit/test_tech_writer_contract.py tests/kernel/test_prompt_references.py
bash scripts/bash/dry-run.sh
git add runtime/stacks runtime/config-template.yml runtime/workflow/phases/build-8-finalize.md runtime/workflow/phases/build-8-documentation.md runtime/workflow/phases/build-8-verify-docs.md prosaic/subagents/echelon.tech-writer.md prosaic/subagents/echelon.docs-verifier.md tests/unit/test_stacks_integration.py tests/unit/test_stack_context_prompt.py tests/unit/test_tech_writer_contract.py tests/kernel/test_prompt_references.py
git commit -m "feat: require runnable browser stack deliveries"
```

Expected: PASS.

### Task 9: Full Regression, Installation, And Browser-Game Acceptance

**Files:**
- Create through the demo delivery repair loop: `/Users/michalbachorik/work/browser-3d-game-stack-smoke/sources/browser-3d-game/.echelon/runnability.yml`
- Expected demo repair surface: `/Users/michalbachorik/work/browser-3d-game-stack-smoke/sources/browser-3d-game/package.json`
- Expected demo repair surface: `/Users/michalbachorik/work/browser-3d-game-stack-smoke/sources/browser-3d-game/apps/api/src/server.ts`
- Expected demo repair surface: `/Users/michalbachorik/work/browser-3d-game-stack-smoke/sources/browser-3d-game/apps/api/src/config.ts`
- Expected demo repair surface: `/Users/michalbachorik/work/browser-3d-game-stack-smoke/sources/browser-3d-game/apps/web/vite.config.ts`
- Expected demo repair surface: `/Users/michalbachorik/work/browser-3d-game-stack-smoke/sources/browser-3d-game/apps/web/src/main.tsx`
- Expected demo repair surface: `/Users/michalbachorik/work/browser-3d-game-stack-smoke/sources/browser-3d-game/README.md`
- Expected demo repair surface: `/Users/michalbachorik/work/browser-3d-game-stack-smoke/sources/browser-3d-game/.env.example`
- Verify only: Echelon repository and demo run state

**Interfaces:**
- Proves the gate detects the current demo's missing composition rather than accepting its existing mocked Playwright suite.
- Proves the repair loop can create a real local path and converge without host-installed project dependencies.

- [ ] **Step 1: Run the focused Echelon regression suite**

```bash
pytest -q \
  tests/unit/test_stacks_schema.py \
  tests/unit/test_stacks_resolver.py \
  tests/unit/test_stacks_integration.py \
  tests/unit/test_runnability_contract.py \
  tests/unit/test_runnability_evidence.py \
  tests/unit/test_runnability_runner.py \
  tests/unit/test_runnability_disposition.py \
  tests/unit/test_ralph_outer.py \
  tests/unit/test_ralph_inner.py \
  tests/unit/test_documentation_gate.py \
  tests/unit/test_cli_delivery_status.py \
  tests/unit/test_land.py
```

Expected: PASS.

- [ ] **Step 2: Run the full non-external regression suite**

```bash
pytest -q
bash scripts/bash/dry-run.sh
```

Expected: PASS, except any already documented unrelated baseline failure must be reproduced on the pre-feature commit before it may be classified as unrelated.

- [ ] **Step 3: Install the edited Echelon runtime**

```bash
bash scripts/install.sh
echelon --version
```

Expected: installation succeeds and reports the repository version.

- [ ] **Step 4: Refresh the demo workspace runtime**

```bash
cd /Users/michalbachorik/work/browser-3d-game-stack-smoke
echelon workspace migrate-to-prosaic
```

Expected: deployed `.echelon/prosaic` and `.echelon/runtime` match the installed Echelon bundle.

- [ ] **Step 5: Prove the old demo state fails for the correct reason**

Run a fresh required-gate delivery attempt against the current browser-game candidate before adding its contract:

```bash
echelon delivery run 003-create-browser-first-3d
```

Expected: the existing unit/integration/Playwright verifier may pass, but delivery does not converge; status reports `user-runnability-contract-missing` and points to `.echelon/runnability.yml`.

- [ ] **Step 6: Add the demo's real local run contract and product support through the repair loop**

Continue delivery so the provider implements, in the target worktree:

- a documented local-development identity command disabled by production default;
- one start command that brings up API and web processes with same-origin API routing;
- correct `DATABASE_URL`, session issuer/audience/public-key configuration;
- a harness-controlled browser journey that collects a real checkpoint;
- direct Postgres observation of the generated player marker before and after application restart;
- README install/provision/start/open/stop instructions matching evidence exactly.

Use:

```bash
echelon delivery continue 003-create-browser-first-3d
```

Expected: the failure report is present in the provider repair context and no host `pnpm install` is required.

- [ ] **Step 7: Verify convergence, status handoff, and landing gate**

```bash
echelon delivery status 003-create-browser-first-3d
echelon delivery land 003-create-browser-first-3d
```

Expected before landing: status reports `user runnable  passed`, the exact local provision/start/open/stop commands, and an evidence path. Landing accepts the passing report, including after a merge-only candidate commit, and refuses if the contract or product content is then changed.

- [ ] **Step 8: Run the documented game locally as the final human-path smoke**

Execute the exact commands printed by `echelon delivery status`; do not substitute internal harness commands. Open the printed URL, establish the documented local player identity, collect a checkpoint, restart the application boundary, and confirm the checkpoint remains. Then execute the printed stop commands.

Expected: a first-time local user can complete the same outcome proved in the sandbox.

- [ ] **Step 9: Record clean acceptance boundaries**

Run `git status --short` in both repositories. Task 9 is acceptance-only for Echelon, so
the Echelon worktree must contain no new uncommitted files from the smoke run. Demo target
changes remain in the demo repository and are not committed unless explicitly requested
during execution. If acceptance exposes an Echelon defect, return to the relevant earlier
task, add a failing regression test there, implement the fix, rerun that task's verification,
and commit those exact task files before repeating Task 9.
