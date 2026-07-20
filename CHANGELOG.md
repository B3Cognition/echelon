# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Changed

- **Complete delivery estimates** — `estimates.md` now has one standard
  contract for Phase A specification authoring and Phase B implementation,
  showing human-only and AI-assisted ranges. AI-assisted estimates must include
  Phase A, Phase B, and total token and USD budgets with explicit pricing and
  contingency assumptions; ASSESS2 reconciles the same scenarios against the
  concrete architecture.

### Fixed

- **Phase A full spec identity** — CARTOGRAPHER can no longer replace the
  controller-bootstrapped full `NNN-slug` identity with a short number. Echelon
  now owns all Phase A branch and directory lifecycle instructions, preserves
  the full run-local and published paths at the state boundary, and ignores
  Claude runtime work directories during workspace Git migration.

- **EGR-153 Lexicon gate lifecycle** — an absent or unevaluated derived
  Lexicon artifact is now recorded as `pending`, rather than as a failed
  validation result. Only controller-run deterministic validation can write
  the Boolean `lexicon_pass` verdict, so stale agent state cannot consume the
  repair budget or route a spec through a false failure loop.

- **Dispatch-scoped result contracts** — Phase A agents now receive typed,
  per-agent verdict and `state_updates` contracts. Undeclared reporting fields
  are quarantined and journaled instead of blocking completed work, while
  reserved writes, invalid authoritative values, and missing routing data stay
  fail-closed with one result-only repair attempt. Consensus ownership is now
  explicit for WHY3, ASSESS2, and PLAN2, preventing planning metrics from
  expanding persistent squad state.

- **Lexicon requirement dependencies** — the SPEC dependency gate now follows
  `DEPENDS` entries nested under `req_metadata`, restoring missing-target,
  self-dependency, and cycle findings.

- **RE continuation orientation** — `echelon re continue` now prints a branded
  controller-owned summary before provider dispatch, including the active run,
  authoritative phase, source/domain progress, workspace-synthesis status,
  quality thresholds, effective repair budget, and artifact directory.

- **Default-branch wiki catalog** — `echelon wiki build`, `status`, and
  command-triggered refresh now read the configured local default-branch commit
  through a temporary detached worktree when another branch is active. This
  prevents published specs from disappearing from the wiki while preserving
  the caller's branch and honoring `.echelon/local.yml` overrides.
- **Delivery finalization recovery** — a documentation-only delivery slice no
  longer fails merely because every canonical task is already terminal. Ralph
  still requires exact task IDs for implementation progress, while the build
  contract now permits the report-driven README/CHANGELOG updates needed to
  close the documentation gate.
- **Spec-result recovery** — a rejected non-authoritative `state_updates` key
  now retries the originating phase instead of recommending an unsafe rewind.

- **Patch-release support** — release metadata tooling and the GitHub release
  workflow now accept the immediate next patch version as well as the next
  minor version.

### Added

- **Execution telemetry and bounded RE profiles** — New RE runs default to a
  `balanced` 5,000,000-token/180-active-minute hard budget with a 60-minute
  performance target; `fast` and `high` goals provide smaller and larger bounded
  envelopes. Provider dispatches now emit content-free, OpenTelemetry-aligned
  local spans, continuation preserves consumed budgets, and hard ceilings stop
  new dispatches without interrupting an in-flight checkpoint. The hidden
  `echelon re analyze` command reports cost, convergence, repeated findings, and
  quality debt, while `echelon wiki build --include-runs` projects those reports
  into optional local Obsidian-friendly operations pages.

- **#166 local spec catalog publication** — `echelon spec publish <id>` and
  `echelon spec publish --all` copy committed spec-only snapshots from canonical
  local Phase A branches into one local default-branch catalog commit. This
  gives the existing main-only human wiki a complete, Git-native input surface
  without making wiki generation branch-aware or merging implementation
  history. Publication is atomic, retains source branches, records branch and
  commit provenance, refuses dirty/conflicting worktrees, and never fetches,
  pushes, or deletes branches.

- **#165 workspace human artifact wiki** — `echelon wiki build`, `status`, and
  `clean` generate and manage a deterministic, offline Markdown navigation vault
  for canonical `specs/` and published `re/` artifacts. The untracked vault
  includes evidence-backed relationships, aggregate views, provenance, safe
  freshness reporting, and optional Obsidian configuration. Existing vaults
  refresh after successful Echelon commands that change canonical inputs unless
  `.echelon/local.yml` sets `wiki.auto_refresh: false`.

- **EGR-151 / #164 exclusive Phase A GitOps** — Echelon now owns Phase A
  branch lifecycle end-to-end: workspace initialization disables competing
  spec-kit Git hooks, fresh specs start as checkpoint-gated sibling branches
  from the recorded default commit, and `echelon spec switch` safely selects
  unfinished runs with clean, managed-stash, or confirmed-discard handling.
  Delivery resolves its requested spec without changing the active authoring
  checkout, landing refuses to disturb a different active spec, and terminal
  Phase A finalization commits the validated run-local and published artifact
  trees through Python-owned checkpoints. A live Phase A controller now owns a
  deterministic execution lease, so duplicate resumes fail safely and a new
  spec or switch cannot move the shared checkout underneath it.

- **First-class reverse-engineering lifecycle** — `echelon re run`, `echelon re
  continue`, and `echelon re resume` now own RE planning, bounded repair, and
  structured recovery under an independent `runs/.current-re` marker. Complete
  output publishes automatically; current `changed` runs avoid provider calls,
  and partial output never auto-publishes. Spec authoring snapshots the latest
  published generation as read-only context by default or records it as ignored
  with `--ignore-re`. Embedded GOLDDIGGER Mode 1/Mode 2 execution and the mutable
  generation guard have been removed from the Phase A workflow.

  Migration:

  ```text
  before: echelon spec run "Build dashboards" --re-policy changed --re-max-inner 10
  after:  echelon re run --re-policy changed --re-max-inner 10
          echelon spec run "Build dashboards"
  ```

- **EGR-148 / #163 product input evidence** — `echelon spec run` now accepts repeatable
  `--input requirement:<path>` and `--input reference:<path>` declarations.
  Accepted local evidence is safely snapshotted before agent dispatch, carries
  stable unit IDs through a controller-owned traceability ledger, and is
  published at `specs/<id>/inputs/`. Normative inputs now block Phase A
  publication until included requirements reach canonical target-owned tasks.
  Offline Figma bundles and reduced-fidelity design exports are supported;
  direct Figma URLs use `FIGMA_ACCESS_TOKEN` without publishing credentials.

### Fixed

- **EGR-152 P0 RE synthesis recovery** — RE specification targets now have a
  file-only result contract, so redundant agent state cannot reject completed
  workspace synthesis. `echelon re continue` recognizes the exact 3.5.1
  failure signature, validates every retained source overview, workspace
  document, and architecture-domain document, then resumes downstream gates
  without paying for another specification dispatch. Incomplete retained output
  fails closed, and terminal blockers now include the controller's precise
  validation detail.

- **EGR-145 ledger-backed Phase A rewind** — `echelon spec rewind` now accepts
  only checkpoint phases or IDs recorded in the active run's ledger. The same
  ledger powers `checkpoint list`, error output, and automatic retry recovery;
  confirmed rewind resets Git to the selected checkpoint and clears only state
  completed after that ledger entry. Early checkpoints such as `phase1-what`
  and `phase2-decide` are no longer rejected by a Phase 3 allowlist.

- **Shared Node runtime discovery** — the installer now refreshes the pinned
  Context7, CodeGraph, and PerlGraph runtimes under
  `${ECHELON_HOME:-$HOME/.echelon}/node`. Primary-workspace wrappers and harness
  evidence commands prefer a complete deployed runtime, then fall back to that
  shared installation, while delivery remains strict worktree-local. Agent
  contracts invoke stable wrappers instead of physical runtime paths, and
  uninstall removes the shared runtime tree.

- **EGR-147 / #162 authoritative implementation targets** — repeatable
  `echelon spec run --target` values are now resolved and persisted before
  Phase A dispatch, written to `targets.yml`, injected into architecture/task
  prompts, and kept separate from workspace reverse engineering. Canonical
  tasks declare `target=`, delivery validates rather than infers ownership, and
  Ralph persists each target's assigned task IDs in build state and prompts.
  Post-hoc `echelon spec target` mutation and delivery target overrides are
  retired because they cannot safely repair target-dependent artifacts.

- **EGR-143 / #161 task target inspection** — `echelon spec targets <id>`
  now prints every canonical task exactly once, grouped by its explicit
  `target=` delivery ownership. Unowned and cross-target tasks remain
  visible in explicit groups, declared-target mismatches are reported, and an
  invalid map exits nonzero only after the complete read-only report is shown.

- **EGR-141 CodeGraph candidate evidence split** — verify-spec CodeGraph
  evidence maps now emit schema v2 candidate leads instead of fields named as
  verified implementation/test evidence. The implementation-map contract now
  separates verified source/test citations from CodeGraph candidates with an
  explicit candidate disposition, the judgment prepass rejects legacy v1 maps,
  and the verified-ledger version was bumped to avoid reusing rows from the old
  evidence semantics.

- **EGR-115 / #140 fulfillment refresh ownership** — scoped fulfillment refresh
  fallback now preserves the authoritative resolved `spec_dir` when it must
  rerun full verification, avoiding a return to spec discovery in workspace
  delivery. Full fulfillment refresh can also assemble, validate, stamp, and
  ledger a report directly from existing deterministic verify artifacts when
  the judgment prepass has no fallback rows and every row is a no-gap
  mechanical judgment, bypassing another LLM provider turn.

- **Delivery summary stale provider-limit state** — repeated-failure
  escalations now clear stale provider session-limit fields before writing Ralph
  state, and delivery summaries classify a strategy as provider-limited only
  when both the build status and termination reason say `provider_session_limit`.

- **EGR-136 / #160 GOLDDIGGER nested result recovery** — Mode 1 discovery now
  detects when a nested `re-extract-*` `echelon_result` is forwarded as the
  outer GOLDDIGGER result, performs the bounded recovery prompt for the required
  outer `golddigger_status`, and then applies normal allowlist validation.

- **EGR-137 verified fulfillment ledger reuse** — full fulfillment refreshes now
  write a Python-owned per-requirement ledger with evidence fingerprints.
  Scoped delivery refreshes reuse unchanged ledger rows, recheck unresolved or
  invalidated rows only, and can restamp scoped evidence when the commit changes
  but row inputs do not. Ralph records and prints reused, rechecked,
  invalidated, and unresolved ledger counts, and the delivery summary surfaces
  the same counts.

- **EGR-139 semantic-review recovery** — invalid semantic-audit payloads now
  receive bounded controller-directed retries with the exact validation failure
  in the next validator prompt. Strict owned-domain `path:line` evidence remains
  required, and a repeated invalid audit still blocks only at the configured
  validation limit.

- **EGR-140 quality-debt budget recovery** — a genuinely higher
  `--re-max-inner` now re-measures and reactivates only the unresolved
  source-local debt it can afford to continue. It preserves previously consumed
  counters, leaves passed sources untouched, and carries semantic debt forward
  rather than treating coverage alone as a pass.

- **EGR-138 RE target artifact containment** — source-domain dispatches now
  retain only their canonical `spec.md`. The controller clears backup,
  temporary, alternate, and scratch siblings before and after each agent call,
  records cleanup in run state, and continues through the existing independent
  quality gate. This keeps failed repair attempts from polluting staged RE
  output without allowing a false `DONE` to advance the target.

- **RE depth enforcement now validates legacy output before it can drain the
  queue** — interrupted runs created before target-level quality enforcement now
  receive a one-time deterministic scan on resume. Every shallow, missing, or
  invalid staged domain is re-queued before another agent dispatch, rather than
  being discovered only by the final workspace-wide gate. RE-SPECIFIER must run
  the new deterministic target checker before returning `DONE`, so an existing
  citation path with an out-of-range line number cannot be self-certified.

- **Legacy RE repair snapshots now migrate on every resume** — older runs may
  have captured Finder `.DS_Store` metadata before it was excluded, and may
  predate the controller-owned architecture map and domain catalog. Each
  recovery now normalizes that historical baseline and admits only those two
  controller-owned files. Any real non-target artifact change remains a
  blocking error.

- **RE recovery now wins over every outer continuation state** — `echelon spec
  continue` checks the nested controller before classifying a run as blocked,
  running, or completed. This prevents a prior `spec resume` from advancing to
  constitution or WHAT while RE remains blocked; it returns safely to
  phase1-discover instead.

- **RE recovery no longer trips the outer discovery cap** — a blocked
  GOLDDIGGER controller is phase1-discover pre-dispatch work, not a SCOUT
  attempt. `echelon spec continue` now resets only that synthetic count while
  RE has a saved blocked state, allowing the controller to resume, publish, and
  continue the normal squad flow. Genuine SCOUT failures retain their cap.

- **RE repair snapshot false blocks on resume** — provider-owned root result
  captures such as `re/echelon_result.json`, plus Finder `.DS_Store` metadata,
  are now excluded from repair-output comparison. Resuming an older run now
  adds the controller-owned architecture catalog to its active snapshot without
  masking any other changed output; nested result captures and all non-target
  artifact changes remain blocking errors.

- **RE architecture composition catalog** — every workspace RE generation now
  publishes a deterministic architecture map and dependency-ordered domain
  catalog. Stable source-owned domain IDs and cache/repair boundaries remain
  unchanged; the new view classifies domains into layers, derives relative
  import dependencies, marks cycles, and groups domains into migration waves.
  Source-domain specs receive their controller-owned layer, prerequisites, and
  wave in the specification prompt, while publication rejects a generation
  without the catalog.

- **RE adaptive quality contract and repair loop** — full-depth domain specs are
  now accepted only when they meet size-derived scenario, functional
  requirement, and non-functional requirement minima. Every scenario requires
  a source-evidenced Given/When/Then acceptance case; every FR and NFR requires
  owned-domain source evidence. RE-VALIDATOR now audits every refreshed domain
  with an explicit `PASS` or source-evidenced `REPAIR` result; the controller
  sends only repair domains back to RE-SPECIFIER and re-audits them before the
  run can proceed. Publication requires a passed current semantic review.

- **RE contract freshness and capacity partitioning** — published source
  manifests record the RE quality-contract version, so changed-only runs do
  not reuse artifacts accepted under an older contract. Domain discovery now
  refines oversized code-bearing component roots before deep-spec quality is
  calculated, while retaining roots with direct source files to avoid dropping
  or overlapping ownership.

