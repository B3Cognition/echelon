# Exact reference source binding implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Check that each proposed reference claim actually names the exact supported reference in its supplied postimage, not merely an existing target revision.

**Architecture:** A pure source-side validator uses the same candidate-image parser as existing preflight and returns stable candidate diagnostics. Extract that existing pure parser unchanged into the new source module and retain its old import alias. Target/lifecycle validation, captured-source authentication and semantic review stay separate; no live producer is enabled by this task.

**Tech Stack:** Existing CandidateArtifact/ReferenceClaim dataclasses, typed Markdown/Lexicon parser, exact UTF-8 SHA-256 and canonical span strings, real store and parser fixtures.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- Historical evidence is retained, not relabeled as proof of the new content.
- References bind the qualified entity and, where they assert verification, the assessed revision.
- No publication/controller/provider/producer activation, ledger writes, memory writes, graph publication or schema changes in this task.

---

### Task 1: match proposed claims to exact parsed postimage references

**Files:** Create `src/harness/element_identity_reference_sources.py` and `tests/unit/test_element_identity_reference_sources.py`; modify `src/harness/element_identity_candidate_store.py` only to import the extracted pure `_parse_image` helper instead of its current definition/imports; document in `docs/element-identity-storage.md`. The explicitly scoped compatibility correction below additionally touches `src/harness/element_artifact_lexicon.py` and adds coverage in `tests/unit/test_element_artifact_lexicon.py`. Preserve all existing store/publication/target validation APIs and behavior. Do not add a second artifact parser or reinterpret existing retained claims.

**Public interface:**

```python
def validate_reference_claim_sources(
    artifacts: Sequence[CandidateArtifact],
    claims: Sequence[ReferenceClaim],
) -> tuple[CandidateDiagnostic, ...]: ...
```

The function checks only proposed claims against supplied after images. It performs no filesystem, database, provider, clock or network access; it does not resolve a namespace, check target existence/revision/currentness, establish source completeness, require one new claim for every reference, or certify semantic verification. A clean result must not be described as publication authority. Existing `validate_projected_bindings` remains the complementary target-side preflight. Retained historical claims with other anchor schemes are not rewritten, rejected at storage load or silently rebound by this new helper.

**Shared parser extraction:** Move the existing `_parse_image(artifact, text)` and its empty-content hash constant unchanged from `element_identity_candidate_store.py` to this new pure module. Preserve its exact absent-image representation, ordinary parser call, and glossary/evidence_inventory empty-fact behavior using the existing bundle helper. Import `_parse_image` into candidate_store under its original name so existing preflight callers still use precisely one implementation. Remove now-unused imports only. Avoid circular imports by following the current candidate/bundle class dependencies; no authority/store import belongs in the new pure source module.

**Input normalization:** Snapshot ordinary Sequence inputs to tuples; reject strings/bytes/generators as containers. Require exact CandidateArtifact and ReferenceClaim instances and revalidate mutable-damaged/deleted frozen fields. Artifacts have unique canonical paths using the existing adapter path policy; role is a nonblank exact string; before/after are exact strings or None with at least one present, and actual text/path/role must be valid UTF-8. Validate paths/text via `_validate_input` using its neutral references role independently of the claimed role, as the current candidate request normalizer does. Claims reuse `bindings.request(..., ReferenceClaim)` for nonempty batches, retaining its exact-field and duplicate rules; an empty claims sequence is valid. Empty artifacts with empty claims is valid. Do not coerce IDs, revisions, source anchors, integers, padding or path spellings. Normalize malformed request structure/type/Unicode/recursion/missing fields to a bounded ValueError without including the full untrusted payload. Preserve original caller objects and sequences.

**Claim matching policy:**

