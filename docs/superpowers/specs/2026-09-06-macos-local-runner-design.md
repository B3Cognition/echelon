# macOS Local Runner Design

## Goal

Add an explicit, opt-in host verification command for a delivery candidate's
documented local user journey. The first supported environment is macOS with
either Docker Desktop or Podman. The command proves that Echelon can execute
the real local lifecycle without modifying the user's checkout or confusing a
host-specific result with the authoritative Linux sandbox result.

The command is:

```text
echelon delivery verify-local <spec_id> [--target <target_id>]
    [--engine auto|docker|podman] [--yes] [--keep-on-failure]
```

It is never started automatically by delivery, verification, repair, landing,
or an LLM. A local failure does not reopen a landed spec and does not trigger a
coding-agent repair turn. It is a separately recorded observation that can
inform a deliberate follow-up.

## Scope and non-goals

### First release scope

- macOS only;
- browser-3D and browser-WASM stacks, including the PostgreSQL persistence
  stack when selected;
- Docker Desktop and Podman through explicit engine adapters;
- a single local verification at a time per Echelon workspace;
- browser, HTTP, service-boundary, and PostgreSQL persistence observations;
- candidate lifecycle commands executed in an Echelon-owned detached worktree.

### Non-goals

- no automatic pre-landing host check;
- no support for iOS/Xcode/simulator, Linux, Windows, remote Docker contexts,
  Kubernetes, or arbitrary provisioners in this release;
- no claim that this is a security sandbox for untrusted application code;
- no execution in the user's source checkout;
- no broad `docker system prune`, global `compose down`, or deletion of
  unlabelled host resources;
- no mutation of sandbox runnability evidence or delivery/landing state.

The existing Linux sandbox remains the authoritative delivery gate. A passing
host check supplements that gate with an exact local-machine attestation; it
does not replace it.

## Authority and trust model

The local runner has four deliberately separate owners.

| Owner | Authority |
|---|---|
| Harness | Candidate selection, host preflight, worktree lifecycle, engine operations, ports, generated runtime identity, independent observations, cleanup, redaction, and immutable evidence. |
| Stack | Supported runner profile, allowed support-service topology, required environment names, and mandatory boundary observations. |
| Candidate project | Candidate-relative Compose input, application lifecycle argv, browser steps, and application-specific persistence query. |
| User | Explicit host-execution invocation and confirmation; optional engine choice. |

Candidate-owned fields can describe the application but cannot weaken stack
obligations, choose host paths, select fixed ports, name Compose resources, or
turn off required persistence observations.

The user must treat candidate install and lifecycle code as trusted code. A
project script can perform arbitrary host actions even when invoked through an
argv-based runner. The runner protects workspace integrity and container
resource isolation; it must not claim to provide a general host-code security
sandbox.

## Candidate selection and provenance

`verify-local` resolves an immutable delivery candidate, not the caller's
current checkout. Commit SHA is informational provenance, not the candidate
identity authority.

1. Resolve the named target and either an explicit build or the latest build
   for the spec with a passing, current sandbox runnability receipt.
2. Validate the sandbox receipt by its product fingerprint, candidate contract
   hash, resolved stack hash, and execution-observer plan hash. The validation
   deliberately permits an equivalent-product receipt whose commit differs.
3. Resolve the **effective candidate revision**: use the recorded landed
   revision when the spec is landed; otherwise use the verified build
   candidate revision. The delivery mirror must contain that revision.
4. Materialize the effective revision in a detached Echelon-owned worktree and
   recompute its product fingerprint and candidate contract hash. They must
   equal the verified sandbox values. A merge-only commit is therefore valid;
   any product or contract change is not.
5. Materialize the selected run's runtime/stack snapshot. The runner must not
   substitute newer installed stack behavior for the stack snapshot that
   passed sandbox delivery.
6. Compute the effective product fingerprint again after the host run,
   excluding runner-owned generated directories. A mismatch makes the
   attestation `stale`; it cannot be recorded as passing.

The target's normal checkout is never read as the candidate source and is
never a command working directory. Echelon records the exact pre-run Git
porcelain baselines for both the target checkout and the workspace, then
requires byte-for-byte identical post-run baselines. The command therefore
preserves an already-dirty user checkout without accepting runner-created
changes. Any difference is `runner_side_effect_detected`, even if all
application observations passed.

