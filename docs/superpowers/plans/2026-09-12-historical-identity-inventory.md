# Historical identity inventory implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Produce a deterministic, read-only inventory of explicitly supplied historical snapshots and expose identity conflicts without choosing a historical meaning or importing assessed revisions.

**Architecture:** Close the reproduced unsupported-declaration omission in the existing typed Markdown adapter, then reuse typed facts in a pure historical inventory module. Add one explicit input-only administration command. The report carries exact source bindings and unresolved conflicts, not authority or semantic approval; historical adoption/reconciliation and managed publication remain separate required work.

**Tech Stack:** Python standard library JSON/hashlib/dataclasses as needed; existing typed artifact and issue-fingerprint APIs; pytest and local subprocess tests. No dependencies or database changes.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Existing labels, including FR-001 and historical composite IDs, remain exactly as published.
- Unsupported composite legacy formats remain opaque reserved identities; migration must not reinterpret them heuristically.
- Imported histories with competing allocations block for explicit reconciliation; do not merge same-looking IDs by assumption.
- Do not infer new definitions from every textual mention or infer authority from historical journal quotes.
- Historical evidence is retained, not relabeled as proof of the new content.
- No authority initialization, allocation, import, lifecycle mutation, schema change, canonical publication, semantic approval or activation in this task.

---

### Task 1: explicit historical inventory with fail-closed unsupported declarations

**Files:** Create `src/harness/element_identity_history.py` and `tests/unit/test_element_identity_history.py`; modify `src/harness/element_artifact_markdown.py`, `src/harness/element_identity_admin.py`, `tests/unit/test_element_artifacts.py`, and `tests/unit/test_issue_identity_candidate.py` only where its unsupported-heading expectations need strengthening; extend `docs/element-identity-storage.md`. New tests use `pytestmark = pytest.mark.unit`. Do not change the shared successful label grammar, Lexicon grammar, task parser, issue fingerprint algorithm, storage schemas or lifecycle rules.

**Root cause already reproduced:** `parse_identity_artifact(path="sample.md", role="issues", text="### ISS-legacy: Collision\nBody\n")` and requirements input `- **FR-legacy**: Collision\n` currently return no declarations and no diagnostics. The loose heading/bullet detectors share the narrower successful numeric grammar, so unsupported explicit declarations disappear instead of receiving the existing unsupported diagnostic. `ISS-099legacy` is an already supported comparison and must remain supported. Broaden only detection of explicit declaration-shaped lines, not successful interpretation of opaque labels or arbitrary prose references.

**Adapter behavior:** A visible Markdown heading starting with a recognized family prefix plus a suffix beginning with an ASCII alphanumeric character and continuing with non-whitespace/non-colon characters, or a visible requirement-shaped list bullet starting with such a label (plain, bold or inline-code wrapped), must receive `unsupported_declaration` when it does not satisfy the existing successful declaration syntax. The initial-character envelope follows the existing authority label grammar: `T-###` remains a template placeholder, while `FR-a_b` is a real opaque label and must not disappear. Plain bullets count as declaration-shaped only with the colon delimiter; wrapped ID-bearing bullets retain the existing missing-colon diagnostic behavior. Ordinary plain `- FR-001 is mentioned here` stays reference prose. Exclude actual enclosing Markdown wrapper characters from the label span, not internal underscores/dots/hyphens. Retain `ambiguous_block_boundary` for indented headings and the existing task-like-row diagnostics. Keep exact unsupported label spans and prevent the rejected declaration label from becoming a shorter reference. Preserve the current active-source exclusions (frontmatter, fenced/indented code, comments, blockquotes), valid nested ownership, recognized numeric/composite behavior, ordinary prose mentions and issue Resolution Guidance/footer boundaries. Do not add an independent regex scanner in the historical inventory. An unsupported heading must also make the existing general issue candidate fail even with an empty occurrence mapping. This closes explicit declaration omission, not every possible unsupported reference spelling or managed report authentication.

**Pure interface:**

```python
class HistoryInventoryError(ValueError):
    """Malformed explicitly supplied historical inventory input."""

def inventory_history(request: object) -> dict:
    """Inventory declared snapshots without file/database access or assessment."""
```