- **RE logical domain recovery** — a repository with one root build manifest is
  no longer collapsed into one whole-repository spec when it contains multiple
  substantive code areas. The deterministic partitioner now creates bounded
  logical domains, includes GraphQL sources, excludes mock/test/documentation
  roots from logical discovery, and keeps explicit multi-package workspaces at
  their existing component boundaries. Interrupted legacy runs carry a
  partition revision: before resuming specification they replace obsolete
  staged specs and queue only the newly required domains, while current runs
  retain their active manifest unchanged.

- **RE first-pass domain acceptance** — a source-domain spec is now checked by
  the deterministic deep-spec gate immediately after its agent returns
  `DONE`. A failing target stays at the head of the queue, receives its own
  exact gate report on the next dispatch, and is bounded independently before
  the controller moves to another domain. The workspace-wide gate remains the
  final consistency check rather than the first time invalid evidence is found.

- **RE repair convergence and recovery** — a completed repair pass that still
  has failing specs now starts a fresh bounded repair pass instead of spinning
  with an empty target list. A resumed run changes from blocked to in-progress
  before dispatch. Extraction leases now reclaim a lock only when its owner is
  demonstrably a dead process on the same host, preventing an interrupted run
  from blocking all future RE work while preserving live and remote owners.

- **RE source-evidence contract alignment** — the deep-spec gate now accepts
  either source-root or owned-domain-root-relative backticked `path:line`
  evidence, always resolving it within the declared domain. The specifier and
  controller explicitly prohibit Markdown-link citations, which the gate
  cannot validate as source evidence.

- **RE repair transaction completion** — a missing, controller-authorized
  domain spec can now be created during deep-spec repair without being
  mistaken for an unauthorized output. The controller prepares the target file
  before dispatch for read-then-edit providers, while the repair snapshot
  ignores root-level `*_RESULT.yaml` agent result captures. Nested captures
  and every other non-target output remain protected.

- **Reverse-engineering hidden-directory exclusion** — workspace/domain
  discovery, deterministic analysis, CodeGraph artifacts, fingerprints, and
  RE agent scope now exclude all hidden directories such as `.git`, `.github`,
  `.claude`, and `.npm`. This prevents repository metadata from becoming RE
  domains or source evidence.

### Added

- **Manifest-bound RE domain coverage** — active workspace RE now derives a
  controller-owned domain manifest for every refreshed source and dispatches
  one deep specification target per required component domain. The quality gate
  rejects missing or unexpected domain specs and validates every cited
  source-relative path and line against the target's owned root. Workspace
  synthesis runs only after all required domain specs pass; repair is limited
  to the failed domain target.

- **Harness-owned RE deep-spec repair loop** — the active workspace Mode 1
  controller owns RE phase transitions and retries; a blocked Phase A run
  resumes through `echelon spec continue`. A deterministic staged-spec gate
  runs before verification and after each bounded repair, reports exact
  missing sections and source-evidence counts, blocks repair writes outside
  listed source specs, and shares the same validation with manual publication.
  Extraction has its own workspace lease; publication retains its independent
  generation-pinned transaction guard.

- **EGR-116 / #142 prompt tool contract scanner closure** — prompt-contract
  scanning now covers every `extension/commands/echelon.*.md` wrapper instead
  of a hand-picked subset, and command-wrapper runtime discovery checks apply
  uniformly across that namespace. The legacy `speckit.echelon.status` wrapper
  now delegates to `echelon spec status` instead of model-reading `state.json`
  and scanning spec artifacts. The active prompt audit currently covers 188
  prompt files with zero findings. The same closure pass also repairs a
  GOLDDIGGER ALWAYS/NEVER pairing violation caught by the broader prompt
  reference suite.

- **EGR-049 provider session-limit recovery** — provider session-limit blocks now
  use `termination_reason=provider_session_limit` instead of flattening into
  ordinary `build_incomplete` state. Legacy blocked states with
  `build_status=provider_session_limit` are normalized on resume/continue,
  avoid git recovery/cherry-pick, and return a nonzero CLI status after
  re-blocking so operators can distinguish “wait for provider reset” from a
  failed recovery.

- **CodeGraph runtime bridge packaging** — delivery worktree runtime-extension
  sync now keeps the executable CodeGraph Node bridge and locked runtime
  dependencies while still excluding `scripts/node/context7`, so CodeGraph
  evidence generation can run from worktrees without copying unrelated Node
  tooling. The CodeGraph integration contract now asserts the pinned
  `@colbymchenry/codegraph` runtime/adapter path instead of stale vendored
  payload metadata, the evidence writer now uses the installed bridge instead
  of probing a global `codegraph` CLI, and CI now carries Node 24 plus a
  scheduled upstream-latest compatibility smoke test and pinned-runtime
  integration script.

- **Workspace RE publication** - reverse engineering now publishes the latest
  complete generation under tracked `re/sources/<id>/` and `re/workspace/`
  with an index-last atomic transaction, source fingerprints/profile hashes,
  direct unchanged-run reuse, empty/unavailable/removal lifecycle handling,
  single-writer locking, and pinned-generation guards. Added `echelon re
  publish <run-id> [--allow-partial] [--commit]`; publication never pushes and
  only `--commit` creates a local durable-RE commit.

- **Workspace source sync** — added `echelon workspace sources sync [--write]`
  to reconcile `.echelon/config.yml` source entries from canonical
  `sources/*` child repositories while preserving explicitly configured
  external roots.
- **EGR-128 / #151 delivery status UX** — added `echelon delivery status [spec_id]`
  with `--strategy` and `--json` so Phase B has a canonical status sibling to
  `echelon spec status`, summarizing Ralph delivery state, checkpoint/salvage
  facts, spec delivery history, and the next canonical command.
- **EGR-123 / #148 source-scoped RE planning** - Phase A `echelon spec run`
  accepts `--target`/`--target-source` and `--re-policy`, fingerprints workspace
  source roots, and skips GOLDDIGGER Mode 1 when the published source context is
  current. `.echelon/cache/re` is migration input only; active freshness and
  reuse authority is `re/index.json`. Existing full-depth defaults and RE
  selection policies are unchanged.
- **EGR-114 / #139 checkpoint namespaces** — added explicit
  `echelon spec checkpoint list|accept|commit` and
  `echelon delivery checkpoint list <spec_id>` commands so Phase A artifact
  checkpoints and delivery recovery checkpoints are discoverable in their own
  lifecycle namespaces. The ambiguous legacy top-level `echelon checkpoint`
  command was removed instead of retained as an alias.
- **EGR-102 / #126 stack detection** — added `echelon stack detect` for
  deterministic source-tree and RE-artifact stack evidence, YAML/JSON/text
  reports under `runs/stack-detect/**`, conservative current-vs-modernization
  recommendations, declarative stack detection hints, and read-only
  `echelon stack preflight --from-detect`.
- **EGR-101 / #113 stack preflight** — added `echelon stack list` and
  `echelon stack preflight` so operators can discover bundled/project stacks
  and verify declared commands, registry requirements, and optional gated tool
  probes before relying on Playbook/MSA/Stark stack tooling.
- **EGR-097 / #109 OpenCode and Copilot AI CLI backends** — OpenCode and
  GitHub Copilot CLI now have first-class `AICodingCliProvider` backends with
  provider-specific JSON output parsing and permission flag mapping, replacing
  the generic `PlainCliBackend` path for supported providers.
- **EGR-096 / #108 Codex AI CLI backend** — Codex is now a first-class
  `AICodingCliProvider` backend selected through `harness.llm.cli`, while
  Docker remains the harness sandbox provider. Squad agents, the review loop,
  and direct skill dispatch now route through concrete AI CLI backends instead
  of local provider-specific command branches.
- **EGR-063 benchmark scoring persistence** — artifact-quality benchmark
  variants now run Phase A spec authoring and delivery in `banzai` mode,
  persist collected squad/build metrics to `runs/benchmarks/**/summary.json`,
  and expose `echelon benchmark show` to print saved scores without rerunning.
- **EGR-063 benchmark baseline snapshots** — `echelon benchmark run` no
  longer requires `--baseline-ref`; when omitted it commits the current
  workspace as an Echelon-attributed benchmark baseline snapshot before
  running reset-wrapped variants.
- **EGR-063 / #85 artifact-quality benchmark** — added an experimental
  artifact-quality benchmark path. `echelon benchmark` can compare baseline
  builds against opt-in constitution, tasks, and ADR cleanse variants;
  experimental `phase-exp-*` workflow nodes are manually runnable through
  `echelon phase run` and are not part of the default workflow.
- **EGR-085 / #116 spec-scoped checkpoints and rewind** - added spec-scoped
  Phase A checkpoint metadata, `echelon checkpoint` commands, branch-level
  rewind with backup refs, manual checkpoint UX, and mandatory Echelon commit
  attribution trailers for generated commits.
- **EGR-080 / #97 TECH WRITER documentation gate** — added a build-phase TECH
  WRITER agent plus a deterministic Ralph gate so completed Echelon
  implementation work records documentation impact and updates `README.md` and
  Keep a Changelog-style `CHANGELOG.md` when user-facing, API, setup,
  configuration, operational, or significant performance behavior changes.