The final attestation records both `sandbox_candidate_commit` and
`effective_candidate_commit`, while product fingerprint, contract hash, stack
hash, and observer-plan hash remain the authorities for whether evidence is
current. This prevents a merge-only commit from recreating a provenance
failure.

## Host execution envelope

The managed worktree alone is insufficient isolation: package managers,
Playwright, Git, temporary files, and engine CLIs otherwise mutate the user's
home directories. Before any candidate command starts, the harness creates a
per-run directory and provides a minimal environment:

```text
HOME=<run>/home
XDG_CACHE_HOME=<run>/cache
XDG_CONFIG_HOME=<run>/config
XDG_DATA_HOME=<run>/data
TMPDIR=<run>/tmp
PLAYWRIGHT_BROWSERS_PATH=<run>/playwright-browsers
PNPM_HOME=<run>/pnpm-home
npm_config_cache=<run>/npm-cache
GIT_CONFIG_GLOBAL=<run>/gitconfig
GIT_TERMINAL_PROMPT=0
```

The runner supplies a profile-owned `PATH`, does not inherit arbitrary
credential-bearing environment variables, and writes an empty controlled Git
configuration. Docker Desktop and Podman adapters connect through a preflight
validated local socket/connection rather than copying the user's engine
configuration or credential store. Initial profiles support public images
only; private-registry credentials are explicitly unsupported until a separate
credential design exists.

Container image layers are the one intentional shared-engine cache: the runner
may pull public images but never deletes images during cleanup. The action plan
and final evidence list their immutable image digests so this retained host
state is visible. All other runner-owned cache, configuration, browser, and
temporary data is removed during cleanup unless diagnostics were explicitly
retained. The durable journal and immutable redacted evidence remain outside
those ephemeral per-run directories.

## Local-execution contract

The contract remains candidate-owned
`.echelon/runnability.yml`; no parallel lifecycle file is introduced. Existing
`local_journey` remains the user-facing manual and remains valid as declared,
unverified documentation when it has no `execution` block.

An executable local journey requires root `schema_version: 2` and adds a typed
`local_journey.execution` block. Version 1 remains accepted exactly as it is:
it has no execution block and produces the existing declared-unverified local
journey. Version 2 has strict, separate root and `local_journey` field sets;
adding `execution` to a version-1 contract is invalid rather than silently
accepted.

The resolved stack, not the candidate, owns runtime environment bindings. For
example, the PostgreSQL local-runner profile declares that it supplies
`DATABASE_URL` and `TEST_DATABASE_URL` from the generated loopback endpoint,
while the browser profile owns `ECHELON_PORT`, `ECHELON_BASE_URL`, the marker,
and session identity variables. A version-2 execution command can interpolate
only these resolved binding names.

The execution schema uses a finite `manual_equivalents` mapping. Every
execution command references one existing `local_journey` command field and
zero-based command index, together with one fixed normalization transform:
`same_argv` or `inject_stack_environment`. The parser normalizes the referenced
manual command with the selected transform and requires exact argv equality.
There is no prose or heuristic notion of “manual equivalent.”

An executable local journey has this shape:

```yaml
schema_version: 2
local_journey:
  # Existing manual prerequisites, commands, URLs, and probes remain here.
  # Version 2 adds install_commands to the version-1 manual stage set.
  install_commands:
    - pnpm install --frozen-lockfile
  execution:
    profile: macos-compose-v1
    compose:
      file: docker-compose.yml
      services: [postgres]
    lifecycle:
      install:
        - [pnpm, install, --frozen-lockfile]
      prepare:
        - [bash, scripts/local-prepare.sh]
      verify:
        - [pnpm, verify]
      start:
        - [bash, scripts/runnability-start.sh, "${ECHELON_PORT}"]
      identity:
        - [pnpm, exec, tsx, scripts/runnability-identity.ts]
      stop:
        - [bash, scripts/runnability-stop.sh]
    manual_equivalents:
      install:
        - {field: install_commands, index: 0, transform: same_argv}
      prepare:
        - {field: prepare_commands, index: 0, transform: same_argv}
      verify:
        - {field: verify_commands, index: 0, transform: inject_stack_environment}
      start:
        - {field: start_commands, index: 0, transform: inject_stack_environment}
      identity:
        - {field: session_commands, index: 0, transform: same_argv}
      stop:
        - {field: stop_commands, index: 0, transform: same_argv}
```

