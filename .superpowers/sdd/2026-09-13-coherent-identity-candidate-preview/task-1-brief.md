### Task 1: compose candidate and exact operation preview in one authority transaction

**Files:** Create `src/harness/element_identity_candidate_preview.py` and `tests/unit/test_element_identity_candidate_preview.py`; modify `src/harness/element_identity_store.py` only for a thin public method and its type annotation; document in `docs/element-identity-storage.md`. No changes to existing candidate/source/binding/journal/history implementations, schemas/codecs, graph assembly, runtime, CLI, provider or prose. Root owns plan/ledger. No live caller.

**Public interface:**

```python
@dataclass(frozen=True, slots=True)
class IdentityCandidatePreview:
    check: IdentityCandidateCheck
    history: IdentityHistorySnapshot | None

# IdentityStore method
def preview_identity_candidate(
    self, *, spec_id: str,
    artifacts: Sequence[CandidateArtifact],
    scope: IdentityEditScope,
    operations: tuple[PublicationOperation, ...] = (),
    projection_sources: Sequence[LexiconProjectionSource] = (),
    evidence_inventories: Sequence[EvidenceInventoryContext] = (),
    issue_reports: Sequence[IssueReportContext] = (),
) -> IdentityCandidatePreview:
    ...
```

Reuse existing class identities. No independent `changes`, `claims` or `occurrences` parameters: decode those exclusively from `validated_operations` and `publication_store.operation_children`. The immutable result has `history is None` if and only if its check contains diagnostics; a clean check has the existing complete proposed IdentityHistorySnapshot. Do not add an accepted/pass flag, semantic result, hash protocol, source carrier, graph wrapper or wire schema. Existing separate APIs remain compatible.

**Normalize before opening authority:** Use existing `validated_operations` to validate/detach exact canonical ordered child records. Derive their batches with the existing journal decoder, then use `candidate.identity_request` for spec/artifacts/scope/lifecycle and supplemental contexts. Own fresh CandidateArtifact records, a normalized scope, fresh supplemental descriptors and fresh IssueReportContext records with independently copied exact native IssueOccurrence records; caller mutation of frozen objects via object.__setattr__ at transaction entry must not change the request already selected. Lifecycle/binding records decoded from the detached payload strings are independently owned. Preserve existing accepted sequence interfaces and native exact scalar validation, no coercion or generic deep-copy framework. Guard malformed/deleted fields, recursive/custom sequence failures and encoding errors before authority opens where normalization can detect them.

**One query-only transaction:** The thin method normalizes first, opens exactly one existing `_transaction()` and executes `PRAGMA query_only=ON`. Use caller-connection helpers; never call public check_identity_candidate, validate_projected_bindings, identity_history or preview_identity_history inside this reader. Require no pending publication for the selected spec and globally unused/unclaimed child operation IDs with existing journal checks. Capture and fully audit retained history once through `element_identity_snapshot.capture` before interpreting candidate rejection diagnostics. This makes authority damage an exception, not a repairable candidate result, even when candidate content also has defects. No allocation, writes, nested connection, transaction upgrade, journal preparation or provider/filesystem acquisition occurs inside the reader.

Use existing `candidate_store.check_identity` with the same connection, normalized inputs and lifecycle batch. Append the existing `validate_reference_claim_sources` diagnostics for the exact decoded proposed reference claims and supplied postimages. This only checks supplied claims; it does not synthesize a stored claim for every parsed reference, infer semantic assessments, or change CandidateReferenceState to pretend proposed claims are retained assessments. Existing candidate target/scope and historical/None binding policies remain in their current owners.

**Issue operation/context association:** Tie native full occurrence payloads, not just display IDs or issue IDs, across three sets: all after_occurrences in the normalized contexts, occurrences decoded from the proposed journal child, and materialized occurrences in the fully audited retained history. Reuse exact IssueOccurrence fields (issue_id, issue_revision, report_id, report_sha256, display_id, title, body); extra retained row metadata/fingerprint is not an alternate identity.

