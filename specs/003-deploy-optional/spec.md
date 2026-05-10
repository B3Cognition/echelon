# Optional Deploy — Specification

> Allow echelon projects to opt out of the blue/green deploy infrastructure entirely via a single config flag (`deploy.enabled: false`). When disabled, all deploy validation gates and post-merge deploy steps are skipped gracefully, with no errors and no infrastructure requirements. All other behaviour (build, verify, merge) is unaffected.

**Status**: Draft

---

## User Scenarios & Testing

### Scenario 1: Build with deploy disabled

**As a** developer working on a project that does not use echelon's local CD,
**I want to** run `echelon.build` (or `echelon.harness-run`) without Traefik, Docker networks, or deploy-state.json present,
**So that** the build pipeline completes normally without deploy-related failures.

#### Acceptance Criteria

- **AC-1.1:** Given `deploy.enabled: false` in echelon config, when `echelon.build` initialises (§1.0b), then `validate-deploy.sh` exits 0 immediately without checking for deploy-state.json, Traefik, or the Docker network.
- **AC-1.2:** Given `deploy.enabled: true` (or key absent) in echelon config, when `validate-deploy.sh` runs, then it performs all existing checks unchanged.
- **AC-1.3:** Given `deploy.enabled: false` and deploy-state.json is missing, when `echelon.build` initialises, then no error is produced and the build proceeds to task iteration.

### Scenario 2: Harness run with deploy disabled

**As a** developer using `echelon.harness-run`,
**I want to** complete the full build → verify → merge cycle without a deploy step,
**So that** the harness run finishes cleanly on projects without local CD infrastructure.

#### Acceptance Criteria

- **AC-2.1:** Given `deploy.enabled: false`, when `harness-run` reaches Step 9b after a successful merge, then the deploy step is skipped entirely — no skill invocation, no error output.
- **AC-2.2:** Given `deploy.enabled: true` (or key absent), when `harness-run` reaches Step 9b, then the deploy step runs exactly as it does today.
- **AC-2.3:** Given `deploy.enabled: false`, when `harness-run` reaches Step 4b (SPA subpath detection), then the step produces `none none` and continues — no change from existing graceful behaviour.

### Scenario 3: Codegen with deploy disabled

**As a** developer using `echelon.codegen`,
**I want to** run the SOAR pipeline without deploy infrastructure,
**So that** `echelon.codegen` is usable in the same environments as `echelon.build`.

#### Acceptance Criteria

- **AC-3.1:** Given `deploy.enabled: false`, when `codegen-A-preamble §A.5` calls `validate-deploy.sh`, then the script exits 0 and the preamble continues to §A.6.
- **AC-3.2:** Given `deploy.enabled: false`, when `codegen-A-preamble §A.7` reads deploy-state.json for the SPA base path fix, then it produces an empty result and skips the fix — no change from existing graceful behaviour (already conditional on `DEPLOY_TYPE = http`).

---

## Functional Requirements

### Config

- **FR-001**: The echelon config schema MUST include `deploy.enabled` as a boolean key with a default of `true`. Absence of the key MUST be treated as `true` by all consumers.
- **FR-002**: The `deploy.enabled` key MUST be defined in `config-template.yml` under the `deploy:` section, with an inline comment explaining its purpose.

### Deploy validation gate

- **FR-003**: `validate-deploy.sh` MUST read `deploy.enabled` via `echelon-config-get.sh deploy.enabled` (the resolver), not by parsing YAML directly.
- **FR-004**: When `deploy.enabled` resolves to `false`, `validate-deploy.sh` MUST print a single informational line and exit 0 before performing any infrastructure checks.
- **FR-005**: When `echelon-config-get.sh` is unavailable or returns an error (e.g., no `.specify/` root found), `validate-deploy.sh` MUST treat the flag as `true` and proceed with all existing checks — fail-safe, not fail-open.

### Harness-run post-merge deploy

- **FR-006**: `echelon.harness-run §Step 9b` MUST check `deploy.enabled` via `echelon-config-get.sh` before invoking `speckit-echelon-deploy`.
- **FR-007**: When `deploy.enabled = false`, Step 9b MUST be skipped entirely — no skill invocation, no output beyond a single informational line.
- **FR-008**: The `deploy.enabled` check in Step 9b MUST occur after the `auto_merge=true` guard — only relevant when a merge actually happened.

---

## Non-Functional Requirements

| ID | Category | Requirement | Measurable Target |
|----|----------|-------------|-------------------|
| NFR-001 | Backward compatibility | All existing projects with no `deploy.enabled` key continue to behave identically | Zero behaviour change when key absent |
| NFR-002 | Consistency | Config is read the same way across all consumers — via `echelon-config-get.sh` | No direct YAML parsing in any new code |
| NFR-003 | Scope | No other workflow phases, agents, or scripts are modified | Exactly 3 files changed |

---

## Scope

### In Scope (MVP)
- `config-template.yml` — add `deploy.enabled: true`
- `validate-deploy.sh` — early-exit when `deploy.enabled = false`
- `echelon.harness-run.md §Step 9b` — skip when `deploy.enabled = false`

### Explicitly Out of Scope
- `deploy-state.json` creation / initialisation — not changed; remains the responsibility of `echelon.run`
- `echelon.deploy` command — not changed; users who want to deploy manually still can
- `echelon-config.yml` (the banzai instance config) — not changed; `deploy.enabled` absent defaults to `true`
- Any UI or status display changes
- CI/CD pipeline changes