1. For each claimed source path, require a supplied artifact with a present after_text. Otherwise emit `CandidateDiagnostic("reference_source_missing", source_path, target_id, "claim requires a present supplied after image")`. None and empty are distinct.
2. Compute the actual after-text UTF-8 SHA-256; a differing claim.source_sha256 emits code `reference_source_hash_mismatch` for that claim. Do not fall back to its before image or a current filesystem file.
3. Claimed source roles must be in existing IDENTITY_SUPPORTED_ROLES. Unknown roles emit `unsupported_role` for the source, not a guessed parser policy. Parse each present supported claimed source once with the shared `_parse_image`; glossary and evidence_inventory deliberately have no reference facts. Validate request structure for unclaimed artifacts, but do not parse them or emit their semantic/parser findings in this claim-only check. Empty claims therefore returns an empty tuple after request validation.
4. Preserve each claimed source's parser diagnostics as CandidateDiagnostic using its existing code, source path, element_id None, and the current preflight detail convention `after span:<start>:<end>: <detail>`. For every parsed reference with a non-null range_end_id emit `unsupported_reference_range` with source path/target_id and a bounded explanation; do not expand the interval or accept its first endpoint as a single reference.
5. Eligible bindings are exact triples `(f"span:{ref.span.start}:{ref.span.end}", ref.target_id, ref.relation)` for parsed references whose range_end_id is None. A claim must match one complete triple; otherwise emit `reference_source_binding_mismatch` for its path/target with a bounded message identifying the absent exact span/target/relation match. Declaration label spans, parser-masked fenced/indented code and comments, unsupported qualified labels and partial-token prefixes do not create eligible reference facts. Inline code is NOT blanket-masked: supported literal IDs inside inline code retain the existing parser's exact inner span. Match parser spans directly; do not parse arbitrarily large anchor numerals into integers or normalize padded anchors. Do not invent zero-width references from the artifact filename: the shared typed parser reads source text, and an empty file named investigations/FR-000001.md produces no reference facts. Other existing inventory locator rules are not a new source-span policy.
6. Different target_revision values for the same genuine source triple remain source-compatible; this helper cannot determine which revision the prose semantically assesses. Null claims remain null. Do not add current/verified flags, mutate a claim, or treat a low-level `evidence` relation as approval. The target-side validator and semantic reviewer must still decide their separate contracts.

Sort and deduplicate the resulting CandidateDiagnostic values using the existing stable candidate result ordering `(path or "", element_id or "", code, detail)`. Use constant bounded messages for missing/hash/binding/role/range problems, rather than interpolating arbitrary claimed anchors or payloads into details. IDs themselves remain exact in the diagnostic element_id field. A source may produce parser diagnostics plus a claim mismatch; do not suppress integrity diagnostics just because one valid claim also exists.

**Required first regression before production edits:** A real store target-side preflight demonstrates its intentional scope, then the new missing source validator is reached:

```python
def test_existing_target_does_not_authenticate_a_wrong_source_anchor(tmp_path):
    import hashlib
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_bindings import ReferenceClaim
    from harness.element_identity_candidate import CandidateArtifact
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
        ElementCreate(label, "Scene", "Scene body.", "reserve"),
    ))
    text = "Before " + label
    claim = ReferenceClaim("evidence.md", hashlib.sha256(text.encode()).hexdigest(),
                           "span:0:9", label, "1", "evidence")
    assert store.validate_projected_bindings(spec_id="demo", claims=(claim,)) is None
    from harness.element_identity_reference_sources import validate_reference_claim_sources
    result = validate_reference_claim_sources(
        (CandidateArtifact("evidence.md", "evidence", text, text),), (claim,),
    )
    assert [item.code for item in result] == ["reference_source_binding_mismatch"]
```

Root verified the existing actual parser emits FR-000001 at span:7:16 with relation evidence for the fixture. Do not mock parser/store/target preflight. The store accepts the target binding by design, not because source authentication is already implemented there. The same pure probe verified inline-code `FR-000001` at inner span:1:10, a fenced block with that ID has no references, and empty investigations/FR-000001.md has no implicit filename reference.

**Compatibility correction discovered in the covering run:** The unchanged `test_every_grammar_valid_unsupported_req_or_ac_label_is_diagnostic` fails because Lexicon header IDs already classified as unsupported declarations are also passed through the newer whole-reference-token scanner, producing extra unsupported_reference diagnostics; valid managed IDs in a wrong declaration family can similarly leak header reference facts. Root confirmed relevant parser/test files are unchanged from BASE and the standalone failing test does not import this new source module. This is an earlier-branch compatibility defect, not a RED proving the new source function was absent. Preserve that existing exact test assertion; do not weaken it or change Lexicon grammar or whole-token policy.

