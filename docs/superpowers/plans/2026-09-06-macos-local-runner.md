# macOS Local Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add an explicit delivery verify-local command that verifies a sandbox-approved browser delivery on macOS with Docker Desktop or Podman, without modifying the user's checkout or weakening sandbox delivery authority.

**Architecture:** The existing candidate-owned runnability contract gains a strict version-2 executable extension, while resolved stacks own the local-runner profile, topology, and environment bindings. A host-local runner materializes an effective candidate in a managed worktree, validates an engine-neutral Compose plan through a Docker Desktop or Podman adapter, executes lifecycle stages in a scrubbed per-run environment, and writes a separate immutable local attestation. The CLI exposes verification, status, and journal-bound cleanup without affecting delivery landing state.

**Tech Stack:** Python 3.11 standard library, existing PyYAML, Typer/Rich CLI, Git worktrees, macOS, Docker Desktop or Podman, Compose, existing Playwright browser helper, pytest.

**Spec:** docs/superpowers/specs/2026-09-06-macos-local-runner-design.md

## Global Constraints

- Support only macOS, docker-desktop-macos-v1, and podman-macos-v1 in this release.
- The command is explicit and opt-in: no delivery, landing, repair loop, or LLM may invoke it.
- The Linux sandbox remains the landing authority; a local result never mutates fulfillment or spec status.
- Use only Python standard-library modules and existing project dependencies.
- Preserve schema-version-1 contracts as declared-unverified. Require schema version 2 for executable local journeys.
- Product fingerprint, contract hash, resolved stack hash, and observer-plan hash are authoritative. Commit SHA is informational; merge-only commits are valid when those hashes match.
- Never execute candidate code in the user's target checkout. Preserve target and workspace Git porcelain baselines byte-for-byte.
- Bind every created network, container, and volume to a generated local-run ID; cleanup may use only journaled IDs after label validation.
- Use loopback-only dynamic ports. Reject candidate-authored host port mappings, remote engine contexts, private registry credentials, and non-public images.
- Candidate lifecycle code is trusted code only because the user explicitly invokes it. Do not represent the runner as a security sandbox.
- Redact before truncating logs. Never persist tokens, URL userinfo, identity material, or environment-file content.
- A profile is not supported for release until the real macOS acceptance suite passes separately for Docker Desktop and Podman.

---

## File Structure

| File | Responsibility |
|---|---|
| src/harness/runnability_contract.py | Strict version-1/version-2 parsing and exact executable/manual-command validation. |
| src/harness/stacks/schema.py | Stack-owned local-runner profile, services, and environment-binding schema. |
| src/harness/stacks/resolver.py | Conflict-safe local-runner resolution and hashing. |
| runtime/stacks/browser-3d-game/stack.yml | Browser-3D local-runner profile declaration. |
| runtime/stacks/browser-wasm-game/stack.yml | Browser-WASM local-runner profile declaration. |
| runtime/stacks/game-persistence-postgres/stack.yml | PostgreSQL topology and generated database binding declaration. |
| src/harness/local_runner_candidate.py | Effective build/landed revision resolution and detached worktree materialization. |
| src/harness/local_runner_journal.py | OS-held lock, atomic journal, controlled environment, and recovery metadata. |
| src/harness/local_runner_compose.py | Engine-neutral, fail-closed Compose resource plan. |
| src/harness/local_runner_engine.py | Engine protocol plus Docker Desktop and Podman adapters. |
| src/harness/local_runner_evidence.py | Immutable local attestations and latest-valid-pass selection. |
| src/harness/local_runner.py | Lifecycle orchestration, independent observations, and terminal dispositions. |
| src/echelon/cli.py | verify-local, cleanup-local, and local verification status output. |
| tests/unit/test_local_runner_*.py | Isolated contract, provenance, journal, Compose, engine, evidence, and lifecycle coverage. |
| tests/integration/test_local_runner_macos.py | Explicit real-engine macOS acceptance. |
| tests/fixtures/local-runner-browser-postgres/ | Minimal schema-v2 browser/PostgreSQL candidate fixture. |
| .github/workflows/local-runner-macos.yml | Separate self-hosted macOS Docker Desktop/Podman workflow. |
| .github/workflows/release.yml | Requires both exact-commit macOS local-runner checks before a release can advertise the profile. |
| README.md | User operation, trust boundary, supported profile, and recovery documentation. |

### Task 1: Add strict version-2 executable local-journey contracts

**Files:**
- Modify: src/harness/runnability_contract.py
- Modify: tests/unit/test_runnability_contract.py

**Interfaces:**
- Produces LocalExecutionCommand(argv: tuple[str, ...]), ManualEquivalent(field: str, index: int, transform: str), and LocalExecution(profile: str, compose_file: str, compose_services: tuple[str, ...], lifecycle: tuple[tuple[str, tuple[LocalExecutionCommand, ...]], ...], manual_equivalents: tuple[tuple[str, tuple[ManualEquivalent, ...]], ...]).
- Extends LocalUserJourney with execution: LocalExecution | None. The existing root install_commands and bootstrap_commands, plus local_journey command fields, remain the human-readable command source of truth.
- load_runnability_contract(worktree: Path) accepts exactly schema versions 1 and 2.

- [ ] **Step 1: Write failing version-2 and version-1 tests**

    def test_v2_local_execution_requires_exact_manual_equivalent(tmp_path: Path) -> None:
        _write_contract(
            tmp_path,
            schema_version=2,
            root_overrides={
                "install_commands": ["pnpm install --frozen-lockfile"],
                "bootstrap_commands": ["pnpm migrate"],
            },
            local_overrides={
                "execution": {
                    "profile": "macos-compose-v1",
                    "compose": {"file": "docker-compose.yml", "services": ["postgres"]},
                    "lifecycle": {
                        "install": [["pnpm", "install", "--frozen-lockfile"]],
                        "bootstrap": [["pnpm", "migrate"]],
                    },
                    "manual_equivalents": {
                        "install": [{"field": "install_commands", "index": 0, "transform": "same_argv"}],
                        "bootstrap": [{"field": "bootstrap_commands", "index": 0, "transform": "same_argv"}],
                    },
                },
            },
        )

        contract = load_runnability_contract(tmp_path)

        assert contract is not None
        assert contract.local_journey is not None
        assert contract.local_journey.execution is not None
        assert contract.local_journey.execution.profile == "macos-compose-v1"


    def test_v1_contract_rejects_execution_field(tmp_path: Path) -> None:
        _write_contract(tmp_path, schema_version=1, local_overrides={"execution": {}})

        with pytest.raises(RunnabilityContractError, match="execution requires schema_version 2"):
            load_runnability_contract(tmp_path)

