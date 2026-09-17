# Discovery Producer Contract Checkpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for the user's selected inline execution. Implement sequentially with an independent read-only review at the checkpoint exit.

**Goal:** Define and consume discovery proposal/author/review contracts without activating managed runtime execution.

**Architecture:** Closed assignment-bound replies carry semantic proposals and candidate text. A pure translator creates existing typed candidate artifacts and create/revise requests; the existing identity preview remains the structural checker. Two neutral Prosaic roles supply semantic protocols, not orchestration.

**Tech Stack:** Python, pytest, Prosaic, existing identity parsers and real temporary SQLite authorities.

**Spec:** `docs/superpowers/specs/2026-09-14-managed-discovery-integration-design.md`, approved after commit `b57e4c60`.

## Global Constraints

- This checkpoint adds no producer dispatch, reservation writer, runtime selector, public flag or managed enrollment.
- Python owns IDs, state, publication and completion; proposals are not allocation or acceptance authority.
- U/A create and same-subject revise only. Keep literal legacy IDs and existing six-digit-minimum/unbounded allocation.
- Reuse typed artifact/lifecycle/candidate APIs. No second parser, allocator, publisher or history model.
- No Markdown placeholders, automatic renumbering, provider-specific prose or native agent lookup.
- Legacy SCOUT, AGENTS.md/CLAUDE.md, mode/default policy and stopped smoke workspace stay unchanged.
- No installation, live calls, push, merge or deferred capability expansion.
- Keep `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract` on `fix/delivery-controller-contract`.
- Use `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python`. Baseline: 117 relevant tests passed in 13.25s.

## Task 1 — Closed semantic envelopes

**Files:** Create `src/harness/discovery_semantics.py`, `tests/unit/test_discovery_semantics.py`.

**Interfaces:** Frozen `DiscoveryAssignment(operation_id, dispatch_id, spec_id, run_id, step, input_fingerprint, artifact_paths, editable_revisions=(), assigned_ids=())`, with `identity() -> dict`. `parse_discovery_reply(raw, assignment) -> dict`; `validate_discovery_reply(value, assignment) -> dict` returns detached data.

- [x] Write RED tests for proposal/author/review, exact binding, duplicate JSON keys, invalid types/versions, nonfinite/deep/oversize/unencodable input, read/blocked envelopes and forbidden authority fields.

```python
assignment = DiscoveryAssignment('op', 'turn', 'game', 'run', 'propose', 'a' * 64,
    ('unknowns.md',), (('U-001', '1'),))
value = {**assignment.identity(), 'action': 'final', 'new_subjects': [
    {'key': 'lighting', 'kind': 'U', 'subject': 'Lighting choice', 'caption': 'Lighting choice'}],
    'revisions': []}
assert parse_discovery_reply(json.dumps(value), assignment)['new_subjects'][0]['key'] == 'lighting'
```

- [x] Run `python -m pytest tests/unit/test_discovery_semantics.py -xq`; confirm missing-boundary RED.
- [x] Implement closed schemas: proposal `new_subjects`/`revisions`; author exact `artifacts`; reviewer overall `verdict`/`reason` and exact per-ID `assessments` (`id`, `verdict`, `reason`, `evidence`). A rejected assessment cannot yield overall accept. The existing host reader validates `read.request`.

```python
if any(value.get(key) != expected for key, expected in assignment.identity().items()):
    raise ValueError('discovery assignment binding mismatch')
```

- [x] Validate proposal handles separately from IDs, preserve literal IDs and decimal revision strings, sort proposal keys/revisions deterministically, and restrict author paths to the six existing outputs. Retain the existing 256-KiB semantic capture ceiling; artifact text preserves UTF-8/CRLF and rejects NUL.
- [x] Run new tests with fulfillment semantic and identity codec regressions; inspect the diff.

## Task 2 — Real candidate/lifecycle consumption

**Files:** Create `src/harness/discovery_candidate.py`, `tests/unit/test_discovery_candidate.py`.

**Interfaces:** Frozen `DiscoveryReservation(key, element_id, operation_id)`. `author_artifacts(assignment, reply, *, before) -> tuple[CandidateArtifact, ...]`. `build_discovery_changes(assignment, reply, *, reservations, artifacts, existing_subjects) -> tuple[ElementCreate | ElementRevision, ...]`. Inputs are captured caller claims, not authenticated state.

- [x] Write RED tests that use actual `IdentityStore.reserve`, parse producer replies, translate lifecycle requests and call real `preview_identity_candidate` with `PublicationOperation` and `IdentityEditScope`.

