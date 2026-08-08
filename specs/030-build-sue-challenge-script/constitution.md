<!--
SYNC IMPACT REPORT
==================
Version change: 1.0.0 (url-shortener — superseded stale artifact) → 1.0.0 (echelon-builder-fe)
Bump rationale: Re-ratification under a new project domain. The prior file at this path
belonged to an unrelated run (url-shortener, which itself had replaced a still-older
word-frequency-cli constitution); it has been replaced in full. This is the initial
ratification of the echelon Builder FE constitution (MAJOR baseline, 1.0.0).

Principles defined:
  I.   CLI + Filesystem Is the Only Integration Contract (NON-NEGOTIABLE)
  II.  Resilient Poll-and-Tolerate Observation (NON-NEGOTIABLE)
  III. Specification-Workflow Primacy
  IV.  Supervised Long-Running, Interactive Processes
  V.   Honour echelon's Trust Boundaries & Local-Operator Blast Radius (NON-NEGOTIABLE)

Added sections:
  - Domain Semantics, Defaults & Deferred Decisions
  - Development Workflow & Quality Gates
  - Governance

Removed sections: none (whole-file replacement of an unrelated prior constitution)

Templates requiring updates:
  ✅ .specify/templates/plan-template.md   — generic Constitution Check; aligns, no edit required
  ✅ .specify/templates/spec-template.md   — no mandatory section added/removed by this constitution
  ✅ .specify/templates/tasks-template.md  — tests-first / integration categories already compatible
  ✅ .specify/templates/commands/*.md      — directory absent; no agent-specific references to update

Follow-up TODOs: none. All placeholders resolved with concrete values. Genuinely open
design points are recorded as explicit Deferred Decisions, not as unresolved placeholders.
-->

# echelon Builder FE Constitution

This constitution governs the **builder-facing frontend (FE) for echelon** — the interface
through which a human *Builder* authors specifications and drives software to delivery. It is
binding on every plan, spec, task, and pull request for this project. The FE is a brownfield
client built around an existing, stable echelon CLI + filesystem contract; these principles
exist to keep it a faithful, safe client of that contract rather than a parallel reimplementation.

## Core Principles

### I. CLI + Filesystem Is the Only Integration Contract (NON-NEGOTIABLE)

The FE integrates with echelon EXCLUSIVELY by invoking the four installed CLIs (`echelon`,
`harness`, `codegen`, `understanding`) and by reading the filesystem state those CLIs write.
echelon exposes NO HTTP API, daemon, event stream, or websocket today.

- The FE MUST NOT invent, assume, or depend on a backend API. Process orchestration, output
  parsing, and file observation are designed around the CLI + filesystem contract, not around
  a hypothetical service.
- The CLIs (and COMMANDER through them) are the SOLE writers of `state.json` (atomic writes)
  and `reasoning-journal.jsonl` (append-only). The FE is a READER and a LAUNCHER; it MUST NEVER
  write, truncate, or mutate echelon's state files directly.
- Builder-initiated changes to runs, specs, branches, PRs, or deploys MUST be effected by
  invoking the appropriate CLI verb — never by editing echelon-owned state out of band.

**Rationale:** The CLI + filesystem contract is echelon's entire programmatic surface and its
COMMANDER-sole-writer invariant is what keeps run state coherent and compaction-recoverable.
A direct write or an assumed API would silently fork the source of truth and corrupt that
invariant.

### II. Resilient Poll-and-Tolerate Observation (NON-NEGOTIABLE)

Live progress is observed by POLLING or WATCHING files — `state.json`, `reasoning-journal.jsonl`,
and `staging/` artifacts — because echelon emits no push events.

- The FE MUST tolerate mid-write and partial reads: `state.json` is replaced by atomic rename
  and the journal is appended concurrently. A torn or transiently-empty read MUST degrade to
  "stale / refreshing", NEVER to a crash or to rendering corrupt state as truth.
- The FE MUST honour the `last_dispatch.post_dispatch_complete` sentinel: when it is `false`
  the run is mid-dispatch, and the FE MUST present that as an in-progress / recovering state
  rather than as a completed or inconsistent one.
- Observation MUST be pull-based and idempotent: re-reading the same files MUST converge to the
  same view; the FE MUST NOT assume it has seen every intermediate state.

**Rationale:** echelon's atomic-write + append-only + compaction-sentinel design is explicitly
a poll-and-recover model. An event-driven contract the substrate cannot emit, or naive reads
that ignore the write races, would surface false or broken state to the Builder.

### III. Specification-Workflow Primacy

The specification-authoring experience is the FE's CORE surface. The spec-quality loop —
WHAT↔WHY iteration, Understanding scores (34 metrics across 7 categories), the seven quality
gates, the per-requirement breakdown, and convergence — is the primary thing the FE renders and
the primary thing a Builder acts on.

- Scope, fidelity, and engineering effort MUST weight toward the spec experience first;
  build / verify / land (the Harness surface) are secondary and MAY be thinner.
- Quality state MUST be shown faithfully: per-category scores, gate pass/fail at both the
  overall and per-requirement level, and the trend across iterations. Gate thresholds are read
  from project configuration (`quality_gates.*`) and MUST reflect the project's actual values,
  never hard-coded defaults.
- Spec artifacts are git-versioned markdown on feature branches; the FE MUST read, render
  (GitHub-Flavoured Markdown), and diff them with branch- and lifecycle-stage awareness, so a
  Builder never sees a stale or wrong-branch artifact presented as current.

**Rationale:** The project's defining mandate is "heavy focus on specification." Mis-investing
in harness/build UI at the expense of the spec-quality loop would betray the FE's reason to exist.

### IV. Supervised Long-Running, Interactive Processes

Authoring and build commands run for minutes, accrue measurable token cost, and are sometimes
interactive (prompting for a MemPalace wing name, or for escalation answers). The FE MUST treat
every CLI invocation as a supervised, potentially-interactive background job.

- The FE MUST launch CLI work as managed background processes, stream their output to the
  Builder, and remain responsive while they run — a synchronous request/response model is
  insufficient and MUST NOT be assumed.
- The FE MUST surface cost and budget pressure (`token_usage`, `token_budget`, `cost_usd`) as
  first-class, continuously-updated information.
- Interactive prompts raised by a CLI (wing provisioning, escalation questions) MUST be routed
  back to the Builder and the answer relayed via the supported mechanism (`echelon resume`),
  never silently auto-answered or dropped.

**Rationale:** These calls are the FE's primary actuator and they block, cost money, and ask
questions. A UI that assumes fast, non-interactive calls would freeze, hide cost, or strand the
run at an unanswered prompt.

### V. Honour echelon's Trust Boundaries & Local-Operator Blast Radius (NON-NEGOTIABLE)

echelon enforces specific trust boundaries and assumes a single trusted local operator. The FE
inherits both and MUST NOT silently weaken or widen them.

- **Host ↔ sandbox:** LLM reasoning, host filesystem, and secrets stay on the host; only
  deterministic build/test/verify runs in the Docker/Podman sandbox under the egress allowlist.
  An FE that triggers builds MUST NOT route LLM calls or secrets into the sandbox.
- **Wing isolation:** MemPalace refuses cross-project writes into a foreign wing. An FE that
  exposes requirement search or mining MUST honour wing scoping and the collision guard.
- **Autonomy gate:** the authority to continue / kill / defer is the Builder's, exercised at
  autonomy-mode checkpoints (`guided` / `semi` / `banzai`) and at escalations. These human
  authority points are the FE's privileged actions and MUST be presented as such, not bypassed.
- echelon provides NO authentication or authorization layer; the terminal path runs with
  `--dangerously-skip-permissions` and can mutate branches, open PRs, and deploy. The FE
  inherits that blast radius. Any shared or hosted deployment MUST add an explicit auth boundary
  as a deliberate, documented decision — it MUST NOT be assumed to exist.

**Rationale:** These boundaries are load-bearing safety properties of echelon. The FE is the
surface where a Builder exercises repo-mutating, PR-opening, deploy-triggering authority;
honouring the existing boundaries (and refusing to silently broaden them) is what keeps that
authority safe.

## Domain Semantics, Defaults & Deferred Decisions

These are the canonical defaults for this FE; any change is an amendment to this constitution.

**Settled defaults:**

- **Persona:** The single user is the *Builder* — a human developer authoring specs and driving
  delivery — distinct from the agent squad and from the COMMANDER orchestrator.
- **Source of truth:** `runs/{id}/state.json`, `runs/{id}/reasoning-journal.jsonl`, `staging/`,
  and `specs/{id}/` (git-versioned markdown) are authoritative; the FE derives all views from them.
- **Deployment assumption:** The FE runs on the same host as the CLIs, Docker/Podman, and the
  selected LLM CLI (`ECHELON_LLM`) — it is a local / local-access tool, not a remote-only web app.
- **Concurrency model:** One Builder per run/spec at a time; there is no concurrent multi-editor
  model, consistent with COMMANDER's sole-writer invariant.
- **Rendering:** Artifacts are GitHub-Flavoured Markdown; `ARTIFACTS.md` is the cheap,
  deterministic (no-LLM) source for a per-spec overview.
- **Degradation:** When a CLI, the LLM provider, Docker, or the git host is unavailable, the FE
  degrades gracefully to read-only over existing filesystem state rather than failing hard.

**Deferred decisions (explicitly OPEN — MUST NOT be assumed settled; resolve via clarification
or an amendment before implementation depends on them):**

- Whether the FE remains single-user-local or targets a shared/hosted deployment — the latter
  requires an added auth/authorization boundary (see Principle V) and is currently OUT of scope
  until decided.
- Whether a thin host-side API / daemon should be built to mediate the CLIs and file watching,
  or whether the FE shells out and watches files directly.
- The observation transport: polling interval vs. a filesystem watcher (and the fallback when
  watch APIs are unavailable).
- The technology stack (desktop app vs. local web UI vs. TUI) and packaging/installation model.
- How far the FE surfaces secondary surfaces (Harness build/verify/PR review loop, MemPalace
  "similar requirements", calibration confidence) beyond the spec-quality core.

## Development Workflow & Quality Gates

- **Test-First (hard gate):** Development follows TDD — tests are written first, observed to
  fail, then implemented to pass (Red-Green-Refactor). No FE behaviour is claimed complete
  without a passing test exercising it.
- The torn-read / partial-state tolerance of Principle II MUST be asserted by tests: a test MUST
  demonstrate that a transiently-empty or mid-write `state.json` and an in-progress
  `post_dispatch_complete: false` sentinel each render as "in progress / refreshing", never as a
  crash or as corrupt state shown as truth.
- Any change that touches state-file reading, CLI process supervision, prompt routing, or quality
  gate / score rendering MUST update the corresponding tests and documentation in the same change.
- The FE MUST NOT acquire a code path that writes echelon-owned state files or that assumes an
  echelon HTTP API; a reviewer MUST reject such a path under Principle I.
- A Deferred Decision MUST be resolved (recorded as an amendment or a documented design choice)
  before any code path relies on a specific answer to it; implementing a silent assumption in its
  place is prohibited.

## Governance

This constitution supersedes other development practices for this project. All plans, reviews,
and pull requests MUST verify compliance with the principles above; any deviation MUST be
justified in writing and approved before merge.

Amendments require: (1) a written description of the change and its rationale, (2) a version bump
per the policy below, and (3) propagation to dependent artifacts (plan, spec, and task templates)
in the same change.

Versioning policy (semantic):
- **MAJOR** — backward-incompatible governance change or removal/redefinition of a principle.
- **MINOR** — a new principle or section, or materially expanded guidance.
- **PATCH** — clarifications, wording, or non-semantic refinements.

Compliance is reviewed at each phase gate of the squad workflow; the NON-NEGOTIABLE principles
(I, II, and V) are hard gates and MUST NOT be waived.

**Version**: 1.0.0 | **Ratified**: 2026-06-18 | **Last Amended**: 2026-06-18