- [ ] **Step 2: Run the parser tests to verify RED**

Run: uv run --extra dev pytest tests/unit/test_runnability_contract.py::test_v2_local_execution_requires_exact_manual_equivalent tests/unit/test_runnability_contract.py::test_v1_contract_rejects_execution_field -q

Expected: FAIL because schema version 2 and execution are unsupported.

- [ ] **Step 3: Implement typed schema-version-2 parsing**

    @dataclass(frozen=True)
    class LocalExecutionCommand:
        argv: tuple[str, ...]


    @dataclass(frozen=True)
    class ManualEquivalent:
        field: str
        index: int
        transform: str


    @dataclass(frozen=True)
    class LocalExecution:
        profile: str
        compose_file: str
        compose_services: tuple[str, ...]
        lifecycle: tuple[tuple[str, tuple[LocalExecutionCommand, ...]], ...]
        manual_equivalents: tuple[tuple[str, tuple[ManualEquivalent, ...]], ...]

Add _parse_local_execution inside _parse_local_journey. It accepts only profile, compose, lifecycle, and manual_equivalents. Permit lifecycle stages install, bootstrap, start, and stop only. Require one manual-equivalent entry per executable command, with the same stage and order. Permit references only to root install_commands, root bootstrap_commands, root start_commands, root stop_commands, and the existing local_journey provision_commands, readiness_commands, prepare_commands, verify_commands, start_commands, session_commands, stop_commands, and cleanup_commands. Validate argv without a shell; allow only same_argv and inject_stack_environment; use shlex.split plus the selected fixed transform to compare every referenced manual command exactly. Keep version-1 defaults execution=None.

- [ ] **Step 4: Add unsafe-shape tests and verify GREEN**

    @pytest.mark.parametrize(
        ("execution", "message"),
        [
            ({"profile": "macos-compose-v1", "compose": {}, "lifecycle": {}, "manual_equivalents": {}}, "compose.file"),
            ({"profile": "macos-compose-v1", "compose": {"file": "/tmp/x", "services": ["postgres"]}, "lifecycle": {}, "manual_equivalents": {}}, "must be candidate-relative"),
            ({"profile": "macos-compose-v1", "compose": {"file": "docker-compose.yml", "services": ["postgres"]}, "lifecycle": {"start": [["sh", "-c", "echo unsafe"]]}, "manual_equivalents": {}}, "shell executable is not allowed"),
        ],
    )
    def test_v2_execution_rejects_unsafe_shapes(tmp_path: Path, execution: dict[str, object], message: str) -> None:
        _write_contract(tmp_path, schema_version=2, local_overrides={"execution": execution})
        with pytest.raises(RunnabilityContractError, match=message):
            load_runnability_contract(tmp_path)

Run: uv run --extra dev pytest tests/unit/test_runnability_contract.py -q

Expected: PASS.

- [ ] **Step 5: Commit the contract slice**

    git add src/harness/runnability_contract.py tests/unit/test_runnability_contract.py
    git commit -m "feat: add executable local journey contract"

### Task 2: Resolve stack-owned local-runner profiles and bindings

**Files:**
- Modify: src/harness/stacks/schema.py
- Modify: src/harness/stacks/resolver.py
- Modify: runtime/stacks/browser-3d-game/stack.yml
- Modify: runtime/stacks/browser-wasm-game/stack.yml
- Modify: runtime/stacks/game-persistence-postgres/stack.yml
- Modify: tests/unit/test_stacks_schema.py
- Modify: tests/unit/test_stacks_resolver.py

**Interfaces:**
- Produces StackLocalRunner(profiles: tuple[str, ...], allowed_services: tuple[str, ...], environment_bindings: tuple[tuple[str, str], ...]).
- Produces ResolvedLocalRunner(profiles: tuple[str, ...], allowed_services: tuple[str, ...], environment_bindings: tuple[tuple[str, str], ...], sources: tuple[str, ...]) as ResolvedRunnability.local_runner.
- resolved_stack_contract_sha256 includes the resolved local-runner object.

- [ ] **Step 1: Write failing schema and resolver tests**

    def test_stack_schema_parses_local_runner_profile_and_bindings() -> None:
        parsed = parse_stack_definition(
            _stack_raw(
                runnability={
                    "classification": "user_facing",
                    "policy": "required",
                    "runner": "linux_container",
                    "local_runner": {
                        "profiles": ["macos-compose-v1"],
                        "allowed_services": ["postgres"],
                        "environment_bindings": {"DATABASE_URL": "postgres_url"},
                    },
                }
            ),
            Path("stack.yml"),
        )

        assert parsed.runnability.local_runner.environment_bindings == (("DATABASE_URL", "postgres_url"),)


    def test_resolve_rejects_conflicting_local_runner_environment_binding() -> None:
        with pytest.raises(StackConflictError, match="local runner environment binding conflict"):
            resolve_stacks(["web", "persistence"], _definitions_with_conflicting_local_binding())

- [ ] **Step 2: Run the focused tests to verify RED**

Run: uv run --extra dev pytest tests/unit/test_stacks_schema.py::test_stack_schema_parses_local_runner_profile_and_bindings tests/unit/test_stacks_resolver.py::test_resolve_rejects_conflicting_local_runner_environment_binding -q

Expected: FAIL because local_runner is currently unknown.

- [ ] **Step 3: Implement schema 1.4 local-runner resolution**

    @dataclass(frozen=True)
    class StackLocalRunner:
        profiles: tuple[str, ...] = ()
        allowed_services: tuple[str, ...] = ()
        environment_bindings: tuple[tuple[str, str], ...] = ()


    @dataclass(frozen=True)
    class ResolvedLocalRunner:
        profiles: tuple[str, ...] = ()
        allowed_services: tuple[str, ...] = ()
        environment_bindings: tuple[tuple[str, str], ...] = ()
        sources: tuple[str, ...] = ()