```python
label, = store.reserve(spec_id='game', kind='U', operation_id='reserve', count=1)
assert label == 'U-000001'
operations = (PublicationOperation('lifecycle', 'candidate', encode_request('lifecycle', changes)),)
preview = store.preview_identity_candidate(spec_id='game', artifacts=artifacts,
    scope=IdentityEditScope(('unknowns.md',), (label,), ('unknowns.md',)), operations=operations)
assert not preview.check.diagnostics
assert preview.history is not None
assert store.lookup(spec_id='game', element_id=label) is None
```

- [x] Run `python -m pytest tests/unit/test_discovery_candidate.py -xq`; confirm RED.
- [x] Use `parse_identity_artifact` to match every proposal key to one distinct reserved ID of the right kind and exact caption. Construct `ElementCreate` from parsed content. Revisions require captured before/after definitions, unchanged captions and explicit expected revision/subject; skip byte-identical revisions. No storage writers.

```python
change = ElementCreate(binding.element_id, proposal['subject'], declaration.content, binding.operation_id)
```

- [x] Exercise missing/extra/duplicate reservations, wrong kinds, caption drift, missing/duplicate definitions, unreserved IDs, stale revisions, scope and reference failures through real consumers. Assert no canonical/history mutation. No durable request association or semantic approval is claimed.
- [x] Run the new suite plus existing discovery candidate, coherent preview and graph/publication composition regressions.

## Task 3 — Neutral profiles and acceptance

**Files:** Create `prosaic/subagents/echelon.discovery-producer.md`, `prosaic/subagents/echelon.discovery-reviewer.md`; register inactive profiles in `runtime/workflow/definition.yaml`; update parent design and convergence receipts.

- [x] Author paired ALWAYS/NEVER protocols. The producer handles only the host-selected propose/author operation. Reviewer checks meaning, scope and references, never publication success. Neither dispatches, allocates, writes files/state or emits completion markers. Handles never enter Markdown.

```yaml
name: echelon.discovery-producer
execution: agent
tools: read
model_tier: balanced
effort: medium
```

Reviewer uses `model_tier: strong`, `effort: high`; execution permissions stay in adapters.

- [x] Inspect both artifacts with the existing Prosaic CLI without installation. Run existing loader regressions; do not claim text-search checks establish model behavior. Composed provider consumption belongs to runtime acceptance.
- [x] Obtain independent read-only review, correct demonstrated defects with RED tests, run all new suites with identity candidate/lifecycle/codec/preview, graph/publication, Prosaic loader and fulfillment semantic regressions, and `git diff --check`.
- [x] Record receipts and commit `feat: define managed discovery producer contracts`. Preserve branch/worktree.

## Following checkpoints in the approved design

1. Durable selected operation, genesis, reservation intent/mapping, bounded provider turns, semantic receipts and accounting through existing writers/adapters.
2. Guarded graph/source/identity publication through real Squad completion/recovery, internal discovery admission and unsupported next-phase blocking.
3. Durable targeted repair and both-provider/mode acceptance through the actual controller, including original smoke failure and crash boundaries.

These are not completed by this plan. Public activation, other families and live tests stay separate. The contract checkpoint is deliberately inactive; pure translation cannot claim source authentication, durable association, semantic review or publication authority.

## Self-review and receipts

Interfaces are shared across Tasks 1–2; Task 3 supplies only neutral role content. All checkpoint requirements have an owning task. Inline execution is already selected. Review and test receipts will record the actual acceptance boundary.

### Completed checkpoint evidence

Missing-module REDs preceded both implementations. A direct-validator coercion
case then failed before correction; accepted values are detached without turning
invalid tuple collections into JSON arrays. The final affected batch passed
**551 tests in 28.36s**, including **94 new tests**. This includes real U/A
reservations (`A-000001`, `U-1000000`), exact legacy/wide labels, CRLF content,
new/revised candidate consumption, rejected stale/forged claims and unchanged
stored history. Existing codec/lifecycle/coherent preview, graph/publication,
Prosaic loader and fulfillment semantic regressions passed in that same batch.

Actual Prosaic inspection accepted both new neutral profiles without deployment.
Independent read-only review found no Critical/Important/Minor defects and
additionally exercised all six output artifacts with fresh U/A creation through
the real preview. `git diff --check` passed. No Squad, completion, identity store,
legacy SCOUT or provider execution path was changed. This is contract/translation
acceptance only, not durable reservation association or managed runtime success.
