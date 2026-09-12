# Issue occurrence candidate implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add explicit ISS occurrence authorization to the inactive general candidate checker while preserving immutable issue history and the existing fingerprint-sensitive resolution guards.

**Architecture:** A dedicated issue-candidate helper validates controller-supplied report/occurrence descriptors against exact parsed report images and retained or projected registry revisions. Integrate it into the existing shared planner and scope flow without treating a replacement review report as the authoritative inventory of all issue entities. Discovery remains narrow; no new publication owner or issue-resolution mechanism is introduced.

**Tech Stack:** Existing Python artifact adapters, IssueOccurrence binding storage, shared lifecycle planner and SQLite read transaction; pytest; no dependency.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Separate a durable issue from an occurrence in a particular review.
- Existing fingerprint-based resolution guards remain. Changed evidence or repair obligations must not inherit a closed resolution merely because the display ID is unchanged.
- Legacy reports that reused ISS-001 are imported as distinct historical occurrences using report provenance and fingerprints; ambiguous correspondence to a durable current issue blocks reconciliation.
- No database/schema/parser change, canonical publication, evidence reassessment, graph/memory mutation, producer routing, resolution-ledger mutation or live activation in this task.
- Detected damaged authority raises IdentityStoreError, not a provider-repair diagnostic. Snapshot caller data before the existing single query-only transaction; never nest public store methods.

---

### Task 1: explicit report provenance and ISS lifecycle projection

**Files:** Create `src/harness/element_identity_issue_candidate.py` and `tests/unit/test_issue_identity_candidate.py`; modify existing candidate types/policies, shared candidate-store checker, thin general IdentityStore wrapper and `docs/element-identity-candidates.md`. Update only obsolete general-wrapper ISS rejection tests to exercise required report context; preserve narrow discovery restrictions. Consume the final reviewed supplemental bundle interfaces, not an intermediate worker edit. Ask before parser/schema changes or an unplanned algorithm split.

**New public descriptor**, exported by `harness.element_identity_issue_candidate`:

```python
@dataclass(frozen=True, slots=True)
class IssueReportContext:
    path: str
    before_report_id: str | None
    after_report_id: str | None
    before_occurrences: tuple[IssueOccurrence, ...] = ()
    after_occurrences: tuple[IssueOccurrence, ...] = ()
```

`IssueOccurrence` is the existing exact immutable type from `harness.element_identity_bindings`; do not create a second occurrence payload or fingerprint algorithm. Add optional `issue_reports: Sequence[IssueReportContext] = ()` to the existing general `check_identity_candidate`, preserving its other parameters and exact `IdentityCandidateCheck` result shape. General scope/lifecycle kinds now include ISS, and role `issues` becomes supported only with explicit report context. No new public checker and no change to the discovery wrapper.

Normalize exact descriptor/occurrence types and all nested sequences before authority entry, reusing existing occurrence scalar validation. Reject wrong types, invalid canonical POSIX paths, invalid report-ID scalars and duplicate context paths as caller errors through IdentityStoreError. A present image requires a nonblank report ID; an absent image requires None and no occurrence entries. Missing context for an `issues` artifact, missing/wrong-role context target or image/context disagreement is a blocking candidate diagnostic (`issue_report_context_missing` or `issue_report_mismatch`), never an implicit unbound review.

Parse issues with the existing role adapter. An occurrence's rendered title is `declaration.caption`; its body is the exact portion of `declaration.content` after the first heading line's newline. Preserve subsequent bytes including CRLF, whitespace and the adapter-owned Resolution Guidance companion. Do not include the heading itself in registry issue content or silently include excluded report footer text. Bind each parsed occurrence one-to-one by display ID, with exact report ID, SHA256 of the complete original report image, title and body. Report missing/extra/mismatched occurrences and duplicate display IDs or durable ISS IDs within one report as `issue_occurrence_mismatch`; preserve all parser diagnostics. The same durable issue can appear in different explicit reports.