Permit runnability.local_runner only in stack schema 1.4. Validate profile macos-compose-v1, existing service names, and binding values postgres_url, browser_port, browser_base_url, marker, or session_token. Merge profiles/services by ordered union; reject one variable mapped to two different sources; include the result in the resolved stack hash.

- [ ] **Step 4: Upgrade built-in stack manifests and verify GREEN**

Bump both browser archetype manifests from schema version 1.3 to 1.4, then add this to each runnability block:

    local_runner:
      profiles: [macos-compose-v1]

Upgrade the PostgreSQL stack to schema 1.4 and add:

    local_runner:
      allowed_services: [postgres]
      environment_bindings:
        DATABASE_URL: postgres_url
        TEST_DATABASE_URL: postgres_url

Run: uv run --extra dev pytest tests/unit/test_stacks_schema.py tests/unit/test_stacks_resolver.py -q

Expected: PASS.

- [ ] **Step 5: Commit the stack-resolution slice**

    git add src/harness/stacks/schema.py src/harness/stacks/resolver.py runtime/stacks/browser-3d-game/stack.yml runtime/stacks/browser-wasm-game/stack.yml runtime/stacks/game-persistence-postgres/stack.yml tests/unit/test_stacks_schema.py tests/unit/test_stacks_resolver.py
    git commit -m "feat: resolve local runner stack profiles"

### Task 3: Add content-authoritative candidate resolution

**Files:**
- Create: src/harness/local_runner_candidate.py
- Create: tests/unit/test_local_runner_candidate.py
- Modify: src/harness/land.py

**Interfaces:**
- Produces LocalCandidateRequest(workspace_root: Path, target_root: Path, spec_id: str, target_id: str, build_id: str | None).
- Produces EffectiveLocalCandidate(build_id: str, sandbox_candidate_commit: str, effective_candidate_commit: str, product_fingerprint: str, contract_hash: str, stack_hash: str, observer_plan_hash: str, mirror_path: Path).
- Produces resolve_effective_local_candidate(request: LocalCandidateRequest) -> EffectiveLocalCandidate.
- Produces materialize_local_candidate(candidate: EffectiveLocalCandidate, destination: Path) -> Path.
- Adds read_landed_candidate_commit(workspace_root: Path, spec_id: str, target_id: str) -> str | None to src/harness/land.py; it reads the canonical landing record without changing landing state.

- [ ] **Step 1: Write failing merge-only and stale-candidate tests**

    def test_resolve_effective_candidate_uses_landed_merge_commit_when_content_matches(tmp_path: Path) -> None:
        fixture = _write_delivery_fixture(tmp_path, landed_commit="merge-commit", verified_commit="build-commit")
        _set_product_fingerprint(fixture.mirror, "build-commit", "same-content")
        _set_product_fingerprint(fixture.mirror, "merge-commit", "same-content")

        candidate = resolve_effective_local_candidate(fixture.request())

        assert candidate.sandbox_candidate_commit == "build-commit"
        assert candidate.effective_candidate_commit == "merge-commit"


    def test_resolve_effective_candidate_rejects_changed_landed_product(tmp_path: Path) -> None:
        fixture = _write_delivery_fixture(tmp_path, landed_commit="merge-commit", verified_commit="build-commit")
        _set_product_fingerprint(fixture.mirror, "build-commit", "original")
        _set_product_fingerprint(fixture.mirror, "merge-commit", "changed")

        with pytest.raises(LocalCandidateError, match="product fingerprint is stale"):
            resolve_effective_local_candidate(fixture.request())


    def test_resolve_effective_candidate_rejects_changed_landed_observer_plan(tmp_path: Path) -> None:
        fixture = _write_delivery_fixture(tmp_path, landed_commit="merge-commit", verified_commit="build-commit")
        _set_product_fingerprint(fixture.mirror, "build-commit", "same-content")
        _set_product_fingerprint(fixture.mirror, "merge-commit", "same-content")
        _set_observer_plan_hash(fixture.mirror, "build-commit", "original-observer-plan")
        _set_observer_plan_hash(fixture.mirror, "merge-commit", "changed-observer-plan")

        with pytest.raises(LocalCandidateError, match="observer plan hash is stale"):
            resolve_effective_local_candidate(fixture.request())

- [ ] **Step 2: Run candidate tests to verify RED**

Run: uv run --extra dev pytest tests/unit/test_local_runner_candidate.py -q

Expected: FAIL because the effective-candidate module does not exist.

- [ ] **Step 3: Implement effective revision resolution and detached materialization**

    def resolve_effective_local_candidate(request: LocalCandidateRequest) -> EffectiveLocalCandidate:
        """Resolve a verified build; prefer its landed revision only if hashes match."""


    def materialize_local_candidate(candidate: EffectiveLocalCandidate, destination: Path) -> Path:
        """Create a detached worktree from candidate.mirror_path at effective commit."""

Read the sandbox receipt, stack snapshot, and landing outcome. When landed, use the landing revision only if recomputed product fingerprint, contract hash, resolved stack hash, and observer-plan hash all equal the sandbox evidence. Retain both SHAs. Use git worktree add --detach through the existing Git command boundary and reject destinations outside the build local-run root.

- [ ] **Step 4: Verify GREEN with existing landing provenance coverage**

Run: uv run --extra dev pytest tests/unit/test_local_runner_candidate.py tests/unit/test_land.py::test_land_accepts_merge_only_commit_when_three_hashes_match tests/unit/test_land.py::test_land_accepts_merge_only_commit_only_with_matching_coverage_observation -q

Expected: PASS.

- [ ] **Step 5: Commit the provenance slice**

    git add src/harness/local_runner_candidate.py tests/unit/test_local_runner_candidate.py src/harness/land.py
    git commit -m "feat: resolve effective local verification candidates"

### Task 4: Build controlled local-run state, lock, and journal recovery

**Files:**
- Create: src/harness/local_runner_journal.py
- Create: tests/unit/test_local_runner_journal.py

**Interfaces:**
- Produces LocalRunJournal, WorkspaceLocalRunLock, HostExecutionEnvironment, and ResourceJournalEntry.
- Produces acquire_workspace_local_run_lock(workspace_root: Path) -> WorkspaceLocalRunLock.
- Produces write_local_run_journal(local_run_root: Path, journal: LocalRunJournal) -> Path and load_local_run_journal(journal_path: Path, trusted_local_run_root: Path) -> LocalRunJournal.
- Produces build_host_execution_environment(run_root: Path, bindings: Mapping[str, str]) -> HostExecutionEnvironment.