- **EGR-079 / #96 delivery command namespace** — added `echelon delivery
  init/run/resume/land` as the canonical Phase B command family, kept
  `harness` and top-level `land` as compatibility aliases, and made
  `echelon help` a first-class command.
- **EGR-073 / #90 Workspace Contract v1** — added canonical committed
  `.echelon/config.yml` workspace configuration, ignored `.echelon/local.yml`
  runtime overrides, workspace doctor/migration commands, source-root-aware
  discovery, and canonical-first init/harness guidance.
- **EGR-053 / #76 single-phase repair/replay** — added `echelon phase list` and
  `echelon phase run <phase-id> [--spec <id>]` so operators can replay one
  workflow phase through normal squad state, journal, artifact, and constitution
  contracts without advancing the whole graph.

### Changed

- **EGR-117 / #141 delivery runtime surface closure** — delivery worktrees no
  longer expose orphaned `codegen-*`/`codegenlight-*` workflow phase contracts
  when the delivery command surface is limited to build and verify-spec. Direct
  and workspace-target runtime sync now have real installed-extension-tree
  invariants proving the copied runtime contains only delivery-safe commands,
  build agents, bash helpers, templates, workflow phases, and required
  CodeGraph runtime support.
- **EGR-135 / #159 verify-spec cache invalidation** — full verify-spec cache
  keys now include measured `test-results/**/*.json` artifacts, so delivery
  refreshes fulfillment evidence after runtime test-result JSON changes instead
  of reusing stale fulfillment reports.
- **EGR-118 / #144 source-root containment** — delivery containment now treats
  generic command transcript blocks (`Shell`, `Command`, `Run`) and subagent
  transcript blocks (`Agent`, `Task`, `Subagent`) as filesystem-relevant tool
  output when matching forbidden sibling source roots, and the prompt plus
  `delivery-containment-policy.json` now explicitly forbid delegating forbidden
  source-root inspection to subagents.
- **EGR-116 / #142 prompt tool contract scanner** — harness-internal
  discovery detection now flags scan/browse/consult/study/parse/view/show/
  display/print/dump phrasing for `src/harness/...` in addition to
  read/open/review/inspect style prompts. The harness-internal target list is
  now a named scanner category instead of an inline regex fragment, and the
  harness-internal discovery verb list is named the same way. Build prompt
  artifact-discovery detection now also covers `progress-report.md` and
  `run-history.json`, keeping those Ralph/spec-owned lifecycle facts in the
  Python-owned context boundary, and rejects soft inspect/open/review/look-at/
  parse style discovery of Ralph-owned spec lifecycle artifacts. The lifecycle
  artifact target and verb lists are now named scanner categories instead of
  inline regex fragments. Verify-spec spec-directory and latest-run discovery
  now use named target and verb categories for `specs/` and `runs/` discovery.
  Delivery command runtime discovery now uses named target and verb categories
  for `agents/control/commander.md` and `workflow/definition.yaml`. Build
  workflow-definition routing discovery now uses named target and verb categories
  for `workflow/definition.yaml` as well. Delivery command runtime discovery
  also blocks soft check/review/examine/look-at/view/show/display/print/dump
  phrasing, list/search-reader phrasing, direct grep/rg search-command
  phrasing, and shell-reader phrasing such as
  cat/sed/less/more/tail/head, plus locator phrasing such as find/glob, for
  `agents/control/commander.md` and
  `workflow/definition.yaml`.
  Build prompt
  git-state discovery now also blocks `git diff`,
  `git branch`, `git show`, `git ls-files`, `git ls-tree`, `git cat-file`, and
  `git grep` prompts so agents consume Ralph-owned git facts instead of
  rediscovering repository state. The git-state command and verb lists are now
  named scanner categories instead of inline regex fragments, and negative
  discovery-boundary verbs are named the same way, reducing future
  one-command-at-a-time drift.
- **EGR-117 / #141 delivery runtime surface** — direct and workspace-target
  delivery runtime sync now excludes Phase A `config/` material such as
  belief registers, top-level config template/default files, and extension
  manifest/packaging metadata from target-visible worktrees. Host-source
  containment now also blocks relative nested reads under Echelon implementation
  package roots such as `src/codegen/...`, unless that file exists inside the
  target worktree, and a legitimate worktree path on the same transcript line no
  longer masks a relative host-source marker. View-style transcript labels such
  as `View`, `Show`, `Display`, `Print`, `Dump`, and `Inspect` now count as file
  access for containment, as do code-execution labels such as `Python`, `Node`,
  `JS`, and `JavaScript`. Direct shell-reader transcript lines using `sed`,
  `head`, `tail`, `less`, or `more` are also recognized, along with direct
  code-execution commands such as `python`, `node`, `deno`, `ruby`, and `perl`.
  File-inspection commands such as `awk`, `nl`, `wc`, `file`, and `stat` are
  now included as well. File-transfer commands such as `cp`, `mv`, `rsync`, and
  `ditto` are now included too. Archive/export commands such as `tar`, `zip`,
  `unzip`, `gzip`, and `gunzip` are now included as well. Diagnostic inspection
  commands such as `strings`, `hexdump`, `xxd`, `od`, `cmp`, and `diff` are now
  included too. VCS inspection commands such as `git` and `gh` are now included
  as well. Network transfer commands such as `curl`, `wget`, `http`, and
  `https` are now included too. Structured-data processors such as `jq`, `yq`,
  `dasel`, and `xmllint` are now included as well. Direct editor/viewer
  commands such as `open`, `vim`, `vi`, `nano`, `emacs`, and `code` are now
  included too. Shell writer/metadata commands such as `tee`, `touch`, `mkdir`,
  `rm`, `chmod`, `ln`, `install`, `truncate`, `dd`, and `patch` are now
  included as well. Shell execution/source commands such as `source`, `bash`,
  `sh`, `zsh`, `dash`, `ksh`, `fish`, `env`, and `xargs` are now included too.
  Path/directory inspection commands such as `fd`, `locate`, `tree`, `du`,
  `readlink`, `realpath`, `dirname`, and `basename` are now included as well.
  Test/build runner commands such as `pytest`, `tox`, `nox`, `coverage`,
  `ruff`, `mypy`, `eslint`, `tsc`, `npm`, `pnpm`, `yarn`, `bun`, `make`,
  `just`, `task`, `go`, `cargo`, `swift`, `xcodebuild`, `gradle`, and `mvn`
  are now included too. The transcript command matcher is now built from
  named filesystem-access command categories instead of one opaque regex list,
  so future containment changes can harden categories rather than repeatedly
  editing regex archaeology. LLM build and feedback runners now also expand
  `delivery-containment-policy.json` into provider-facing
  `ECHELON_ALLOWED_ROOTS_JSON`, `ECHELON_FORBIDDEN_ROOTS_JSON`, and
  `ECHELON_FORBIDDEN_ROOT_ALIASES_JSON` environment variables, so provider
  backends can consume deterministic root boundaries without parsing Echelon
  internals. The same normalized containment roots are now attached to
  `CliRunRequest.metadata["containment"]`, giving provider implementations a
  typed API surface for enforcement instead of requiring env parsing. The
  provider facade now rejects LLM prompt/agent invocations whose cwd is under a
  forbidden root or outside declared allowed roots before any concrete CLI
  backend starts, and malformed containment root JSON now fails closed instead
  of silently disabling provider containment. Malformed
  `delivery-containment-policy.json` files now also stop build/feedback runner
  execution before any LLM provider is launched. Missing explicit containment
  policy files now fail closed as well instead of starting the LLM without the
  promised provider boundary. Empty containment policies that produce no
  allowed or forbidden roots now fail closed too. Policies whose allowed roots
  do not contain the build worktree, or whose forbidden roots contain it, now
  fail before any provider prompt starts.
- **EGR-118 / #144 declared context roots** — targeted delivery containment
  now exempts state-declared `allowed_context_roots` from forbidden sibling
  source roots, resolves workspace-relative context roots, exposes them as
  read-only build-prompt inputs, and records them under `allowed_roots.context`
  in `delivery-containment-policy.json`.
- **EGR-129 / #152 legacy harness worktree recovery** — legacy
  `harness/<spec>/<strategy>/iter-N` worktree creation now removes stale
  registered harness worktrees under `runs/` and retries `git worktree add`,
  matching the existing feature-branch cleanup behavior. Later legacy
  iterations now also branch from the prior iteration branch when present
  instead of resetting to the default branch.
- **EGR-132 / #155 no-answer delivery recovery guidance** — no-progress
  escalations now put `echelon delivery continue <spec_id>` first when no
  answer is required, while preserving `delivery resume <spec_id> "<answer>"`
  for clarification-bearing recovery.
- **EGR-130 / #153 fulfillment summary validation** — verify-spec fulfillment
  artifact validation now fails when explicit summary/status counts disagree
  with the parsed per-requirement verdict rows, and reports the exact mismatch
  in CLI output and verify-spec state.
- **EGR-134 / #157 CodeGraph degraded evidence quality** — degraded
  verify-spec CodeGraph runs now write a deterministic `codegraph-summary.json`
  with `structural_evidence=degraded` and `manual_fallback_required`, and stamp
  the same evidence-quality metadata into verify-spec state.
- **EGR-133 / #156 lint evidence boundaries** — VERIFICATION now separates
  `full-repo lint`, `scoped lint`, and `new-file lint` evidence, and is
  forbidden from claiming global lint cleanliness unless the configured
  full-repo lint command passed in the same verification pass.
- **EGR-131 / #154 verify-spec artifact write containment** — fulfillment
  refresh now rejects provider transcripts that write/copy mapping or
  implementation-map artifacts outside the Python-owned verify run, spec, or
  worktree roots.
- **EGR-119 / #143 verify-spec init preflight** — `python -m harness
  init-verify-spec-run` now rejects missing `project_root` or `spec_dir`
  before creating run state, returning a clean input error instead of letting
  later verify phases fail against fabricated paths; `spec_dir` must contain
  `spec.md`, and unsupported `--scope` values are rejected instead of silently
  falling back to `full`; scoped runs now require at least one scoped
  requirement ID, and full runs reject scoped ID or base full-verify commit
  arguments; explicit timestamps and spec IDs are validated as path-safe labels
  before run directories are created; `runs/.current` pointers are also
  validated before verify init follows them, and current-run paths must resolve
  under the canonical `runs/` directory. Stale `.current` pointers now fail
  fast instead of falling back to unrelated timestamped verify runs, and empty
  `.current` pointers are reported as corrupted run state. Existing verify-run
  paths must resolve under the canonical `runs/` directory before state is
  written.
- **Workspace source discovery** — configured orchestration workspaces with
  `sources: []` now still auto-discover child projects under the canonical
  `sources/` directory. Empty configured workspaces without a `sources/`
  directory remain planning-only.
- **EGR-119 / #143 verify-spec state ownership** — verify-spec phase commands
  that stamp run state now fail when the init-created `state.json` is missing
  instead of silently creating a replacement file in the wrong run directory;
  Stage 6 reconciliation commands now apply the same rule when a state path is
  supplied, before mutating `tasks.md` or writing reconciliation artifacts.
  Stage 5 judgment/report commands also require that state before writing
  prepass, fallback, or assembled fulfillment artifacts, and fulfillment artifact
  row-set validation checks state before importing or validating report inputs.
  CodeGraph evidence-map generation now applies the same state-before-write rule
  on both normal and degraded paths. Stage 4 mapping instructions now forbid
  broad source exploration and bound manual inspection to
  `summary.fallback_requirement_ids` plus cited contradictory high/medium
  evidence.
- **EGR-118 / #144 containment policy** — `delivery-containment-policy.json`
  now records workspace-relative forbidden source-root aliases alongside
  absolute sibling roots, sharing the same alias logic used by Ralph's transcript
  scanner so provider-side enforcement can consume the deterministic boundary
  without rediscovering paths. Ralph's transcript scanner now also treats
  Claude-style `LS`, `BashOutput`, `NotebookEdit`, and `NotebookWrite` tool
  lines as filesystem access for source-root containment, and blocks
  dot-relative sibling paths such as `./sources/<sibling>`.
- **EGR-115 / #140 direct fulfillment refresh** — direct verify-spec fulfillment
  refresh prompts now embed the copied verify-spec phase contracts and an
  explicit invocation guard, so the LLM does not need to search `.claude/skills`,
  `SKILL.md`, workflow phase files, or workflow definitions before executing the
  Python-owned verify-spec commands.
- **EGR-116 / #142 build phase routing** — build phase prompts now reject and
  avoid quality-gate routing instructions that tell delivery agents to follow
  `workflow/definition.yaml`; agents use Ralph-provided gate order and the
  current phase contract instead. Prompt-contract scanning now also rejects
  softer harness-script/function discovery phrasing such as "check the harness
  verify script" and "inspect harness functions".
- **EGR-117 / #141 delivery runtime surface** — delivery worktrees and
  workspace-target harness roots no longer copy raw `agents/control` prompts
  such as `commander.md`; generated Claude delivery skill wrappers also strip
  obsolete bootstrap prose that tells agents to read
  `agents/control/commander.md` or `workflow/definition.yaml`. Delivery runtime
  workflow phase sync also excludes `bugfix-*` phase contracts, keeping the
  target-visible phase set aligned to build, verify-spec, and codegen delivery
  dispatch only. Node helper source under `scripts/node` is no longer copied
  into delivery worktrees; Ralph still syncs the vendored CodeGraph
  `node_modules` runtime deps explicitly. Runtime template sync is now
  allowlisted to delivery-safe task/review/fulfillment fragments and the
  build-finalize schema consolidation template instead of copying all Phase A
  planning templates.
- **EGR-116 / #142 prompt tool contracts** — static prompt scanning now treats
  shell file-reader commands such as `cat`, `sed`, `less`, `tail`, and `head`
  against `src/harness/*`, `ralph.py`, or fulfillment internals as harness
  internal discovery instructions. The legacy harness-run command wrapper now
  blocks when Python did not provide a resolved `spec_dir` instead of telling
  the model to locate or glob `specs/{spec_id}-*/`. Manual specialist command
  wrappers for INNOVATE and GROUND now also require `state.json.spec_dir` and
  fail fast instead of rediscovering spec directories. RE single-phase command
  wrappers now carry explicit phase routing metadata and no longer tell agents
  to read `agents/control/commander.md` or `workflow/definition.yaml`; the
  multi-phase `re-extract`, `re-plan-all`, and `re-retarget` commands now carry
  their phase sequences directly for the same reason, and `reopen` now points
  directly at its single apply-gaps phase. The diagnostic `bugfix` command now
  also carries its phase sequence directly.
- **EGR-062 / #84 verify-spec provider-session UX** — fulfillment refresh
  provider-limit reasons now extract the concise session-limit/reset line from
  provider output instead of surfacing the full LLM transcript in the blocked
  reason.
- **EGR-127 CLI help contract UX** — Typer now declares documented
  arguments/options across the visible command tree instead of leaving
  workspace, phase, benchmark, stack, spec checkpoint/target/artifacts, delivery
  resume, and top-level skill aliases as opaque legacy passthrough help pages.
  Root `echelon --help` now hides compatibility aliases so the canonical
  workspace/spec/delivery surface is not buried.
- Operator-facing hints, recovery banners, prompts, README, and setup docs now
  consistently recommend canonical `echelon workspace ...`,
  `echelon spec ...`, and `echelon delivery ...` commands instead of legacy
  top-level or `harness` aliases.
- Nested CLI help now matches the canonical command surface: `echelon spec
  --help` lists current Phase A source-target/cache options and `spec target
  --init`, while `echelon delivery land --help` exposes the supported land
  flags instead of only `--help`.
- **EGR-124 / #138 result repair** — squad agent dispatch now performs one
  no-edit repair invocation after a clean provider exit when the final
  `echelon_result` control payload is missing or schema-invalid. Timeout and
  nonzero exits remain blocking, and repaired payloads still pass through the
  existing schema validator before state can advance.
- **EGR-117 / #141 runtime surface** — delivery runtime extension sync now
  filters `workflow/phases` to delivery-safe contracts, keeping build,
  verify-spec, bugfix, codegen, and appendices while excluding Phase A,
  standalone reverse-engineering, and experimental artifact-quality phase docs
  from target-visible worktrees. Copied `workflow/definition.yaml` is also
  pruned to delivery-safe sections and phase nodes. Delivery runtime copies now
  also exclude Phase A learning, journal, and meta-control shell helpers such
  as `kb-*.sh`, `journal-append.sh`, `phase-timing.sh`, `state-backup.sh`, and
  `validate-journal-entry.sh`. Raw runtime agent prompts are now limited to
  `agents/control` and `agents/build`; Phase A, RE, learning, feasibility, and
  specialist agent prompt directories are not copied into delivery worktrees.
  Top-level `scripts/bash` files are allowlisted to delivery-used helpers only,
  and Phase A stack playbooks under `stacks/` are excluded. Workflow phase
  appendices are now filtered by the same delivery-safe filename policy as
  phase contracts instead of exposing the entire `appendices/` directory.
- **EGR-118 / #144 source-root containment** — Ralph now writes a
  machine-readable `delivery-containment-policy.json` beside harness state for
  build prompts. The policy records implementation, spec-input, harness-state,
  and forbidden sibling source roots for future provider-level enforcement,
  without granting the entire orchestration workspace as an allowed root. LLM
  build/feedback runners receive its path through
  `ECHELON_CONTAINMENT_POLICY_FILE`. Prompt and policy wording now also forbids
  softer sibling-source probes such as checking or looking at forbidden roots.
  Transcript containment treats `NotebookRead` as filesystem access.
- **EGR-119 / #143 verify-spec orchestration** — verify-spec stage 5 now uses
  `python -m harness write-fallback-fulfillment-template` to create a bounded
  fallback report for SPEC-GUARD. The LLM fills only TODO cells for unresolved
  IDs, and Python still assembles the final canonical fulfillment report.
  Assembly now rejects fallback rows that still contain `TODO_STATUS` or
  `TODO_EVIDENCE`, and rejects fallback statuses outside the canonical
  fulfillment status set. Fallback report assembly now also rejects rows outside
  the exact prepass fallback ID set, duplicate fallback rows, and missing
  expected fallback rows. Verify-spec fallback/report writers now create output
  parent directories before writing, avoiding raw `FileNotFoundError` crashes
  when run artifacts target a not-yet-created subdirectory. CodeGraph evidence
  mapping now also requires the init-owned verify-spec `state.json` before
  treating an absent `codegraph-analysis.json` as a degraded-CodeGraph skip.
  CodeGraph evidence generation itself now checks the init-owned state file
  before invoking CodeGraph or writing analysis artifacts. Canonical requirement
  inventory and requirement-audit writers now also require init-owned state
  before writing their artifacts. Progress-integrity writing now reports the
  same state-boundary error instead of surfacing raw missing-file exceptions.
- **EGR-115 / #140 Ralph-owned delivery state** — build prompts no longer expose
  Ralph's mutable `state/default.json` path. Agents receive bounded progress
  facts in the prompt and must report progress through the build status marker,
  leaving harness state reads/writes owned by Ralph. `verify-spec-1-init` now
  hard-stops when `spec_dir=` is absent instead of asking COMMANDER to locate
  or glob `specs/{spec_id}-*/`; callers must pass the authoritative spec
  directory. Markerless clean-exit recovery now ignores agent-owned report
  files such as `echelon_result.json` when deciding whether authoritative
  delivery progress exists.
- **EGR-116 / #142 prompt tool contracts** — static prompt scanning now rejects
  verify-spec phase prompts that ask COMMANDER to find, locate, glob, list, or
  search `specs/` for a spec directory, or to find/list/sort/search `runs/` to
  infer the latest verification run. It also rejects build prompts that ask
  agents to discover Ralph-owned state/spec artifacts such as `state.json`,
  `runs/`, `tasks.md`, `spec.md`, or `specs/`. Negative boundary wording
  remains allowed. Delivery-visible `echelon.build` and `echelon.verify-spec`
  command wrappers now start from Ralph/Python-owned context and exact phase
  invocations instead of instructing agents to read `commander.md` or
  `workflow/definition.yaml`; static scanning rejects equivalent
  `inspect`/`open`/discovery phrasing too. The scanner also treats known
  fulfillment-report helper names such as `fulfillment_report_is_current` as
  harness internals when prompts ask agents to find, locate, discover, or
  inspect their implementation. Build prompt scanning now also rejects `get` or
  `query` phrasing for exploratory git-state discovery, and rejects direct
  reads of Ralph-owned build/spec artifacts such as `state.json` or `tasks.md`.
  Harness-internal discovery scanning now also catches softer phrasing such as
  checking, reviewing, examining, or looking at harness source files.
- **EGR-125 / #149 build-slice context** — Ralph now writes a Python-owned
  `context/<strategy>-build-slice-context.md` artifact for delivery build and
  feedback turns. The initial context includes deterministic roots, spec input
  paths, bounded open task rows, referenced requirement excerpts, bounded
  spec-adjacent artifact excerpts, dirty verify artifact notes, the progress
  ledger, current build slice task/phase/requirement/row hints, focused current
  requirement excerpts, canonical workspace constitution excerpts, bounded ADR
  excerpts, configured quality commands, last verifier failures, target package manifest excerpts for
  `package.json` and `pyproject.toml`, package entry-point hints, package
  dependency hints, package-manager lockfile hints, Python package-manager
  hints, Python dependency hints, Python project script hints,
  target layout excerpts with representative source/test files, target
  source/test file-count hints, target config-file hints, documentation artifact
  hints, target git branch/HEAD/recent-commit/dirty-state hints, and build
  rules, and the prompt tells agents to read it before implementation. Prompt
  contract tests now reject build-agent instructions that ask models to
  rediscover target git state with exploratory `git status`/`git log` turns.
- **EGR-126 / #150 build context-pack compiler groundwork** — Ralph now writes a
  machine-readable `context/<strategy>-build-slice-context.json` sidecar beside
  the Markdown build-slice context. The sidecar records the Markdown path, spec
  inputs, strategy, generated section list, and structured section blocks so
  future per-agent build context packs can consume Python-owned context without
  parsing prompt prose. It also includes `agent_sections` selector maps and
  materialized context packs for IMPLEMENTER, SPEC_GUARD, CODE_REVIEWER, and
  TEST_GUARDIAN, TECH_WRITER, DOCS_VERIFIER, PROGRESS_TRACKER, INTEGRATOR, and
  VISUAL_VALIDATOR, ENGINEERING_MANAGER, and VERIFICATION, and Ralph names both
  `build_slice_context_index_file` and `build_implementer_context_file` in
  harness context. Build, progress, integration, visual-validation,
  documentation, and finalization phase docs now instruct COMMANDER to use the
  Ralph-owned context pack files instead of compiling ad hoc packs.
- **EGR-095 / #125 active delivery UX** — top-level `echelon land` help and
  option errors now point at canonical `echelon delivery land`, while legacy
  harness compatibility command docs and status output suggest
  `echelon delivery init|run|resume|status`.

### Fixed

- **Delivery Docker recovery** — `echelon delivery continue <spec_id>` now
  resumes runs blocked with `termination_reason: docker_unavailable` after the
  container runtime is restarted, and status/error guidance points at
  `delivery continue` instead of fresh `run`/deprecated answerless `resume`.
- **EGR-117 / #141 host harness-source containment** — Ralph now blocks build
  turns whose LLM transcript shows tool access to host Echelon implementation
  source such as any `src/harness/*.py` file or
  `src/kernel/fulfillment.py`, while still allowing target-worktree reads when
  Echelon itself is the project under delivery. Relative transcript paths are
  covered too, so these known harness/kernel files no longer slip past the
  guard unless the referenced file exists inside the target worktree.
- **EGR-119 / #143 verify-spec state ownership** — successful
  `python -m harness write-progress-integrity ...` runs now stamp
  `progress_integrity: valid` and progress counts in `state.json`; invalid
  progress writes `progress_integrity: invalid` with validation errors before
  exiting non-zero.
  `python -m harness write-canonical-requirements ...` and
  `python -m harness write-requirement-audit ...` runs now stamp Stage 3
  inventory/audit readiness and counts in `state.json`.
  Successful
  `python -m harness write-codegraph-evidence-map ...` runs now stamp
  `codegraph_evidence_map: ready` in the Python-owned verify-spec `state.json`,
  matching the existing degraded-path stamp and reducing later prompt-side state
  inference. `python -m harness write-judgment-prepass ...` now likewise stamps
  `judgment_prepass: ready` plus deterministic mechanical/fallback row counts,
  and `write-fallback-fulfillment-template` stamps fallback queue readiness when
  called with a verify-spec state file. `assemble-fulfillment-report` now stamps
  final fulfillment report readiness and the report path after successful
  assembly. `plan-reopen-gaps` now preflights required inputs and reports
  missing files without a traceback before writing reopen plan artifacts.
  assembly. `validate-fulfillment-artifacts` now accepts the verify-spec
  `state.json` path and stamps row-set validation counts on success or the
  missing/extra row IDs on failure. Stage 6 reconciliation candidate commands
  now also accept the verify-spec `state.json` path and stamp safe/ambiguous
  mapping and progress candidate counts. The paired Stage 6 apply commands now
  stamp dry-run/applied status plus safe/applied counts in the same state file.
- **EGR-117 / #141 runtime surface reduction** — delivery runtime sync now
  omits reverse-engineering shell helpers under
  `.specify/extensions/echelon/scripts/bash/re` from target worktrees and
  workspace-target harness roots. It also omits Phase A preset seed material
  under `.specify/extensions/echelon/presets`.
- **EGR-117 / #141 delivery agent wrapper scope** — generated
  `.claude/agents` files in delivery worktrees are now limited to build agents
  instead of exposing control, exploration, solution, reverse-engineering,
  learning, feasibility, and specialist agents. Claude-specific `.claude`
  wrapper materialization now runs only when `harness.llm.cli: claude`, through
  a provider runtime scaffolder boundary rather than GitOps-owned Claude logic.
  Generated `.claude/skills` command wrappers are now likewise limited to the
  delivery-safe `echelon.build` and `echelon.verify-spec` commands.
- **EGR-117 / #141 delivery command surface** — delivery runtime extension sync
  now copies only delivery-safe command docs (`echelon.build.md` and
  `echelon.verify-spec.md`) into target worktrees and workspace-target harness
  roots, matching the provider wrapper allowlist and hiding Phase A/RE command
  docs from build turns.
- **EGR-116 / #142 fulfillment report inspection command** — added
  `python -m harness inspect-fulfillment-report <spec-dir> [current-commit]`
  as an opaque JSON command for fulfillment report metadata, freshness, scope,
  and blocking-gap facts, and pointed verify-spec prompts at it instead of
  harness-source discovery.
- **EGR-118 / #144 source-root transcript containment** — Ralph now treats
  forbidden sibling source roots found in tool output blocks as containment
  violations, not only paths shown on the same `Read`/`Bash` invocation line.
  It also treats `Write`/`Edit`/`MultiEdit` transcript lines as filesystem
  access, and detects workspace-relative sibling source paths such as
  `sources/spec-kit-skills-agents/package.json` with path-boundary matching so
  similarly named roots like `sources/ruler2` do not falsely match
  `sources/ruler`. Prompt echoes of `forbidden_source_roots` remain ignored.
- **EGR-119 / #143 verify-spec run initialization** — added
  `python -m harness init-verify-spec-run` to create the verify-spec runtime
  directory and stamp `state.json` from Python-owned logic. The
  `verify-spec-1-init` phase now tells COMMANDER to consume the command's JSON
  instead of reading `runs/.current`, deriving orchestration roots, choosing
  timestamps, or writing state by hand.
- **EGR-119 / #143 CodeGraph state stamping** — `python -m harness
  write-codegraph-evidence` now updates `state.json.structural_evidence` to
  `ready` or `degraded` itself, and `verify-spec-2-codegraph` now forbids
  hand-editing state after CodeGraph degradation.
- **EGR-119 / #143 requirement-audit ownership** — added
  `python -m harness write-requirement-audit` to render
  `requirement-audit.md` from `canonical-requirements.json`, and converted
  `verify-spec-3-audit` from an auditor-agent dispatch to a
  commander-internal deterministic phase.
- **EGR-119 / #143 fulfillment row-set validation** — added
  `python -m harness validate-fulfillment-artifacts` and updated
  `verify-spec-5-judge` to use it for final row-set integrity instead of asking
  COMMANDER to compare fulfillment report IDs by hand.
- **EGR-119 / #143 degraded CodeGraph map handling** —
  `write-codegraph-evidence-map` now handles degraded/missing CodeGraph analysis
  by writing skipped map artifacts and stamping `state.json`, so
  `verify-spec-4-map` no longer asks COMMANDER to skip and edit state manually.
- **EGR-119 / #143 progress reconciliation candidates** — added
  `python -m harness write-progress-reconciliation-candidates` to generate
  conservative task DONE candidates from canonical task metadata and
  `fulfillment-report.md`, replacing COMMANDER-authored reconciliation
  candidate JSON for mapped implemented requirements.
- **EGR-119 / #143 task requirement mapping candidates** — added
  `python -m harness write-task-requirement-mapping-candidates` to generate
  conservative `req=UNMAPPED` mapping candidates only when canonical task text
  explicitly names requirement IDs, replacing COMMANDER-authored
  `task-requirement-map.candidates.json`.
- **EGR-120 / #145 delivery-slice documentation gates** — Ralph now passes the
  delivery slice's changed-file list into the TECH WRITER documentation gate,
  so later checkpoint/status commits do not trigger false README/CHANGELOG
  repair loops after documentation was already updated in the implementation
  slice.
- **EGR-121 / #146 workspace spec convergence commits** — workspace-target
  delivery now commits workspace-owned spec lifecycle artifacts after target
  output is committed and before Ralph reports convergence, using a bounded
  spec-directory pathspec so unrelated workspace changes are not swept in.
- **EGR-122 / #147 TECH WRITER docs verification** — the documentation gate now
  rejects overview-only README updates for runnable npm/CLI projects when they
  omit first-run manual essentials such as prerequisites, minimal working input,
  expected dry-run output, generated output, troubleshooting, and development
  commands. Keep a Changelog `[Unreleased]` entries that describe planned
  roadmap work are also rejected. The build workflow now routes TECH WRITER
  output through a DOCS VERIFIER phase that writes `docs-verification-report.md`
  and loops structured repair findings back to TECH WRITER before finalization.
  Ralph now requires a machine-readable PASS `docs-verification-report.md` with
  zero blocking findings and project-evidence metadata before required
  documentation can pass the final gate. README npm script commands are now
  checked against `package.json` so docs repair loops catch invented local
  commands before finalization. `python -m harness verify-docs` now writes the
  authoritative docs verification report, and DOCS VERIFIER is instructed to run
  it before returning PASS or structured repair findings.
- **EGR-123 / #148 Phase A source-root boundaries** — feature context builders
  now ignore numbered directories that lack `spec.md`, preventing RE overview
  folders from being treated as product specs, and Phase A prompts now include
  explicit workspace `SOURCE_ROOT` boundaries so agents distinguish orchestration
  workspace paths from implementation source roots.
- **EGR-123 / #148 RE source fingerprints** — added deterministic source
  fingerprinting for future reverse-engineering cache keys, covering clean Git
  sources, dirty Git sources with tracked/untracked changes, non-Git file trees,
  and RE profile inputs.
- **EGR-123 / #148 RE cache storage** — added persistent per-source
  reverse-engineering cache storage primitives with safe source-id path
  resolution, manifest-backed cache-hit validation, and replacement writes that
  remove stale artifacts.
- `echelon delivery land <spec_id>` now dispatches through the spec-declared
  workspace target before landing, so polyrepo delivery lands the selected
  source repository instead of using the orchestration workspace mirror. The
  legacy `echelon harness land` alias is wired through the same path. Targeted
  land also uses the workspace spec's readiness state instead of treating a
  stale copied spec on the target feature branch as authoritative, and compares
  workspace fulfillment reports against the target repo feature branch instead
  of the orchestration workspace commit.
- **EGR-115 / #140 deterministic Ralph recovery boundary** — Ralph now
  continues to verification when a clean markerless build has all canonical
  tasks already marked done, instead of paying for another LLM turn only to
  rediscover completion. The verify-spec judgment phase also forbids agents
  from inspecting harness source or sibling `sources/` repos to infer
  fulfillment-report provenance that Ralph owns. Ralph now passes the resolved
  spec directory into fulfillment refreshes so verify-spec does not need to
  locate `specs/<id>-*` from inside target delivery worktrees.
- **EGR-116 / #142 harness source prompt boundary** — build-agent execution no
  longer receives `HARNESS_SOURCE_DIR`, and Ralph's harness context now forbids
  reading or searching harness implementation files instead of pointing agents
  at `src/harness`. The prompt tool-contract scanner now rejects future agent
  or phase prompts that instruct LLMs to find/read/search harness internals.
- **EGR-118 / #144 targeted source-root containment reporting** — Ralph's build
  context now reports sibling workspace `sources/*` directories as
  `forbidden_source_roots` and tells build agents not to inspect, read, list,
  grep, or search those roots during targeted delivery. Ralph also blocks a
  build when the LLM transcript shows tool access to a forbidden sibling root.
- **EGR-117 / #141 reduced target-visible runtime extension surface** — delivery
  worktree runtime sync no longer copies workspace migration helper source from
  `.specify/extensions/echelon/scripts/python`, and polyrepo wrapper sync uses
  the same runtime-extension ignore policy.
- **EGR-113 / #137 build resume recovery** — `delivery resume` can now recover
  from a clean preserved build worktree whose committed output uses normal
  feature commit subjects instead of harness/checkpoint metadata, allowing the
  resumed run to reach verify and the TECH WRITER documentation gate. Blocked
  recovery can also discover legacy `harness/<spec>/<strategy>/iter-*` branches
  from the mirror when state lacks an explicit `harness_branch`.
- **EGR-112 / #136 TECH WRITER first-run README manuals** — TECH WRITER now
  treats newly created or substantially rewritten READMEs as first-run local
  manuals, requiring evidence-backed prerequisites, minimal configuration, dry
  run, real run, expected output, troubleshooting, development commands, and
  deeper-doc links instead of product-overview-only updates.
- Benchmark baseline snapshots now stage tracked changes plus non-ignored
  untracked files without touching ignored `runs/`, avoiding `git add` failures
  in workspaces that correctly ignore runtime state.
- **EGR-108 CI dependency drift** — GitHub Actions now handles Typer's vendored
  Click exceptions for delivery/harness parse errors, stabilizes Typer help
  output assertions under Rich terminal-width rendering, and exports the
  CI-selected Python interpreter into shell suites so E2E tests use the same
  environment that received `pip install -e ".[dev]"`.
- **EGR-105 / #129 scoped fulfillment deferral** — `fulfillment.refresh_policy=scoped`
  now treats successful scoped verification as deferred full evidence while
  tasks remain incomplete, avoiding inner-fix/no-progress loops on
  `fulfillment-report-scoped`; once task progress reaches the convergence
  boundary, Ralph switches scoped policy to a full verify-spec refresh.
- `echelon workspace init` now bootstraps lightweight workspace Git for Spec Kit
  workspaces when needed, committing `.gitignore`, `.echelon/config.yml`, and
  `specs/` as the initial workspace contract, so the documented `workspace init`
  -> `delivery init` flow works even when `specify init` did not create `.git`.
- `echelon delivery init` now fails fast with workspace Git setup guidance when
  run from a non-Git workspace instead of falling through to a confusing
  `git clone --mirror` failure.
- **EGR-104 / #128 Typer CLI front door** — `delivery` and `harness`
  commands now route through a Typer parser that documents canonical
  `--mode`, `--strategy`, `--max-outer`, and related options while preserving
  legacy `key=value` delivery arguments for compatibility.
- **EGR-103 / #127 installed-extension path prompt guidance** — runtime agent prompts
  now expose `EXTENSION_DIR`, template/agent subdirectory aliases, and explicit
  `extension/...` path-resolution rules so agents do not double-prefix the
  installed extension root when reading bundled templates or prompts.
- **EGR-100 / #112 Phase A blocked exit code** — `echelon spec run` /
  `echelon run` now exits nonzero when the squad result is blocked or otherwise
  unsuccessful, and benchmark variants stop before delivery if a zero-exit
  Phase A command left squad state blocked.
- **EGR-099 / #111 validation-failure masking** — executor-side phase
  validation no longer revalidates provider-created `BLOCKED` wrappers against
  per-phase agent `state_updates` allowlists, preserving the original validation
  error such as `quality_scores must be a list`.
- **EGR-098 / #110 ASSESS2 implementability metrics** — ASSESS2/GATEKEEPER now
  has a dedicated `implementability_metrics` state update in `phase3-consensus`
  instead of putting task-readiness and effort metrics under reserved
  list-shaped `quality_scores`.
- **EGR-094 / #124 checkpoint-plan deterministic routing** — banzai/semi checkpoint
  auto-approval no longer falls through to a COMMANDER routing judgment. The
  condition evaluator now resolves `autonomy` from `autonomy_mode` and
  short-circuits `OR` conditions when one branch is already true.
- **EGR-093 / #123 Phase A finalization outputs** — `phase4-document` now writes a
  deterministic `squad-report.md`, records a Phase A `run-history.json` entry,
  and refreshes `ARTIFACTS.md` after those outputs are present instead of
  checkpointing a harness no-op as complete.
- **EGR-092 / #122 TECH WRITER endocrine registry drift** — TECH WRITER is now listed
  in the endocrine `ALL_AGENTS` roster and explicitly mapped to the build
  archetype, keeping the legacy hormone registry consistent with the agent files
  added by EGR-080.
- **EGR-091 / #121 Context7 CLI tool integration** — ARCHITECT no longer asks for
  Context7 MCP tools. Echelon now ships a pinned extension-local `ctx7` runtime
  plus `context7-docs.sh`, installs it via `scripts/install.sh`, and prompts
  ARCHITECT to use the wrapper with an official-doc fallback. The wrapper's
  `--json` mode now emits a stable `echelon.context7.v1` envelope so agents
  parse `result` deterministically instead of inferring raw `ctx7` output shapes.
- **EGR-090 / #120 validate-plan help handling** — `python -m harness validate-plan
  --help` now prints usage and exits cleanly instead of treating `--help` as a
  plan file path and emitting a traceback. Missing plan files now produce a
  readable CLI error without a Python stack trace.
- **EGR-089 / #119 CARTOGRAPHER Understanding JSON shape contract** — WHAT prompts now
  document that enhanced `understanding scan --json --output` produces a
  list-root payload and require normalizing to `payload[0]` before reading
  metrics or analysis sections, preventing `.keys()`/dict-method failures during
  CARTOGRAPHER diagnostic scoring.
- **EGR-088 / #118 CARTOGRAPHER incomplete-result retry context** — when WHAT creates a
  spec branch/directory but the provider connection drops before `echelon_result`,
  the squad blocked state now preserves the existing spec id, spec directory,
  published spec directory, feature branch, and CARTOGRAPHER resume guard flag so
  `echelon continue` retries the same spec instead of risking a second
  `speckit.specify`/branch allocation.
- **EGR-087 / #117 banzai Phase 1 continuation defects** — squad runs no longer stop
  after CHIEF when a valid constitution's leading Sync Impact Report mentions
  old template placeholders, and node-level workflow conditions are now honored
  at runtime. Greenfield runs skip brownfield-only MODELER instead of dispatching
  it despite `condition: "mode = brownfield"`.
- **EGR-086 / #106 equals-form mode flags** — Phase A CLI parsing now accepts
  both `--mode banzai` and `--mode=banzai` for `echelon run`,
  `echelon spec run`, `echelon continue`, `echelon spec continue`, and
  `echelon phase run`, instead of silently treating equals-form flags as task
  text and falling back to `semi`.
- **EGR-084 / #115 constitution guard workflow override** — squad routing no longer
  lets the controller-level constitution provenance guard bypass required
  upstream Phase 1 context phases. `phase1-synthesizer`, `phase1-modeler`, and
  `phase1-tracker` now run before CHIEF when the workflow graph routes there,
  so TRACKER can produce `user-intent.md` for CHIEF's constitution context pack.
- **EGR-083 / #114 quality gate pass normalization** — WHY/SAGE quality routing now
  treats `quality_scores[*].pass` as a boolean-only contract. Non-boolean or
  missing WHY pass flags are normalized deterministically from configured
  thresholds or verdict before routing/state persistence, and raw non-WHY
  `quality_scores.pass` strings are rejected by schema validation. SAGE prompt
  examples now use `pass_id` for iteration labels.
- **EGR-082 / #105 benchmark baseline reset discipline** — experimental
  artifact-quality benchmark runs now require an explicit `--baseline-ref`
  for real execution and wrap each variant with `git reset --hard <ref>` plus
  `git clean -fd -e runs/benchmarks/`, so cleanse variants do not inherit
  mutations from prior variants.
- **EGR-081 / #104 Dockerless workspace init** — `echelon workspace init` now
  treats HTTP deploy provisioning as optional workspace setup. Missing or
  unavailable Docker/Podman writes `deploy.enabled: false`, skips local HTTP
  deploy infra with actionable guidance, and still completes MemPalace/config
  bootstrap.
- **EGR-078 / #95 recovery backup gitignore contract** — workspace migration,
  doctor, and docs now treat `.echelon/recovery-backups/` as ignored runtime
  state so recovery artifacts do not appear as untracked files after migration.
- **EGR-077 / #94 noninteractive land archive prompt** — successful
  `echelon land` no longer crashes with `EOFError` when the optional archive
  prompt runs without interactive stdin.
- **EGR-076 / #93 local land cleanup recovery** — landing cleanup now skips
  remote feature-branch deletion when `origin` is absent or local, and
  recognizes already-merged feature branches from either checkout.
- **EGR-075 / #92 generated verification drift during land** — `echelon land`
  discards allowlisted generated verification metrics before final merge
  checkout, blocks other dirty files, and skips default-branch push when no
  non-local origin exists.
- **EGR-074 / #91 local/no-origin land continuation** — `echelon land
  --continue` now treats a clean feature branch that already contains the
  default branch as prepared after push-only failures in local/no-origin repos.
- **EGR-072 / #89 autonomous land runtime-state conflict resolution** —
  `echelon land` now autoresolves the legacy transition where a feature branch
  still tracks `.specify/*` runtime files while the default branch ignores
  `.specify/`. Land keeps a unioned `.gitignore`, removes `.specify/*` from the
  Git index, and applies the same resolver when recovering with
  `echelon land <id> --continue`; source/spec artifact conflicts still block.
- **EGR-071 / #88 spec-kit runtime gitignore contract** — workspace Git initialization
  guidance and migration now treat `.specify/` as local spec-kit/Echelon runtime
  state, add it to `.gitignore`, and stage only `.gitignore` plus `specs/`.
  The tracked constitution handoff remains the published
  `specs/<id>-*/constitution.md` snapshot rather than
  `.specify/memory/constitution.md`.
- **EGR-070 / #87 land feature-branch readiness** — `echelon land`
  now falls back to the resolved feature branch for readiness and fulfillment
  preflight when the current checkout has stale spec artifacts. Fulfillment
  reports verified at an ancestor commit are accepted only when later feature
  branch commits changed landing/verification artifacts without touching
  implementation inputs or semantic spec inputs.
- **EGR-069 harness resume salvage recovery** — `echelon harness resume` now
  recovers from a state-recorded salvage/checkpoint commit even when later
  generated verification artifacts leave the preserved worktree with tracked
  modifications. Dirty preserved worktrees still block only when recovery has
  to infer an unrecorded commit.
- **EGR-068 verify-spec CodeGraph confidence mapping** — verify-spec now rejects
  stale CodeGraph exports whose `repo_path` does not match the current project
  root before summary/map generation, falling back to a fresh bridge export when
  available. The deterministic evidence mapper also uses CodeGraph call edges
  from requirement-anchored tests to lift directly called implementation symbols,
  reducing low-confidence fallback when source/test relationships are already
  present structurally.
- **EGR-066 build quality gate sequencing contract** — `echelon.build` and the
  build task phase now explicitly require SPEC GUARD, CODE REVIEWER, and TEST
  GUARDIAN to run as sequential hard gates, not one parallel batch. CODE
  REVIEWER and TEST GUARDIAN may no longer be skipped by vacuity; any skip
  needs a workflow-approved condition and journaled rationale, while the generic
  COMMANDER prompt remains judge/governance-oriented.
- **EGR-067 Ruff formatting evidence in Python language rules** — CODE
  REVIEWER's Python language rule now requires both `ruff check` and
  `ruff format --check` before reporting Python style, lint, or formatting as
  clean, preventing lint-only evidence from masking formatter failures while
  keeping the generic code-reviewer prompt language-neutral.
- **EGR-065 provider-limit salvage task-progress reconciliation** — Ralph now
  reapplies completed task statuses from Python-owned harness state after
  syncing Phase A inputs into a build worktree. Stale project-visible
  `tasks.md` copies can no longer erase checked task rows before readiness
  validation or provider-limit salvage.
- **EGR-064 / #86 harness recovery idempotence** — `echelon harness
  resume` no longer requires a clean current checkout when the selected
  checkpoint/salvage commit is already contained in the resolved target feature
  branch. Recovery now reports the commit as already present and continues
  without checkout/cherry-pick; dirty-tree blocking remains for commits that
  still need to be applied.
- **EGR-062 / #84 verify-spec provider-session recovery** — provider
  session limits during fulfillment refresh now stop Ralph as a first-class
  checkpoint block instead of becoming ordinary `verify-spec-failed`
  verification failures that can trigger more LLM feedback work. When an older
  fulfillment report exists, the failure reason now includes the report's
  verified commit and the current HEAD so stale evidence is not mistaken for
  current fulfillment status.
- **EGR-061 / #83 harness LLM tool-policy inheritance** — harness config
  loading now treats top-level `llm` as lower-precedence compatibility
  defaults for `harness.llm`, so approved `llm.tool_policy` settings are no
  longer silently ignored when a nested `harness:` section exists. Nested
  `harness.llm` values still override top-level defaults.
- **EGR-060 / #82 missing verify-command recovery UX** — `echelon harness init`
  now stops suggesting `harness run` as the next step when verify-command
  detection declined, and `echelon harness resume` uses persisted detection
  metadata to prioritize manual `verify_command` setup instead of sending users
  back through another no-op `harness init`.
- **EGR-059 / #81 harness resume contract** — `echelon harness resume`
  now accepts `blocker_escalation` as a legitimate blocked harness state and
  delegates back into the coordinator instead of telling users to use
  `harness run` to resume. Unsupported blocked reasons now point to
  `harness resume` after fixing the blocker or `harness run --reset` only when
  discarding blocked state.
- **EGR-057 / #79 Phase-A-only harness resume retry** — `echelon harness
  resume` now skips git recovery for build-incomplete states caused solely by
  Phase A readiness blockers when there is no salvage/checkpoint commit to
  recover.
- **EGR-056 / #78 build-worktree Phase A artifact sync** — Ralph now
  materializes the current project-visible Phase A spec inputs and constitution
  snapshot into generated build worktrees before LLM dispatch, then validates
  the worktree copy with the shared readiness gate.
- **EGR-055 / #77 repaired harness-error resume** — `echelon harness resume`
  now refreshes stale persisted spec artifact paths and retries prior
  `harness_error` runs only after deterministic artifact preflight confirms the
  current spec is resolvable and build-ready.
- Clarified and enforced squad recovery command contracts. `echelon continue`
  is now the no-input recovery executor, `echelon resume` only answers human
  gates before delegating back to continuation, and blocked runs without human
  questions no longer point to unusable resume commands.
  - Recoverable dispatch failures including `missing_echelon_result`,
    `missing_phase_outputs`, `agent_timeout`, `agent_blocked`, and
    `agent_exit_code_*` now prioritize the failed incomplete
    `last_dispatch.phase_id`.
  - Safe Phase 3 failures point to `echelon rewind`; incomplete Phase 1
    dispatches retry the failed phase and clear stale block metadata before
    re-running.
  - Interrupted squad runs now persist `status=interrupted` and the interrupted
    phase so `echelon continue` retries the interrupted phase instead of
    inferring a later phase from artifacts.
- Fixed checkpoint human-gate recovery after `echelon resume`: stale
  `escalation_resolved: true` state no longer suppresses a later fresh
  `escalation_question`, so real checkpoint questions are preserved instead of
  being overwritten by the generic `phase_dispatch_limit` block.
- Fixed consensus ownership routing bounds after PR #18: WHY3 spec-quality
  failures now route back to WHAT only while `iteration < max_iterations`, and
  ASSESS2 feasibility failures route back to HOW only while below the same cap,
  preserving the executable force-convergence fallback at the iteration limit.
- Stabilized full-suite verification by making the shell runner use `bash`
  without mutating tracked test file modes, reusing the installed Echelon venv
  for shell Python detection, initializing empty endocrine state files, skipping
  Docker visual smoke checks when Docker is unavailable, and aligning phase 3
  consensus state-update allowlists with accepted-risk routing.
- Fixed Phase 2 tracker routing so `ALIGNED` / `DRIFT` verdicts advance to
  `phase3-specialists` and `STOP_AND_ASK` escalates instead of falling through
  to `DONE` with misleading incomplete-build guidance.
  - The workflow still accepts legacy `DRIFTING` / `ESCALATE` tracker verdicts
    for compatibility, while the tracker prompt and intent-alignment template
    now document the canonical verdict contract.
  - Next-step guidance for missing Phase A authoring artifacts now reports
    `PHASE A INCOMPLETE` rather than `BUILD BLOCKED`.
- **EGR-019 RepairLoop adoption pilot** — the coordinator-owned Phase 3
  review-fix/re-entry cycle now runs through the reusable `RepairLoop`
  primitive while preserving existing review terminal and Phase 1 re-entry
  semantics.
  - Focused regression coverage asserts that review re-entry still injects
    `review-fix-*.md` content into the next Phase 1 build prompt and that the
    coordinator invokes `RepairLoop` for the bounded cycle.
- **EGR-025 workflow condition-field validation** — workflow validation now
  rejects transition conditions that reference unresolvable fields, while
  allowing explicit result fields, known config/derived predicates, declared
  current/prior phase `allowed_state_updates`, transition `state_update` keys,
  and declared output fields.
- **EGR-026 verdict-contract static validation** — explicit routing verdict
  contracts in phase specs are now checked against workflow transition
  verdicts, related agent prompts, and related templates; the tracker prompt's
  stale `DRIFTING` / `ESCALATE` repair instruction was migrated to canonical
  `DRIFT` / `STOP_AND_ASK`.
- **EGR-027 continue recovery hardening** — `echelon continue` now detects
  already-affected runs where tracker alignment completed but
  `phase3-specialists` was skipped, and resumes at `phase3-specialists` before
  treating missing HOW artifacts as the next repair target.
- **EGR-028 GUARDIAN config naming reconciliation** — public docs and
  agent/phase prompts now use the executable `specialists.guardian_mode` config
  key consistently, with static pytest coverage preventing regression. Workflow
  conditions keep the derived predicate form `guardian_mode = ...`.
- **EGR-029 Phase A artifact publishing** — `phase4-document` now publishes
  run-local Phase A artifacts into the project-visible `specs/<id>-<slug>`
  directory, writes `ARTIFACTS.md`, records `published_spec_dir`, and validates
  that published build target before build-ready guidance. `echelon continue`
  routes old done-but-unpublished runs back through Phase 4 instead of claiming
  build-ready from run-local artifacts alone.
- **EGR-030 Lexicon/spec contract reconciliation** — `spec.md` remains the
  canonical rich spec-kit feature specification when the Lexicon gate is enabled.
  CARTOGRAPHER now derives `requirements.lexicon.md` for controlled-grammar
  validation, the tasks gate validates against the configured derived `spec_ref`,
  and static pytest coverage prevents reintroducing destructive `spec.md`
  replacement by default.
- **EGR-031 status roadmap derivation** — `echelon status` now derives its
  roadmap from the primary forward path in `workflow/definition.yaml` instead of
  a stale hardcoded phase list, and re-dispatched phases that already appear in
  `completed_phases` no longer make progress counts move backward.
- **EGR-032 RUNNABLE evidence wording** — codegen RUNNABLE phase text now
  describes the implemented gate as build plus static composition evidence,
  avoids boot/render claims, and reserves runtime/browser verification for a
  future higher-fidelity gate.
- **EGR-033/#54 derived Lexicon artifact contract** — `requirements.lexicon.md`
  is now registered in `ARTIFACTS.md` as a derived requirements index, and
  `lexicon validate --source-ref spec.md` enforces source hash freshness plus
  requirement/acceptance/error ID projection from the canonical rich `spec.md`.
  CARTOGRAPHER and phase docs now pass the source reference explicitly.
- **EGR-034/#55 CodeGraph vendor contract** — the RE CodeGraph bridge now has
  a deterministic vendor manifest and provenance note for the vendored
  `@colbymchenry/codegraph` runtime package, including package version, npm
  tarball integrity, license evidence, local payload hash, update procedure,
  and the explicit split from the optional global CodeGraph CLI version.
- **EGR-035 project context and memory reconciliation** — squad Phase A now
  generates run-local context under `runs/<run-id>/context/`, publishes
  canonical feature metadata for finalized specs, mines finalized canonical
  specs into MemPalace with artifact hashes, excludes stale MemPalace drawers
  from prompt context, and executes GOLDDIGGER Mode 2 queue requests.
- **EGR-036 CARTOGRAPHER validation tool contract** — CARTOGRAPHER now has an
  explicit diagnostic command contract for Understanding and Lexicon during
  amendment passes. It uses `understanding scan ... --output` for diagnostic
  scoring, avoids guessed `understanding validate` subcommands, and treats
  `lexicon validate --source-ref` as the authoritative derived-artifact gate.
- **EGR-037/#58 prompt tool-contract scanner** — agent and phase prompts are
  now scanned for executable tool references that omit an exact nearby command,
  Skill id, slash command, or first-class tool name. The scanner caught and fixed
  remaining ambiguous CHIEF, GOLDDIGGER, SAGE consensus, and verify-spec
  command references.
- **EGR-039/#60 resume missing-result recovery** — retryable dispatch-block
  recovery now preserves the latest `last_dispatch.phase_id` even when a prior
  pass of the same phase appears in `completed_phases`, so `missing_echelon_result`
  after `echelon resume` guides `echelon continue` back to the failed phase
  instead of vague manual recovery.
- **EGR-042 / #63 harness blocker UX consistency** — repeated-failure
  escalation context now reports the actual consecutive streak, threshold, and
  fingerprint count, and terminal guidance points to `echelon harness resume
  <spec_id>` after appending `## Answer`.
