# Echelon

A multi-agent system for AI-assisted software development. Instead of one AI doing everything, specialized agents handle specific cognitive tasks — understanding, critiquing, planning, building, and learning.

**Version 3.9.0** — 56 registered agent roles across the Echelon architecture, with 46 active-routed manifest roles in the executable workflow, a first-class independently resumable RE lifecycle, immutable published-RE snapshots for spec authoring, MemPalace requirements memory, endocrine context, journal contracts, Understanding quality gates, BUILD/QA workflow, and multi-LLM provider support (Claude, Codex, Copilot, Opencode)

For the grounded role inventory, see [Agent Role Catalog](docs/agent-role-catalog.md).

## Quick Start

### Install Spec Kit and Echelon

Install `uv` first. You also need Git and the AI coding CLI that you intend to
use (Claude, Codex, Copilot, or Opencode) before running agent-backed commands.
Docker or Podman is needed only for Phase B delivery; Node.js with npm is
optional and enables Context7, CodeGraph, and PerlGraph evidence. `pdftotext`
(Poppler) is recommended when you need higher-fidelity PDF input extraction.

```bash
# 1. Install spec-kit
uv tool install specify-cli --force --from "git+git@github.com:mbachorik/spec-kit.git"

# 2. Clone echelon
git clone https://github.com/B3Cognition/echelon.git ~/echelon

# 3. Install the core CLI tools and shared MemPalace support
bash ~/echelon/scripts/install.sh
source ~/.zshrc   # or restart terminal
```

`install.sh` installs the core CLI tools into `~/.echelon/venv/bin/`, adds that
directory to your PATH, and keeps MemPalace available to ordinary squad runs.
This is enough to author specs and run the default delivery strategy. The
SOAR-backed codegen pipeline is opt-in:

```bash
bash ~/echelon/scripts/install.sh --with-codegen
```

| Tool | Purpose |
| ---- | ------- |
| `echelon` | Main CLI - workspace, spec, phase, RE publication, delivery, benchmark, stack |
| `echelon delivery` | Build/delivery subcommands — init, run, resume, land |
| `echelon spec` | Spec lifecycle subcommands — run, status, targets, verify, defer, plan, reopen |
| `codegen` | Optional SOAR codegen pipeline, installed with `--with-codegen` |
| `understanding` | Requirements quality metrics |

See [INSTALLATION.md](INSTALLATION.md) for prerequisites, upgrade, and uninstall instructions.

### First spec in a new or existing workspace

Create or enter a Git-backed workspace, initialize Spec Kit there, install the
Echelon extension into that workspace, then initialize Echelon. The extension
belongs in your project—not in the `~/echelon` checkout.

```bash
# For an existing repository
cd ~/work/my-project

# For a new project instead:
# mkdir -p ~/work/hello-world && cd ~/work/hello-world && git init -b main

# Choose the integration you use; Claude is shown here. `--offline` keeps
# initialization local to the installed Spec Kit templates.
specify init --here --integration claude --offline
specify extension add --force --dev ~/echelon/extension

# Creates .echelon/config.yml and asks for local host-tool approval on a TTY.
echelon workspace init

# Phase A: write a specification and plan. No SOAR/codegen installation needed.
echelon spec run "Create a sample Hello World program in Python"
```

Use `--integration copilot`, `--integration codex`, or another supported Spec
Kit integration in place of `--integration claude` when appropriate. Add
`--force` to `specify init --here` only when you intentionally want it to merge
into an existing non-empty setup. The extension command uses `--force` so it
can safely refresh a prior development install.

### Local Git hooks

Enable the tracked hooks in each checkout:

```bash
git config core.hooksPath .githooks
```

The pre-push hook runs `bash tests/run-all.sh` before pushes to `origin` and
blocks the push when any suite is red.

When Node.js and npm are available, the installer also prepares pinned
Context7, CodeGraph, and PerlGraph runtimes under
`${ECHELON_HOME:-$HOME/.echelon}/node`. Without Node, core Echelon commands
remain available; only those optional evidence integrations are skipped.

### Update to latest version

```bash
cd ~/echelon && git pull
bash ~/echelon/scripts/install.sh   # re-run to pick up dependency updates
specify extension add --dev --force ~/echelon/extension
```

Knowledge-base data (calibration, feedback, patterns) is protected by `.extensionignore` — updates never overwrite your runtime learning data.

Terminal `echelon spec status`, `echelon spec run`, `echelon spec continue`, and `echelon spec resume`
warn when the installed project extension under `.specify/extensions/echelon`
differs from a trusted source extension. In a dev checkout this is detected
automatically; otherwise set `ECHELON_EXTENSION_SOURCE` to your Echelon repo or
extension directory before running the command. When you see `EXTENSION DRIFT`,
rerun:

```bash
specify extension add --dev --force ~/echelon/extension
```

`echelon workspace init` is pure Python—no AI session is required. Run
`echelon delivery init` later, when you are ready to start Phase B delivery.

### Workspace contract

Echelon expects a Git-backed workspace with a committed `.echelon/config.yml`.
Runtime state is local: `.specify/`, `runs/`, `.claude/`, `.echelon/runtime/`,
`.echelon/cache/`, `.echelon/recovery-backups/`, and `.echelon/local.yml`
should be ignored. Spec artifacts under `specs/<id>-*/` are the tracked
handoff between Phase A, harness build, and land. New workspaces also include a
tracked `sources/README.md`; clone or copy implementation repositories under
`sources/`. Rather than editing `sources:` by hand, let Echelon discover the
canonical roots and update `.echelon/config.yml`:

```bash
# Preview the source roots Echelon found under sources/.
echelon workspace sources sync

# Add missing roots and remove stale sources/* entries in the workspace config.
echelon workspace sources sync --write

# Validate the complete workspace, source, and runtime contract.
echelon workspace doctor
```

`sync --write` preserves source roots configured outside `sources/`. Use
`sources: []` for a planning-only workspace. For an existing pre-workspace
layout, `echelon workspace migrate --write` copies the legacy configuration,
ignores runtime state, and stages canonical workspace files; add `--commit` to
commit that migration after reviewing it.

### Optional: add an existing repository and publish reverse engineering

For an existing implementation repository, place it under `sources/`, sync the
workspace configuration, then run RE. This is optional: a greenfield spec can
start immediately after `echelon workspace init`.

```bash
git clone <repository-url> sources/app
echelon workspace sources sync --write
echelon workspace doctor

# Analyze the declared source roots. Keep the run ID printed by this command.
echelon re run --re-policy changed

# Publish a validated completed run so subsequent spec runs receive its snapshot.
echelon re publish <run-id>

# Target the existing repository when authoring a spec for it.
echelon spec run "Add a health endpoint" --target sources/app
```

### Published reverse engineering

Reverse engineering is a first-class workspace lifecycle. Echelon keeps only the
latest published generation under `re/`; active RE work is isolated under
`runs/re-*/re/` and selected by `runs/.current-re`. Spec runs never execute or
freshness-check RE. By default they take one immutable run-local snapshot of the
latest publication; use `echelon spec run ... --ignore-re` to omit it.

New RE runs use the bounded `balanced` execution goal by default. It targets
completion within 60 active minutes and has hard ceilings of 180 active minutes
and 5,000,000 provider-reported tokens. `fast` uses 30/60 minutes and 1,000,000
tokens; `high` uses 180/720 minutes and 15,000,000 tokens. Select one with
`echelon re run --profile fast|balanced|high`. Active time excludes periods when
the command is stopped. `continue` preserves the original profile and consumed
budget instead of resetting either. Providers that do not report usage remain
explicitly unknown rather than being estimated.

Every new RE provider dispatch writes content-free, OpenTelemetry-aligned local
telemetry below `runs/<run-id>/telemetry/`. Raw prompts, responses, source code,
and secrets are excluded. Diagnostic commands are intentionally hidden from
ordinary help; run `echelon admin commands` to discover them, including the
read-only `echelon re analyze` baseline and cost report.

When Node.js and npm are installed, RE analysis can include optional CodeGraph and PerlGraph artifacts; their absence does not block core RE or spec authoring.

```text
re/
  .gitignore                    # ignores .cache/, .staging/, and .locks/
  index.json                    # generation and source-id mapping
  sources/<source-id>/
    manifest.json
    overview.md
    specs/<domain-id>/spec.md
  workspace/
    manifest.json
    overview.md
    relationships.md
    contracts.md
    domains/*.md
  .cache/                       # ignored heavy extraction cache
  .staging/                     # ignored publication transactions
  .locks/                       # ignored single-writer lock
```

`<source-id>` is the stable `sources[].id` from `.echelon/config.yml`; its
manifest records the matching `sources[].path`. Source content/fingerprint
changes, dirty Git state, or any profile-hash change trigger refresh. The
default profile remains `full` depth with `max_lines_per_file: 5000` and
`git_history_limit: 2500`; `echelon re run --re-policy` overrides selection
without changing those depth defaults.