The schema rules are:

- every command is an argv array; shell interpolation, redirection, chaining,
  and caller-controlled working directories are forbidden;
- command binaries resolve through a profile-owned, fixed toolchain path;
  candidate-relative script paths resolve inside the detached worktree with no
  symlink escape;
- only resolved stack-owned variables in an allowlist may be interpolated;
- `compose.file` is a regular, candidate-relative file; the resolver rejects
  absolute paths and paths escaping the worktree;
- `compose.services` must be a non-empty subset of stack-allowed support
  services; and
- engine provisioning and cleanup commands cannot appear in the execution
  lifecycle. The harness owns them.

Version 2 adds `local_journey.install_commands`; all version-1 local-journey
fields retain their names and validation. The contract parser accepts only
version 1 or version 2. It upgrades no data implicitly, rejects unknown fields
in either version, and represents version-1 local journeys as
execution-unavailable rather than attempting to infer executable commands.

The manual `local_journey` still documents a user's normal command sequence.
Documentation verification consumes the exact `manual_equivalents` mapping and
renders the same normalized command data. It reports a schema error for a
missing reference, out-of-range index, unsupported transform, or non-identical
argv. User-visible environment assignments are represented only through the
fixed `inject_stack_environment` transform.

The initial stack integration permits `macos-compose-v1` only when the
resolved browser stack requires a local journey and the selected support
service topology is supported by that stack. It rejects iOS and any unknown
profile before host actions begin.

## Compose policy and engine adapters

The runner exposes a narrow `LocalEngineAdapter` interface:

```text
probe(profile) -> EngineProfile
validate_compose(plan) -> validated topology
up(plan) -> ResourceSet
inspect(ResourceSet) -> ResourceFacts
down(ResourceSet) -> CleanupFacts
```

There are two implementations: `docker-desktop-macos-v1` and
`podman-macos-v1`. `auto` selects one only after successful capability probes;
it never assumes that a `docker` binary is a compatible Podman alias. The
probe records the engine executable, engine/provider version, daemon or
machine readiness, Compose implementation, loopback port-publish capability,
and required image/build support. Docker must resolve to a local Unix-socket
context and Podman must resolve to its local macOS machine; a remote context is
unsupported. A missing or unhealthy capability returns `host_preflight_failed`
before creating a worktree or engine resource.

The harness builds an engine-specific, generated override file with an opaque
Compose project name and loopback-only dynamically published service ports.
The app receives only generated environment variables such as
`ECHELON_PORT`, `ECHELON_DATABASE_URL`, and generated test identity values.
No fixed port such as `4173` or `5432` is reserved by contract.

Before `up`, the harness parses the candidate Compose input into a
profile-neutral canonical resource plan, then asks the selected adapter to
render and validate the same plan. The two plans must agree on service,
network, volume, image/build, and published-port identities. Any engine
feature that cannot round-trip through this representation is unsupported.

The parser rejects:

- `privileged`, host PID/IPC/network mode, or Docker socket mounts;
- `devices`, `device_cgroup_rules`, `cap_add`, `security_opt`, `userns_mode`,
  and other privilege- or namespace-altering service options;
- absolute bind mounts, host-home mounts, or symlink escapes;
- build contexts or Dockerfile paths outside the candidate worktree, and
  symlink escapes from either path;
- `extends`, `include`, `env_file`, Compose `configs`, Compose `secrets`, and
  profiles not selected by the stack;
- external networks or volumes, top-level network/volume `name` values, or
  custom volume drivers/`driver_opts`;
- fixed `container_name` values or explicit project/resource names;
- any candidate-authored published-port declaration; candidate services use
  internal ports only and the generated override owns every loopback mapping;
- services outside the stack-approved set; and
- unsupported Compose constructs whose resource behavior cannot be attributed
  to the run.

The harness labels every created container, network, and volume with the local
run ID. It uses adapter-returned resource IDs for inspection and cleanup; it
does not discover resources by an unscoped name or glob.

## Command lifecycle

The workspace creates an exclusive OS-held local-run lock before an engine
probe. The lock is advisory-file-descriptor based, so the operating system
releases it when a process is killed; it cannot become a permanent stale file.
A durable journal records the run ID, owner PID, effective candidate identity,
and completed cleanup actions independently of the lock. Before a new run,
Echelon detects a non-terminal journal and refuses to start another lifecycle;
it prints the exact `cleanup-local <local_run_id>` recovery command rather
than deleting stale resources implicitly. This prevents two local runs from
competing for the same host, browser cache, or project-level configuration.