- **EGR-041 / #62 fulfillment cache invalidation** — full verify-spec cache keys
  now include deterministic implementation-input content hashes for source,
  tests, and build manifests so uncommitted implementation changes cannot reuse
  stale fulfillment reports.
- **EGR-040 / #61 project config compatibility** — terminal CLI now warns or
  blocks before Phase A dispatch when existing project config still points the
  Lexicon tasks gate at stale `spec.md` instead of the derived requirements
  artifact.
- **EGR-038 SAGE Understanding handoff contract** — SAGE's follow-up
  Understanding appendix now documents the actual enhanced JSON list shape for
  behavioral-transition extraction, including `.[0].behavioral_analysis.transitions`,
  empty-list handling, and null-safe table cells for SENTINEL handoff evidence.
- **EGR-043/#64, EGR-044/#65, EGR-045/#66, EGR-046/#67 harness evidence hardening** — harness
  runtime extension sync now materializes valid Claude custom-agent files for
  Echelon agents, reported `completed_task_ids` that cannot be written to
  canonical `tasks.md` now block before verification, Phase A readiness rejects
  missing or placeholder `constitution.md`, and CodeGraph term-match-only
  source/test rows stay low-confidence fallback evidence instead of being
  treated as resolved medium-confidence mappings.
- **EGR-047/#68 dry-run validation repair** — `scripts/bash/dry-run.sh`
  now resolves repository and extension roots explicitly, supports both the
  documented repo-root invocation and an explicit extension-root argument,
  validates the current thin-wrapper plus COMMANDER role-separation contract,
  and keeps knowledge-base YAML parseable as part of the gate.