A successful complete `echelon re run` remains run-local until you explicitly
publish it with `echelon re publish <run-id>`. A default `--re-policy changed`
run makes zero provider calls when the publication is current. Empty declared
sources can publish an explicit `empty` manifest without inventing domain specs.
Partial output never auto-publishes and remains blocked for inspection or an
explicit `--allow-partial` publication.

```bash
echelon re run                               # changed policy; no-op when current
echelon re continue --re-max-inner 10       # continue without a new answer
echelon re resume "Use the v2 contract"     # answer a structured RE block
echelon re publish <run-id>                   # publish a validated complete run
echelon re publish <run-id> --allow-partial   # explicit structural override
echelon re publish <run-id> --commit          # also make a local durable-RE commit
```

Publication never pushes. Without `--commit`, it does not invoke Git. With
`--commit`, it stages only `re/.gitignore`, `re/index.json`, `re/sources`, and
`re/workspace`; runtime directories remain ignored. Legacy
`.echelon/cache/re` data is one-way migration input for manual publication and
is never freshness or publication authority.

### Typical workflow

```bash
# Optional — refresh published brownfield knowledge only when needed
echelon re run --re-policy changed --re-max-inner 10

# Phase A — spec authoring (default: Claude)
echelon spec run "Build a photo album app with sharing and tagging"
echelon spec status                        # re-orient: run state, artifacts, cost, next step
echelon spec artifacts 001                 # generate specs/001-*/ARTIFACTS.md
echelon wiki build                         # generate workspace-wide human navigation
echelon spec continue                      # run the next no-input recovery/phase action
echelon spec resume "your clarification"   # answer a human-input block, then continue
echelon spec rewind <phase-id> --confirm   # recover the latest recorded checkpoint for a phase
echelon spec rewind <phase-id> --commit <sha> --confirm  # select an explicit historical checkpoint

# Deliberately remove a requirement or task from the landing scope, without an LLM call
echelon spec defer 001 NFR-008 --reason "Owner decision" --dry-run
echelon spec defer 001 NFR-008 --reason "Owner decision"
echelon spec continue

# Return explicitly deferred work to the planned scope
echelon spec plan 001 NFR-008

# Phase B — build, verify in Docker, open PR
echelon delivery run 001                    # echelon squad build (default)
echelon delivery run 001 --strategy codegen # SOAR pipeline build (alternative)

# Polyrepo/workspace: declare implementation roots before Phase A dispatches
echelon spec run "Build dashboards" --target sources/api --target sources/web
echelon spec run "Modernize search" --target og-platform
echelon spec run "Create a tool" --target sources/new-tool --init
# Normative product requirements and informative reference-product evidence
echelon spec run "Add player connections" \
  --target sources/pressbox-search \
  --target sources/pressbox-search-api \
  --input requirement:sources/PBS-E-45 \
  --input reference:sources/provision
echelon spec targets 001                        # display every task grouped by target
echelon delivery target 001                     # detect target verify metadata from targets.yml
echelon delivery run 001 --mode semi             # validates and runs target-owned task slices
echelon delivery run 001 --mode banzai           # same deterministic target/dependency selection

# After build converges, fulfillment passes, and PR is open
echelon delivery land 001                  # lands the target repo branch, then marks the spec landed

# After PR is open — review triage runs automatically via harness Phase 3
# but can also be invoked directly:
echelon review 001 --pr-url https://github.com/org/repo/pull/42
```

### Artifact graph workflow

The artifact graph connects a canonical specification with the published RE and
verification evidence that apply to it. Those sources are published
independently: RE is optional and normally precedes spec authoring, while
verification evidence normally becomes available after delivery and landing.
The graph uses whichever canonical sources are present; it never reads
unpublished run-local artifacts.

Before building the graph, refresh the MemPalace projections for the source
domains that exist. Each refresh mines only its own canonical source and audits
the result, so the graph does not duplicate mining:

```bash
# Publish canonical sources as they become available.
echelon re publish <run-id>                 # optional brownfield context
echelon spec publish <spec>                 # canonical spec on local default branch
echelon spec evidence publish <spec>        # normally after land

# Reconcile each applicable canonical source with MemPalace.
echelon re memory refresh                   # when published RE is attached
echelon spec memory refresh <spec> --write
echelon spec evidence memory refresh <spec> # when evidence is published

# Build, persist, and audit the graph, then inspect it.
echelon graph refresh <spec> --write
echelon graph view <spec>
```

`graph refresh --write` is the normal shorthand for a persisted build followed
by a persisted audit. Automation may run the stages separately:

```bash
echelon graph build <spec> --write
echelon graph audit <spec> --write
echelon graph view <spec> --no-open
echelon graph export <spec> --format dot --output graph.dot
```

Every graph records hashes for its canonical input set and its MemPalace audit
receipts. The audits distinguish three stale transitions:

- a canonical artifact changed after its MemPalace projection was refreshed;
- a canonical graph input changed after the graph was built;
- MemPalace was refreshed after the graph was built.

Refresh the affected memory domain first, then rebuild the graph. `view` and
`export` are read-only and do not repair stale state. They still produce output
when the live graph audit fails, but return exit code `1` and show the findings;
missing or invalid graph state returns `2`.

### Product inputs: requirements versus references

`--input` is repeatable and deliberately separates product obligations from
contextual evidence. Choose the role based on the authority you want the input to
have—not its file type.

| Role | Use it for | What Echelon records |
| ---- | ---------- | -------------------- |
| `requirement:<path>` | Statements that must be resolved by the specification and delivery plan | `IN-REQ-*` units in the requirement traceability ledger. Included units must map to specification IDs and implementation tasks before finalization. |
| `reference:<path>` | API documentation, design material, examples, existing-product behavior, or other context that informs decisions | `IN-REF-*` catalog entries. Agents may use them as evidence, but they never become requirements or task mappings. |

For example, API documentation for a new SDK is reference evidence, while a
commitment such as “publish a Python SDK” belongs in the request itself or in a
`requirement:` input:

```bash
echelon spec run "Create a Python SDK for our API" \
  --input reference:sources/api-docs
```

During DISCOVER, references inform SCOUT's domain analysis only; they do not
change the requirement-traceability ledger. Use `requirement:` when a statement
must be represented by functional requirements, acceptance criteria, and tasks.

Echelon snapshots accepted inputs under the run and publishes the manifest,
catalog, snapshots, and traceability evidence at `specs/<id>/inputs/`. It excludes
hidden files and scans text for high-confidence secret patterns, but this is a
safety net—not a secret-sharing mechanism. Never put passwords, API keys, tokens,
or private keys in an input file; use your normal secret-management path instead.
An offline Figma evidence bundle (`manifest.json`, `design.json`, frame assets) is
supported; PNG/SVG/PDF exports are reduced-fidelity evidence. A Figma URL is
resolved with `FIGMA_ACCESS_TOKEN` (or an offline bundle); the token is never placed
in the run or spec evidence.

Echelon models every project as a workspace with zero or more source roots. See [`docs/workspace-model.md`](docs/workspace-model.md) for single-repo, polyrepo, and lightweight workspace Git setup.

