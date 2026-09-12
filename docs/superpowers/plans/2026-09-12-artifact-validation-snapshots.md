# Immutable ancillary artifact validation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make existing derived-Lexicon and evidence-inventory rules available against immutable captured text so later managed publication can validate exactly the bytes it will promote.

**Architecture:** Extract text-only counterparts of the existing source, glossary and inventory validators and one complete derived-Lexicon text validation entry point. Preserve Path-based entry points and their existing legacy behavior through thin wrappers. This is reusable validation preparation, not activation or an alternative identity checker.

**Tech Stack:** Python standard library, existing Lexicon validity/source rules, pytest; no dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Keep derived representations distinct from authoritative definitions, and retain current Lexicon grammar/validity, source metadata, ID equivalence, approved source terms and glossary rules.
- Evidence inventory JSON describes discovered sources and frontier coverage. Its source IDs and ID-like URL strings are not AC/FR/NFR/ISS/U/A/T definitions or implicit element references.
- Pure functions must use only supplied text, never open supplied names or paths, write files, allocate IDs, change registry state, or certify publication.
- Preserve existing Path APIs, returned error wording/order, report fields and legacy newline/hash behavior. No parser grammar, JSON schema, identity schema, producer routing or controller activation change in this task.
- Exact snapshot hashes use the original supplied strings encoded as UTF-8. Preserve CRLF and Unicode; never normalize snapshot source before hashing.

---

### Task 1: shared text-only validation rules with legacy wrappers

**Files:** Modify `src/lexicon/source_contract.py`, `src/lexicon/glossary.py`, `src/harness/spec_lexicon_gate.py` and the existing `_validate_evidence_inventory` wrapper in `src/harness/squad_executors.py`. Create `src/harness/evidence_inventory.py`, `tests/unit/test_artifact_validation_snapshots.py` and `docs/artifact-validation-snapshots.md`. Existing tests remain intact. Do not grow the already-large executor module with the moved inventory implementation.

**Interfaces:** Add these exact text APIs, retaining all existing APIs:

```python
# lexicon.source_contract
def source_contract_findings_text(
    derived_text: str, *, source_text: str, source_name: str,
) -> list[Finding]: ...

def source_approved_terms_text(source_text: str) -> set[str]: ...

# lexicon.glossary
def parse_glossary_terms(text: str) -> set[str]: ...

# harness.evidence_inventory
def validate_evidence_inventory_text(
    text: str, *, required_seed_locators: tuple[str, ...] = (),
) -> str | None: ...

# harness.spec_lexicon_gate
def validate_spec_lexicon_texts(
    *, derived_text: str, source_text: str, source_name: str,
    glossary_text: str | None, artifact_type: str,
) -> dict[str, object]: ...
```

The full Lexicon text result contains exactly the existing report's `schema_version`, `artifact_type`, `artifact_sha256`, `source_sha256`, `glossary_sha256`, `ok` and `findings` fields. It does not invent filesystem paths, timestamps or publication authority. `glossary_text=None` means absent glossary, an empty term set and a null glossary digest; an empty supplied glossary has the SHA256 of empty bytes. Findings retain existing code/message/line/span formatting. Source-name checks compare basenames using the same rule as the current source-ref check, with no filesystem access.

Source-contract and glossary Path functions read and delegate to the text algorithms. Move the inventory's existing JSON parsing and complete structural/required-seed algorithm into its pure module. The executor wrapper retains OSError handling and delegates text validation without copying the algorithm. Preserve all original accepted shapes and diagnostic order here; this refactor does not introduce a new inventory schema or infer typed element bindings.

The existing `_validate_spec_lexicon_artifacts` Path entry point delegates its rule evaluation to `validate_spec_lexicon_texts`, then adds the existing artifact/source/glossary path fields and preserves its current raw-file report digest convention. Existing legacy Path calls use `read_text` newline normalization; the new immutable-text API does not. This is an explicit compatibility boundary, not a claim that a mutable Path validation is atomic or that a legacy report authorizes managed publication. Later managed publication must use captured exact text and bind that snapshot, not trust a separately reread legacy report. Avoid incidental redesign of the Path gate or timestamps in this task.