Input is a JSON-compatible object with exactly this shape:

```json
{"schema_version":1,"spec_id":"demo","snapshots":[{"snapshot_id":"9976af0","artifacts":[{"path":"unknowns.md","role":"unknowns","text":"### U-005: Largest-step collision\nInvestigate movement.\n"},{"path":"evidence-grades.md","role":"evidence","text":"U-005 needs evidence.\n"}]},{"snapshot_id":"76f2b80","artifacts":[{"path":"unknowns.md","role":"unknowns","text":""},{"path":"evidence-grades.md","role":"evidence","text":"U-005 needs evidence.\n"}]}]}
```

Require exact dictionary keys and scalar types at every level; integer-not-bool schema version 1; nonempty arrays for snapshots and artifacts; unique nonblank UTF-8/NUL-free snapshot IDs and a nonblank UTF-8/NUL-free spec ID. Within a snapshot each physical path is unique and has exactly one role and one image; reject duplicate paths even when their roles or texts differ. Across snapshots explicitly list the same set of paths with the same assigned roles, so omitted input cannot masquerade as a deleted artifact. This manifest represents captured files, not multiple independently supplied parser views of the same file. `text` is an exact UTF-8/NUL-free string or null, where null means explicitly absent and empty string remains a present document. Reuse the adapter's existing `element_artifacts._validate_input` on absent images with `text=""` to validate path/role without invoking Lexicon grammar; present images use `parse_identity_artifact`. Accepted roles are exactly those already accepted by that public adapter; no glossary/inventory-JSON interpretation in this checkpoint. Snapshot array order is caller-declared history order, never claimed to be Git-authenticated chronology. Copy/normalize inputs; do not mutate caller objects or return mutable aliases. Expected input errors become HistoryInventoryError; do not catch arbitrary programming exceptions.

Report exact top-level keys:

```python
{
    "report_version": 1,
    "spec_id": "demo",
    "input_sha256": "...",
    "coverage": "declared_snapshots_only",
    "source_authentication": "caller_supplied",
    "assessment": "unassessed",
    "snapshots": [],
    "conflicts": [],
}
```

`input_sha256` binds a canonical JSON encoding (`sort_keys=True`, compact separators, `ensure_ascii=True`) of the validated input with artifacts sorted by path within each snapshot and snapshot order preserved. No external files, current workspace, timestamps or registry maxima enter the digest. Reports preserve snapshot order; artifacts sort by path; source declarations/references/diagnostics preserve parser order. Conflicts use deterministic ordering and stable exact ID strings; numeric ordering, when needed, uses the shared unbounded helper, not builtin whole-string conversion. Do not output an `ok`, `approved`, `ready`, current revision, automatic reconciliation decision or fabricated authority UUID.

Each snapshot report contains only `snapshot_id` and `artifacts`. Each artifact contains `path`, `role`, `present`, `content_sha256` (null for absent), `declarations`, `references`, `diagnostics`. Each declaration contains its existing `element_id`, `kind`, `disposition`, `caption`, `span`, `label_span`, and a `content_sha256` of its exact typed declaration content rather than printing raw content. Span objects contain `start`, `end`, `line`. For issue occurrences also include `typed_fingerprint`: reuse `issue_identity.issue_fingerprint` with the parsed caption and exact typed body after the first heading newline. This is a newly computed fingerprint under the typed artifact body boundary, not an authenticated old resolution fingerprint and never a closure transfer. Preserve each occurrence separately by snapshot/path/source hash/span even when display ID, body or fingerprint repeats. Projection declarations remain projections, never additional authoritative entities.

Each reference contains existing `target_id`, `range_end_id`, `owner_id`, `relation`, `span`, plus `assessment: "unassessed"`; no inferred assessed revision, latest target head, or verification certification. Each artifact diagnostic contains existing `code`, `span`, `detail` unchanged.

Every conflict contains exactly `code`, `element_ids` (list), `locations` (list), `detail`. Each location contains `snapshot_id`, `path`, `artifact_sha256`, `span`; a missing target location uses the explicitly captured artifact hash/presence and null span. Required conflict rules:

- `artifact_diagnostic`: retain every parser diagnostic as a conflict with its original code/detail identifiable in `detail` and source location; do not silently continue to a clean inventory after parse failure.
- `duplicate_definition`: the same authoritative label appears more than once in a snapshot, including across files; issue occurrences and derived projections are not authoritative definitions.
- `padding_alias`: any two distinct numeric label spellings of the same family/positive ordinal occur as authoritative definitions anywhere in the selected history. Do not normalize output labels or interpret opaque composites as numeric ordinals.
- `definition_changed`: one authoritative exact label has multiple distinct typed content hashes across selected snapshots. Include all observed variants/locations. This means explicit lifecycle/semantic reconciliation is required; it is not a claim that every edit changed the subject. Even a valid normal revision remains unassessed here.
- `definition_missing`: a label defined in one snapshot is absent from authoritative definitions in the immediately following snapshot. Include original definition locations and the corresponding explicitly captured next artifact locations. Do not infer retirement, and do not flag merely not-yet-created IDs in earlier snapshots.
- `issue_mapping_required`: every reported ISS display-label group requires an explicit durable-issue mapping, even a single occurrence or identical fingerprints. Keep all source occurrences; never merge histories or transfer resolution by display ID/fingerprint.
- `unresolved_reference`: a supported bare target has no authoritative declaration in its own snapshot; references to issue occurrences use `issue_mapping_required` instead and cannot become resolved by a display label. References to duplicate/alias targets use `ambiguous_reference`. Do not resolve from another snapshot, current filesystem, projections, or raw mentions.
- `unsupported_reference_range`: retain intervals as typed reference facts and report the unresolved interval; do not expand ranges into identities or silently use only one endpoint. Qualified reference diagnostics remain explicit as emitted by the parser.

Parser diagnostics and conflicts can coexist; the report is an inventory, not a pass/fail publication gate. A reference to a uniquely declared target is still unassessed. Exact duplicate locations need not be repeated within the same conflict, but declarations/occurrences in separate report locations must never be collapsed. Validate parsed declaration/reference labels with the existing strict lifecycle label validator before treating them as eligible identities; invalid zero or unsupported labels produce `invalid_identity_label` conflicts at their exact source spans and are excluded from resolvable authority, not converted into invented allocations.

**Administration interface:** Add `python -m harness.element_identity_admin inventory-history --input PATH`. This new read-only command has no workspace argument or authority discovery. Read only the explicitly named strict UTF-8 JSON input, reject duplicate object keys and malformed JSON/Unicode, call the pure API and print its deterministic report directly. Exit 0 means an inventory was produced, including when it contains conflicts; it never means migration succeeded. Invalid inputs return 2 with concise stderr, no success JSON or traceback. Reuse the existing JSON/output/error boundary without a second command framework or broad catch-all. Existing six administration commands retain their behavior. No scan of Git, folders, current files or the stopped smoke, and no persisted report/authority unless the user later explicitly directs an output action.

- [ ] Write this regression before production edits:

```python
def test_opaque_issue_heading_is_diagnostic_not_empty_report():
    from harness.element_artifacts import parse_identity_artifact
    text = "### ISS-legacy: Collision\nBody\n"
    result = parse_identity_artifact(path="issues.md", role="issues", text=text)
    assert not result.declarations
    assert not result.references
    assert [d.code for d in result.diagnostics] == ["unsupported_declaration"]
    span = result.diagnostics[0].span
    assert text[span.start:span.end] == "ISS-legacy"
```

