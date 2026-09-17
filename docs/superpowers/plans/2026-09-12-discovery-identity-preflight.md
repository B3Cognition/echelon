# Discovery identity candidate preflight implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reject the observed discovery question reassignment and deletion using real registry history, typed artifact facts and controller-supplied edit scope, without publishing or mutating anything.

**Architecture:** Add one read-only store API whose helper parses the captured before/after artifacts and validates them against the same transaction's current and projected lifecycle heads. Reuse the shared lifecycle planner; do not call public store APIs inside that transaction. The result reports structural diagnostics and retained reference assessment state, not semantic approval or publication authority. This first candidate checker supports discovery declarations only; it is not coverage for requirements, tasks, issue reports, derived Lexicon or JSON evidence.

**Tech Stack:** Python standard library, existing typed artifact adapters, SQLite identity authority and shared lifecycle planner, pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Existing labels, immutable subjects, revision history, lifecycle lineage and old evidence bindings remain unchanged.
- Ordinary discovery repair preserves question identity and subject headings. New questions require new allocated IDs.
- Helpers receive the caller-owned connection and never open another connection, allocate IDs, commit or write files.
- Structural preflight is not semantic verification or a durable publication receipt. Recording or matching a source hash cannot certify evidence.
- No canonical publication, graph/memory writes, provider routing, or live activation in this task.
- Unsupported candidate syntax or roles must produce explicit blocking diagnostics, never be silently accepted as covered.

---

### Task 1: read-only discovery candidate checking and smoke regression

**Files:** Create `src/harness/element_identity_candidate.py` for immutable inputs/results and pure scope/text checks; create `src/harness/element_identity_candidate_store.py` for connection-owned discovery checks; extend `src/harness/element_identity_store.py` with a thin read-transaction API. Create `tests/unit/test_discovery_identity_candidate.py` and `docs/element-identity-candidates.md`. Reuse existing sanitized discovery fixtures unchanged. Do not change schema, allocation, binding-record semantics or parser grammar in this task; report a necessary adapter change to the controller first.

**Public inputs and output:**

```python
@dataclass(frozen=True, slots=True)
class CandidateArtifact:
    path: str
    role: str
    before_text: str | None
    after_text: str | None

@dataclass(frozen=True, slots=True)
class DiscoveryEditScope:
    writable_paths: tuple[str, ...]
    element_ids: tuple[str, ...]
    unowned_text_paths: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class CandidateDiagnostic:
    code: str
    path: str | None
    element_id: str | None
    detail: str

@dataclass(frozen=True, slots=True)
class CandidateReferenceState:
    path: str
    source_sha256: str
    start: int
    end: int
    target_id: str
    relation: str
    assessed_revisions: tuple[str | None, ...]
    assessment_state: str

@dataclass(frozen=True, slots=True)
class DiscoveryCandidateCheck:
    diagnostics: tuple[CandidateDiagnostic, ...]
    references: tuple[CandidateReferenceState, ...]
```

```python
IdentityStore.check_discovery_candidate(
    *, spec_id: str,
    artifacts: Sequence[CandidateArtifact],
    scope: DiscoveryEditScope,
    changes: Sequence[lifecycle.LifecycleChange] = (),
) -> DiscoveryCandidateCheck
```

All sequences are snapshotted into tuples and validated before opening the transaction. Require exact request classes and scalar types, canonical relative POSIX paths using the existing path rules, UTF-8 text without NUL, at least one artifact, at least one non-null image per artifact, unique paths and unique scope entries. Scope unowned-text paths must be a subset of writable paths, and writable paths must be in the artifact bundle; scoped element labels must be U/A only. Reject invalid API shape with `IdentityStoreError`; candidate defects are returned as diagnostics. A malformed nonempty lifecycle batch still uses the existing lifecycle request validation. An empty lifecycle batch means no proposed state changes, not an invented no-op operation. Reference `start`/`end` use the adapter's Python string offsets, not byte offsets; their source hash binds the exact UTF-8 bytes.

Supported roles are `unknowns`, `assumptions`, `investigation`, `evidence` and `references`. Unknowns/assumptions provide U/A definitions. The other roles provide references only and cannot define identities. Do not infer roles from arbitrary filenames; these role assignments are controller inputs. Other adapter roles return `unsupported_role`. Inputs describe the exact captured artifact set, including read-only dependencies; the later publisher must authenticate that set and its preimages. This library cannot prove the caller supplied every file or the real canonical baseline and must not claim to.

