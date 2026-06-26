# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Fixed

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
- Added EGR-029 to track Phase 4 publishing/readiness drift: repaired runs can
  finish with complete run-local Phase A artifacts while the project-visible
  `specs/<id>-<slug>` directory remains stale, so build-ready guidance can point
  at incomplete harness inputs.

### Changed

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
