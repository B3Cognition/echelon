# Delivery Controller Phase 1 Implementation Plan

> Execute inline, one tested change at a time. The user authorized phased repair;
> this plan covers the first reviewable phase only.

**Goal:** Resolve delivery command identity before provider invocation and block
invalid command setup without falling back to ambiguous COMMANDER instructions.

**Architecture:** A strict delivery resolver uses the existing Prosaic loader and
role-neutral rendering. The strategy coordinator loads it lazily for actual build
or repair execution and records a recoverable setup block on failure.

**Tech Stack:** Python, Prosaic command artifacts, pytest, existing StateStore.

**Spec:** `docs/superpowers/specs/2026-09-11-delivery-controller-ownership-design.md`

## Global Constraints

- Keep each phase separately testable and do not label the full issue fixed
  before controller-enforced reviews and recovery are active.
- Preserve canonical spec/task identities and existing target containment.
- Reuse Prosaic loading, provider adapters, and atomic state primitives.
- Do not change provider configuration, install dependencies, or run a live
  delivery against user projects as part of offline validation.
- Test consuming behavior at the external provider boundary; prose substring
  assertions do not prove orchestration or review completion.

## Task 1: delivery-specific command resolution

Files: add `src/harness/delivery_prompt.py` and
`tests/unit/test_delivery_prompt.py`; amend `src/harness/prompt_framing.py` and
`src/harness/prosaic_prompt_loader.py`.

Interface:

```python
class DeliveryPromptError(RuntimeError): ...

def resolve_delivery_build_prompt(
    build_command: str, arguments: str, project_dir: Path,
) -> str: ...

# Existing render API gains one optional keyword, preserving all defaults.
ProsaicPromptLoader.render_command(artifact, arguments, *, preamble=COMMANDER_PREAMBLE)
```

- [x] Add tests that load an actual temporary canonical bundle, substitute
  arguments, inline companions, and render through the real loader. Stub only
  the external `prosaic inspect` process. Assert the dispatched role comes from
  the selected body, and ordinary command rendering retains compatibility.
- [x] Cover missing bundles, empty bodies, mismatched artifact names,
  malformed inspect output, unresolved companions, unsupported commands, and
  preserved literal arguments. Each failure must raise DeliveryPromptError.
- [x] Run the new tests and observe failures before implementing the resolver.
- [x] Implement command validation, existing-loader integration, and typed errors.
  Use a role-neutral delivery preamble; do not assign a second role in Python.
- [x] Run resolver, Prosaic loading, and skill-loader tests.

## Task 2: integrate at the actual delivery boundary

Files: amend `src/harness/coordinator.py`, `src/harness/visual_ralph.py`, and
`src/echelon/cli.py`; cover coordinator behavior in
`tests/unit/test_delivery_prompt.py`, visual accounting in
`tests/unit/test_visual_ralph.py`, and continuation in
`tests/unit/test_cli_harness_resume.py`.

- [x] Add coordinator tests proving an invalid build command prevents Ralph/provider
  invocation and persists `delivery_prompt_invalid` with a diagnostic, leaving
  the state lock released. Use the real StateStore and fake external execution.
- [x] Add a downstream-resume test proving successful finalization does not load
  a build command, plus a successful implementation case observing the resolved
  delivery prompt at Ralph's invocation boundary. Also capture dispatch through
  real Ralph and LlmBuildRunner at the fake external executor.
- [x] Observe the failing tests, then add a lazy cached prompt resolver inside
  strategy execution. Compose pending review repair content only when requested.
  Route initial builds, visual repair, and review repair through that resolver.
- [x] Catch DeliveryPromptError at the strategy boundary and persist the block
  in the active delivery phase. Keep existing lock release in `finally`.
- [x] Preserve downstream usage, pending review tasks, persisted verification,
  and fresh visual receipts through normal phase-result accounting. Record the
  setup diagnostic in the same transition as the block.
- [x] Recognize the blocker in continue/resume without Git recovery.
- [x] Run the coordinator, delivery-prompt, Prosaic-loader, skill-loader,
  LLM-build-runner, and build-quality-gate tests.

## Task 3: handoff and phase boundary

- [x] Review the diff for unintended direct-command/provider behavior changes.
- [x] Run whitespace checks and the targeted regression suite; record results.
- [x] Update this plan with completed checks and remaining phases. Explain that
  gate sequencing still runs through the legacy build invocation until Phase 2.
- [x] Commit the independently reviewable first phase on its isolated branch.
  Do not merge or install it into the user's runtime during offline validation.

## Validation record

- Final phase regression gate: **622 passed in 98.59 seconds** on 2026-09-11.
  `git diff --check` passed. This is the targeted gate below, not a claim that
  the full repository suite or a live delivery was executed.
- Resolver failures, coordinator dispatch failures, continuation handling, and
  the review-discovered malformed-companion/accounting cases were reproduced
  before their corresponding implementation changes.
- The independent review identified missing typed parse errors and downstream
  accounting/evidence loss; regression tests now cover each, and re-review
  reported no remaining critical or important findings.
- A real canonical artifact was inspected with installed Prosaic. Offline tests
  replace external processes/providers, not command loading or rendering.
- No live delivery, runtime installation, provider change, merge, or push is
  part of this checkpoint.

Reproduce the phase regression gate from this branch with the project's Python
test environment active:

```bash
python -m pytest -q \
  tests/unit/test_delivery_prompt.py \
  tests/unit/test_coordinator.py \
  tests/unit/test_coordinator_review_reentry.py \
  tests/unit/test_prosaic_prompt_loader.py \
  tests/unit/test_skill_loader_prosaic.py \
  tests/unit/test_llm_build_runner.py \
  tests/unit/test_build_quality_gate_sequence.py \
  tests/unit/test_visual_ralph.py \
  tests/unit/test_cli_harness_resume.py \
  tests/unit/test_cli_delivery.py \
  tests/unit/test_cli_continue.py \
  tests/unit/test_cli_resume_spec_context.py \
  tests/unit/test_ralph_inner.py \
  tests/unit/test_ralph_outer.py \
  tests/integration/test_polyrepo_delivery_convergence.py --tb=short
```

## Next checkpoint

Phase 2 introduces actual Python-owned slice selection and independent review
dispatch, with tests of routing and invalidation rather than prose assertions.
The current legacy build invocation still sequences its own review agents;
phase 1 must not be treated as proof those gates executed.
