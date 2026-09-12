# RE Knowledge Quality M4 Fresh-Run and Live-Smoke Plan

> **Execution note:** Implement inline with `superpowers:executing-plans`, one checked work package and commit at a time. Preserve historical protocol readers and keep provider selection behind Echelon's configured-provider facade.

**Goal:** Make the ordinary `echelon re run` action create, resume, synthesize, and publish repaired RE knowledge from a clean declared workspace, then validate the path with a budget-bounded Codex smoke run on the isolated MSA fixture.

**Architecture:** Add one controller-owned fresh-analysis constructor ahead of the existing reviewed protocol-2.8 analysis and protocol-2.7 publication lifecycle. It freezes the workspace snapshot and partition, derives non-semantic target authority directly from that snapshot, runs bounded discovery and an independent review per source through `KnowledgeLLMBackend`, activates the reviewed catalogue, and publishes the existing reviewed-analysis child manifest last. All phases share the same immutable logical request and aggregate resource authority. Existing protocol-specific commands and readers remain compatibility surfaces; they are not invoked to manufacture prerequisite knowledge.

**Tech stack:** Python 3.11+, pytest, existing RE v2 object/ledger stores, existing Prosaic prompt loader, `AICodingCliProvider` configured-provider facade.

---

## Task 1: Freeze honest snapshot-bootstrap authority

**Files:**
- Create: `src/harness/re_v2/knowledge_bootstrap.py`
- Modify: `src/harness/re_v2/protocol_28/authority.py`
- Modify: `src/harness/re_v2/protocol_28/preparation.py`
- Test: `tests/unit/test_re_v2_knowledge_bootstrap.py`
- Test: `tests/unit/test_re_v2_protocol_28_preparation.py`

- [x] Write failing tests proving a clean workspace snapshot and partition produce exactly one source target plus every discovered domain target, with identities bound to snapshot content and installed contracts rather than fabricated L2/L3 findings.
- [x] Add a versioned snapshot-bootstrap parent authority and target projection builder. Give each field a provenance/replay purpose; do not claim legacy analysis completion.
- [x] Reuse the existing protocol-2.8 compatibility envelope for the authenticated snapshot bootstrap, keeping old manifests and readers byte-identical rather than adding another parent union.
- [x] Prove cross-snapshot, unknown-source, exact-target, and content-identity failures before a child can be published; existing preparation retains its clean-source and complete-closure checks.
- [x] Run `pytest -q tests/unit/test_re_v2_knowledge_bootstrap.py tests/unit/test_re_v2_protocol_28_preparation.py tests/unit/test_re_v2_knowledge_activation.py` (41 passed).
- [x] Commit: `feat(re): add snapshot-backed reviewed analysis bootstrap`.

## Task 2: Compose recoverable discovery and independent review

**Files:**
- Create: `src/harness/re_v2/knowledge_creation.py`
- Modify: `src/harness/re_v2/knowledge_llm.py`
- Modify: `src/harness/re_v2/knowledge_revision.py`
- Test: `tests/unit/test_re_v2_knowledge_creation.py`
- Test: `tests/integration/test_re_v2_knowledge_creation.py`

- [x] Write failing tests for a two-source fresh request using scripted provider replies. Exercise real snapshot capture, evidence screening, acquisition, discovery, independent review, activation, preparation, manifest-last publication, crash/replay, and exact-source closure.
- [x] Load the neutral discovery and review role plus phase contracts through `ProsaicPromptLoader`; derive the configured strong model through the shared provider mapping, with no direct Codex selection or fallback.
- [ ] Construct one `KnowledgeDispatchAccount` for the logical request, one bounded acquisition/controller pair per selected source, and finite producer/reviewer repair turns. Reopening must reuse captured/applied work and must never reset attempts.
- [x] Persist a creation intent before provider dispatch and publish the reviewed protocol-2.8 child only after every source has reviewed authority. A malformed/unsafe result, unavailable provider, exhausted budget, or unsettled dispatch returns one closed reason and preserves recoverable state.
- [x] Transfer the discovery/review account exactly once into analysis resource authority. Ensure analysis cannot receive a fresh copy of the original ceiling; synthesis sharing is completed in Task 3.
- [x] Run `pytest -q tests/unit/test_re_v2_knowledge_creation.py tests/integration/test_re_v2_knowledge_creation.py tests/integration/test_re_v2_knowledge_revision_recovery.py` (101 creation/LLM/recovery tests passed in the combined run).
- [ ] Commit: `feat(re): create reviewed analysis from declared sources`.