- Every proposed occurrence must equal an after occurrence in a supplied context. Otherwise emit `CandidateDiagnostic("issue_operation_unbound", None, occurrence.issue_id, "proposed occurrence requires an exact captured after report occurrence")`.
- Every supplied after occurrence must either equal a proposed occurrence or already have exact retained provenance. Otherwise emit `CandidateDiagnostic("issue_operation_missing", context.path, occurrence.issue_id, "after occurrence requires an exact proposed operation or retained provenance")`.
- Existing candidate issue checks still own report path/role/hash/body/title/display identity, before provenance, current/projected active revision and unchanged historic-report exceptions. Association alone cannot bless a malformed report or old issue content.
- Existing authenticated unchanged reports need no duplicate child operation. A supplied occurrence already retained and explicitly proposed is not independently forbidden here; current journal/binding duplicate and operation-id rules remain authoritative. Do not silently remove or add proposed entries, infer closure from report omission or accept an orphan journal occurrence merely because its target revision exists.

Merge diagnostics into a fresh IdentityCandidateCheck using existing `(path or "", element_id or "", code, detail)` sorted unique order; preserve the candidate reference observations exactly in fresh records. If diagnostics exist, return history=None without planning/overlaying a passing history. Otherwise call `publication_store.planned_effects` for the exact decoded children, then existing `snapshot_preview._overlay(retained, spec_id, children, plan)`. This shares journal lifecycle/binding validation and canonical full snapshot generation rather than inventing another overlay. Invalid projected bindings, executed/claimed child operation IDs, malformed authority or input remain bounded IdentityStoreError exceptions; lifecycle proposals rejected by the existing candidate checker remain its diagnostics. All ordinary exceptions exit one public handler and produce `IdentityStoreError("invalid identity candidate preview authority or request")` outside the handler, without source-bearing cause/context. BaseException process-control subclasses propagate unchanged.

**Actual first RED before implementation:** Use real typed parsing, allocated identity, candidate checking and proposed-history preview successfully before invoking the absent new method. Minimal setup:

```python
store = IdentityStore.initialize(tmp_path)
label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
assert label == "FR-000001"
before = f"- **{label}**: Move using WASD.\n"
after = f"- **{label}**: Move using arrow keys.\n"
old, = parse_identity_artifact(path="spec.md", role="requirements", text=before).declarations
new, = parse_identity_artifact(path="spec.md", role="requirements", text=after).declarations
store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
    ElementCreate(label, "Movement", old.content, "reserve"),))
changes = (ElementRevision(label, "1", "Movement", new.content),)
operations = (PublicationOperation("lifecycle", "revise", encode_request("lifecycle", changes)),)
artifacts = (CandidateArtifact("spec.md", "requirements", before, after),)
scope = IdentityEditScope(("spec.md",), (label,))
existing_check = store.check_identity_candidate(
    spec_id="demo", artifacts=artifacts, scope=scope, changes=changes)
assert existing_check.diagnostics == ()
existing_history = store.preview_identity_history(spec_id="demo", operations=operations)
value = json.loads(existing_history.payload)
assert [row["revision"] for row in value["revisions"]] == ["1", "2"]
assert value["revisions"][0]["content"] == old.content
assert value["revisions"][1]["content"] == new.content
result = store.preview_identity_candidate(
    spec_id="demo", artifacts=artifacts, scope=scope, operations=operations)
assert result.check == existing_check
assert result.history == existing_history
```