- **EGR-048/#69 Phase A readiness at harness dispatch** — reconciled the
  existing tracked issue for placeholder `constitution.md` reaching harness
  build dispatch; the register now records that the deterministic Phase A
  readiness gate blocks missing or template constitution input before build
  agents run.
- **EGR-052 / #73 constitution context packs** — CARTOGRAPHER, ORCHESTRATOR
  PLAN, SAGE WHY3, and ORCHESTRATOR PLAN2 now receive read-only constitution
  context, while ARCHITECT no longer claims fallback constitution creation or
  edit authority.
- **EGR-051 / #72 recovery untracked-collision handling** — harness recovery now
  preflights untracked paths that collide with recovered commits, removes
  identical duplicates before cherry-pick, and backs up differing local copies
  under `.echelon/recovery-backups/`.
- **EGR-050 / #71 constitution ownership contract** — CHIEF/spec-kit remains the
  only constitution source of truth; non-CHIEF phases consume snapshots or emit
  amendment candidates, and codegen/finalize paths validate snapshots instead of
  copying or repairing constitution files.
- **EGR-049 / #98 provider session-limit blocked UX** — provider session-limit
  failures now render as first-class harness blocks across Ralph stop banners,
  `echelon status`, and delivery summaries, including reset hints, salvage
  details, retry guidance, and token context where available.
