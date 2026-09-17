# Identity memory width compatibility implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Remove the remaining deterministic memory drawer input-width ceiling while preserving every existing drawer key and exact-write identity check.

**Architecture:** Keep the existing canonical JSON/hash formula and memory owner. Remove only the requirement-ID length rejection; IDs remain nonempty exact strings, and unrelated wing/room/input validation remains unchanged. Exercise pure planning and the established in-memory collection test boundary without accessing a real palace.

**Tech Stack:** Existing memory writer, canonical requirement parser/planner, pytest and standard-library hashing.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- Existing labels, including FR-001 and historical composite IDs, remain exactly as published.
- Six is a minimum display width, not a storage width or maximum value.
- No live memory writes, graph publication, controller/provider/producer activation or identity lifecycle interpretation in this task.

---

### Task 1: preserve unbounded identity labels in deterministic memory planning

**Files:** Modify only `src/codegen/memory/mempalace_writer.py`, `tests/unit/test_mempalace_writer.py`, `tests/unit/test_spec_memory_miner.py`, and `docs/element-identity-storage.md`. The canonical planner in `src/echelon/spec_memory_miner.py` is an unchanged consumer under test. Do not refactor unrelated memory code, change drawer namespaces, add a parser dependency, or change retrieval/current-revision policy.

**Interface:** Keep `deterministic_requirement_drawer_id(*, wing, room, spec_sha256, requirement_id, content) -> str` and `MemPalaceWriter.write_exact` unchanged. Preserve the exact identity JSON member names/values, sorted compact serialization, schema_version integer 1, UTF-8 encoding, content hash and `drawer_<wing>_<room>_<digest>` format. Remove only `or len(requirement_id) > 512` from input validation. Keep exact-string/nonempty ID checks, wing/room length and path-character checks, hash validation and all other existing behavior. Do not normalize numeric padding or coerce identifiers. This function already accepts opaque nonempty string labels, so do not replace the removed width bound with a new numeric/composite grammar.

**Required first regression:** Add this to the existing writer tests before production edits, with imports under their existing style:

```python
def test_deterministic_drawer_identity_accepts_complete_wide_id():
    label = "AC-" + "9" * 5000
    identity = {
        "schema_version": 1,
        "wing": "demo",
        "room": "acceptance-criteria",
        "canonical_spec_sha256": "a" * 64,
        "requirement_id": label,
        "requirement_content_sha256": hashlib.sha256(b"Accepted").hexdigest(),
    }
    expected = "drawer_demo_acceptance-criteria_" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert writer_module.deterministic_requirement_drawer_id(
        wing="demo", room="acceptance-criteria", spec_sha256="a" * 64,
        requirement_id=label, content="Accepted",
    ) == expected
```

- [ ] Run the marked test using `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_mempalace_writer.py::test_deterministic_drawer_identity_accepts_complete_wide_id`. Retain the actual ValueError RED at the existing width guard, then remove the single guard and verify GREEN.
- [ ] Parameterize complete-ID expected digest checks for all seven families at 000001, 999999, 1000000 and a 5,000-digit string; boundary lengths 512/513; preserved FR-001, FR-MP-006 and long opaque composite strings. The test's expected digest must be independent literal formula, not a call to the function under test. Two labels identical through the old cap but different afterward must produce distinct hashes; exact replay must match. Keep the existing schema/fields/padding/UTF-8 formula unchanged. Cover invalid empty and non-string labels and unchanged invalid wing/room/hash controls without broadening validation policy.
- [ ] Add a real `plan_canonical_requirement_drawers` integration test using FR/NFR/AC 5,000-digit labels in actual UTF-8 Markdown bytes, matching canonical artifact hash and the actual shared parser. Assert exact complete labels, correct rooms, exact source/hash metadata and independently expected drawer IDs. Do not mock the planner/parser/hash function or claim unsupported other-family canonical mining.
- [ ] Exercise `write_exact` with a wide label using the existing `_ExactCollection` test boundary and its established patch pattern; assert stored metadata retains the entire string, replay is already_present, and changed stored requirement_id readback is drift. This is a local protocol test, not a real SDK/palace write or a revision-currentness certificate. Preserve the existing no-overwrite behavior and actual add-call counts.
- [ ] Run once the covering modules `tests/unit/test_mempalace_writer.py` and `tests/unit/test_spec_memory_miner.py`; no full/million/provider/live or post-commit repeat. Document the width correction and that drawer IDs identify immutable source/content occurrences, not the durable registry entity or current verification.
- [ ] Self-review that the only production change is the width guard, run git diff --check, commit task files and write full actual RED/GREEN commands and results to the report. Root owns plan/ledger and independent review.

## Remaining integration

Lifecycle/revision-aware memory metadata, current retrieval filtering, managed namespace selection and complete source/semantic/publication enforcement remain separate required adapters. Accepting a wide string does not establish its authority or authorize any memory write.