- [ ] **Step 1: Write failing lock and controlled-environment tests**

    def test_lock_is_released_when_owner_process_exits(tmp_path: Path) -> None:
        owner = _spawn_lock_owner(tmp_path)
        assert _wait_for_lock(tmp_path)
        owner.kill()
        owner.wait(timeout=5)

        with acquire_workspace_local_run_lock(tmp_path):
            assert True


    def test_host_environment_redirects_all_runner_owned_state(tmp_path: Path) -> None:
        environment = build_host_execution_environment(tmp_path / "run-1", {"DATABASE_URL": "postgresql://generated"})

        assert environment.values["HOME"].startswith(str(tmp_path / "run-1"))
        assert environment.values["PLAYWRIGHT_BROWSERS_PATH"].startswith(str(tmp_path / "run-1"))
        assert environment.values["DATABASE_URL"] == "postgresql://generated"
        assert "AWS_SECRET_ACCESS_KEY" not in environment.values

- [ ] **Step 2: Run journal tests to verify RED**

Run: uv run --extra dev pytest tests/unit/test_local_runner_journal.py -q

Expected: FAIL because the journal module does not exist.

- [ ] **Step 3: Implement OS-held locking, atomic journals, baselines, and scrubbed environment**

    @dataclass(frozen=True)
    class LocalRunJournal:
        local_run_id: str
        status: str
        target_git_baseline: str
        workspace_git_baseline: str
        resources: tuple[ResourceJournalEntry, ...]
        completed_actions: tuple[str, ...]


    def git_porcelain_baseline(path: Path) -> str:
        return _run_git_status_porcelain(path)


    @dataclass(frozen=True)
    class ResourceJournalEntry:
        engine: str
        resource_kind: str
        resource_id: str
        labels: tuple[tuple[str, str], ...]

Use fcntl.flock on runs/.local-run.lock and retain its descriptor for the context lifetime. Write JSON journals through a temp file plus os.replace. Reject journal paths outside the trusted build local-run root. Build the exact HOME, XDG, tmp, pnpm, npm, Playwright, and Git environment from the design; do not inherit arbitrary parent secrets. Set HOME, XDG_CONFIG_HOME, XDG_CACHE_HOME, XDG_DATA_HOME, TMPDIR, PNPM_HOME, npm_config_cache, PLAYWRIGHT_BROWSERS_PATH, GIT_CONFIG_NOSYSTEM, and a fresh GIT_CONFIG_GLOBAL. Preserve only PATH, LANG, LC_ALL, TERM, and explicit stack bindings after filtering the parent environment.

- [ ] **Step 4: Add recovery and Git-baseline tests, then verify GREEN**

    def test_non_terminal_journal_requires_explicit_cleanup(tmp_path: Path) -> None:
        journal_path = _write_journal(tmp_path, status="running", resource_ids=("container-1",))

        with pytest.raises(LocalRunRecoveryRequired, match=journal_path.name):
            assert_no_recovery_journal(tmp_path)


    def test_baseline_check_accepts_preexisting_dirty_state_but_rejects_new_change(tmp_path: Path) -> None:
        baseline = " M existing.txt\n"
        assert_git_baseline_unchanged(tmp_path, baseline, baseline)
        with pytest.raises(LocalRunSideEffectError):
            assert_git_baseline_unchanged(tmp_path, baseline, baseline + "?? generated.txt\n")

Run: uv run --extra dev pytest tests/unit/test_local_runner_journal.py -q

Expected: PASS.

- [ ] **Step 5: Commit the local-state slice**

    git add src/harness/local_runner_journal.py tests/unit/test_local_runner_journal.py
    git commit -m "feat: isolate and journal local verification runs"

### Task 5: Validate canonical Compose plans and engine adapters

**Files:**
- Create: src/harness/local_runner_compose.py
- Create: src/harness/local_runner_engine.py
- Create: tests/unit/test_local_runner_compose.py
- Create: tests/unit/test_local_runner_engine.py

**Interfaces:**
- Produces CanonicalComposePlan, CanonicalComposeService, RenderedEnginePlan, LocalResourceSet, and EngineProfile.
- Produces parse_canonical_compose_plan(worktree: Path, compose_file: str, allowed_services: Collection[str]) -> CanonicalComposePlan.
- Produces LocalEngineAdapter protocol with probe, render_plan, up, inspect, and down methods, each with a concrete return type.
- Produces DockerDesktopMacOSAdapter and PodmanMacOSAdapter.

- [ ] **Step 1: Write failing fail-closed Compose tests**

    @pytest.mark.parametrize(
        ("compose", "message"),
        [
            ("services: {postgres: {image: postgres:17, privileged: true}}", "privileged"),
            ("services: {postgres: {image: postgres:17, ports: ['127.0.0.1:5432:5432']}}", "candidate-authored published port"),
            ("services: {postgres: {image: postgres:17, volumes: ['/tmp/host:/data']}}", "absolute bind mount"),
            ("volumes: {data: {driver_opts: {type: none}}}\nservices: {postgres: {image: postgres:17, volumes: [data:/data]}}", "driver_opts"),
        ],
    )
    def test_compose_plan_rejects_unsafe_host_topology(tmp_path: Path, compose: str, message: str) -> None:
        _write_compose(tmp_path, compose)
        with pytest.raises(LocalComposePolicyError, match=message):
            parse_canonical_compose_plan(tmp_path, "docker-compose.yml", {"postgres"})

- [ ] **Step 2: Run Compose and adapter tests to verify RED**

Run: uv run --extra dev pytest tests/unit/test_local_runner_compose.py tests/unit/test_local_runner_engine.py -q

Expected: FAIL because neither module exists.

- [ ] **Step 3: Implement canonical Compose parsing and policy**

    def parse_canonical_compose_plan(
        worktree: Path,
        compose_file: str,
        allowed_services: Collection[str],
    ) -> CanonicalComposePlan:
        """Return only attributable internal services; reject every unsupported shape."""