- **EGR-054/#70 workspace/source-root model** — Echelon now treats projects as
  Git-backed orchestration workspaces with zero or more source roots. Reverse
  engineering emits and prefers `workspace-manifest.json`, harness target
  selection resolves against source roots, harness state records workspace and
  source metadata, branchless workspaces are blocked for new runs with legacy
  recovery only, and a one-time migration script initializes lightweight
  workspace Git without staging child implementation repositories.
- **EGR-058/#80 harness inner-fix task progress** — Ralph now preserves
  `completed_task_ids` from LLM feedback invocations, reconciles them into
  canonical `tasks.md` and harness state before checkpointing, and treats a
  sole remaining full-spec `fulfillment-gaps` failure after task progress as an
  outer-loop continuation boundary instead of same-failure escalation.

### Changed

- Added `docs/pipeline-matrix.md` to make the two independent pipeline axes
  explicit: Phase A spec authoring format versus Phase B build execution
  strategy and to document the supported dual-artifact contract for Lexicon
  validation.
- **EGR-022 shell-to-pytest migration step** — moved the no-new-dependencies
  repository-policy contract from `tests/unit/test-no-new-deps.sh` into pytest
  via `tests/contract/no_new_deps.py` and
  `tests/unit/test_no_new_deps_pytest.py`, then moved the extension registry
  sync contract from `tests/test-unit-registry-sync.sh` into pytest via
  `tests/contract/registry_sync.py` and
  `tests/unit/test_registry_sync_pytest.py`, then moved the language-rule file
  contract from `tests/unit/test-language-rules-exist.sh` into pytest via
  `tests/contract/language_rules.py` and
  `tests/unit/test_language_rules_pytest.py`, then moved static prompt,
  knowledge-base, and schema contract checks into
  `tests/contract/static_contracts.py` and
  `tests/unit/test_static_contracts_pytest.py`; updated `tests/README.md` to
  make pytest the primary local test path, and updated `tests/run-all.sh` to run
  the migrated contracts through pytest while retaining shell coverage only
  where shell/runtime behavior is the subject.

### Added

- Documented the EGR completion gate: every implemented EGR now requires a
  matching `[Unreleased]` changelog entry, register update, and verification
  notes before the work is considered complete.
- **EGR-001 deterministic `echelon_result` validation** — added `src/harness/echelon_result_schema.py` to validate agent result payloads before harness state mutation.
  - Covers required string `verdict`, supported verdict values, `state_updates` object shape, `journal_entries` list shape, and reserved harness-owned state keys including `last_dispatch`.
  - `src/harness/squad_provider.py` now converts invalid parsed agent results into blocked results before executors can consume `state_updates`; when `ECHELON_DEBUG_RAW_DIR` is set, the blocked result includes a raw-output debug path.
  - `src/harness/squad_state.py` now defensively validates again in `SquadStateStore.advance()` so malformed results cannot complete phases or mutate state.
  - Focused tests added in `tests/kernel/test_echelon_result_schema.py`, `tests/kernel/test_squad_provider.py`, and `tests/kernel/test_squad_state.py`.
  - Verification: `pytest tests/kernel -q` (`532 passed in 1.59s`).
- **EGR-002 deterministic Phase A readiness validation** — added shared Phase A build-input validation so blocked runs and specs missing `spec.md`, `plan.md`, `research.md`, `data-model.md`, or `tasks.md` cannot be reported as ready to build.
  - `echelon status` / next-step guidance and `echelon continue` now use the same artifact readiness predicate.
  - `phase4-document` blocks the squad run with `phase_a_readiness_failed` instead of finalizing incomplete Phase A output.
  - Focused tests added in `tests/unit/test_phase_a_readiness.py`, `tests/unit/test_cli_next_step_escalation.py`, `tests/unit/test_cli_continue.py`, and `tests/integration/test_squad_controller.py`.
  - Verification: `pytest tests/unit/test_phase_a_readiness.py tests/unit/test_cli_next_step_escalation.py tests/unit/test_run_readiness.py tests/unit/test_cli_continue.py tests/integration/test_squad_controller.py -q` (`83 passed`); `pytest tests/kernel -q` (`532 passed`). Broader `pytest tests/unit tests/kernel tests/integration/test_squad_controller.py -q` collection is blocked in this environment by missing existing dependencies `freezegun` and `lark`.
- **EGR-003 deterministic host LLM tool policy** — added `harness.llm.tool_policy` defaults and shared host-side LLM command builders that inject the effective policy into prompt-based dispatches and only enable dangerous CLI permission-bypass flags after explicit approval metadata.
  - Defaults use `file_boundary: workspace`, `network_boundary: harness_allowlist`, and `allow_unsafe_host_execution: false`.
  - Unapproved unsafe host execution fails config validation; approved mode requires `approval_reason` and then re-enables the underlying AI CLI bypass flags.
  - `AICodingCliProvider`, review-loop skill invocation, and direct `echelon build/review/change/codegen/...` skill dispatch now share deterministic policy command construction; native opencode `--command speckit...` dispatch is preserved while sharing the same unsafe-bypass gate.
  - Remaining scope: this first pass deterministically gates known CLI bypass flags and prompt preamble disclosure; deeper file, network, and tool-call isolation still depends on each selected AI CLI runtime.
  - Focused tests added in `tests/unit/test_llm_tool_policy.py`, `tests/unit/test_cli_llm_tool_policy.py`, `tests/unit/test_llm_provider.py`, `tests/unit/test_review_loop.py`, and `tests/unit/test_config.py`.
  - Verification: `pytest tests/unit/test_cli_llm_tool_policy.py tests/unit/test_llm_tool_policy.py tests/unit/test_llm_provider.py tests/unit/test_review_loop.py tests/unit/test_config.py -q` (`61 passed`); `pytest tests/kernel -q` (`534 passed`).