In `parse_lexicon_source`, pass the exact source spans already classified with `unsupported_lexicon_id` or `unexpected_definition` to the existing `_references(..., excluded_spans=...)` parameter. That shared parameter already distinguishes declaration-label spans from body references. Do not mask whole lines/blocks or suppress diagnostics by text/code after scanning. Keep the existing declaration diagnostic at its original span, and keep real valid/unsupported references elsewhere in the same block visible. This is the only additional parser change authorized by this amendment.

Before that parser edit, retain the actual existing failing test output and add a focused wrong-family header/body control: `REQ: AC-000001` remains an unsupported declaration, but an ordinary reference to AC-000001 in its THEN body remains a reference at its own span. Include an unexpected-definition header (for example RULE: FR-009) with a valid body reference and unsupported body-label control. Cover native and projection roles and exact CRLF/Unicode offsets. Existing correctly supported definitions/references stay unchanged. Run focused amended-parser controls, then the same eight-module covering command once on the amended code; do not relabel the original 1,510-pass/1-fail result as passing. Report the unchanged baseline failure, new regression RED and corrected GREEN separately.

- [ ] Add required real regression and retain missing-module RED before production edits. Implement minimal source matching and parser extraction, then verify GREEN.
- [ ] Cover positive exact spans for all seven ID families, preserved legacy/composite labels and six/seven/5,000-digit IDs, repeated labels at distinct positions, multiple claims and sources, null and differing historical revision claims, all four supported relations through real parser outputs, Markdown/Lexicon references, UTF-8/CRLF code-point spans and original byte hashes. Use hand-calculated literal spans where practical; test expected triples independently instead of copying parser output into both input and assertion for every case.
- [ ] Reject wrong/missing source, stale before-only hash, None versus empty, wrong target/relation/span, padded/negative/huge/non-span anchors, declaration-only labels, parser-masked fenced/indented code and comments, unsupported whole qualified/suffixed labels and intervals. Include positive supported inline-code references with the exact inner span. Preserve existing parser qualification/range semantics rather than broadening grammar. Reject a fabricated zero-width claim based only on an empty investigation file's name and distinguish an empty present file from absence.
- [ ] Cover exact type/container/duplicate/canonical-path and damaged frozen-field rejection; unclaimed malformed request fields still fail structurally, while unclaimed well-formed artifacts with parser problems are outside this claim-only validation. Show deterministic sorted/deduplicated diagnostics and no mutation. Verify no I/O using focused interdiction after real fixture setup. No test may imply source-compatible claims certify target currentness or semantic evidence.
- [ ] Verify extracted `_parse_image` retains exact absent/empty behavior and old candidate preflight semantics. Run once final covering modules: new `tests/unit/test_element_identity_reference_sources.py`, `tests/unit/test_discovery_identity_candidate.py`, `tests/unit/test_definition_identity_candidate.py`, `tests/unit/test_issue_identity_candidate.py`, `tests/unit/test_supplemental_identity_bundle.py`, `tests/unit/test_element_artifacts.py`, `tests/unit/test_element_artifact_lexicon.py`, `tests/unit/test_element_artifact_reference_tokens.py`. Existing paths were verified by root; no full/million/provider/live/postcommit repeats.
- [ ] Document source-side checks and explicit complementary target/semantic/captured-baseline duties. Self-review unchanged parser behavior and import layering, run git diff --check, commit task files and retain actual commands/RED/GREEN/provenance in report. Root owns plan/ledger and independent review.

## Remaining integration

Future publication acceptance must combine authenticated complete physical before/postimages, this source matching, projected target validation and real read-only semantic review under the existing completion/recovery owner. Managed-spec/run enforcement and all producers remain unwired; no earlier historical record or current workflow is changed by this pure adapter.