Set `ECHELON_LLM` to switch AI provider for any command above — see [AI Provider Support](#ai-provider-support) below.

Echelon has separate Phase A spec-authoring choices and Phase B build-strategy
choices. Before enabling the derived Lexicon controlled-grammar gate or SOAR
codegen, read [Echelon Pipeline Matrix](docs/pipeline-matrix.md) for the current
compatibility contract.

### Other echelon commands

```bash
echelon spec change 001 "scope change description" # mid-build spec change
echelon delivery init                            # workspace/global delivery setup
echelon delivery target 001                      # target-specific verify detection
# If target detection reports "not configured", set delivery.verify_command in specs/<id>/targets.yml.
```

### Harness fulfillment refresh policy

Harness fulfillment refreshes are controlled from the repo config under
`harness.fulfillment.refresh_policy`. Set this in
`.echelon/config.yml` for a committed project default, or in
`.echelon/local.yml` for a local override.
For normal generated projects, `.specify/` is local spec-kit/Echelon runtime
state and should be gitignored; the tracked governance handoff is the published
`specs/<id>-*/constitution.md` snapshot.

```yaml
harness:
  verify_command: env NP_SMOKE_SKIP_IOS=1 bash scripts/smoke.sh
  fulfillment:
    refresh_policy: scoped
```

Available policies:

- `milestone` — default; run full `verify-spec` at normal milestone boundaries
- `scoped` — run scoped incremental fulfillment refreshes after passing slices, but still require a full `verify-spec` before convergence or land
- `every_slice` — old behavior; run full `verify-spec` after each passing build slice
- `convergence_only` — defer full fulfillment refresh until task progress is complete enough to attempt convergence

Use `scoped` when full fulfillment refreshes are dominating cost or latency during
active harness loops. Use `milestone` when you want the most conservative default.

With `scoped` or `convergence_only`, harness output may show `verify: deferred`
or `fulfillment refresh: cached`. That is not a failed build. It means the
current slice did not require a full fulfillment refresh, or no requirements were
deterministically impacted. In short: full fulfillment evidence is still required before convergence or land.

Harness `run` and `resume` also print `HARNESS HISTORY`: tracked runs, checkpoint state, and token/cost totals for the same spec so repeated resumes do not feel like a black box.

### Explicit scope deferrals

Use `echelon spec defer <id> <T-*|FR-*|NFR-*|AC-*|SC-*> --reason "..."` when an
owner deliberately removes work from the current landing scope. `--dry-run` shows
the direct tasks that will become deferred and any other requirements on those
mixed tasks that remain active. The command writes the committed, auditable
`specs/<id>-*/deferred-scope.json` ledger and marks directly mapped unfinished
tasks `DEFERRED` in `tasks.md`.

`echelon spec continue` then treats those selected requirement IDs and deferred
tasks as intentionally out of scope. It does not suppress unrelated gaps or the
other requirement IDs attached to a mixed task. Fulfillment reports record each
selected requirement as `DEFERRED_SCOPE` with its ledger entry and reason; landing
rejects a deferred row that is not backed by an active ledger entry.

Use `echelon spec plan <id> <ID...>` to return a deferred requirement or task to
planned work. The original ledger entry remains as history, its task statuses are
restored, and the next verification again reports any fulfillment gap normally.

### Active run recovery

During spec authoring, `runs/.current` is the active-run pointer. `echelon
continue` reads that pointer, loads the named run directory, and resumes from the
phase recorded in that run's `state.json`.

The active squad workspace is run-local: agents read and write
`runs/<run>/specs/<id>`. The canonical `specs/<id>` folder is the published spec
folder used by humans and by Phase B. The build harness reads canonical `specs/<id>`
and should not consume run-local staging paths. When a squad run is
continued after artifacts were already published, `echelon spec continue` syncs
missing canonical artifacts back into the active run copy; it never guesses the newest `specs/*` directory.

Use rewind when a resumed squad run reports `missing_echelon_result`,
`missing_phase_outputs`, or a safe Phase 3 phase needs to be replayed with the
proper context:

```bash
echelon spec rewind phase3-sentinel --confirm
echelon spec continue
```

Safe rewind targets are intentionally narrow. They reset the active run state and
clean downstream generated artifacts, but they do not ask you to manually copy
`state.json` or `reasoning-journal.jsonl` into `specs/<id>`.

### Spec-kit skills (Claude session)

All of the above are also available as spec-kit slash commands inside a Claude Code session:

```bash
speckit.echelon.init
speckit.echelon.run "Build a photo album app"
speckit.echelon.bugfix 001 "upload button does nothing"
speckit.echelon.harness-run 001
speckit.echelon.harness-run 001 strategy=codegen
speckit.echelon.verify
speckit.echelon.feedback 001
./scripts/bash/dry-run.sh    # validate extension setup without running agents
```

## Execution Paths

Echelon commands can be invoked two ways. Both paths are fully supported and run independently of each other.

### Interactive Claude Code session (spec-kit skill system)

When you type a slash command inside a Claude Code session (e.g. `speckit.echelon.run`), spec-kit reads the skill file directly and injects its content into the current conversation context. The `disable-model-invocation: true` frontmatter in each skill file is honoured — Claude executes the instructions in-context rather than spawning a subprocess.

This path has no dependency on the `echelon` CLI tool or the `ECHELON_LLM` env var. It always uses the Claude instance already running your session.

### Terminal CLI (`echelon` / `harness` commands)

When you run `echelon spec run "..."` from the terminal, the `echelon` CLI:

1. Locates the skill file for the selected provider (Claude, Copilot, or Opencode)
2. Strips the YAML frontmatter (which is meaningful only to spec-kit, not to the LLM)
3. Prepends an execution preamble ("You are COMMANDER running non-interactively…") so the model acts on the instructions rather than narrating them
4. Injects the effective host tool-policy preamble and invokes the LLM CLI subprocess (`claude -p <prompt>`, `codex exec <prompt>`, `copilot -p <prompt>`, or `opencode run <prompt>`)

This path requires the `echelon` CLI to be installed (`scripts/install.sh`) and the target LLM CLI to be on your PATH. The `ECHELON_LLM` env var (or `harness.llm.cli` in `.echelon/config.yml`) selects the provider.

By default, terminal CLI runs do **not** add dangerous permission-bypass flags to the underlying AI CLI. Unsafe host execution is fail-closed and must be explicitly configured under `harness.llm.tool_policy` with both `allow_unsafe_host_execution: true` and an `approval_reason`. `echelon workspace init` prompts for this local approval on an interactive TTY, and `echelon workspace init --allow-unsafe-host-execution` writes the same approval non-interactively to `.echelon/local.yml`. When approved, Echelon re-enables the selected provider's equivalent bypass flag, such as Claude/Opencode `--dangerously-skip-permissions` or Codex `--dangerously-bypass-approvals-and-sandbox`. File, network, and individual tool-call isolation beyond those CLI flags still depends on the selected AI CLI runtime.

The two paths share the same skill content but are otherwise fully independent — changes to one do not affect the other.

## AI Provider Support

All `echelon` and `harness` CLI commands are provider-agnostic. Set the `ECHELON_LLM` environment variable to select which AI tool runs the skills:

| Value | AI tool | Skill location |
| ----- | ------- | -------------- |
| `claude` | Claude CLI (default) | `.claude/skills/speckit-echelon-<cmd>/skill.md` |
| `codex` | Codex CLI | `.claude/skills/speckit-echelon-<cmd>/skill.md` |
| `copilot` | GitHub Copilot CLI | `.github/agents/speckit.echelon.<cmd>.agent.md` |
| `opencode` | Opencode | `.opencode/command/speckit.echelon.<cmd>.md` |

```bash
# Use Copilot for all echelon commands
export ECHELON_LLM=copilot
echelon spec run "Build a photo album app"

# Use Opencode for a single command
ECHELON_LLM=opencode echelon spec bugfix 001 "upload button broken on Safari"
```

Skill files are placed in the right location automatically by `specify extension add` after `specify init --integration <tool>`. Each provider's skill files are rewritten for that tool's conventions — do not copy them between providers manually.

The delivery build loop (`echelon delivery run`) also respects `ECHELON_LLM` — LLM-driven build steps, feedback loops, and the PR review skill all use the same provider. Set it in your CI environment or `.echelon/config.yml` (`harness.llm.cli`).

## Delivery Harness

Delivery is Echelon's user-facing Phase B lifecycle: build, verify, recover,
review, and land a completed spec. The harness is the internal execution
substrate: it takes Echelon's Phase A output (spec.md, tasks.md, feature branch)
and runs build → Docker verify → PR in an isolated sandbox. LLM reasoning stays
on the host; deterministic work (build, test, verify) runs inside Docker.

### Container Runtime

`echelon delivery` uses a Docker-compatible container CLI for sandbox creation.
Docker is the default, and Podman is supported by setting `harness.container_cli`
to `podman`.

Initialize a project with Podman:

```bash
ECHELON_CONTAINER_CLI=podman echelon delivery init
```

`echelon delivery init` persists the selected CLI in the project config.
New-layout workspaces use `.echelon/config.yml`. Run `echelon workspace migrate
--write` before relying on a legacy workspace configuration:

```yaml
harness:
  provider: docker
  container_cli: podman
```

On macOS, make sure the Podman machine is running first:

```bash
podman machine start
podman info
```

Future `echelon delivery run`, `echelon delivery continue`, and
`echelon delivery resume` commands read the
persisted `harness.container_cli` value. If no value is configured, Echelon uses
Docker.

### Deployment Models

**Workspace repo (recommended):** Initialize Echelon in a lightweight workspace Git repo. Specs and Echelon runtime config live at the workspace root; implementation repos live under `sources/` and are selected per spec.

```
my-project/
  .git
  .echelon/
    config.yml             ← runtime settings only; no implementation target
  sources/
    app/
      .git
      src/
  specs/
    001-feature/           ← echelon Phase A artifacts
      spec.md
      tasks.md
      constitution.md      ← published snapshot from spec-kit memory
  runs/                    ← mirrors, worktrees, and run state
```

Set the implementation repo when authoring begins:

```bash
echelon spec run "Describe the feature" --target sources/app
```

### How to read a spec folder

Start with `specs/<id>-*/ARTIFACTS.md`. Echelon generates this file deterministically, without LLM tokens, as a concise map of known spec artifacts, what each file is for, when it is updated, and which expected files are missing for the current lifecycle stage.

Refresh it manually with:

```bash
echelon spec artifacts <id>
```

### Human artifact wiki

Use `echelon wiki build` when you want one workspace-wide reading surface for
published `specs/` and `re/` artifacts. The command is deterministic and offline:
it does not invoke an LLM, install a viewer, or change canonical artifacts. It
generates a disposable, untracked Markdown vault at `.echelon/runtime/wiki/` and
prints the path to `Home.md`.

```bash
echelon wiki build    # complete rebuild
echelon wiki build --include-runs  # add local Spec and RE execution analysis
echelon wiki status   # absent, fresh, stale, or invalid; includes changed inputs
echelon wiki clean    # remove only a manifest-owned generated vault
```

The Markdown works in an ordinary viewer. Obsidian is optional but recommended
for backlinks and graph navigation; Echelon does not install or launch it.
Run analysis is excluded by default because `runs/` is local and volatile. Set
`wiki.include_run_analysis: true` to include it persistently, or use
`--include-runs`/`--no-include-runs` per build. Operational pages are labelled
local and ephemeral, and raw span ledgers are never copied into the vault.

Spec and RE runs use the same local, content-free telemetry format under each
run's `telemetry/` directory. Prompts, model responses, source content, and
artifact bodies are not recorded. Advanced local analysis is available through
the intentionally hidden commands:

```bash
echelon spec analyze runs/spec-or-squad-run
echelon spec analyze runs --format json
echelon re analyze runs/re-run
```

Spec analysis reports phase, agent, model, dispatch-kind, token, duration,
repair-loop, and repeated-blocker measures. Runs created before telemetry was
enabled remain readable, with unavailable fields identified explicitly.

The wiki reads `specs/` and `re/` from the configured local default branch,
without switching the active checkout. Phase A specs usually live on separate
canonical branches, so publish committed spec-only snapshots to that catalog
before building a complete wiki:

```bash
echelon spec publish 003  # spec-only snapshot commit on local main
echelon spec publish --all
echelon wiki build        # reads the local default-branch catalog
git push origin main      # explicit; publish never pushes
```

`publish` discovers canonical local spec branches only, copies each matching
`specs/<id>/` tree with source branch/commit provenance, and creates at most one
local default-branch commit. It retains the source branches and does not merge
implementation history, fetch, push, or delete branches. Use the full canonical
branch name instead of its numeric ID when desired, for example
`echelon spec publish 003-add-feature-opta-search`.

Build, status, and command-triggered refresh all resolve the same configured
local default branch. When another branch is active, Echelon reads the exact
default-branch commit through a temporary detached worktree and removes it when
the operation finishes; it never fetches, switches, or modifies the caller's
checkout.

After the first explicit build, successful Echelon commands automatically rebuild
the wiki only when they changed catalog inputs under `specs/` or `re/`. There is
no background watcher: manual edits and pulls make `wiki status` stale until the
next `echelon wiki build`. Disable command-triggered refresh locally with an
override in `.echelon/local.yml` (which takes precedence over
`.echelon/config.yml`):

```yaml
wiki:
  auto_refresh: false
```

**Two-repo (advanced):** A dedicated control-plane repo manages one or more target repos. Useful when build infrastructure should be separate from product code, or when managing multiple products from one place.

### Build Strategies

`echelon delivery run` accepts `--strategy` to choose the build engine used in
Phase 1:

| Strategy | Build engine | When to use |
| -------- | ------------ | ----------- |
| `default` (omit) | `echelon.build` — multi-agent squad | General use |
| `codegen` | `echelon.codegen` — SOAR CQ-ISC pipeline | Inviolable quality gates instead of agent review |

```bash
echelon delivery run 001                    # default — echelon squad build
echelon delivery run 001 --strategy codegen # SOAR pipeline build
```

Both strategies follow the same outer loop: build → Docker verify → feedback if needed → commit + PR. On retry, both strategies fix failures by editing worktree files directly rather than re-running the full pipeline.

Build strategy is independent from Phase A spec format. The default and codegen
strategies both consume the published Phase A artifacts under `specs/<id>-*/`.
See [Echelon Pipeline Matrix](docs/pipeline-matrix.md) for the supported
spec-format/build-strategy combinations.

### Review Loop (Phase 3)

After Phase 1 converges and a PR is open, the harness optionally enters a review
loop. Enable it in `.echelon/config.yml` under `harness:`:

```yaml
pr_host: github
review_loop:
  enabled: true
  poll_interval_minutes: 1
  merge_timeout_hours: 1
  max_fix_iterations: 3
```

The loop polls for blocking inline comments, invokes `echelon.review` (DEBUGGER → SENTINEL → SPEC GUARD per comment group), writes `review-fix-{n}.md` tasks to the branch, then re-enters Phase 1 with the review content injected into the build prompt.

### Harness Architecture

```
+-------------------------------+       +---------------------------+
|        HOST (LLM side)        |       |    DOCKER SANDBOX         |
|                               |       |                           |
|  StrategyCoordinator          |       |  deterministic execution  |
|    |                          |       |    - build (fallback)     |
|    ├── Phase 1: RalphController|       |    - test                 |
|    │     ├── ClaudeCliProvider |------>|    - verify               |
|    │     └── DockerProvider   |       |      (npm ci/test/build)  |
|    ├── Phase 2: VisualRalph   |       |                           |
|    │     (Playwright, optional)|       |  network: squid proxy     |
|    └── Phase 3: ReviewLoop    |       +---------------------------+
|          (gh api + echelon.review)
|
|  GitOpsManager
|    - mirror.git / state store / GC
+-------------------------------+
```

| Step | Executor |
| ---- | -------- |
| Build (Phase 1) | `claude -p` on host (or `echelon build`/`echelon codegen`) |
| Verify | Docker sandbox — always |
| Visual tests (Phase 2) | Docker sandbox — Playwright; disabled by default |
| Review skill (Phase 3) | `claude -p` on host via `echelon.review` |

## How It Works

### The 4-Phase Model

```
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: UNDERSTAND                                                     │
│                                                                         │
│   [GOLDDIGGER] ──► SCOUT ──► SYNTHESIZER ──►                            │
│   (brownfield)    (discover)  (fuse)                                    │
│                                                                         │
│   ──► SAGE ──► CARTOGRAPHER ──► SAGE ──► GATEKEEPER                     │
│      (why1)   (what)         (why2)    (assess)                         │
│                                                                         │
│   + Specialists: INVESTIGATOR, GUARDIAN, ORACLE, BENCHMARK, ADVOCAT     │
│   Output: spec.md, feasibility.md, estimates.md, priorities.md          │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: DECIDE                                                         │
│                                                                         │
│   CHECKPOINT: Internalize spec — every agent proves comprehension       │
│   Decision: PASS (continue) / KILL (stop) / DEFER (reduce scope)        │
│   STRATEGIST: Alignment analysis and advisory                           │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 3: SOLUTION                                                       │
│                                                                         │
│   ARCHITECT ──► Specialists ──► SENTINEL ──► ORCHESTRATOR               │
│   (how)                         (test)        (plan)                    │
│                                                                         │
│   Output: plan.md, data-model.md, contracts/, test-strategy.md, tasks.md│
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 4: BUILD (optional)                                               │
│                                                                         │
│   Per task: IMPLEMENTER → SPEC GUARD → CODE REVIEWER → TEST GUARDIAN    │
│   Per phase: ENGINEERING MANAGER + INTEGRATOR + TECH WRITER + VISUAL    │
│              VALIDATOR                                                  │
│   Debug: DEBUGGER (root cause analysis on non-obvious failures)         │
│   Final: VERIFICATION (100% spec coverage check)                        │
└─────────────────────────────────────────────────────────────────────────┘
```

### Autonomy Modes

Set in `.echelon/config.yml`:

```yaml
autonomy:
  mode: semi  # guided | semi | banzai
```

| Mode | Behavior |
|------|----------|
| `guided` | Checkpoint after every phase |
| `semi` | Checkpoint after Phase 1 only (default) |
| `banzai` | Full autonomous — human reviews final output |

## Agents

The active workflow is organized into control, exploration, feasibility,
solution, specialist, learning, and build layers. The maintained role count
and inventory are in the [Agent Role Catalog](docs/agent-role-catalog.md).

### Naming Convention

Each agent has a **codename** (file name, what you see in logs) and a **functional name** (what it does):

```
SCOUT (DISCOVER) — codename is SCOUT, functional name is DISCOVER
File: agents/exploration/scout.md
```

### Agent Reference

#### Control Layer (5 agents)
| Codename | Functional | Purpose |
|----------|------------|---------|
| **COMMANDER** | MANAGER | Orchestrates all phases, dispatches agents, conflict resolution |
| **CHECKPOINT** | INTERNALIZE | Ensures agents prove comprehension before building |
| **TRACKER** | INTENT-TRACKER | Watches user intent vs spec drift |
| **STRATEGIST** | STRATEGIC-ADVISOR | Alignment analysis and advisory |
| **SCOREKEEPER** | SCOREKEEPER | Tracks agent performance, enables self-healing |

#### Exploration Layer (6 agents)
| Codename | Functional | Purpose |
|----------|------------|---------|
| **SCOUT** | DISCOVER | Maps domain, glossary, boundaries |
| **GOLDDIGGER** | BROWNFIELD-EXTRACT | Drives native brownfield RE (Mode 1: full workspace reverse engineering, Mode 2: focused-domain deep dive) |
| **SYNTHESIZER** | FUSE | Fuses discovery outputs into unified knowledge base |
| **CARTOGRAPHER** | WHAT | Writes testable requirements via spec-kit |
| **SAGE** | WHY | Adversarial critic, quality gates via Understanding CLI |
| **MODELER** | MENTAL-MODEL | Maintains code graph with invariants |

#### Feasibility Layer (2 agents)
| Codename | Functional | Purpose |
|----------|------------|---------|
| **GATEKEEPER** | ASSESS | Kill gate — feasibility, RICE scoring, estimation |
| **VALIDATOR** | INTERNALIZATION-GATE | Ensures agents prove comprehension before working |

#### Solution Layer (3 agents)
| Codename | Functional | Purpose |
|----------|------------|---------|
| **ARCHITECT** | HOW | Tech stack, data model, ADRs |
| **ORCHESTRATOR** | PLAN | Tasks, critical path, dependencies |
| **SENTINEL** | TEST-ARCHITECT | Test strategy, coverage mapping, flakiness management |

#### Specialists (6 agents, summoned adaptively)
| Codename | Functional | Trigger |
|----------|------------|---------|
| **INVESTIGATOR** | SCIENTIST | Unknowns, unproven tech |
| **GUARDIAN** | SECURITY | Auth, payments, PII, compliance (always-on by default) |
| **BENCHMARK** | PERFORMANCE | High-load, scalability |
| **ADVOCATE** | UX-A11Y | Frontend, accessibility |
| **ORACLE** | DOMAIN-EXPERT | Domain-specific knowledge |
| **MAVERICK** | INNOVATE | Stagnation, need alternatives (uses AutoTRIZ) |

#### Learning Layer (8 agents, cross-cutting)
| Codename | Functional | Purpose |
|----------|------------|---------|
| **AUDITOR** | CALIBRATE | Tracks accuracy, adjusts confidence |
| **INTERNALIZER** | INTERNALIZATION-SCORING | Computes 16 deterministic metrics per agent |
| **ADAPTIVE** | EVOLVE | Detects regressions across runs |
| **REALIST** | GROUND | Reality-checks estimates with real-world data |
| **MIRROR** | REFLECT | Extracts patterns and pitfalls |
| **MONITOR** | METACOGNITION-MONITOR | "Are we still doing the right thing?" |
| **VETERAN** | GLOBAL-MEMORY | Cross-project knowledge — promotes validated patterns to ~/.specify/squad-global/ |
| **CONSOLIDATOR** | CONSOLIDATE | Transforms episodic experience into generalized schemas across projects |

#### Build Layer (14 agents, Phase 4)
| Agent | Purpose |
|-------|---------|
| **IMPLEMENTER** | Writes code following TDD |
| **SPEC GUARD** | Verifies code matches requirements |
| **SPEC FULFILLMENT AUDITOR** | Audits implementation fulfillment against canonical spec requirements |
| **IMPLEMENTATION MAPPER** | Maps implementation evidence back to spec IDs and tasks |
| **CODE REVIEWER** | Reviews quality, ADR compliance |
| **TEST GUARDIAN** | Validates test quality |
| **ENGINEERING MANAGER** | Phase gates, rework decisions, verification loop |
| **TECH WRITER** | Keeps README and Keep a Changelog release history current |
| **INTEGRATOR** | System integration checks |
| **PROGRESS TRACKER** | Effort tracking, drift detection |
| **CHANGE CONTROLLER** | Handles mid-build spec changes |
| **DEBUGGER** | Systematic root cause analysis |
| **VERIFICATION** | 100% spec coverage backpropagation check |
| **VISUAL VALIDATOR** | Screenshot-based visual verification |

## Brownfield Support

Run brownfield extraction explicitly with `echelon re run`, then publish a
validated run with `echelon re publish <run-id>`. Blocked work uses `echelon re
continue` or `echelon re resume`. Phase A does not invoke GOLDDIGGER. SCOUT
receives the immutable
published snapshot when available and otherwise performs normal scoped manual
analysis.

## Commands

Each command is available two ways: as a terminal CLI tool (no Claude session needed) and as a spec-kit skill inside a Claude Code session.

### Command architecture

All major command files (`echelon.run.md`, `echelon.bugfix.md`, `echelon.build.md`, `echelon.codegen.md`, `echelon.codegenlight.md`) are **thin wrappers** (~35–75 lines). They set the role, load `agents/control/commander.md` (the shared behavioral framework for COMMANDER-driven commands), then delegate to `workflow/definition.yaml` and `workflow/phases/` for the full workflow logic.

The workflow is split into two layers:

- **`workflow/definition.yaml`** — phase graph with routing conditions, transitions, agent assignments, convergence thresholds, and the build task-loop state machine. COMMANDER reads this before every routing decision.
- **`workflow/phases/*.md`** — per-phase spec files with context pack assembly, exact dispatch prompts, and expected outputs. Each phase node in `definition.yaml` points to its spec file via `spec_file:`.

This keeps commands readable and makes individual phases independently editable without touching the command files.

### echelon — spec authoring

| Terminal | Spec-kit skill | Purpose |
| -------- | -------------- | ------- |
| `echelon workspace init [--allow-unsafe-host-execution]` | `speckit.echelon.init` | One-time project setup — `.echelon/config.yml`, local tool-policy approval, deploy infra, git hook |
| `echelon spec run "<description>" [--mode <semi\|banzai\|guided>] [--target <source-path>]... [--input <role:path>]... [--init] [--ignore-re]` | `speckit.echelon.run` | Phase A: snapshot optional published RE and immutable product evidence, then run the squad → spec.md, plan.md, tasks.md, targets.yml, feature branch |
| `echelon re run [--re-policy <policy>] [--re-max-inner <n>] [--profile <fast\|balanced\|high>] [--reset]` | — | Start or resume the independent workspace RE lifecycle; publish a validated completed run explicitly |
| `echelon re continue [--re-max-inner <n>]` | — | Continue the active RE run without supplying a new answer |
| `echelon re resume "<answer>" [--re-max-inner <n>]` | — | Resolve a structured RE human-input block and continue |
| `echelon re publish <run-id> [--allow-partial] [--commit]` | — | Publish a validated RE run into `re/`; optionally commit only durable published RE artifacts |
| `echelon spec bugfix <id> "<desc>"` | `speckit.echelon.bugfix` | DEBUGGER + SENTINEL + SPEC GUARD → bugfix plan + tasks |
| `echelon build <id>` | `speckit.echelon.build` | Build phase (agent-driven) |
| `echelon codegen <id>` | `speckit.echelon.codegen` | Build phase via SOAR pipeline (alternative to build) |
| `echelon review <id> [--pr-url <url>]` | `speckit.echelon.review` | PR review triage — groups blocking comments, runs DEBUGGER → SENTINEL → SPEC GUARD per group, writes `review-fix-{n}.md` + tasks, signals `review_fix_queued` to harness |
| `echelon spec verify <id> [--reconcile] [--dry-run]` | `speckit.echelon.verify-spec` | Audit fulfillment; with `--reconcile`, apply deterministic task-progress bookkeeping fixes through harness helpers. Use `--reconcile --dry-run` to preview changes only |
| `echelon spec defer <id> <ID...> --reason <reason> [--dry-run]` | — | Commit an auditable owner deferral for direct tasks or canonical FR/NFR/AC/SC requirements; displays mapped tasks and requirements that remain active |
| `echelon spec plan <id> <ID...> [--dry-run]` | — | Restore matching deferred work to the planned scope, preserving the deferral ledger history |
| `echelon spec reopen <id> [from=<report>]` | `speckit.echelon.reopen` | Reopen a spec from fulfillment gaps and append harness-ready `FG-T*` tasks |
| `echelon spec change <id> "<desc>"` | `speckit.echelon.change` | Handle spec change during build |
| `echelon spec amend <id> "<desc>" [--input <role:path>]... [--dry-run]` | — | Prepare an isolated product-input amendment for an unbuilt spec |
| `echelon spec repair-traceability [--confirm]` | — | Preview or apply a safe repair that removes only contextual task references, then resumes finalization |
| `echelon cicd` | — | Retired; re-run `echelon delivery init` to auto-detect high-confidence `verify_command` |
| `echelon spec status` | `speckit.echelon.status` | Re-orient summary — run state, staging artifacts, open issues, cost, next step |
| `echelon spec publish <numeric-id>` | — | Copy the matching committed `specs/<id>/` snapshot from its unique canonical local branch to the local default branch and commit it; source branches are retained and nothing is pushed |
| `echelon spec publish <canonical-branch>` | — | Publish one exact canonical local spec branch by full name without merging implementation history |
| `echelon spec publish --all` | — | Atomically publish every unambiguous canonical local spec branch in one local default-branch commit |
| `echelon spec memory refresh <id> [--write]` | — | Mine canonical spec artifacts into MemPalace and immediately audit reconciliation; optionally persist the audit reports |
| `echelon re memory refresh` | — | Mine published RE artifacts into MemPalace and immediately audit reconciliation |
| `echelon spec evidence publish <id>` | — | Publish the canonical verification-evidence package for a landed spec |
| `echelon spec evidence memory refresh <id>` | — | Mine published spec evidence into MemPalace and immediately audit reconciliation |
| `echelon graph refresh <id> --write` | — | Build and audit the persisted artifact graph from current canonical artifacts and MemPalace receipts without mining memory |
| `echelon graph view <id> [--lens <lens>] [--no-open]` | — | Generate an offline interactive graph viewer with live audit findings |
| `echelon graph export <id> --format dot [--output <path>]` | — | Export the persisted graph as deterministic DOT without rebuilding or mining |
| `echelon spec targets <id>` | — | Read-only task ownership report: display every canonical task grouped by explicit `target=` ownership, including `UNOWNED`, `CROSS-TARGET`, and target/path mismatch diagnostics; exits nonzero when ownership is invalid |
| `echelon spec artifacts <id>` | — | Generate or refresh `specs/<id>-*/ARTIFACTS.md`, the deterministic human map of spec-folder outputs |
| `echelon wiki build` | — | Build the local, read-only human-navigation vault from canonical `specs/` and published `re/` artifacts |
| `echelon wiki status` | — | Report vault freshness and added, changed, or removed canonical inputs |
| `echelon wiki clean` | — | Safely remove only the manifest-owned generated vault under `.echelon/runtime/wiki/` |
| `echelon spec continue` | — | Run the next no-input recovery action: resume an active/interrupted run, retry recoverable failed dispatches, or advance incomplete Phase A work |
| `echelon spec resume "<answer>"` | `speckit.echelon.resume` | Provide an answer only when the squad asked for human input; after recording it, Echelon delegates back to continuation |
| `echelon spec rewind <phase-id> [--commit <sha>] [--confirm]` | — | Preview or rewind the active squad run. Phase-only selection uses the last matching ledger row; `--commit` selects an explicit historical occurrence by full or unique abbreviated commit |
| `echelon spec switch <spec-or-run-id> [--stash \| --discard --confirm]` | — | Select a checkpointed Phase A spec run while preserving or explicitly discarding outgoing dirty state |
| `echelon spec checkpoint list\|accept\|commit ...` | — | Inspect checkpoints in authoritative oldest-to-newest ledger order with UTC creation time and latest-per-phase markers, or accept/commit a named Phase A checkpoint |
| `echelon phase list` | — | List deterministic workflow phase IDs available for targeted repair/replay |
| `echelon phase run <phase-id> [--spec <id>]` | — | Run exactly one workflow phase through the normal COMMANDER/state/journal contracts, publish artifacts to the target spec directory when resolvable, then stop |
| `echelon benchmark list` / `echelon benchmark run <fixture> --variant <id> --baseline-ref <ref>` | — | Experimental EGR-063 artifact-quality benchmark runner. Variants compare baseline Phase A/build behavior against opt-in constitution, tasks, and ADR cleanse phases; each real run resets to the supplied committed Phase A baseline before and after execution |
| `echelon delivery land <id>` | — | Merge PR, delete remote branch, clean worktrees, mark spec landed; uses `targets:` to land the target repo branch and blocks on unresolved fulfillment gaps |
| `echelon delivery land <id> --allow-fulfillment-gaps` | — | Emergency override for knowingly landing despite fulfillment gaps |
| *(spec-kit only)* | `speckit.echelon.verify` | Check 100% spec coverage |
| *(spec-kit only)* | `speckit.echelon.health` | Periodic health check (drift, KB freshness) |
| *(spec-kit only)* | `speckit.echelon.investigate` | Trigger INVESTIGATOR |
| *(spec-kit only)* | `speckit.echelon.innovate` | Trigger MAVERICK |
| *(spec-kit only)* | `speckit.echelon.ground` | Trigger REALIST |
| *(spec-kit only)* | `speckit.echelon.feedback` | Post-implementation feedback |
| *(spec-kit only)* | `speckit.echelon.deploy` | Trigger deploy, check status, or rollback |

### delivery — build, verify, PR

| Terminal | Spec-kit skill | Purpose |
| -------- | -------------- | ------- |
| `echelon delivery init` | `speckit.echelon.harness-init` | One-time workspace delivery setup — provider, sandbox, config defaults |
| `echelon delivery target <id>` | — | Prepare target-scoped delivery metadata in `specs/<id>/targets.yml`, including high-confidence `verify_command` detection |
| `echelon delivery run <id>` | `speckit.echelon.harness-run <id>` | Build → Docker verify → PR (echelon squad strategy); validates persisted Phase A targets and target-owned task slices without inferring or rewriting them; prints `HARNESS HISTORY` |
| `echelon delivery run <id> --strategy codegen` | `speckit.echelon.harness-run <id> strategy=codegen` | Build → Docker verify → PR (SOAR pipeline strategy) |
| `echelon delivery continue <id>` | `speckit.echelon.harness-resume <id>` | Continue a blocked/checkpointed delivery loop when no new human answer is needed, including missing `verify_command`, Docker/Podman outage recovery, checkpoint recovery, provider reset, or repaired harness errors; prints `HARNESS HISTORY` |
| `echelon delivery resume <id> "<answer>"` | `speckit.echelon.harness-resume <id> <answer>` | Resume a blocked delivery loop by recording the human answer to a pending escalation, then continuing the loop |
| `echelon delivery status [<id>] [--strategy <strategy>]` | `speckit.echelon.harness-status [<id>]` | Show the active or selected delivery state, iterations, cost, and PR context |
| `echelon delivery checkpoint list <id>` | — | List delivery checkpoints and recovery commits for a spec |
| `echelon delivery land <id> [--continue] [--prepare-only]` | — | Merge or prepare the target feature branch, then clean up after fulfillment gates pass |
| *(spec-kit only)* | `speckit.echelon.harness-status [<id>]` | Show active loop status, iterations, token usage, PR URL |

Legacy aliases may still exist for older scripts, but current docs and operator
guidance use the `spec` and `delivery` namespaces.

## Codegen Pipeline

SOAR-backed codegen is an optional Phase B build strategy. Install it explicitly:

```bash
bash ~/echelon/scripts/install.sh --with-codegen
```

After Phase A artifacts are ready, select it with the standard delivery command:

```bash
echelon delivery run 001 --strategy codegen
```

`echelon workspace init` establishes the project’s MemPalace wing in the
committed `.echelon/config.yml`; do not change that identity casually. The
pipeline uses that memory automatically. For strategy compatibility and the
full pipeline contract, see [Echelon Pipeline Matrix](docs/pipeline-matrix.md).

## PR Review Loop

When `echelon delivery run` creates a PR and reviewers comment, the harness can
automatically triage those comments and re-run Phase 1 to address them.
`echelon review` is also available for an explicit review pass when needed.

**Flow:**

```text
Reviewer leaves comments on PR
        │
        ▼
harness Phase 3 (ReviewLoopController)
  fetches blocking comments via GitHub/GitLab API
        │
        ▼
echelon.review skill (claude -p)
  groups comments by file proximity + reviewer
  per group: DEBUGGER → root cause
             SENTINEL → failing test spec
             SPEC GUARD → scope check
  writes specs/{id}-*/review-fix-{n}.md
  writes RF{n}-T* tasks to tasks.md
  commits to feature branch
        │
        ▼
harness re-enters Phase 1
  review-fix-{n}.md content injected into build prompt
  Claude addresses reviewer feedback
        │
        ▼
verify → push → re-request review
```

**What counts as blocking:** comments containing `must`, `needs to`, `fix`, `change`, `remove`, `refactor`, etc. Nits, pure questions, and already-processed comment IDs are skipped.

## Configuration

`echelon workspace init` creates the committed `.echelon/config.yml`. Keep
machine-local overrides in `.echelon/local.yml`; use `echelon workspace doctor`
after a configuration or workspace-layout change. The installer and workspace
commands own generated configuration—do not start by copying an extension
template into your project.

Common configuration areas include:

| Section | Purpose | Example |
|---------|---------|---------|
| `analysis.max_iterations` | Squad iteration limit | `5` (range: 3-10) |
| `analysis.token_budget_k` | Token budget in thousands | `1000` (range: 100-2000) |
| `quality_gates.overall` | Minimum spec quality | `0.70` |
| `quality_gates.depth` | Minimum depth score | `0.30` (Understanding v3.6+) |
| `convergence.quality_delta_threshold` | Stop when improvement below | `0.02` |
| `harness.container_cli` | Docker-compatible sandbox CLI | `docker` (default) or `podman` |
| `specialists.guardian_mode` | GUARDIAN dispatch mode | `always_on` (default) |
| `endocrine.enabled` | Hormone-modulated motivation | `false` (default) |
| `deploy.enabled` | Enable local blue/green CD after merge | `true` (default); set `false` to skip deploy infra |

The installed extension’s configuration template is the detailed reference for
advanced settings; retain the canonical `.echelon/config.yml` path in project
documentation and automation.

## Local CD

Echelon includes built-in local continuous delivery. After `echelon delivery run`
merges a feature branch to main, it calls `deploy.sh` directly. Set
`deploy.enabled: false` in `.echelon/config.yml` to skip all deploy
infrastructure checks and the post-merge deploy step — useful for projects that
manage their own CD pipeline.

`echelon workspace init` does not require Docker to complete workspace bootstrap. If `deploy.type: http` is configured and Docker is missing or stopped, Echelon writes `deploy.enabled: false`, skips HTTP deploy provisioning with an actionable warning, and completes initialization. Install/start Docker, set `deploy.enabled: true`, and rerun `echelon workspace init` later if local HTTP deploy is needed.

**Both UI and CLI apps use blue/green deployment.** Two image slots (blue/green) are maintained. Each deploy builds to the inactive slot, health-checks it, then flips the active pointer — keeping the previous slot available for instant rollback. Everything runs in Docker to keep the dev machine clean.

The only difference between UI and CLI is how traffic is routed to the active slot:

- **UI apps (`type: http`)** — single shared Traefik at `:80` routes by path prefix: `http://localhost/{app-name}/`
- **CLI apps (`type: cli`)** — no long-lived containers; a wrapper script reads the active image tag at invocation time

### UI apps — `type: http` (blue/green via Traefik)

Two Docker containers run concurrently. On each deploy, the inactive slot is started, health-checked via `curl`, then Traefik switches traffic. All apps on a machine share one Traefik instance — adding a new app never restarts Traefik.

**Config (`.echelon/config.yml`):**

```yaml
deploy:
  type: http
  blue_port: 3000    # health-check port only (unique per app)
  green_port: 3001   # health-check port only (unique per app)
  # Convention: App1=3000/3001, App2=3100/3101, AppN=3N00/3N01
  # Live URL: http://localhost/{app-name}/  (all apps share Traefik at :80)
```

**Dockerfile (minimal Vite/React example):**

```dockerfile
FROM nginx:alpine
COPY dist/ /usr/share/nginx/html/
EXPOSE 80
```

> **SPA base path:** `echelon workspace init` automatically sets `base` (Vite), `basePath` (Next.js), or `homepage` (CRA) to `/{app-name}/` in your framework config so assets load correctly under the path prefix. This is auto-corrected even if the value is wrong or computed — no manual step needed.

**What happens on `echelon workspace init`:**
- Docker network `speckit-deploy` created (shared across all apps on this machine)
- `speckit-traefik` container started at `:80` — one per machine, started once, never recreated
- SPA framework config auto-corrected for path-prefix routing (Vite/Next.js/CRA)

**Deploy flow (automatic after merge to main):**

1. `docker build` → `{app}:candidate` (Dockerfile auto-generated if missing; `.env.local` injected as `--build-arg`)
2. Start inactive slot with Traefik labels `PathPrefix(/{app})`, expose health-check port on host
3. `curl -sf http://localhost:{blue_port|green_port}` — 5 attempts, 2s apart
4. On success: stop old slot, tag image, update state
5. On failure: stop new slot, old slot unchanged (automatic rollback)

**Rollback:** `speckit.echelon.deploy rollback` restarts the stopped inactive container and flips Traefik routing.

---

### CLI apps — `type: cli` (blue/green via tag pointer)

Two image tags (blue/green) are maintained. No Traefik, no long-lived containers. Each deploy builds a new image, optionally verifies it via `docker run --rm`, then updates the active-tag pointer. An optional wrapper script at `install_path` reads the active tag on every invocation — rollback is instant since the wrapper always checks the pointer at runtime.

**Config (`.echelon/config.yml`):**

```yaml
deploy:
  type: cli
  health_check: "myapp --version"  # command run inside container; empty = skip
  install_path: "~/.local/bin"     # where to install wrapper; empty = no wrapper
```

**Dockerfile (minimal Python CLI example):**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install -e .
ENTRYPOINT ["myapp"]
```

**What happens on `echelon workspace init`:**

- Wrapper script installed to `install_path/myapp` (if `install_path` set)

**Deploy flow (automatic after merge to main):**

1. `docker build` → `{app}:candidate` (Dockerfile auto-generated if missing; `.env.local` injected as `--build-arg`)
2. If `health_check` set: `docker run --rm {app}:candidate {health_check_cmd}` (exit 0 = healthy)
3. On success: tag image → `{app}:{inactive_slot}`, update state pointer
4. On failure: build discarded, active pointer unchanged

**Running the app:**
```bash
# Via wrapper (transparent — always runs the active version):
myapp --help

# Or directly:
docker run --rm myapp:blue --help
```

**Rollback:** `speckit.echelon.deploy rollback` flips the active pointer — the wrapper picks it up on next invocation, no reinstall needed.

---

### Deploy Commands

| Command | Purpose |
|---------|---------|
| `speckit.echelon.deploy` | Trigger a deploy manually |
| `speckit.echelon.deploy status` | Show active slot, image, ports, last deploy time |
| `speckit.echelon.deploy rollback` | Roll back to the previous slot |

Deploy state lives in two locations (kept in sync on every deploy and rollback):
- Active run `deploy-state.json` — project-local copy (`runs/.current`, `squad/.current`, with legacy fallback for older workspaces)
- `~/.speckit-deploy/{app}.json` — global registry (used for port conflict detection and CLI wrapper scripts)

## Innovation Templates

MAVERICK uses evidence-based innovation with TRIZ (ISO/TR 18686:2017):

| Template | Purpose |
|----------|---------|
| `templates/triz-40-principles.md` | All 40 TRIZ principles adapted for software |
| `templates/triz-contradiction-matrix.md` | 16 software parameters + resolution matrix |

Innovation process: Design Thinking (find right problem) → AutoTRIZ (resolve contradictions) → Lateral Thinking (break patterns)

## Fallback Mode

When spec-kit skill invocations fail at runtime, the system degrades gracefully:

- spec-kit dependencies are validated at install time via `specify extension add echelon` (declared in `extension.yml requires.skills[]`)
- If a skill invocation fails during the run, COMMANDER sets `fallback_mode=true` and continues with manual specification
- All fallback artifacts are marked with `FALLBACK STATUS: UNVALIDATED_DEPENDENCY`
- Quality gates remain active — no phase skipping allowed
- Recovery runs reconciliation checklist when skills become available

See [docs/fallback-mode.md](docs/fallback-mode.md) for details.

## Knowledge Base Management

Scripts for managing the knowledge base with concurrent write protection:

| Script | Purpose |
|--------|---------|
| `kb-write.sh` | Atomic KB writes with locking |
| `kb-lock.sh` | Manage KB file locks |
| `kb-pending-write.sh` | Queue pending KB updates |
| `kb-pending-merge.sh` | Merge pending updates safely |
| `kb-recover.sh` | Recover from failed KB operations |
| `kb-seed.sh` | Initialize KB with baseline data |
| `kb-validate-evolution.sh` | Validate evolution signal integrity |

## Quality Gates

### Phase 1: Understanding (via Understanding CLI)
| Gate | Threshold | Standard |
|------|-----------|----------|
| Overall | >= 0.70 | ISO 29148 |
| Structure | >= 0.70 | IEEE 830 |
| Testability | >= 0.70 | ISO 29148 |
| Semantic | >= 0.60 | Lucassen 2017 |
| Cognitive | >= 0.60 | Sweller 1988 |
| Readability | >= 0.50 | Flesch 1948 |
| Depth | >= 0.30 | B3 Benchmark (Understanding v3.6+) |

### Phase 4: Build (per task)
| Gate | Agent | Pass Criteria |
|------|-------|---------------|
| Spec compliance | SPEC GUARD | All requirements implemented |
| Code quality | CODE REVIEWER | No violations, ADR-compliant |
| Test quality | TEST GUARDIAN | Min tests per component |
| Documentation currency | TECH WRITER | `documentation-impact-report.md`; README/CHANGELOG updated when required |
| Verification | VERIFICATION | 100% spec coverage |

After implementation phase groups complete, the build routes through TECH WRITER
before finalization. TECH WRITER writes `documentation-impact-report.md` every
time and updates repo-root `README.md` plus Keep a Changelog-style
`CHANGELOG.md` when the work changes user-visible behavior, public APIs,
install/run instructions, configuration, operations, or significant performance
characteristics. Ralph enforces this report before publish.

## Validation

Validate the extension setup without running agents:

```bash
./scripts/bash/dry-run.sh
```

Checks: agent files, commands, config, templates, state machine flow, role separation rules.

## Directory Structure

```text
extension/
├── extension.yml        # Single merged extension manifest (covers echelon + harness skills)
├── agents/
│   ├── control/         # COMMANDER, CHECKPOINT, TRACKER, STRATEGIST, SCOREKEEPER
│   ├── exploration/     # SCOUT, GOLDDIGGER, SYNTHESIZER, CARTOGRAPHER, SAGE, MODELER
│   ├── feasibility/     # GATEKEEPER, VALIDATOR
│   ├── solution/        # ARCHITECT, ORCHESTRATOR, SENTINEL
│   ├── specialists/     # INVESTIGATOR, GUARDIAN, BENCHMARK, ADVOCATE, ORACLE, MAVERICK
│   ├── learning/        # AUDITOR, INTERNALIZER, ADAPTIVE, REALIST, MIRROR, MONITOR, VETERAN, CONSOLIDATOR
│   └── build/           # IMPLEMENTER, SPEC GUARD, CODE REVIEWER, TEST GUARDIAN, EM, INTEGRATOR,
│                        # PROGRESS TRACKER, CHANGE CONTROLLER, DEBUGGER, VERIFICATION, VISUAL VALIDATOR
├── commands/            # Thin wrappers (~35–75 lines each) — delegate to workflow/phases/
│   ├── echelon.run.md          # Squad run: reads commander.md + workflow/definition.yaml, starts at init
│   ├── echelon.bugfix.md       # Bugfix: reads commander.md + phases[], starts at bugfix-1-init
│   ├── echelon.build.md        # Build phase (agent-driven): starts at build-1-init
│   ├── echelon.codegen.md      # Build phase (SOAR pipeline): reads workflow/phases/codegen-*.md
│   ├── echelon.codegenlight.md # Build phase (SOAR, brownfield/greenfield): reads codegenlight-*.md
│   ├── echelon.*.md            # Other echelon commands (10 more)
│   ├── echelon.harness-init.md   # Delivery initialization
│   ├── echelon.harness-run.md    # Build → verify → PR loop
│   ├── echelon.harness-status.md # Loop status
│   ├── echelon.harness-resume.md # Resume blocked loop
│   ├── understanding.scan.md   # 34-metric spec quality scan
│   ├── understanding.validate.md
│   ├── understanding.energy.md
│   ├── understanding.diagram.md
│   └── understanding.batch.md
└── workflow/            # Externalized workflow logic (deployed with the extension)
    ├── definition.yaml          # Phase graph, routing rules, convergence thresholds, build state machine
    ├── journal-entry-types.yaml # Canonical registry of valid reasoning-journal entry types
    └── phases/                  # Per-phase spec files — context pack assembly, dispatch prompts, outputs
        ├── init.md / phase1-*.md / phase2-*.md / phase3-*.md / phase4-document.md
        ├── bugfix-1-init.md … bugfix-5-finalize.md
        ├── build-1-init.md … build-8-finalize.md
        ├── codegen-A-preamble.md … codegen-7-deliver.md / codegen-resume.md
        └── codegenlight-0-preflight.md … codegenlight-7-deliver.md / codegenlight-resume.md
src/
├── echelon/             # echelon CLI (entry point: echelon) — terminal-invokable skills
├── codegen/             # SOAR build pipeline CLI (entry point: codegen)
├── understanding/       # Requirements quality metrics CLI (entry point: understanding)
└── harness/             # Build harness library (invoked via: echelon delivery)
    ├── provider.py        SandboxProvider abstract interface
    ├── docker_provider.py DockerWorktreeProvider — Docker sandbox lifecycle
    ├── llm_provider.py    ClaudeCliProvider — claude -p subprocess for LLM build
    ├── build_prompt.py    BuildPromptBuilder — self-contained prompt construction
    ├── gitops.py          GitOpsManager — mirror, worktrees, push, PR creation
    ├── state.py           State store (per-strategy JSON, atomic writes)
    ├── config.py          Configuration (4-level cascade)
    ├── ralph.py           RalphController — Phase 1 outer/inner loop
    ├── visual_ralph.py    VisualRalphController — Phase 2 Playwright loop
    ├── review_loop.py     ReviewLoopController — Phase 3 PR review cycle
    ├── coordinator.py     StrategyCoordinator — fans out strategies, owns Phase 1→3 loop
    └── skills/            CLI skill entry points
network/
├── generate-squid-conf.sh   # Generate Squid proxy config for sandbox network policy
└── squid.conf.template      # Squid config template with egress allowlist
scripts/
├── install.sh               # Downloads SOAR; installs CLIs and shared Node runtimes
├── uninstall.sh             # Removes venv, SOAR, shared Node runtimes, memory, PATH entries
├── docker-gc.sh             # Garbage-collect stale sandbox containers and worktrees
├── docker-network.sh        # Create/teardown the Docker bridge network + Squid proxy
├── docker-sandbox.sh        # Lifecycle helpers for the Docker sandbox container
└── sandbox-exec.sh          # Run a command inside the active sandbox
docs/
└── fallback-mode.md
knowledge-base/
├── calibration-profile.yaml
├── estimates-log.yaml
├── patterns.yaml
└── pitfalls.yaml
templates/
├── triz-40-principles.md
├── triz-contradiction-matrix.md
└── state-schema.json
```

## Why Multiple Agents?

A single prompt can't:
- Challenge its own output (SAGE rejects what CARTOGRAPHER wrote)
- Track its own accuracy (AUDITOR logs: "estimation accuracy: 0.45")
- Verify 100% coverage backward (VERIFICATION: spec → code)
- Watch for process violations (MONITOR: "you skipped quality gates")
- Accumulate cross-project knowledge (VETERAN maintains global patterns)
- Detect brownfield structure before understanding (GOLDDIGGER → SCOUT)
- Modulate urgency based on budget pressure (endocrine system)

These require separation of concerns. That is why Echelon uses specialized
roles instead of one general-purpose agent.

## Agent Colors

Each layer has a distinct color in the Claude Code UI task list:

| Layer | Color | Agents |
|-------|-------|--------|
| Control | `blue` | COMMANDER, CHECKPOINT, SCOREKEEPER, STRATEGIST, TRACKER |
| Exploration | `green` | SCOUT, GOLDDIGGER, SYNTHESIZER, CARTOGRAPHER, SAGE, MODELER |
| Feasibility | `orange` | GATEKEEPER, VALIDATOR |
| Solution | `purple` | ARCHITECT, ORCHESTRATOR, SENTINEL |
| Specialists | `cyan` | INVESTIGATOR, GUARDIAN, BENCHMARK, ADVOCATE, ORACLE, MAVERICK |
| Build | `red` | IMPLEMENTER, SPEC GUARD, CODE REVIEWER, TEST GUARDIAN, ENGINEERING MANAGER, TECH WRITER, INTEGRATOR, PROGRESS TRACKER, CHANGE CONTROLLER, DEBUGGER, VERIFICATION, VISUAL VALIDATOR |
| Learning | `yellow` | AUDITOR, INTERNALIZER, ADAPTIVE, REALIST, MIRROR, MONITOR, VETERAN, CONSOLIDATOR |

The `understanding` extension commands also use `green` — they are invoked by SAGE during the exploration phase (WHY2/WHY3).

## Journal Architecture

All agents return structured output via an `echelon_result` YAML block at the end of their response. Agents put durable reasoning records in `echelon_result.journal_entries` and state changes in `echelon_result.state_updates`. The harness/COMMANDER runtime is the only writer to `reasoning-journal.jsonl` and `state.json`.

Agents must not use Write, Edit, Bash redirection, `cat >>`, or `tee` to mutate `reasoning-journal.jsonl` or `state.json` directly. Direct writes split ownership and make rewind/continue recovery nondeterministic.

```yaml
echelon_result:
  agent: SCOUT
  verdict: COMPLETE
  journal_entries:
    - id: RJ-NNN
      type: insight
      phase: discover
      data: { ... }
  state_updates:
    phase: synthesize
  artifacts_written:
    - staging/glossary.md
```

**Compaction safety:** Before dispatching each agent, COMMANDER writes a `last_dispatch` sentinel to `state.json` with `post_dispatch_complete: false`. After completing the Post-Dispatch Protocol (parse echelon_result → write journal → apply state updates → confirm), it flips the flag to `true`. On every bootstrap, COMMANDER checks this flag to detect and recover from mid-dispatch compaction.

## License

MIT

---