- **EGR-004 sandbox suggestion report** — added a deterministic `harness.sandbox_suggestion` report before risky dependency install or app execution decisions.
  - The report records repository evidence, confidence label and score, suggested strategy and commands, risks, an explicit human approval point, and a fallback path for manual config.
  - `echelon harness init` now persists the structured report under `harness.sandbox_suggestion`, writes `sandbox-suggestion.md`, and surfaces its confidence and approval point in the init summary.
  - Focused tests added in `tests/unit/test_sandbox_suggestion.py` and `tests/unit/test_cli_harness_init_summary.py`.
  - Verification: `pytest tests/unit/test_sandbox_suggestion.py tests/unit/test_cli_harness_init_summary.py tests/unit/test_harness_init_verify.py tests/unit/test_harness_init_app_runtime.py tests/unit/test_init.py -q` (`20 passed`); `pytest tests/kernel -q` (`534 passed`).
- **EGR-005 typed blocked decisions** — blocked squad runs now persist machine-readable `blocked_decision` data alongside the existing human-readable escalation question.
  - Captures answer type (`free_text` or `choice`), normalized options, recommended/default answer when present, supported risk levels, blocked phase/reason, and stable blocked-at metadata.
  - `echelon resume` now records `resume_metadata`, marks the blocked decision resolved, preserves existing choice-option routing, and supports free-text blocked decisions without requiring executable options.
  - File-based harness escalations now include JSON `Decision Metadata` and `Resume Metadata` sections while preserving the Markdown answer flow.
  - Focused tests added in `tests/unit/test_blocked_decision.py`, `tests/unit/test_escalation.py`, `tests/unit/test_cli_resume_escalation_options.py`, and `tests/kernel/test_squad_state.py`.
  - Verification: `pytest tests/unit/test_blocked_decision.py tests/unit/test_escalation.py tests/unit/test_cli_resume_escalation_options.py tests/unit/test_cli_continue.py tests/unit/test_cli_next_step_escalation.py tests/kernel/test_squad_state.py tests/integration/test_squad_controller.py -q` (`145 passed`); `pytest tests/kernel -q` (`534 passed`).
- **EGR-006 reusable repair-loop primitive** — added `src/harness/repair_loop.py` as a deterministic Draft output -> Critique -> Repair -> Re-check -> Accept / Block / Exhaust substrate for harness feedback loops.
  - The primitive is LLM-agnostic: callers provide critique, repair, and re-check functions while the harness bounds iterations, records structured events, tracks token counts, and blocks repeated critique signatures before infinite loops.
  - This intentionally lands as a small substrate first; Ralph/review-loop controller rewiring can now use a tested primitive instead of introducing a risky large-controller refactor.
  - Focused tests added in `tests/unit/test_repair_loop.py`.
  - Verification: `pytest tests/unit/test_repair_loop.py -q` (`4 passed`); `pytest tests/kernel -q` (`534 passed`).
- **EGR-007 deterministic knowledge-base memory validation** — added `src/codegen/memory/kb_schema_validator.py` to validate durable knowledge-base and pending-operation records before future internalization writers apply them.
  - Covers documented schema versions, append-only markers, required provenance, internalization-log gate metadata, pending-operation checksum/provenance requirements, and project scoping for durable pattern/pitfall learnings.
  - `knowledge-base/kb-schema.md` now points to the Python validator as the deterministic enforcement point for durable memory writes.
  - Focused tests added in `tests/unit/test_kb_schema_validator.py`.
  - Verification: `pytest tests/unit/test_kb_schema_validator.py -q` (`5 passed`); `pytest tests/kernel -q` (`534 passed`).
- **EGR-008 routed role contract validation** — added `src/harness/role_contracts.py` to validate routed squad roles against machine-checkable `echelon_result` and output declarations.
  - `PhaseGraph` now preserves phase `outputs` from `extension/workflow/definition.yaml` so deterministic checks can inspect declared artifacts.
  - Routed agent prompts now include explicit `state_updates: {}` in their final output templates when no state mutation is expected.
  - Build-phase workflow nodes now declare outputs for implementation, spec-guard, code-review, test-guardian, progress, and integration roles.
  - Focused tests added in `tests/unit/test_role_contracts.py` with coverage for missing result fields, missing declared outputs, and the shipped routed-role surface.
  - Verification: `pytest tests/unit/test_role_contracts.py tests/kernel/test_phase_graph.py -q` (`18 passed`); `pytest tests/kernel -q` (`535 passed`).
- **EGR-010 deterministic GitOps secret scan gate** — added `src/harness/secret_scan.py` to detect high-confidence secret patterns before GitOps commits.
  - `GitOpsManager.commit()` now stages changes, scans the staged file set, and blocks the commit with a sanitized error summary when findings are present.
  - The scanner covers GitHub tokens, GitLab personal access tokens, AWS access key IDs, Slack tokens, and private-key headers while skipping binary files and never storing matched secret text in findings.
  - Focused tests added in `tests/unit/test_secret_scan.py`; `tests/integration/test_gitops_safety.py` now covers secret-scan commit blocking.
  - Verification: `pytest tests/unit/test_secret_scan.py tests/integration/test_gitops_safety.py::TestSecretScanGate -q` (`5 passed`); `pytest tests/integration/test_gitops_safety.py tests/integration/test_gitops_commit_push.py tests/unit/test_secret_scan.py -q` (`11 passed`); `pytest tests/kernel -q` (`535 passed`).
- **EGR-011 per-phase `state_updates` allowlists** — added machine-checkable allowlists to routed workflow phases and enforced them before state mutation.
  - `validate_echelon_result()` now accepts an optional `allowed_state_update_keys` set and rejects unexpected top-level `state_updates` keys while preserving reserved-key checks.
  - `SquadStateStore.advance()` now revalidates agent results with the current phase allowlist before mutating `state.json`.
  - Staged and conditional executor paths now validate intermediate agent results before applying executor-side direct state writes.
  - `PhaseGraph` preserves `allowed_state_updates` from `extension/workflow/definition.yaml`, and `role_contracts` now fails routed roles that omit a state-update allowlist.
  - Focused tests added in `tests/kernel/test_echelon_result_schema.py`, `tests/kernel/test_squad_state.py`, `tests/kernel/test_phase_graph.py`, `tests/kernel/test_squad_executors_journal.py`, and `tests/unit/test_role_contracts.py`.
  - Verification: `pytest tests/kernel/test_echelon_result_schema.py tests/kernel/test_squad_state.py tests/kernel/test_phase_graph.py tests/unit/test_role_contracts.py -q` (`82 passed`); `pytest tests/kernel/test_squad_executors_journal.py -q` (`39 passed`); `pytest tests/kernel -q` (`540 passed`).
- **EGR-012 pre-dispatch state-update validation** — pre-dispatch agents now use the same per-phase `state_updates` allowlist validation as staged and conditional executor paths before any direct state write.
  - Invalid pre-dispatch results now return a blocked executor result before journal or state mutation, preventing unauthorized keys from entering `state.json`.
  - Valid pre-dispatch updates that are declared in the parent phase allowlist continue to apply normally.
  - Focused tests added in `tests/kernel/test_squad_executors_journal.py`.
  - Verification: `pytest tests/kernel/test_squad_executors_journal.py -q` (`41 passed`); `pytest tests/kernel/test_echelon_result_schema.py tests/kernel/test_squad_state.py tests/kernel/test_phase_graph.py tests/unit/test_role_contracts.py tests/kernel/test_squad_executors_journal.py -q` (`123 passed`); `pytest tests/kernel -q` (`542 passed`).
- **EGR-013 deterministic COMMANDER judgment update validation** — COMMANDER judgment `state_updates` now pass through a narrow judgment-specific allowlist before mutation.
  - Routing judgments may still return `next_phase`/`phase`, and documented control updates such as `iteration`, escalation metadata, and fallback recovery keys remain allowed.
  - Invalid judgment keys now block the run before state mutation; banzai escalation cleanup preserves intentional null-as-delete behavior only after allowlist validation.
  - Focused tests added in `tests/integration/test_squad_controller.py`.
  - Verification: `pytest tests/integration/test_squad_controller.py -q` (`64 passed`); `pytest tests/kernel/test_echelon_result_schema.py tests/kernel/test_squad_state.py tests/kernel/test_squad_executors_journal.py tests/integration/test_squad_controller.py -q` (`167 passed`).
- **EGR-014 allowed `state_updates` prompt disclosure** — agent prompts now include the full allowed state-update key list enforced by the harness.
  - Normal agent, pre-dispatch, staged consensus, and conditional sequential prompts all render an explicit "Allowed state_updates for this dispatch" block before the canonical `echelon_result` template.
  - Empty allowlists are shown as `state_updates: {}`, and prompts warn that unexpected top-level update keys block the run.
  - Focused tests added in `tests/kernel/test_squad_executors_journal.py`.
  - Verification: `pytest tests/kernel/test_squad_executors_journal.py -q` (`47 passed`); `pytest tests/kernel -q` (`548 passed`); `pytest` (`2318 passed, 22 skipped`).
- **EGR-015 normal agent pre-journal validation** — normal `AgentExecutor` dispatches now validate `echelon_result.state_updates` against the phase allowlist before journal writes, cost accounting, or shadow-output recovery.
  - Invalid normal-agent update keys now block before mutating either `state.json` or `reasoning-journal.jsonl`, matching the pre-dispatch, staged, and conditional executor ordering.
  - Build-routing verdicts `CHANGES_REQUESTED` and `NEEDS_CONTEXT`, plus build progress routing keys, are now explicit deterministic contracts instead of tolerated late-routing assumptions.
  - Focused tests added in `tests/kernel/test_squad_executors_journal.py`.
  - Verification: `pytest tests/kernel/test_squad_executors_journal.py -q` (`48 passed`); `pytest tests/integration/test_squad_controller.py::TestBuildPhaseRouting -q` (`13 passed`); `pytest tests/kernel/test_echelon_result_schema.py tests/kernel/test_squad_executors_journal.py tests/kernel/test_phase_graph.py -q` (`76 passed`); `pytest tests/kernel -q` (`550 passed`); `pytest` (`2320 passed, 22 skipped`); `bash tests/run-all.sh` (`678 passed` on retry after a transient prompt-budget shell-test failure passed directly).
- **EGR-016 workflow-definition validation** — added deterministic validation for the executable `workflow/definition.yaml` phase graph before runtime dispatch.
  - `src/harness/workflow_validator.py` now rejects non-object transitions, unsupported transition keys such as `guard`, missing or unknown transition targets, unsupported condition syntax, non-string actions, and non-object `state_update` blocks.
  - `scripts/bash/dry-run.sh` now runs the workflow contract validator as a structural preflight when the Python harness source is available.
  - Focused tests added in `tests/kernel/test_workflow_validator.py`.
  - Verification: `pytest tests/kernel/test_workflow_validator.py tests/kernel/test_phase_graph.py -q` (`35 passed`); direct workflow validation reported `workflow definition valid`; `bash -n scripts/bash/dry-run.sh` passed.
- **EGR-017 tool-policy documentation drift** — updated `README.md` so terminal CLI documentation matches the fail-closed host LLM tool-policy contract.
  - The README no longer describes Claude as always running with `--dangerously-skip-permissions`.
  - It now documents that unsafe provider bypass flags are only added when `harness.llm.tool_policy.allow_unsafe_host_execution: true` is configured with an `approval_reason`.
  - Focused regression test added in `tests/unit/test_readme_tool_policy_docs.py`.
- **EGR-018 Python journal-entry validation** — added a Python validator for reasoning-journal entries and wired both Python journal writers through it.
  - `src/harness/journal_entry_validator.py` validates registered entry types against `extension/workflow/journal-entry-types.yaml`, preserves unknown types with warnings, and mirrors the existing DR-001 warn-then-allow behavior for registered entries missing required data fields.
  - `src/harness/squad_executors.py` and `src/harness/squad.py` now append canonical `schema_warning` sibling entries when invalid registered journal entries are returned by agents or COMMANDER judgment dispatches.
  - Focused tests added in `tests/unit/test_journal_entry_validator.py` and `tests/kernel/test_squad_executors_journal.py`.
  - Verification: `pytest tests/unit/test_journal_entry_validator.py tests/kernel/test_squad_executors_journal.py tests/integration/test_journal_append_helper.py -q` (`58 passed`); `pytest tests/kernel -q` (`572 passed`).
- **EGR-023 strict journal-entry runtime handling** — tightened Python journal writers so invalid registered entries are quarantined instead of persisted as first-class journal records.
  - `prepare_journal_entries_for_append()` now supports an explicit `invalid_registered_policy="quarantine"` mode while preserving DR-001 warn-then-allow as the default helper behavior for shell compatibility.
  - Squad and COMMANDER Python journal writers use quarantine mode: invalid registered entries are replaced by canonical `schema_warning` entries, while unknown future types remain preserved.
  - The canonical `echelon_result` template now shows schema-complete `journal_entries.data` for the registered `insight` type instead of the old sparse `type: <entry_type>` example.
  - Focused tests added/updated in `tests/unit/test_journal_entry_validator.py` and `tests/kernel/test_squad_executors_journal.py`.
  - Verification: `pytest tests/unit/test_journal_entry_validator.py tests/kernel/test_squad_executors_journal.py tests/integration/test_journal_append_helper.py -q` (`60 passed`); `bash tests/unit/test-json-freshness.sh` passed; `pytest tests/kernel -q` (`573 passed`).
- **EGR-024 static journal prompt validation** — added deterministic validation for concrete `echelon_result.journal_entries` examples embedded in agent, command, phase, and template prompts.
  - `src/harness/journal_prompt_validator.py` scans YAML-shaped prompt examples and blocks concrete unregistered journal types or registered examples missing required `data` fields.
  - Prompt examples were migrated to schema-complete `data` payloads; RE completion examples now use the registered `phase_complete` type.
  - Added canonical registry entries for `phase_complete`, `constitution_created`, and `constitution_placeholder_fix`.
  - Focused tests added in `tests/unit/test_journal_prompt_validator.py`; `tests/kernel/test_prompt_references.py` now scans the shipped prompt surface.
  - Verification: `pytest tests/unit/test_journal_prompt_validator.py tests/kernel/test_prompt_references.py -q` (`46 passed`); `bash tests/unit/test-json-freshness.sh` passed; `pytest tests/kernel -q` (`574 passed`).
- **EGR-020 role catalog reconciliation** — reconciled the public architecture narrative with the current agent registry and workflow graph.
  - `README.md` now describes 53 registered agent roles and 45 active-routed manifest roles instead of the stale 41-agent claim.
  - Added `docs/agent-role-catalog.md` with grounded counts for registered roles, active-routed roles, manifest-only roles, workflow-only aliases, support prompt files, and layer totals.
  - Updated the technical dossier demo language so it no longer repeats the stale 41-agent narrative.
  - Added `tests/kernel/test_agent_role_catalog_docs.py` to derive counts from `extension/extension.yml`, `extension/workflow/definition.yaml`, and `extension/agents/`.
  - Verification: `pytest tests/kernel/test_agent_role_catalog_docs.py tests/unit/test_readme_tool_policy_docs.py -q` (`2 passed`); `bash tests/test-unit-registry-sync.sh` passed; `pytest tests/kernel -q` (`575 passed`); `pytest -q` (`2411 passed, 22 skipped`).