Use duplicate-key-safe YAML parsing. Resolve every candidate-relative file through Path.resolve(strict=True) and relative_to(worktree). Reject the full design policy: host namespaces, devices/capabilities/security options, sockets, bind/build/Dockerfile escapes, extends, include, env_file, configs, secrets, non-selected profiles, external/named networks or volumes, custom volume drivers, container names, all candidate ports, and unknown Compose keys.

- [ ] **Step 4: Implement adapters with recording-executor tests**

    class LocalEngineAdapter(Protocol):
        profile_id: str
        def probe(self) -> EngineProfile:
            raise NotImplementedError

        def render_plan(self, plan: CanonicalComposePlan, run_id: str) -> RenderedEnginePlan:
            raise NotImplementedError

        def up(self, rendered: RenderedEnginePlan) -> LocalResourceSet:
            raise NotImplementedError

        def inspect(self, resources: LocalResourceSet) -> LocalResourceSet:
            raise NotImplementedError

        def down(self, resources: LocalResourceSet) -> LocalResourceSet:
            raise NotImplementedError

Define RenderedEnginePlan(canonical_plan: CanonicalComposePlan, command_argv: tuple[str, ...], generated_override_path: Path, generated_bindings: tuple[tuple[str, str], ...]). Docker Desktop probing accepts only a local Unix-socket context. Podman probing accepts only a local macOS machine connection. Generate override input with a unique project name, Echelon labels, and dynamic loopback mappings. Re-parse the generated override and assert that its static topology reduces exactly to canonical_plan before up. Use a recording subprocess executor to assert journaled resource IDs are the only cleanup inputs.

Run: uv run --extra dev pytest tests/unit/test_local_runner_compose.py tests/unit/test_local_runner_engine.py -q

Expected: PASS.

- [ ] **Step 5: Commit the Compose and adapter slice**

    git add src/harness/local_runner_compose.py src/harness/local_runner_engine.py tests/unit/test_local_runner_compose.py tests/unit/test_local_runner_engine.py
    git commit -m "feat: add local compose engine adapters"

### Task 6: Add immutable local evidence and latest-valid-pass selection

**Files:**
- Create: src/harness/local_runner_evidence.py
- Create: tests/unit/test_local_runner_evidence.py

**Interfaces:**
- Produces LocalRunnabilityAttestationRef, LocalRunnabilityAttestation, and LocalVerificationStatus.
- Produces LocalRunnabilityAttestationInput(status: str, candidate: EffectiveLocalCandidate, sandbox_receipt_sha256: str, runner_profile_digest: str, cleanup_complete: bool, redacted_logs: str).
- Produces write_local_runnability_attestation(evidence_root: Path, input: LocalRunnabilityAttestationInput) -> LocalRunnabilityAttestationRef.
- Produces validate_local_runnability_attestation(attestation_path: Path, candidate: EffectiveLocalCandidate) -> LocalRunnabilityAttestation.
- Produces select_local_verification_status(evidence_root: Path, candidate: EffectiveLocalCandidate) -> LocalVerificationStatus.

- [ ] **Step 1: Write failing attestation-selection tests**

    def test_latest_valid_pass_survives_later_preflight_failure(tmp_path: Path) -> None:
        passed = _write_attestation(tmp_path, status="passed", candidate_fingerprint="same")
        failed = _write_attestation(tmp_path, status="host_preflight_failed", candidate_fingerprint="same")

        status = select_local_verification_status(tmp_path, candidate_fingerprint="same")

        assert status.valid_pass_path == passed
        assert status.latest_attempt_path == failed
        assert status.display_status == "passed"


    def test_changed_effective_candidate_makes_prior_attestation_stale(tmp_path: Path) -> None:
        _write_attestation(tmp_path, status="passed", candidate_fingerprint="old")

        status = select_local_verification_status(tmp_path, candidate_fingerprint="new")

        assert status.display_status == "stale"

- [ ] **Step 2: Run evidence tests to verify RED**

Run: uv run --extra dev pytest tests/unit/test_local_runner_evidence.py -q

Expected: FAIL because the local evidence module does not exist.

- [ ] **Step 3: Implement immutable redacted attestations**

    @dataclass(frozen=True)
    class LocalRunnabilityAttestation:
        status: str
        sandbox_candidate_commit: str
        effective_candidate_commit: str
        candidate_fingerprint: str
        contract_hash: str
        stack_hash: str
        observer_plan_hash: str
        sandbox_receipt_sha256: str
        runner_profile_digest: str
        cleanup_complete: bool


    @dataclass(frozen=True)
    class LocalVerificationStatus:
        valid_pass_path: Path | None
        latest_attempt_path: Path | None
        display_status: str

Write exclusive JSON attempts beneath evidence/local-runnability, then atomically update Markdown. Redact before truncation. Validate evidence digest, fingerprint tuple, contract/stack/observer hashes, and cleanup completion. Return newest valid passing attestation and newest attempt independently.

- [ ] **Step 4: Add tamper and secret-redaction tests, then verify GREEN**

    def test_attestation_redacts_url_userinfo_and_session_token(tmp_path: Path) -> None:
        path = write_local_runnability_attestation(
            tmp_path,
            _attestation_input(logs="postgres://game:secret@127.0.0.1/db token=abc"),
        )

        text = path.markdown_path.read_text(encoding="utf-8")

        assert "secret" not in text
        assert "token=abc" not in text
        assert "[REDACTED" in text

Run: uv run --extra dev pytest tests/unit/test_local_runner_evidence.py -q

Expected: PASS.

- [ ] **Step 5: Commit the evidence slice**

    git add src/harness/local_runner_evidence.py tests/unit/test_local_runner_evidence.py
    git commit -m "feat: record local runnability attestations"

### Task 7: Orchestrate isolated host lifecycle and recovery-safe cleanup

**Files:**
- Create: src/harness/local_runner.py
- Create: tests/unit/test_local_runner.py

**Interfaces:**
- Produces LocalVerificationRequest(workspace_root: Path, target_root: Path, spec_id: str, target_id: str, candidate_request: LocalCandidateRequest, local_run_root: Path).
- Produces LocalRunnerOptions(engine: str, action_confirmed: bool, keep_on_failure: bool) and LocalRunnerResult(status: str, local_run_id: str, attestation_path: Path | None, cleanup_complete: bool).
- Produces LocalRunnabilityRunner.
- LocalRunnabilityRunner.verify(request: LocalVerificationRequest, options: LocalRunnerOptions) -> LocalRunnerResult is the only method that creates host resources.
- LocalRunnabilityRunner.cleanup(local_run_id: str) -> LocalRunnerResult consumes only a validated journal.