The lifecycle is:

1. Resolve and validate the immutable sandbox-verified candidate.
2. Run macOS and engine preflight, then print a host-action plan containing
   the candidate fingerprint, engine profile, generated resource namespace,
   requested ports, declared lifecycle commands, and cleanup action.
3. Require interactive confirmation unless `--yes` was explicitly passed.
4. Create the detached managed worktree and a durable local-run journal.
5. Start only validated, labelled support services through the adapter.
6. Execute candidate install, prepare, verification, app start, and identity
   stages in the managed worktree with generated environment values.
7. Run harness-owned readiness, browser, HTTP, service-boundary, and durable
   persistence observations, including the restart probe when selected by the
   stack contract.
8. Stop candidate app processes with tracked process-group ownership.
9. Tear down only the adapter-returned labelled resources, inspect that no
   labelled resources remain, remove temporary identity/environment files,
   and remove the managed worktree.
10. Atomically write a final local attestation and release the lock.

Every operation after journal creation executes under `finally` and signal
handling. If cleanup cannot complete, Echelon never broadens deletion scope.
It persists the exact surviving labelled IDs, marks the result
`cleanup_incomplete`, and prints only:

```text
echelon delivery cleanup-local <local_run_id>
```

`cleanup-local` acquires the same OS-held lock and replays adapter cleanup from
the journal after revalidating the run ID and labels; it cannot accept
arbitrary container, volume, network, or Compose project names. A successful
recovery finalizes the original journal and evidence rather than creating an
unrelated new attempt.

`--keep-on-failure` is an explicit diagnostic exception. It leaves the
managed worktree and labelled resources intact, marks the result
`retained_for_diagnostics`, and still requires `cleanup-local` for removal.
It is not permitted in non-interactive `--yes` automation.

## Observations and result semantics

The harness, not project commands, proves the result. Required observations
are selected from the recorded stack snapshot and include:

- browser journey with the generated session identity;
- HTTP readiness from the host consumer boundary;
- service readiness through the generated host endpoint;
- direct PostgreSQL marker query through the same generated host connection;
- persistence check before and after a controlled application restart; and
- a final check that managed host resources are removed and the normal source
  checkout and workspace match their captured pre-run Git baselines.

An attempt result has one terminal disposition:

| Disposition | Meaning | Automatic product repair? |
|---|---|---|
| `passed` | All lifecycle, observations, provenance, and cleanup checks passed. | No |
| `host_preflight_failed` | macOS, Docker Desktop, Podman, browser, or required host tool was unavailable or incompatible. | No |
| `candidate_lifecycle_failed` | Candidate install, startup, journey, or persistence behavior failed. | No |
| `evidence_stale` | Candidate, contract, stack snapshot, or product fingerprint no longer matched the sandbox-verified candidate. | No |
| `cleanup_incomplete` | Product result may be known, but Echelon could not prove removal of its labelled resources. | No |
| `retained_for_diagnostics` | User explicitly retained the isolated run after a failure. | No |
| `runner_side_effect_detected` | The user's source checkout or workspace changed unexpectedly. | No |

This is intentionally conservative: host-specific faults must not consume
delivery repair cycles or cause a landed product to oscillate between states.
`verify-local` can offer an advisory follow-up spec only for a classified
candidate lifecycle failure, never create one implicitly.

## Evidence and status

Each attempt writes immutable, redacted evidence under:

```text
runs/targets/<target>/runs/<build>/evidence/local-runnability/
  attempt-<sequence>-<nonce>.json
  attempt-<sequence>-<nonce>.md
  artifacts/
```

The JSON attestation includes:

- spec, target, build, strategy, local-run ID, and schema version;
- sandbox candidate commit and effective candidate commit as informational
  provenance, plus authoritative product fingerprint, contract hash, stack
  hash, observer-plan hash, and sandbox receipt hash;
- runner binary version and runner-profile digest;
- macOS and selected engine capability profile;
- approved action-plan digest, generated resource IDs, and loopback endpoints;
- stage outcomes, sanitized logs, observations, browser artifacts, and
  persistence results;
- cleanup facts and source/workspace cleanliness observations; and
- an evidence digest over the normalized content.