Before-image records must match exact retained binding records authenticated through the connection-owned binding reader/receipt validator. Match all IssueOccurrence payload fields, not a fingerprint alone. No matching retained record is `unrecorded_issue_occurrence`; detected damaged records/receipts/targets propagate the existing integrity exception. Historic before-image display labels may differ from canonical issue IDs only through this exact retained mapping. A prior report/body interpretation that disagrees with the current typed block boundary must reject explicitly, not be rewritten or silently re-fingerprinted.

After-image managed report labels must equal their canonical durable `issue_id` exactly, including preserved legacy spellings for existing entities. New managed reports must not restart ISS numbering or reuse a local display label for another issue. Reject mismatched labels as `issue_display_identity_mismatch`. Legacy reused display labels remain retained historical provenance for explicit migration, not a new managed numbering scheme.

An after occurrence normally matches the exact current/projected active ISS revision, immutable subject/title and body. Use `issue_revision_mismatch` for missing/non-active/wrong-revision or content/subject mismatch. Permit unchanged retained history only when the complete after text, report ID and full occurrence tuple equal the authenticated before image: those exact historic active-revision occurrences can stay visible even when the entity's current head has advanced or become terminal. Changing a report's bytes or attribution cannot use this exception to issue fresh stale/current evidence. All after labels must still satisfy canonical-label rules.

ISS source bodies differ from other families' full-declaration registry content. Keep occurrences out of authoritative definition and ordinal maps. Extend the shared candidate flow deliberately:

- Include descriptor canonical ISS IDs in current-head/integrity validation and relevant scope/lifecycle presence checks.
- Use the same shared lifecycle planner once for mixed-family proposed changes. Do not implement another create/revise/retire/transition algorithm.
- For ISS, validate exact current/projected issue content through the occurrence helper rather than comparing a full Markdown heading block to registry body text.
- Active proposed ISS creations/revisions/successors need a matching after occurrence; use `issue_occurrence_missing` if absent. Existing issues omitted from a later report do not require fabricated retirement or deletion.
- Terminal lifecycle changes require explicit existing canonical ISS scope and a captured before occurrence, retaining original history. An unchanged historic rendering can stay or a scoped report occurrence can disappear; neither event closes a review obligation by itself.
- Source requirements/tasks/U/A and supplemental projections retain their existing rules unchanged. No lifecycle effects may target IDs without captured, validated declaration/occurrence presence.

For report scope, use full rendered occurrence blocks with canonical IDs mapped from the explicit descriptors while retaining their original source spans. Exact labels in the existing collision-free masks identify canonical entities, but source text stays untouched. Every changed, introduced or removed occurrence needs appropriate artifact/element permission; report headers/footers and layout changes follow the existing unowned-text permission rules. A before display alias does not grant permission for a different canonical issue. Multiple occurrences of the same entity in different reports remain independently artifact-scoped.

Issue-body references use the shared after-image target and retained-claim logic with the report's own path/hash/span. After labels are canonical, so no heuristic report-local ISS alias resolver is introduced. Old source hashes and old fingerprint resolutions are never relabeled as proof of a changed report or issue revision. This checker does not interpret PASS/FAIL, resolved/unresolved, banzai eligibility or report omission as lifecycle status. Later managed quality-gate integration must explicitly reconcile outstanding issues against the existing resolution ledger; this structural API cannot certify their resolution.

- [ ] Write this real-storage creation regression before implementation:

```python
def test_reserved_issue_creation_binds_body_without_writing_history(tmp_path):
    from contextlib import closing
    import hashlib
    import sqlite3
    from harness.element_identity_bindings import IssueOccurrence
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
    from harness.element_identity_issue_candidate import IssueReportContext
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_store import IdentityStore

    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="ISS", operation_id="reserve-issue", count=1)
    title = "Collision handling is missing"
    body = "**Severity:** HIGH\nMovement can cross a wall.\n"
    report = f"### {label}: {title}\n{body}"
    occurrence = IssueOccurrence(label, "1", "review-1",
        hashlib.sha256(report.encode("utf-8")).hexdigest(), label, title, body)

    def logical_state():
        with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
            return tuple(connection.iterdump())

    original = logical_state()
    result = store.check_identity_candidate(
        spec_id="demo", artifacts=(CandidateArtifact("issues.md", "issues", None, report),),
        scope=IdentityEditScope(("issues.md",), (label,), ("issues.md",)),
        changes=(ElementCreate(label, title, body, "reserve-issue"),),
        issue_reports=(IssueReportContext("issues.md", None, "review-1", (), (occurrence,)),),
    )
    assert result.diagnostics == ()
    assert logical_state() == original
    assert store.lookup(spec_id="demo", element_id=label) is None
```

- [ ] Run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_issue_identity_candidate.py -q` and retain behavioral RED before implementation.
- [ ] Add exact current occurrence creation/revision, real stored before provenance, missing reservation, immutable title change, wrong active revision/body, create/replace/split/merge/retire, active proposal lacking after occurrence, and unsupported unrepresented lifecycle cases before corresponding implementation. Use the existing binding API only to establish real fixture history, not inside the checker.
- [ ] Add complete report mapping tests: wrong/missing report context, wrong hash/ID/title/body, duplicate display/canonical occurrence within a report, same entity across distinct reports, before historical display alias with exact retained mapping, canonical after-label enforcement, imported unassessed issue, retained historic active revision under an advanced/terminal head, and rejection of freshly attributed stale occurrences.
- [ ] Prove report omission leaves the entity active, original occurrences and fingerprint resolution history unchanged, and no implicit retirement/closure occurs. Prove a meaningful repair-obligation or evidence-field change cannot inherit an existing fingerprint-sensitive resolution; reuse `issue_identity.issue_fingerprint` and `matching_issue_resolution` unchanged for this assertion. Preserve the existing fingerprint treatment of presentation/status fields rather than assuming every byte/revision change is a new repair obligation. Revision-bound reference claims remain an independent provenance check. This is not a new resolution ledger.
- [ ] Add full-block scope tests for unauthorized issue edits/removal, alias-to-canonical mapping, independently scoped multiple reports, report footer/header permissions, Resolution Guidance body ownership and exact CRLF/Unicode. Preserve None-versus-empty image distinction; a present report with zero declarations can have an explicit report ID and empty occurrence tuple without inventing an issue.
- [ ] Add real damaged-occurrence/receipt/target integrity tests showing exceptions rather than repair diagnostics, full logical prestate equality for every scenario, nested-sequence snapshots and one query-only transaction. Keep source claims historical after changed report bytes or referenced requirement revisions.
- [ ] Implement the focused occurrence helper and narrow shared-checker integration. Resolve public annotations, avoid duplicated lifecycle/binding algorithms, and preserve existing U/A/requirement/task/projection/inventory behavior.
- [ ] Run new issue tests plus `tests/unit/test_supplemental_identity_bundle.py`, `tests/unit/test_definition_identity_candidate.py`, `tests/unit/test_discovery_identity_candidate.py`, `tests/unit/test_element_identity_bindings.py`, `tests/unit/test_element_identity_lifecycle.py`, `tests/unit/test_element_artifacts.py`, `tests/unit/test_issue_identity.py`, `tests/unit/test_phase3_review_assessment.py` and `tests/kernel/test_phase3_repair_handoff.py`.
- [ ] Document current versus historical occurrence rules, canonical new-report labels, original fingerprint guards, absence-not-closure and remaining managed gate/publication limitations. Self-review, run `git diff --check`, commit only task files and retain full RED/GREEN commands/output, exact guarding test paths and concerns in the ignored task report.

## Following work

This provides seven-family structural candidate coverage with explicit unsupported interval/qualified-reference policies. Historical reconciliation tools, canonical/staged byte authentication, semantic identity review, durable publication and graph receipts, managed producer/resolution-gate integration, bounded repair and crash/live verification remain required. No managed run is activated here.