## Task 3: Route the ordinary run and refresh journeys

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `src/harness/re_v2/knowledge_workflow.py`
- Modify: `src/harness/re_v2/knowledge_refresh.py`
- Test: `tests/unit/test_cli_re_knowledge_actions.py`
- Test: `tests/integration/test_re_v2_knowledge_end_to_end.py`

- [ ] Write failing CLI tests proving `echelon re run` creates a fresh reviewed request when none exists, resumes only a compatible active request, and creates a new immutable request when a stopped run binds obsolete inputs.
- [ ] Route changed-source refresh through the same constructor for the selected snapshot while retaining authenticated unchanged publication inputs. Preserve no-op refresh with zero provider calls and no generation increment.
- [x] Display effective depth, selected sources, configured provider, and aggregate ceilings before fresh dispatch. Report running/completed/completed-with-limitations/needs-attention without protocol or layer instructions.
- [x] Remove the ordinary run-creation release refusal only for this repaired path; leave explicit legacy commands routed by their pinned manifests. Refresh release routing remains below.
- [ ] Run `pytest -q tests/unit/test_cli_re_knowledge_actions.py tests/integration/test_re_v2_knowledge_end_to_end.py`.
- [ ] Commit: `feat(re): enable ordinary repaired run and refresh`.

## Task 4: Verify the full offline product contract

**Files:**
- Modify: `tests/integration/test_re_v2_knowledge_end_to_end.py`
- Modify: `tests/integration/test_re_v2_knowledge_refresh.py`
- Modify: `tests/unit/test_re_v2_knowledge_llm.py`

- [ ] Add a fresh A1 ordinary run followed by an A2 `re refresh` test. Assert removed facts disappear, changed contracts invalidate workspace relationships, an unchanged sibling is retained honestly, publication advances once, and old/new spec consumers stay pinned to their generations.
- [ ] Add failures for provider mismatch, unsupported constrained execution, secret canaries, dirty sources, insufficient aggregate budget, source changes during execution, and publication CAS races.
- [ ] Run the targeted RE suites, then `pytest -q tests/unit/test_re_v2_knowledge*.py tests/integration/test_re_v2_knowledge*.py`.
- [ ] Commit: `test(re): verify fresh run and refresh lifecycle`.

## Task 5: Install and run the authorized Codex MSA smoke

**Files:**
- Modify only if the live run exposes a reproducible product defect; add its regression beside the owning module before the fix.
- Record: `docs/superpowers/reports/2026-09-12-msa-re-smoke.md`

- [ ] Run the full relevant unit/integration suite and `bash scripts/bash/dry-run.sh`.
- [ ] Install the checkout with `bash scripts/install.sh`, refresh `/Users/michalbachorik/work/msa-re-smoke`, and verify its root plus all three selected source repositories are clean. Preserve every unrelated workspace and stash.
- [ ] Confirm the effective provider is Codex and run one `echelon re run --depth quick` trial under the existing default 5,000,000-token and 180-minute aggregate ceilings. Do not raise or duplicate the allowance.
- [ ] Observe the process, durable ledger, accepted analysis progress, synthesis, publication, and generated source/workspace documents. Inspect evidence support and limitations, not only completion counts.
- [ ] If a deterministic harness bug appears, stop, reproduce offline, fix via RED/GREEN, commit the work package, reinstall, and resume the same compatible request. If the default ceiling is genuinely insufficient, report the required absolute ceiling instead of raising it.
- [ ] Record actual provider/model, spend, duration, source cleanliness, document coverage, supported/unsupported claims, and any blocker without copying source secrets.
- [ ] Commit the smoke report and any proven fix separately. Do not claim the full three-trial M4 release gate from this single smoke run.

## Final verification

- [ ] `git status --short --branch` is clean in Echelon.
- [ ] The MSA smoke root and its three selected repositories are clean.
- [ ] `echelon re run --help` leads with depth and aggregate limits, not protocols/layers.
- [ ] Ordinary `echelon re run` either publishes usable source/workspace knowledge or returns one actionable, durable reason without a manual deepening/synthesis command.
- [ ] Report remaining M4 release evidence separately: synthetic known-answer live trials, repeated-run gate, and live A1-to-A2 refresh trials require their own explicit cumulative budget authorization.