- **EGR-021 installed extension drift detection** — added a deterministic warning when terminal CLI commands see stale installed extension content.
  - `src/harness/extension_drift.py` fingerprints shipped extension files while ignoring project-local `echelon-config.yml` and `local-config.yml`.
  - Drift detection now requires a trusted source path: `ECHELON_EXTENSION_SOURCE`, an installed `.echelon-source.json` marker, or a verified editable checkout. Packaged installs without a known source stay silent instead of guessing a machine-local checkout.
  - `echelon status`, `echelon run`, `echelon continue`, and `echelon resume` now print an `EXTENSION DRIFT` banner with changed/missing/extra counts, sample paths, and the `specify extension update --dev ...` command when a trusted source is available.
  - Focused tests added in `tests/unit/test_extension_drift.py`; `tests/unit/test_cli_status.py` covers the operator-facing warning.
  - Verification: `pytest tests/unit/test_extension_drift.py tests/unit/test_cli_status.py tests/unit/test_readme_tool_policy_docs.py -q` (`19 passed`); `pytest tests/kernel -q` (`574 passed`); `pytest -q` (`2408 passed, 22 skipped`).

## [2.1.0] - 2026-05-17

### Added

- **Native brownfield extraction (re-* commands)** — absorbed the standalone `revenge` extension into echelon; no separate install required.
  - 12 new commands: `speckit.echelon.re-extract`, `re-retarget`, `re-plan-all`, `re-analyze`, `re-specify`, `re-verify`, `re-expand`, `re-validate`, `re-checklist`, `re-constitute`, `re-plan`, `re-tasks`
  - 8 bash extraction scripts in `extension/scripts/bash/re/` (structure, deps, git, configs, chunks, cross-repo, polyrepo discovery)
  - Node CodeGraph bridge at `extension/scripts/node/re/` for structural code intelligence
  - 3 presets: `echelon-brownfield-microservices`, `echelon-brownfield-cloud-native`, `echelon-brownfield-compliance`
  - Polyrepo support via `discover-repos.sh` auto-detection
  - Config under `re:` top-level key in `echelon-config.yml`
  - Test suite: 48 assertions across 3 brownfield integration test scripts

### Changed

- `extension.yml` version bumped `2.0.0` → `2.1.0`
- `GOLDDIGGER` agent now invokes `speckit.echelon.re-extract` (was `speckit.revenge.extract`)
- Config layer-2 overrides now written to `.specify/extensions/echelon/local-config.yml` under `re:` key
- Preflight probe renamed from `"revenge"` to `"brownfield"` — update any `degraded_mode_stack` strings accordingly
- `integration-smoke-test.sh`: `--revenge PATH` flag deprecated (brownfield is now built-in); accepted as no-op with warning

### Removed

- `revenge` optional tool dependency from `extension.yml` `requires.tools`
- Standalone `revenge/` extension directory (absorbed; the `revenge` spec-kit extension is now obsolete)

## [1.5.0] - 2026-04-27

### Added

- **MemPalace requirements memory** — wing-scoped, per-project semantic memory store backed by ChromaDB
  - `MemPalaceContext` dataclass — single source of truth for `wing`, `run_id`, and `palace_path` across the entire memory subsystem
  - `codegen requirements mine <spec>` — parse spec files (FR/NFR/AC/ADR/US IDs) and write drawers with real `source_file` paths for traceability
  - `codegen requirements search <query> --wing <name>` — semantic retrieval from mined requirements
  - `codegen requirements clean --from-wing <name>` — remove stale drawers by project path prefix; `--dry-run` preview support
  - `check_wing_collision()` — detects when a wing name is already used by a different project (checked at init time and mine time)
- **`echelon init` wing provisioning** — new step added to `echelon init` flow
  - Auto-suggests wing name from `git remote get-url origin` slug (fallback: `{dirname}-{hash6}`)
  - Interactive confirm with collision check; force-accept by entering same name twice
  - Idempotent: skips if `mempalace.wing` already set in `echelon-config.yml`
  - Wing written to `echelon-config.yml` and committed with the project — all clones inherit it automatically
- **Endocrine system fully enabled by default** — opt-out model (was opt-in)
  - `endocrine.sh get_enabled()` defaults to `"true"` when key absent; explicitly disable with `enabled: false`
  - `echelon.run.md` endocrine call is now unconditional
  - `config-template.yml` updated belief: phase 3 (all 6 hormones) is the validated default
- Integration tests: 7 tests covering MemPalace mine/search round-trip, wing isolation, SHA256 drawer ID format, collision detection, requirements clean
- E2E tests: 17 tests covering CLI subprocess mine/search/clean and PipelineEngine wing threading with mocked SOAR bridge
- `docs/superpowers/specs/2026-04-27-mempalace-integration-fix-design.md` — design doc
- `docs/superpowers/plans/2026-04-27-mempalace-integration-fix.md` — implementation plan
- `tests/fixtures/mempalace/spec-alpha.md`, `spec-beta.md` — fixture specs for integration/e2e tests

### Fixed

- **SHA256 drawer_id** (Critical) — `MemPalaceWriter._write_drawer()` was using MD5[:16] while `add_drawer` uses SHA256[:24]; drawer IDs never matched, making `backfill_run_outcome()` and `backfill_status()` completely broken
- **Deterministic chunk_index** (Medium) — replaced `hash(run_id) & 0xFFFF` (non-deterministic across process restarts due to Python hash randomisation) with `int(sha256(run_id).hexdigest(), 16) & 0xFFFF`
- **Wing collision** (Critical) — `PipelineEngine._get_mempalace_writer()` was deriving wing from `state_file.parent.name` which returns `""` for a relative path, falling back to `"codegen"` — all projects shared the same wing
- **Dead memory-config.yml** (Low) — `install.sh` was writing `~/.echelon/memory-config.yml` which `MempalaceConfig()` never read (reads `~/.mempalace/config.json`); dead write removed
- `PhaseGateRunner` wing derivation via dead `_memory_config.wing` replaced with state-file read (`state.get("wing")`)
- `MemPalaceReader`, `MemPalaceWriter`, `RequirementsMiner`, `PipelineEngine`, `PhaseGateRunner`, `codegen CLI` all use `MemPalaceContext` — no more scattered `wing=` / `run_id=` kwargs
- `_read_state()` in `PipelineEngine` now deserialises `wing` field from `codegen-state.json` (resume preserves wing)
- `RequirementsMiner` now passes actual `source_file` path to `MemPalaceWriter.write()` — enables `requirements clean` to correctly identify and delete project-specific drawers

### Changed

- `MemPalaceReader.__init__` — takes `ctx: MemPalaceContext` instead of `wing: str`; uses `ctx.palace_path` directly
- `MemPalaceWriter.__init__` — takes `ctx: MemPalaceContext` instead of `(wing, run_id)`; methods renamed `_mcp_write` → `_write_drawer`, `_mcp_update_metadata` → `_update_drawer_metadata`
- `RequirementsMiner.__init__` — takes `(ctx: MemPalaceContext, project_dir: Path)` instead of `(wing, run_id)`
- `PipelineEngine` — new `set_context(ctx)` method; `wing` field added to `PipelineState`; `run_re_phase` and `search_requirements` take `ctx` instead of `wing`
- `echelon.codegenlight.md` — `WING=$(basename $(pwd))` replaced with python snippet reading `mempalace.wing` from `echelon-config.yml`
- `extension/echelon-config.yml`, `extension/config-template.yml` — `mempalace: { wing: "" }` block added
- `README.md` — new `### MemPalace requirements memory` subsection under Codegen Pipeline
- `INSTALLATION.md` — new `Per-project setup: wing provisioning` and `Mine requirements into MemPalace` sections

### Migration

Existing projects with drawers stored under wing `"codegen"` (the broken default):

```bash
# 1. Set wing in echelon-config.yml
echelon init

# 2. Re-mine specs under correct wing
codegen requirements mine specs/*.md

# 3. Optional: remove old "codegen" wing drawers
codegen requirements clean --from-wing codegen --project-dir .
```

## [1.0.0] - 2026-04-25

### Added

- **harness consolidated** — `echelon-harness` repo merged into `echelon`; `echelon-harness` is deprecated
  - `src/harness/` — full execution substrate (38 Python modules: docker sandbox, GitOps, ralph-loop, review loop, GC, CLI, skills)
  - `extension/commands/harness.{init,run,status,resume}.md` — 4 harness skill commands
  - `network/` — Squid proxy config assets for sandbox network policy
  - `scripts/docker-{gc,network,sandbox}.sh`, `sandbox-exec.sh` — sandbox lifecycle helpers
  - All harness tests migrated: unit (33), integration (11), contract (1), shim (5), e2e (6), fixtures
  - `echelon harness init/run` — harness subcommands merged into the `echelon` CLI; `harness` binary removed
- **Single config file** — `harness:` section added to `echelon.yml`; `harness-config.yml` eliminated
  - `echelon harness init` writes into the `harness:` section of `echelon.yml` (merging with existing squad settings)
  - `harness.llm.config_dir` — sets `CLAUDE_CONFIG_DIR` for Claude invocations (persistent alternative to env var)
- `docs/soar-delivery.md` — FR-019-001 SOAR state delivery documentation (delivery gate)
- `codegen` CLI absorbed into echelon (`src/codegen/`) — SOAR-powered build pipeline now bundled
- `understanding` CLI absorbed into echelon (`src/understanding/`) — 31-metric requirements quality analysis now bundled
- `scripts/install.sh` — single installer: downloads SOAR 9.6.4, creates `~/.echelon/venv/`, installs all 4 CLIs
- `INSTALLATION.md` — prerequisites, verify, upgrade, uninstall instructions
- 5 `speckit.echelon.understanding-*` commands added to extension (`scan`, `validate`, `energy`, `diagram`, `batch`)
- `before_plan` hook: `speckit.echelon.understanding-scan` (runs quality scan before planning)
- Single extension registration: `specify extension add --dev ~/echelon/extension`

### Changed

- `scripts/install.sh` — harness now installed from main package; sibling-dir lookup removed; all 4 CLIs installed unconditionally
- `extension/extension.yml` — 4 harness commands + docker/git tool requirements + single `echelon.yml` config entry
- Extension assets consolidated into `extension/`: `config-template.yml`, `agents.yaml`, `echelon-config.yml`, `.extensionignore` — root duplicates removed
- `*.egg-info/` added to `.gitignore`
- Extension moved from root to `extension/` subfolder (`agents/`, `commands/`, `extension.yml`)
- Runtime state directory: `~/.codegen/` → `~/.echelon/` (memory, SOAR binary, venv, config)
- `pyproject.toml` added — unified package with all 4 CLI entry points
- Understanding v3.6 integration: Depth quality gate (>= 0.30) in config-template and SAGE
- SAGE references updated from 31 to 34 metrics (Understanding v3.6 adds Depth category)
- Build and verify command guidance updated (dependency-safe lanes, QA entry gate, deterministic QA completion)

### Fixed

- `test_belief_parser.py` — fixture expiry dates were in the past (×2)
- `test_soar_seed_rules.py` — expected `COMMANDER.md` at repo root; delivery doc moved to `docs/soar-delivery.md`
- `test_llm_provider.py` — `shutil.which` PATH resolution made tests environment-dependent (×2); `shutil.which` now mocked
- `dry-run.sh` and `kb-validate-evolution.sh` — `agents.yaml` path updated after move to `extension/`

## [0.3.0] - 2026-03-21

### Added

- 7-layer agent architecture: Control, Exploration, Feasibility, Solution, Specialists, Build, Learning
- 35 agents with codename system (SCOUT, SAGE, CARTOGRAPHER, GATEKEEPER, ARCHITECT, ORCHESTRATOR, etc.)
- Fallback mode with graceful degradation when spec-kit unavailable
- Knowledge base management: locking, checksums, pending queue, recovery
- KB schema validation (kb-schema.md) and evolution validation (kb-validate-evolution.sh)
- BUILD/QA split workflow with deterministic light gates
- Phase timing telemetry with budget tracking and anomaly detection
- Dry-run health check script (dry-run.sh)
- Preflight dependency detection (preflight-speckit.sh)
- Unit tests (80+), integration tests (41+), benchmarks
- NEVER rules in agent prompt files for role separation enforcement
- TRACKER dispatch for user-intent alignment
- state.json split_metrics initialization (prevents stale data carry-forward)
- Pre-dispatch enforcement gate (Tier 1, bash-based)

### Changed

- Extension version: 0.2.0 → 0.3.0
- Agent naming: functional names (DISCOVER, WHY, WHAT) → codenames (SCOUT, SAGE, CARTOGRAPHER)
- agent-scores.yaml: migrated to codename keys
- calibration-profile.yaml correction_factor_max: 3.0 → 6.0
- Staging directory cleared on init to prevent cross-run contamination

### Fixed

- dry-run.sh false failures (14) caused by old functional names in FLOW array
- GATEKEEPER intent-check NEVER rule now has required user-intent.md input
- loc-estimation correction factor uncapped (was 3.0, observed need ~5x)

## [0.1.0] - 2026-03-16

### Added

- Initial release
- 7 core agents: MANAGER, DISCOVER, WHAT, WHY, ASSESS, HOW, PLAN
- 7 specialist agents: SCIENTIST, SECURITY, TEST ARCHITECT, DOMAIN EXPERT, UX/A11Y, PERFORMANCE, INNOVATE
- 4 learning layer agents: REFLECT, EVOLVE, CALIBRATE, GROUND
- FEEDBACK intake for post-implementation learning
- 7 slash commands: run, status, innovate, investigate, ground, feedback, resume
- Reasoning journal (JSON) for inter-agent communication
- YAML knowledge base with patterns, estimates, pitfalls, calibration
- Evidence quality grading system (A-E)
- State machine with convergence detection and human escalation
- Brownfield support via spec-kit-revenge
- Greenfield support via domain research pipeline
- Implementability check in ASSESS2 consensus phase

### Requirements

- Spec Kit: >=0.3.0
- Optional: Understanding CLI >=3.4.0
- Optional: spec-kit-revenge >=1.0.0

[Unreleased]: https://github.com/Testimonial/echelon/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Testimonial/echelon/releases/tag/v0.1.0
