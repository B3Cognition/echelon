# Sandbox-Owned Delivery Verification Design

**Status:** Proposed replacement for the unmerged stack-verification-provisioning implementation.

## Problem

Echelon creates a Docker sandbox for delivery work but `RalphController` runs a
configured `verify_command` with host `subprocess.run`. This splits a single
verification operation across two trust boundaries. A browser test can therefore
download or launch a browser on the host, and a persistent test dependency must
be provisioned manually outside the sandbox. The browser-3D-game delivery run
demonstrated the result: the host lacked Playwright's requested Chromium binary,
all browser tests failed before application assertions, and retries spent tokens
without changing that prerequisite.

## Goals

- Make sandbox verification the default and authoritative delivery path.
- Install project dependencies and Playwright browsers only inside the sandbox.
- Start stack-declared test services, including PostgreSQL, as harness-owned
  sidecars on the sandbox's internal Docker network.
- Keep host state limited to the Docker-compatible runtime, worktree mount, and
  immutable evidence artifacts.
- Preserve a deliberate host-verification fallback for environments that cannot
  use the sandbox, but never select it silently.
- Report target outcomes truthfully: blocked delivery is never success.

## Non-goals

- Replacing the existing Docker-compatible provider with a cloud provider.
- General deployment or production database provisioning.
- Exposing database ports on the host.
- Installing project dependencies, Playwright, or browsers into a source
  checkout on the host.

## Execution model

`harness.verification.execution` has these values:

| Value | Meaning |
| --- | --- |
| `sandbox` (default) | Run all verification stages through `SandboxProvider`. |
| `host` | Explicit, opt-in fallback; its evidence is marked `host-fallback`. |

Delivery refuses to silently downgrade from `sandbox` to `host`. If the Docker
runtime, selected image, or sandbox setup is unavailable, delivery blocks before
the LLM loop with a stable `SANDBOX_VERIFICATION_UNAVAILABLE` remediation.

The authoritative receipt records execution mode, sandbox image digest/reference,
network/service identities, commands, durations, redacted output, candidate
commit, and candidate fingerprint. The existing fulfillment provenance checks
consume the receipt independent of its execution mode.

## Sandbox lifecycle

For each verification attempt Echelon:

1. Resolves the candidate worktree and effective target-local stack selection.
2. Resolves a verification image. A target that declares or locks Playwright
   selects a compatible Playwright image pinned to the target's Playwright major
   and minor version; a `devcontainer` or explicit image remains an intentional
   override only when it proves it can run the declared verifier.
3. Creates the sandbox container and an internal Docker network through
   `DockerWorktreeProvider`.
4. Creates required stack service sidecars on that same network. The provider,
   not sandbox code, invokes Docker; the sandbox never receives the Docker socket
   or Docker CLI authority.
5. Runs dependency bootstrap and verification commands in the sandbox. For a
   pnpm target, bootstrap is `pnpm install --frozen-lockfile`; Playwright browser
   installation is unnecessary when the selected image carries the matching
   browser revision. If a compatible image cannot be selected, the sandbox may
   run `pnpm exec playwright install --with-deps chromium` through the existing
   network allowlist and records it as a bootstrap stage.
6. Copies bounded test artifacts and provider/service logs to the evidence
   directory, writes the authoritative receipt, then destroys sandbox, sidecars,
   and network even when verification fails.

No browser GUI or `node_modules` directory is created in the source checkout.

## Stack service contract

The existing provisioner declaration is split by intent:

- `sandbox_service` declares a harness-managed verification dependency.
- `manual_reproduction` declares optional target-local files rendered by
  `echelon stack provision` for a developer reproducing a failure.

The bundled `game-persistence-postgres` stack declares a sandbox PostgreSQL 16
service. The service has no published host port. Echelon injects its internal
connection URI into the declared verification environment names (for example,
`TEST_DATABASE_URL`) and waits for the service's health check before executing
the verifier. Service data belongs to the attempt and is destroyed on cleanup.

Missing or malformed sandbox-service declarations fail stack validation before
delivery. A failure to pull an image, create the service, or pass its health
check is classified as environment setup failure, not as a repeatable product
test failure. It cannot consume inner repair retries.

## Browser verification detection

Target analysis identifies Playwright from `@playwright/test`, `playwright`, a
Playwright configuration file, or a verifier command containing `playwright`.
The verifier plan includes a browser requirement and image selection outcome.
This requirement is evaluated only after dependency bootstrap in the sandbox;
host Playwright caches are not consulted.

The preflight/status output reports one of:

- `sandbox-ready` — image and declared services can be created;
- `sandbox-bootstrap-required` — the sandbox will install dependencies/browser
  during verification;
- `sandbox-unavailable` — actionable Docker/image/network remediation;
- `host-fallback-configured` — visible warning, never automatic.

## CLI behaviour

`echelon delivery run`, `continue`, and `resume` print the verification mode and
environment plan before provider/LLM work. A sandbox setup block names the exact
unavailable prerequisite, retains logs, and recommends `echelon delivery
continue` only after that prerequisite changes.

`echelon stack preflight --target <path>` becomes target-aware and read-only. It
reports effective stack selection, sandbox services, browser requirement, and
the next action. `echelon stack provision --target <path>` remains available only
to render optional local-reproduction artifacts; it no longer claims to prepare
the default delivery environment.

Multi-target delivery preserves independent targets after an environment block,
skips dependent targets, returns a non-zero aggregate exit status, and labels
each target accurately in the final summary.

## Safety and cleanup

- The sandbox never receives Docker socket, host credential stores, or a host
  browser path.
- All sidecars carry session labels and are deleted with the sandbox network.
- No database port is published to the host.
- Pulls/downloads are constrained by Echelon's existing allowlist.
- Verification service credentials are generated per attempt, injected only
  into sandbox/service containers, redacted from evidence, and discarded during
  cleanup.
- Manual reproduction files retain path containment and explicit `--force`
  overwrite semantics.

## Verification requirements

- Unit tests prove configured verification uses `SandboxProvider.exec` by
  default and never `subprocess.run` on the host.
- Docker-provider tests prove sidecars share the internal network, have no host
  ports, receive labels, health-check, and clean up after failure.
- Browser-plan tests cover version-compatible image selection and sandbox
  bootstrap fallback without inspecting host Playwright cache.
- Stack tests distinguish sandbox services from manual reproduction renderers.
- Delivery tests prove setup failures stop before LLM retries, blocked targets
  are reported as blocked, and independent targets still run.
- An opt-in Docker integration test runs a Playwright fixture plus PostgreSQL
  sidecar and verifies no host `node_modules` or browser cache is required.