- [ ] Run `test_candidate_preview_uses_exact_journal_operations` with `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_element_identity_candidate_preview.py::test_candidate_preview_uses_exact_journal_operations -q` from this worktree. Native setup/assertions must succeed before missing-method RED. Notify root before production, then implement the narrow reader and obtain GREEN. Assert complete SQL state unchanged by preview and equality to real v3 prepare/apply/reopen history afterward, not only selected rows. Keep opaque test recovery/manifest claims explicitly separate from filesystem publication.
- [ ] Cover clean creation/revision/retirement/split/merge, canonical six/seven-plus labels and preserved legacy labels, nested task/requirement edits, U/A subject preservation, supplemental projection/inventory contexts and None/empty distinctions using native fixtures. No family-specific changes to existing semantics. Retained old evidence remains revision-bound, imported unassessed entities remain unassessed; reference observations retain their original meaning even when an explicit proposed claim is present.
- [ ] Add independently expected sorted diagnostic fixtures for forbidden renumbering/removal/out-of-scope edits, orphan occurrence child, missing occurrence child, mismatched full occurrence fields, exact retained unchanged historical report without a child, changed report requiring a matching child, and invalid report provenance despite matching child. Proposed claim source hash/span/target/relation mismatches must prevent history; valid source claims still fail if their target binding is invalid. A missing/invalid supplied claim does not auto-create an assessment. Operations for lifecycle content different from the rendered candidate must not yield history.
- [ ] Prove one real authority snapshot: count reader transactions and use a SQL authorizer to reject writes. Synchronize a real second writer with events while the first reader is between candidate work and overlay; the writer may have executed its changes but cannot commit until the reader exits under the existing rollback journal. The result remains from one old snapshot, and after the writer commits existing v3 preparation rejects the stale proposed history. No timing sleeps, mocked store/snapshot results, repeated stress loops or new production test hooks. Native helper wrappers may only coordinate/count while calling their originals.
- [ ] Validate pending-spec and globally used/claimed child rejection, empty operations, another spec's independent pending state, stale lifecycle revisions, corrupt retained rows including unrelated retained history plus malformed candidate, and durable reopen/retry semantics. Preview is pre-intent/new-child only; do not relax pending guards to support recovery.
- [ ] Test caller-record/sequence detachment at transaction entry, immutable/detached result records, exact types/subclasses/deleted slots/custom recursive or raising sequences, bounded public exceptions with no cause/context source objects, process-control propagation and both import orders. Block source-file/planner/provider/graph/memory/publication writer entry points after real fixture setup while allowing only the existing identity authority read path; show no ledger mutation by whole logical SQL snapshots.
- [ ] Add one actual integration fixture: sealed source capture -> assemble_candidate_sources -> this preview -> project_publication_source_images -> build_captured_identity_graph using actual native canonical planner and explicit deterministic audit -> real v3 identity journal prepare/apply with this history hash. Compare retained projected graph bytes with the same graph/history assembled after real identity application. Independently assert stable keys and old evidence targets; declare that this fixture does not seal/publish the graph or authenticate semantic review. Use current graph tests for fixture setup, not expected output borrowed as an oracle.
- [ ] Run once these nine covering modules: `tests/unit/test_element_identity_candidate_preview.py`, `tests/unit/test_definition_identity_candidate.py`, `tests/unit/test_issue_identity_candidate.py`, `tests/unit/test_element_identity_reference_sources.py`, `tests/unit/test_element_identity_binding_preview.py`, `tests/unit/test_element_identity_snapshot_preview.py`, `tests/unit/test_element_identity_publication_history.py`, `tests/unit/test_element_identity_candidate_sources.py`, `tests/unit/test_spec_graph_captured.py`. No capacity/full-unit/live/global-install or unchanged postcommit repeats. Later code/test amendments get named scoped verification and exact tested-tree chronology.
- [ ] Self-review transaction ownership, request detachment, exact operation/context association, diagnostic-versus-authority failure, existing helper reuse and honest remaining boundaries; diff-check, commit only scoped module/method/tests/docs, and write full report with every actual run/fixture failure/RED/GREEN, commands/output, tested tree and later amendments. Root performs original-BASE independent review after DONE.

## Remaining integration

This reader does not supply semantic review, physical source/dependency acquisition, source-context acceptance, graph sealing or atomic publication/recovery. The managed controller must bind the selected operation request and exact candidate/graph to subsequent v3 publication, validate managed run ownership and guard real source bytes. Runtime/manual/CLI/producers, bounded repair and final offline regression remain required before rollout.