- [ ] **Step 1: Write failing orchestration tests with fake adapter and process runner**

    def test_runner_uses_managed_worktree_and_preserves_user_checkout(tmp_path: Path) -> None:
        runner, fixture = _runner_with_fakes(tmp_path)

        result = runner.verify(
            fixture.request(),
            LocalRunnerOptions(engine="docker", action_confirmed=True, keep_on_failure=False),
        )

        assert result.status == "passed"
        assert fixture.target_git_status_calls == ["before", "after"]
        assert all(call.cwd == fixture.managed_worktree for call in fixture.candidate_command_calls)


    def test_runner_cleans_only_journalled_resources_after_journey_failure(tmp_path: Path) -> None:
        runner, fixture = _runner_with_fakes(tmp_path, browser_result="failed")

        result = runner.verify(
            fixture.request(),
            LocalRunnerOptions(engine="docker", action_confirmed=True, keep_on_failure=False),
        )

        assert result.status == "candidate_lifecycle_failed"
        assert fixture.adapter.down_resource_ids == fixture.journalled_resource_ids
        assert fixture.adapter.global_prune_called is False

- [ ] **Step 2: Run lifecycle tests to verify RED**

Run: uv run --extra dev pytest tests/unit/test_local_runner.py -q

Expected: FAIL because the host lifecycle runner does not exist.

- [ ] **Step 3: Implement one lifecycle and one cleanup path**

    class LocalRunnabilityRunner:
        def verify(self, request: LocalVerificationRequest, options: LocalRunnerOptions) -> LocalRunnerResult:
            if not options.action_confirmed:
                raise LocalActionConfirmationRequired("local verification requires explicit confirmation")
            candidate = resolve_effective_local_candidate(request.candidate_request)
            with acquire_workspace_local_run_lock(request.workspace_root):
                assert_no_recovery_journal(request.local_run_root)
                return self._verify_locked(candidate, request, options)

Inside _verify_locked, enforce macOS/engine preflight before worktree or resource creation. The CLI is the only confirmation UI: it creates an in-memory LocalActionPlan, records its accepted digest in the journal, and passes action_confirmed=True; direct library callers must supply the same completed plan or receive LocalActionConfirmationRequired. After detached materialization, load only that managed worktree's `.echelon/runnability.yml`, recompute its hash, and require it to equal the sandbox receipt. Resolve the runner profile, service list, bindings, and observer plan only from the sandbox-recorded resolved stack snapshot; never re-run candidate `.echelon/config.yml` stack selection. Create the journal before adapter.up. Run argv with subprocess.Popen(start_new_session=True, env=controlled_env, cwd=managed_worktree). A project command exiting zero is never a passing result by itself: independently wait for the browser readiness endpoint, invoke the configured browser journey using the generated identity token, require its response to contain the generated marker after application restart, and query Postgres directly through the runner-generated DATABASE_URL for that marker. Mark the attestation passed only if every selected stack observation passes. In one finally path, terminate owned process groups, call adapter cleanup only with journal entries, compare Git baselines, delete ephemeral directories, and write a terminal attestation.

- [ ] **Step 4: Add interruption, retained-diagnostics, and no-auto-repair tests**

    def test_runner_requires_cleanup_for_interrupted_journal(tmp_path: Path) -> None:
        runner, fixture = _runner_with_fakes(tmp_path, interrupt_after="up")
        runner.verify(fixture.request(), LocalRunnerOptions(engine="docker", action_confirmed=True, keep_on_failure=False))

        with pytest.raises(LocalRunRecoveryRequired):
            runner.verify(fixture.request(), LocalRunnerOptions(engine="docker", action_confirmed=True, keep_on_failure=False))

        recovered = runner.cleanup(fixture.local_run_id)
        assert recovered.status == "cleanup_complete"


    def test_candidate_lifecycle_failure_never_calls_repair_callback(tmp_path: Path) -> None:
        runner, fixture = _runner_with_fakes(tmp_path, start_result=1)
        runner.verify(fixture.request(), LocalRunnerOptions(engine="docker", action_confirmed=True, keep_on_failure=False))
        assert fixture.repair_callback_calls == []


    def test_runner_rejects_post_build_contract_change_before_creating_resources(tmp_path: Path) -> None:
        runner, fixture = _runner_with_fakes(tmp_path, candidate_contract_hash="stale")

        result = runner.verify(
            fixture.request(),
            LocalRunnerOptions(engine="docker", action_confirmed=True, keep_on_failure=False),
        )

        assert result.status == "candidate_contract_mismatch"
        assert fixture.adapter.up_calls == 0
        assert fixture.stack_resolution_source == "sandbox-receipt"

Run: uv run --extra dev pytest tests/unit/test_local_runner.py tests/unit/test_local_runner_candidate.py tests/unit/test_local_runner_journal.py tests/unit/test_local_runner_compose.py tests/unit/test_local_runner_engine.py tests/unit/test_local_runner_evidence.py -q

Expected: PASS.

- [ ] **Step 5: Commit the runner slice**

    git add src/harness/local_runner.py tests/unit/test_local_runner.py
    git commit -m "feat: run isolated local delivery verification"

### Task 8: Expose opt-in CLI and truthful delivery status

**Files:**
- Modify: src/echelon/cli.py
- Create: tests/unit/test_cli_delivery_local.py
- Modify: tests/unit/test_cli_delivery.py
- Modify: tests/unit/test_cli_delivery_status.py

**Interfaces:**
- Adds delivery verify-local <spec_id> [--target <target_id>] [--engine auto|docker|podman] [--yes] [--keep-on-failure].
- Adds delivery cleanup-local <local_run_id>.
- Extends _delivery_status_summary with local_verification and _delivery_status_fields with local verification, local runner, local evidence, and last local attempt.
- Adds LocalActionPlan(spec_id: str, target_id: str, engine: str, candidate_fingerprint: str, planned_actions: tuple[str, ...], digest: str).
- Adds _build_local_action_plan(project_dir: Path, spec_id: str, target_id: str | None, engine: str) -> LocalActionPlan and _run_local_delivery_verification(project_dir: Path, action_plan: LocalActionPlan, keep_on_failure: bool) -> LocalRunnerResult.