**Integrity-error boundary:** A detected contradiction or damaged retained registry record is not a repairable candidate defect: propagate `IdentityStoreError`. Keep missing identities, valid-but-unassessed heads, content drift and invalid proposals as candidate diagnostics. Validate relevant existing namespace/head/reservation records and retained binding receipts outside candidate-diagnostic exception catches, on the same read connection. A missing reservation may reject a candidate; a present but internally inconsistent reservation is an authority failure. Do not duplicate storage validators or reinterpret all store exceptions as repair instructions. This avoids spending provider repair attempts on damaged controller state.

**Checks, in one read transaction:**

1. Parse both images with `parse_identity_artifact`; propagate parser diagnostics with the image (`before`/`after`) in detail. Retain duplicate facts and reject duplicates across files, too. Reject numeric-padding aliases by their shared unbounded ordinal even when their strings differ. Do not invent entities from references.
2. For every baseline definition, look up and validate the exact current head, namespace counter and content binding. Require assessed history and exact declaration content; report `baseline_identity_mismatch` for missing, unbound or drifted baseline definitions. An unchanged rendered terminal declaration is legitimate retained history, never a new active identity. This checker is not a history-import tool.
3. Validate nonempty proposed lifecycle changes through `element_identity_lifecycle_store.plan_changes` on the same connection. Convert rejected lifecycle proposals into `lifecycle_rejected`; stop dependent checks rather than using a partial projection. Limit changes to U/A identities and require every changed/predecessor/successor ID in the supplied element scope. All lifecycle-affected identities must correspond to a before/after declaration in this captured bundle; otherwise report `lifecycle_without_artifact`.
4. Compare after definitions to current or projected heads. New definitions require exact reserved `ElementCreate` or transition-successor materialization. Existing active definitions may change only with a matching authorized projected revision and exact projected content. Their U/A caption must remain the same for in-place revision. Caption changes require new identities via explicit transitions; reusing the old label reports `subject_changed`. Missing old active definitions require an explicit retirement or transition; otherwise report `definition_removed`. Candidate-retained terminal declarations must retain the old content, whether terminal before this proposal or retired/superseded by it; terminal IDs cannot acquire a new active subject. An already-terminal rendered row may be removed under explicit element/artifact scope without a second retirement; its registry history remains. No new/revised lifecycle row may silently lack its required active after definition.
5. Every changed artifact must be in writable paths. Every changed/introduced/removed definition must be in element scope. Independently verify unchanged definitions retain their exact content. Unless a path is explicitly in unowned-text paths, all text outside authorized definition spans must remain byte-for-byte equivalent as UTF-8, including order and comments. Use exact source spans, not a broad line-based diff heuristic. Replace each surviving authorized definition span with a collision-free marker containing its exact ID in both images; remove the span for an authorized deleted/new definition only from the side where it exists; compare the resulting strings. The adapter rejects NUL, so NUL-delimited ID markers cannot collide with user text. Discovery declarations are non-overlapping; reject any unexpected overlap rather than guessing ownership. Unowned-text permission never relaxes identity/lifecycle checks or edits to unscoped definitions. Reference-only artifacts need explicit writable + unowned-text permission for changes; otherwise they remain byte-identical.
6. Resolve each supported after-image reference against the current/projected same-spec entity. Require exact labels, validated namespace/head bindings and existence. `requires`/`depends` references to terminal heads report `inactive_dependency`; generic/evidence references may retain a historical target. For this first checker, interval references return `unsupported_reference_range`, and qualified references retain the parser's blocking diagnostic. Do not expand arbitrary ranges or silently use their endpoints as complete references. Other entity kinds may be referenced if already materialized; they cannot be created/revised by this discovery checker.
7. Read retained source claims using the existing connection-owned binding reader for exact path/hash. Only claims whose anchor is exactly `span:<start>:<end>` and whose target and relation match that parsed reference are eligible to describe that occurrence. Do not reinterpret another arbitrary anchor as this span. Preserve assessed revision values in deterministic retained-operation order. State is `unassessed` if no non-null bound revision exists; `current` if at least one non-null bound revision equals the projected/current active head; `historical` otherwise. A null claim never certifies current content. A changed source hash gets no automatic carry-over or reassessment; an unchanged evidence source referencing a revised target remains historical. These are reference states, not verdicts, and are returned separately from structural diagnostics. No claims are inserted, copied or rebound. Future review/publication must authenticate any new assessments and decide which required evidence gates are satisfied.

Return diagnostics in deterministic `(path-or-empty, element_id-or-empty, code, detail)` order, deduplicating only exactly identical diagnostics. Reference results follow artifact path and source-span order. Do not expose `accepted`, `published`, `verified`, `passed`, or a semantic gate flag. Zero structural diagnostics means only that these explicit supported checks found no defect in the supplied snapshot.