All secrets, URL userinfo, session tokens, generated identity values, and
environment-file contents are redacted before persistence. Logs have bounded
size and record truncation explicitly.

`echelon delivery status` keeps sandbox and local facts distinct. For a given
effective candidate identity it selects the newest valid passing attestation;
a later failed preflight or diagnostic run cannot erase that pass. It displays
the newest attempt separately.

```text
sandbox journey       passed
local verification    passed | not-run | failed | stale | unsupported
local runner          macos-compose-v1 / docker-desktop-macos-v1
local evidence        <immutable attestation path>
last local attempt    host_preflight_failed | candidate_lifecycle_failed | passed
```

For a landing candidate, a matching local attestation may be displayed as
`passed`; otherwise status remains `not-run`, `failed`, `stale`, or
`unsupported`. A changed effective candidate invalidates old attestations;
mere later host preflight failures do not. Local status never changes `spec
status: landed`, alters fulfillment truth, or overwrites the original sandbox
user-runnability report.

## Rollout and compatibility

1. Preserve schema-version-1 `local_journey` contracts exactly as declared
   and unverified. Existing delivery behavior does not change.
2. Add parser, stack profile, preflight, generated-worktree, engine-adapter,
   journal, evidence, status, and cleanup primitives behind the explicit
   command only.
3. Enable `macos-compose-v1` for browser 3D and browser WASM with the
   PostgreSQL persistence stack; retain clear `unsupported` results for every
   other topology.
4. Use the browser 3D demo as the first full acceptance fixture. It must
   prove Docker Desktop and Podman separately before either profile is
   advertised as supported.
5. A future policy may require a local attestation for a class of releases,
   but that is a separate design. This release remains opt-in.

## Verification strategy

The implementation must not be considered stable without all of the following.

### Deterministic unit and contract tests

- schema parsing and backward compatibility;
- strict version-1/version-2 field boundaries, stack-owned environment
  bindings, and exact manual-equivalence mapping;
- candidate provenance and stale-evidence rejection;
- macOS/engine preflight selection and explicit unsupported results;
- generated argv/environment interpolation, controlled-host-environment, and
  source-boundary checks;
- Compose-policy rejection for every prohibited construct;
- canonical-plan versus adapter-rendered-plan agreement for Docker Desktop and
  Podman;
- adapter action-plan/resource-label construction;
- journal durability, cancellation, redaction, evidence digesting, and
  status rendering;
- matching landed merge commits, plus preservation of a valid local pass when
  a later host preflight attempt fails;
- every terminal disposition and the no-auto-repair rule; and
- cleanup-local rejection of arbitrary/non-labelled resource identifiers.

### Process and filesystem integration tests

- synthetic engine adapters that simulate partial `up`, failed start,
  interrupted browser journey, and partial `down`;
- abrupt process loss with an OS-released lock, a non-terminal journal, and
  explicit recovery through `cleanup-local`;
- process-group termination and orphan detection;
- target/workspace Git-baseline equality before and after every failure path,
  including pre-existing user changes;
- per-run cache/config isolation and intentional retained image-cache
  reporting;
- mutually exclusive workspace lock behavior; and
- candidate worktree removal, retained diagnostic worktree, and recovery
  cleanup behavior.

### Real macOS acceptance

A small fixture containing a browser app and PostgreSQL must run through the
complete local lifecycle on a maintained macOS host for each adapter in
separate clean sessions:

- Docker Desktop;
- Podman;
- generated loopback ports;
- real browser observation;
- durable persistence across restart; and
- verified resource and worktree cleanup; and
- intentional interruption followed by journal-based recovery cleanup.

The acceptance artifact is versioned by Echelon release commit and runner
profile. A profile cannot be described as supported in a release unless its
matching macOS acceptance artifact is passing. Normal unit suites may use fake
adapters; they do not substitute for this acceptance requirement.

## Design invariants

- Host verification is explicit, opt-in, and never an LLM action.
- Sandbox verification remains the landing authority.
- No runner action targets the user's source checkout.
- Every engine resource is uniquely labelled, loopback-bound, journaled, and
  cleaned only by exact identity.
- Host failures do not become autonomous delivery-repair work.
- A local pass is meaningful only when bound to the exact sandbox-verified
  candidate and recorded stack/contract snapshot.
- Unsupported environments fail before mutation, and unsupported profiles are
  never presented as passing.