- [ ] **Step 1: Write failing CLI and status tests**

    def test_delivery_verify_local_requires_explicit_confirmation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("echelon.cli._run_local_delivery_verification", _record_local_runner)
        monkeypatch.setattr("builtins.input", lambda _: "no")

        with pytest.raises(SystemExit, match="1"):
            main_with_args(["delivery", "verify-local", "001-demo"])

        assert _record_local_runner.calls == []


    def test_delivery_status_keeps_matching_pass_after_later_failed_attempt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write_delivery_state_with_local_attempts(tmp_path, statuses=["passed", "host_preflight_failed"])

        _cmd_delivery_status(["001-demo"], project_dir=tmp_path)

        output = capsys.readouterr().out
        assert "local verification  passed" in output
        assert "last local attempt  host_preflight_failed" in output

- [ ] **Step 2: Run focused CLI tests to verify RED**

Run: uv run --extra dev pytest tests/unit/test_cli_delivery_local.py tests/unit/test_cli_delivery_status.py::test_delivery_status_keeps_matching_pass_after_later_failed_attempt -q

Expected: FAIL because the CLI subcommands and status fields do not exist.

- [ ] **Step 3: Implement parser, confirmation, cleanup dispatch, and status integration**

    def _cmd_delivery_verify_local(args: list[str], project_dir: Path) -> None:
        spec_id, target_id, engine, assume_yes, keep_on_failure = _parse_delivery_verify_local_args(args)
        if keep_on_failure and assume_yes:
            raise typer.BadParameter("--keep-on-failure cannot be combined with --yes")
        action_plan = _build_local_action_plan(project_dir, spec_id, target_id, engine)
        if not assume_yes:
            _confirm_local_action_plan(action_plan)
        result = _run_local_delivery_verification(
            project_dir,
            action_plan,
            keep_on_failure,
        )
        _print_local_verification_result(result)

Reject unsupported platforms/engines before worktree creation. Use existing target-resolution dispatch. cleanup-local accepts only the journal local-run ID. Help text must state host verification is opt-in, does not affect landing, executes trusted candidate code in a managed worktree, and may retain public image layers.

- [ ] **Step 4: Run CLI and delivery-status suites to verify GREEN**

Run: uv run --extra dev pytest tests/unit/test_cli_delivery_local.py tests/unit/test_cli_delivery.py tests/unit/test_cli_delivery_status.py -q

Expected: PASS.

- [ ] **Step 5: Commit the CLI slice**

    git add src/echelon/cli.py tests/unit/test_cli_delivery_local.py tests/unit/test_cli_delivery.py tests/unit/test_cli_delivery_status.py
    git commit -m "feat: expose local delivery verification"

### Task 9: Add macOS acceptance fixture, release workflow, and user documentation

**Files:**
- Create: tests/fixtures/local-runner-browser-postgres/docker-compose.yml
- Create: tests/fixtures/local-runner-browser-postgres/.echelon/runnability.yml
- Create: tests/fixtures/local-runner-browser-postgres/package.json
- Create: tests/fixtures/local-runner-browser-postgres/scripts/start.mjs
- Create: tests/integration/test_local_runner_macos.py
- Modify: tests/conftest.py
- Modify: pyproject.toml
- Create: .github/workflows/local-runner-macos.yml
- Modify: .github/workflows/release.yml
- Modify: README.md

**Interfaces:**
- The fixture exposes a browser boundary at generated ECHELON_PORT, stores a generated marker in Postgres, and supports application restart.
- The acceptance test runs only when ECHELON_RUN_LOCAL_ENGINE=1 and ECHELON_LOCAL_ENGINE is docker or podman on macOS.

- [ ] **Step 1: Write opt-in real-engine acceptance and verify its default skip**

    @pytest.mark.integration
    @pytest.mark.macos_engine
    def test_macos_local_runner_browser_postgres(tmp_path: Path) -> None:
        engine = os.environ["ECHELON_LOCAL_ENGINE"]
        result = _run_fixture_local_verification(tmp_path, engine=engine)

        assert result.status == "passed"
        assert result.cleanup_complete is True
        assert result.persistence_after_restart is True

Register macos_engine in pyproject.toml and tests/conftest.py. Skip unless sys.platform == "darwin", ECHELON_RUN_LOCAL_ENGINE == "1", and ECHELON_LOCAL_ENGINE is exactly docker or podman. The CI matrix supplies one engine per job; a manual maintainer run must do the same.

Run: uv run --extra dev pytest tests/integration/test_local_runner_macos.py -q

Expected: SKIPPED outside the explicitly enabled macOS acceptance environment.

- [ ] **Step 2: Create the minimal version-2 browser/PostgreSQL fixture**

Create `docker-compose.yml` with no `ports`, `volumes`, `networks`, `container_name`, `env_file`, or `build` keys:

    services:
      postgres:
        image: postgres:17-alpine
        environment:
          POSTGRES_USER: runner
          POSTGRES_PASSWORD: runner
          POSTGRES_DB: runner
        healthcheck:
          test: ["CMD-SHELL", "pg_isready -U runner -d runner"]
          interval: 2s
          timeout: 2s
          retries: 20