- [ ] Write a behavioral test before adding the new APIs, collecting and executing the test before the missing API import:

```python
def test_inventory_snapshot_does_not_infer_element_ids_from_source_strings():
    import json
    from harness.evidence_inventory import validate_evidence_inventory_text

    locator = "https://example.test/AC-1000000"
    text = json.dumps({
        "schema_version": 1,
        "sources": [{"id": "U-000001", "locator": locator, "kind": "web",
                     "status": "read", "disposition": "relevant",
                     "discovered_from": "prompt", "discovery_method": "seed"}],
        "frontier": {"disposition": "complete", "unvisited_relevant_sources": [],
                     "expanded_seed_locators": [locator]},
    })
    assert validate_evidence_inventory_text(text, required_seed_locators=(locator,)) is None
    assert validate_evidence_inventory_text(text, required_seed_locators=("missing",)) == (
        "missing declared source seed(s): missing")
```

- [ ] Run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_artifact_validation_snapshots.py -q` and retain the expected behavioral RED before implementation.
- [ ] Add tests before corresponding changes for full Lexicon snapshot success; stale source hash; missing/wrong SOURCE metadata; missing/extra FR/AC and existing ERROR-family checks; invalid grammar without false source-ID-diff noise; source-owned measurable terms and unknown terms; glossary heading/bold/plain-line parsing; absent versus empty glossary; exact CRLF/Unicode hashes and source-metadata matching.
- [ ] For valid Lexicon text use the complete shape already exercised in `tests/unit/test_spec_lexicon_gate.py`: SOURCE, SOURCE_SHA256, ARTIFACT/TITLE, FR REQ with GIVEN/WHEN/THEN/OUTPUT/EXAMPLE and AC GIVEN/WHEN/THEN. Retain real parsing/validity instead of substituting a mocked validator. Use source FR/AC IDs with seven-digit and preserved legacy spellings in coverage.
- [ ] Cover every existing inventory validation branch using real JSON: invalid/root/version/sources/list item/required source strings/frontier/disposition/unvisited/expanded seeds/missing seeds/missing expanded seeds. Verify retained error messages and ordering, and compare pure results with the existing Path wrapper on equivalent input.
- [ ] Implement the named pure functions and shared legacy wrappers. Preserve source-ID extraction, approved-term and glossary semantics; no duplicate copied validators. Hash exact pure inputs with `hashlib.sha256(text.encode("utf-8")).hexdigest()` and return existing Finding representations.
- [ ] Add boundary tests proving pure APIs do not read/write filesystem or use the supplied name as an openable path. Exercise real text while trapping filesystem calls, plus independent LF Path-wrapper parity and explicit legacy CRLF compatibility. Do not claim this test authenticates future staged publication.
- [ ] Run new snapshot tests plus `tests/unit/test_spec_lexicon_gate.py`, `tests/unit/test_tasks_lexicon_gate.py`, `tests/unit/test_lexicon_cli.py`, `tests/unit/test_lexicon_validity.py`, `tests/unit/test_element_artifact_lexicon.py`, and `tests/kernel/test_squad_executors_journal.py`. Retain exact commands/output and any failure honestly; no live provider calls or global install.
- [ ] Document text APIs, exact snapshot semantics and legacy Path compatibility, source-inventory non-identity status, and the remaining managed bundle/publication integration. Self-review, run `git diff --check`, commit only task files and write full RED/GREEN report to this plan's ignored task report.

## Following work

Managed candidate bundle integration still needs explicit source/projection/glossary associations, source-inventory artifact scope, issue occurrence authorization, interval/qualified reference policies, authenticated canonical/staged bytes, semantic review and durable publication. These text APIs alone do not satisfy those requirements or enable any managed run.