- [ ] Run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_artifacts.py::test_opaque_issue_heading_is_diagnostic_not_empty_report -q` and retain actual RED. Extend real parser cases for all seven family prefixes, letter-leading/dotted/hyphenated legacy suffixes, plain/bold/code bullets, malformed numeric headings, active-source exclusions, supported numeric/composite controls, exact CRLF/Unicode spans and no shorter rejected-label references. Add a real-store issue candidate regression proving an unsupported heading cannot pass with empty occurrence context and full SQL-prestate preservation.
- [ ] Implement only the explicit declaration detector correction, run covering adapter/issue tests, and retain GREEN. Do not widen supported identity syntax or alter fingerprints.
- [ ] Add the pure inventory regression below and run the new test module to retain missing-API RED before implementing it:

```python
def test_removed_question_keeps_evidence_unassessed_and_unresolved():
    from harness.element_identity_history import inventory_history
    request = {"schema_version": 1, "spec_id": "demo", "snapshots": [
        {"snapshot_id": "before", "artifacts": [
            {"path": "unknowns.md", "role": "unknowns", "text": "### U-005: Collision\nInvestigate.\n"},
            {"path": "evidence.md", "role": "evidence", "text": "U-005 needs evidence.\n"}]},
        {"snapshot_id": "after", "artifacts": [
            {"path": "unknowns.md", "role": "unknowns", "text": ""},
            {"path": "evidence.md", "role": "evidence", "text": "U-005 needs evidence.\n"}]},
    ]}
    result = inventory_history(request)
    assert result["assessment"] == "unassessed"
    assert {c["code"] for c in result["conflicts"]} == {"definition_missing", "unresolved_reference"}
    after_evidence = next(a for a in result["snapshots"][1]["artifacts"] if a["path"] == "evidence.md")
    assert after_evidence["references"][0]["target_id"] == "U-005"
    assert after_evidence["references"][0]["assessment"] == "unassessed"
```

- [ ] Implement pure validated report construction through the existing adapter, deterministic conflict analysis and input-only command. Use small responsibility-focused helpers; no copied Markdown parser, semantic heuristic, allocator or lifecycle implementation.
- [ ] Cover the exact sanitized before/after unknowns and retained evidence fixtures under `tests/fixtures/element_identity/discovery/`; expect changed U-001 through U-004, missing U-005 and retained unresolved U-005 evidence, all source hashes/spans preserved. Do not open the live smoke workspace.
- [ ] Cover unchanged clean definitions without semantic approval; ordinary content revisions flagged for explicit reconciliation; introduction versus removal/move across files; duplicate definitions; legacy padding alias across snapshots; seven-plus-digit and over-4300-digit numeric labels; distinct opaque labels rejected as unsupported explicit declarations rather than merged; derived projection not authority; malformed/absent/present-empty native Lexicon; issue ID reuse with different and same fingerprints retaining all occurrences; typed fingerprint equality with the existing function without old resolution claims; unresolved/ambiguous/range/qualified references; ignored quoted/fenced examples; exact source hashes and spans including CRLF; deep input/output detachment; stable canonical digest and artifact ordering; strict input shapes and same captured path/role set across snapshots.
- [ ] Add real subprocess command tests using checkout `PYTHONPATH=src`, covering valid/conflicting inventory, required input, duplicate JSON keys, invalid JSON/UTF-8/Unicode/types including decoder limit errors, no implicit workspace/authority access and no output files. Check an initialized temporary authority and all input bytes are unchanged; no authority directory is created in an empty working directory. Preserve existing administration command tests.
- [ ] Run `tests/unit/test_element_identity_history.py`, `tests/unit/test_element_identity_admin.py`, `tests/unit/test_element_artifacts.py`, `tests/unit/test_issue_identity_candidate.py`, `tests/unit/test_definition_identity_candidate.py`, `tests/unit/test_discovery_identity_candidate.py`, and `tests/unit/test_element_ids.py` with `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q`. Do not launch the repository-wide or million-record suite. Record every actual RED/GREEN command/output and any fixture corrections honestly.
- [ ] Document command schema, exact report/provenance limits and conflict meanings. `inventory-history` is not historical import/adoption, cannot authenticate completeness or Git chronology, and does not resolve unknown grammar/qualified references. Run self-review and `git diff --check`, commit only task files and retain the full report in this plan's ignored workspace.

## Following work

Explicit authenticated reconciliation/application of historical definitions, revisions and evidence; durable publication intent and completion/graph receipts; managed producers and their exact format/scope/semantic review; bounded repair and final offline/live verification remain required. No report from this task authorizes resuming the stopped run or bootstrapping authority from its latest files.