Create the fixture contract with these root commands and a complete manual local journey. It deliberately contains no credential value, because the resolved persistence stack generates the binding:

    schema_version: 2
    install_commands:
      - pnpm install --frozen-lockfile
    bootstrap_commands:
      - pnpm migrate
    start_commands:
      - pnpm start
    stop_commands:
      - pnpm stop
    local_journey:
      prerequisites: [Docker Desktop or Podman, pnpm]
      provision_commands: [docker compose up -d postgres]
      readiness_commands: [docker compose exec -T postgres pg_isready -U runner -d runner]
      prepare_commands: [pnpm migrate]
      verify_commands: [pnpm verify]
      start_commands: [pnpm start]
      session_commands: [pnpm issue-session]
      open_urls: [http://127.0.0.1:3000]
      boundary_probes:
        - id: postgres-from-app
          service: postgres
          command: pnpm db:probe
        - id: web-from-browser
          service: web
          command: curl -fsS http://127.0.0.1:3000/health/ready
      stop_commands: [pnpm stop]
      cleanup_commands: [docker compose down -v]
      execution:
        profile: macos-compose-v1
        compose:
          file: docker-compose.yml
          services: [postgres]
        lifecycle:
          install:
            - [pnpm, install, --frozen-lockfile]
          bootstrap:
            - [pnpm, migrate]
          start:
            - [pnpm, start]
        manual_equivalents:
          install:
            - field: install_commands
              index: 0
              transform: same_argv
          bootstrap:
            - field: bootstrap_commands
              index: 0
              transform: same_argv
          start:
            - field: local_journey.start_commands
              index: 0
              transform: same_argv

Also include the complete existing root runnability contract: enabled=true; loopback readiness at `http://127.0.0.1:${ECHELON_PORT}/health/ready`; an identity command that writes `ECHELON_SESSION_TOKEN`; a browser primary journey that goes to `${ECHELON_BASE_URL}` and asserts `[data-marker="${ECHELON_MARKER}"]`; and a `postgres_query` observation selecting the marker with `$1`. Its persistence probe selects both observations after restart. For a version-2 local run, the runner implements restart by terminating its owned start-command process group and re-running the validated start lifecycle; it records the root persistence restart command as documentation but never sends it through a shell. The local runner, not the candidate, owns process-group termination.

Make `scripts/start.mjs` bind only `process.env.ECHELON_PORT` on `127.0.0.1`. Its `/health/ready` response is 200 only after the Postgres connection succeeds. Its authenticated `POST /marker` handler checks the generated `ECHELON_IDENTITY_TOKEN`, inserts `ECHELON_MARKER` into a `markers` table, and its authenticated `GET /marker` handler returns that exact marker from Postgres. The browser root script reads the session token injected by the primary journey, calls `POST /marker`, and renders `data-marker` only after that request succeeds. The acceptance test must stop the Node process, start it again with the same runner-generated bindings, and require the same marker to be returned after restart. The fixture `package.json` uses pinned `pg` and `tsx` versions, exposes `migrate`, `start`, `stop`, `issue-session`, and `db:probe` scripts, and commits its lockfile. The fixture helper creates the same single-target delivery-state, sandbox receipt, stack snapshot, and candidate mirror layout used by `tests/unit/test_local_runner_candidate.py`, so this is an end-to-end runner test rather than a direct module call.

- [ ] **Step 3: Add separate self-hosted macOS workflow and exact-commit release gate**

    name: local-runner-macos
    on:
      push:
        branches: [main]
      workflow_dispatch:
      schedule:
        - cron: "17 3 * * *"
    jobs:
      acceptance:
        name: macOS local runner (${{ matrix.engine }})
        runs-on: [self-hosted, macos, echelon-local-runner]
        strategy:
          fail-fast: false
          matrix:
            engine: [docker, podman]
        concurrency:
          group: local-runner-macos-${{ github.ref }}-${{ matrix.engine }}
          cancel-in-progress: false
        steps:
          - uses: actions/checkout@v4
          - uses: astral-sh/setup-uv@v5
          - run: uv sync --extra dev
          - run: uv run --extra dev pytest tests/integration/test_local_runner_macos.py -q
            env:
              ECHELON_RUN_LOCAL_ENGINE: "1"
              ECHELON_LOCAL_ENGINE: \${{ matrix.engine }}
              ECHELON_LOCAL_RUN_ARTIFACT_ROOT: \${{ runner.temp }}/local-runner-evidence
          - if: always()
            uses: actions/upload-artifact@v4
            with:
              name: local-runner-evidence-${{ github.sha }}-${{ matrix.engine }}
              path: ${{ runner.temp }}/local-runner-evidence
              if-no-files-found: error

Make the integration fixture copy only its redacted local attestation and engine probe summary into `ECHELON_LOCAL_RUN_ARTIFACT_ROOT`; it must not copy journal files, generated environment, or raw command logs. Change `.github/workflows/release.yml` `REQUIRED_CHECKS` to include `macOS local runner (docker)` and `macOS local runner (podman)`. The existing exact-commit check-runs query then rejects a release tag if either engine check is absent or non-successful. This makes the README's “supported” claim depend on both current-commit macOS acceptance checks, not a historical or scheduled run.

- [ ] **Step 4: Document operation and recovery**

Add a README section containing:

    echelon delivery verify-local <spec_id> --engine auto
    echelon delivery cleanup-local <local_run_id>

State that verification is macOS-only, explicit, does not change landing, executes trusted candidate code in a managed worktree, uses Docker Desktop or Podman with public images, leaves pulled image layers intact, and fails safely with a journal-bound cleanup command when interrupted.

- [ ] **Step 5: Run focused and full verification**

Run: uv run --extra dev pytest tests/unit/test_runnability_contract.py tests/unit/test_stacks_schema.py tests/unit/test_stacks_resolver.py tests/unit/test_local_runner_candidate.py tests/unit/test_local_runner_journal.py tests/unit/test_local_runner_compose.py tests/unit/test_local_runner_engine.py tests/unit/test_local_runner_evidence.py tests/unit/test_local_runner.py tests/unit/test_cli_delivery_local.py tests/unit/test_cli_delivery.py tests/unit/test_cli_delivery_status.py -q

Expected: PASS.

Run: uv run --extra dev pytest -q

Expected: PASS, with macos_engine acceptance skipped unless explicitly enabled on the maintained macOS runner.

- [ ] **Step 6: Commit the acceptance and documentation slice**

    git add tests/fixtures/local-runner-browser-postgres tests/integration/test_local_runner_macos.py tests/conftest.py pyproject.toml .github/workflows/local-runner-macos.yml README.md
    git commit -m "test: add macOS local runner acceptance"

## Final Verification

- [ ] Run git diff --check and verify the source checkout is clean.
- [ ] Run uv run --extra dev pytest -q and record exact pass/skip counts.
- [ ] On the maintained macOS runner, run the Docker Desktop and Podman matrix in separate sessions with ECHELON_RUN_LOCAL_ENGINE=1.
- [ ] Confirm each acceptance attestation records a generated loopback endpoint, public image digest, matching effective-candidate fingerprint tuple, persistence after restart, and verified cleanup.
- [ ] Confirm echelon delivery status <spec_id> retains a matching local pass after a deliberately simulated later host_preflight_failed attempt.