- [ ] Write the smoke regression before implementing the API. Parse `tests/fixtures/element_identity/discovery/before/unknowns.md`, import its exact U labels/subjects into a fresh real store and adopt their exact declaration content. Submit its after fixture under U/A discovery scope with no lifecycle changes. Assert `subject_changed` for the reassigned U-002 and `definition_removed` for U-005, plus an unchanged complete logical database state. Import the new API inside the test to retain behavioral RED rather than only a collection error.

```python
def test_smoke_question_reassignment_rejects_without_registry_effect(tmp_path):
    import sqlite3
    from pathlib import Path
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_candidate import CandidateArtifact, DiscoveryEditScope
    from harness.element_identity_lifecycle import ElementAdopt
    from harness.element_identity_store import IdentityStore

    fixture = Path(__file__).parents[1] / "fixtures/element_identity/discovery"
    before = (fixture / "before/unknowns.md").read_text()
    after = (fixture / "after/unknowns.md").read_text()
    declarations = parse_identity_artifact(
        path="unknowns.md", role="unknowns", text=before).declarations
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="001-game", operation_id="import", definitions=tuple(
        (entry.element_id, entry.caption) for entry in declarations))
    store.apply_lifecycle(spec_id="001-game", operation_id="adopt", changes=tuple(
        ElementAdopt(entry.element_id, entry.caption, entry.content) for entry in declarations))

    def logical_state():
        with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
            return tuple(connection.iterdump())

    original = logical_state()
    result = store.check_discovery_candidate(
        spec_id="001-game",
        artifacts=(CandidateArtifact("unknowns.md", "unknowns", before, after),),
        scope=DiscoveryEditScope(("unknowns.md",), tuple(
            entry.element_id for entry in declarations)))
    codes = {(entry.code, entry.element_id) for entry in result.diagnostics}
    assert ("subject_changed", "U-002") in codes
    assert ("definition_removed", "U-005") in codes
    assert logical_state() == original
```

- [ ] Run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_discovery_identity_candidate.py -q` and record RED.
- [ ] Add focused tests before corresponding behavior for unchanged accepted structure, authorized same-caption revision, wrong reservation/padding alias, unallocated introduction, retirement with old references, replacement/split/merge with reserved successors, scope violations, baseline drift, malformed parser syntax, duplicates across files, overlapping spans, unsupported roles/ranges and incomplete lifecycle-to-artifact mapping.
- [ ] Include subsequent-candidate tests after retirement: unchanged terminal rendering remains valid history, terminal subject/content reuse rejects, and scoped removal of an already-terminal rendering leaves retained history intact.
- [ ] Add exact-scope tests with Unicode/CRLF, comments and declarations reordered or surrounded by changed unowned content. Unowned-text authorization must not authorize an unscoped question edit. A reference-only dependency changing without its owner's scope must reject.
- [ ] Add retained evidence tests with a real `ReferenceClaim` anchored to the parsed span: unchanged evidence against a revised target yields `historical` and retains revision 1; a modified source hash yields `unassessed`; neither changes stored receipts. An arbitrary other anchor with the same target cannot be silently assigned to this occurrence. A current active match is reported only as reference state, never as semantic approval.
- [ ] Add focused RED/GREEN for detected damaged counters, heads, present reservation bindings and retained claim receipts: propagate `IdentityStoreError` and preserve complete logical prestate. Candidate-only stale revisions, missing reservations, unassessed heads and source-content drift still return their specified diagnostics.
- [ ] Implement strict inputs, pure exact-span scope checks and the connection-owned checker incrementally. The store wrapper owns one read transaction; share lifecycle planning and existing binding read validation. Do not nest `lookup`, `preview_lifecycle` or `reference_claims` public calls.
- [ ] Run candidate tests plus `tests/unit/test_element_identity_preview.py`, `tests/unit/test_element_artifacts.py`, `tests/unit/test_element_artifact_lexicon.py`, `tests/unit/test_element_identity_lifecycle.py`, `tests/unit/test_element_identity_bindings.py` and `tests/unit/test_element_identity_store.py`. Verify complete database prestate for successful and rejected checks. No million-record or full-repository rerun unless an affected routine storage path warrants it.
- [ ] Document exact supported roles, scope semantics, parser/range limitations, span-anchor convention, structural-versus-semantic distinction and the remaining publisher-authentication boundary. Self-review, run `git diff --check`, commit only task files and report exact RED/GREEN evidence and any necessary follow-on work.

## Following work

This is the first offline candidate checker, not activation. Requirements/tasks, issue occurrence authorization, derived Lexicon and JSON evidence adapters still need candidate contracts before managed coverage can be claimed. Durable intents/CAS must bind authenticated staged bytes to these checks and lifecycle/reference effects inside the existing publication owners; graph/memory consumers, producer integration, history tools, bounded repair, combined simulated-provider verification and explicit rollout remain required.
