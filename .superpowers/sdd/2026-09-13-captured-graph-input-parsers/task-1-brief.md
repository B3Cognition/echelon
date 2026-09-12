### Task 1: extract the three existing readers' pure text boundaries

**Files:** Modify `src/harness/canonical_requirements.py`, `src/harness/deferred_scope.py`, and `src/harness/verified_fulfillment_ledger.py`. Create `tests/unit/test_graph_source_parsers.py`; narrowly extend the three existing reader test modules if needed. Document in `docs/element-identity-storage.md`. No graph production, other parsing/lifecycle/publication/state/controller/executor/provider/CLI/startup/memory production, schemas, prose or unrelated refactor. Root owns plan/ledger. These three same-shaped extractions form one batch with one review.

**Public interfaces:**

```python
# harness.canonical_requirements
def extract_canonical_requirements_from_texts(
    *, spec_text: str | None = None, plan_text: str | None = None,
    coverage_text: str | None = None, tasks_text: str | None = None,
) -> list[CanonicalRequirement]: ...

# harness.deferred_scope
def parse_deferred_scope_ledger(text: str) -> DeferredScopeLedger: ...

# harness.verified_fulfillment_ledger
def parse_verified_ledger(text: str) -> VerifiedFulfillmentLedger: ...
```

New text parameters require exact strings (or None only for the four explicitly optional requirement images), with a fixed TypeError for wrong outer argument type. Do not accept bytes, Paths, duck-typed readers, a mapping of arbitrary filenames or new JSON objects in these text APIs. No filesystem/stat/open, environment, clock, adapter, database or provider access. Outputs are fresh detached existing records; existing mapping-valued verified-row fields remain fresh ordinary dictionaries, not a newly invented immutable wire type.

The requirement text function processes spec.md/spec, plan.md/plan, coverage-map.md/coverage and tasks.md/task_metadata in precisely existing precedence/order. Reuse the same REQ_ID_RE, TASK_REQ_RE, `_is_explicit_requirement_definition`, `_split_reqs` and element_id_sort_key. Preserve exact source filename strings, source kind, one-based splitlines numbering and stripped source text. Explicit definitions still supersede earlier references according to the current helper, task metadata remains setdefault, UNMAPPED and invalid task tokens remain excluded. None means absent; an empty present Markdown string has no rows but must not be converted into a filesystem observation. Legacy inventory accepts families and patterns beyond the managed seven-family grammar; preserve them, including historical suffix/composite/range-endpoint behavior. This function does not decide which observations are managed definitions or authorize a reference.

`extract_canonical_requirements(spec_dir)` retains existing is_file checks and UTF-8 errors="replace" reads, then delegates to the pure shared body. Small private `_collect_markdown_text`/`_collect_task_metadata_text` helpers are allowed. Preserve private filesystem helper signatures if they have callers; do not copy the regex/precedence loops between paths. Existing output writers, fingerprints and CLI routing remain unchanged.

Move deferred JSON parsing/shape/entry/duplicate-ID validation into `parse_deferred_scope_ledger`, sharing existing DeferredScopeEntry.from_dict and helpers. Keep the exact existing accepted schema/entry interpretation and exception types/messages for equivalent text; do not introduce stricter duplicate JSON-key/version/numeric policies in this compatibility extraction. `read_ledger(spec_dir)` still returns an empty ledger for a nonexistent file; an existing empty or malformed JSON file remains an error. I/O and Unicode errors retain existing DeferredScopeError wrapping in the filesystem owner. The pure function never treats None or empty text as an absent ledger.

Move verified JSON-to-row conversion into `parse_verified_ledger`. Preserve existing v1/v2/default fields, uppercase status conversion, `_string` behavior, row order, duplicate requirement rows, ignored non-dict row entries, evidence/reference tuple conversion and fresh artifact_hashes/receipt_refs dictionaries. Preserve existing malformed shape/error behavior rather than turning this into a new validator. `read_verified_ledger(path)` still performs its existing UTF-8 read and propagates missing-file/decoding failures, then calls the same pure parser. The new parser returns exactly the existing dataclass records and does not assess evidence or rebind old evidence to a current identity revision.

These helpers deliberately retain compatibility parsing, including permissive legacy behavior. They must be documented as observations, not canonical managed validation or proof. A future managed graph owner still must use the existing typed candidate/source/identity checks and authenticate captured dependencies before building or publishing a graph. No live graph caller is changed to use captured inputs in this task.

**Actual RED before production:** Add three separate real tests, one per entry point. Import each existing module (not the missing new symbol), construct/capture a valid existing source, assert its current filesystem reader returns an independently expected complete result, change the source file, and call the missing pure entry on the original captured string. This must fail with AttributeError for each missing entry after valid fixture/read setup—not an import or invalid fixture error. Example requirement core:

```python
import harness.canonical_requirements as requirements

def test_requirement_capture_survives_later_file_change(tmp_path):
    path = tmp_path / "spec.md"
    text = "- **FR-000001**: Keep the scene.\r\n"
    path.write_bytes(text.encode("utf-8"))
    expected = [requirements.CanonicalRequirement(
        "FR-000001", "spec", "spec.md", 1, "- **FR-000001**: Keep the scene.")]
    assert requirements.extract_canonical_requirements(tmp_path) == expected
    captured = path.read_bytes().decode("utf-8")
    path.write_text("- **FR-000002**: Different scene.\n", encoding="utf-8")
    assert requirements.extract_canonical_requirements_from_texts(spec_text=captured) == expected
```

- [ ] Write the three actual regressions and run `tests/unit/test_graph_source_parsers.py`; notify root of each expected missing-attribute RED before production. Use `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest` from this worktree; standalone Python requires PYTHONPATH=src.
- [ ] Extract the smallest shared parsing bodies and keep existing wrappers' I/O behavior. Obtain GREEN on the new tests without graph/runtime changes.
- [ ] Add independent complete expected records across all four requirement images: explicit-definition precedence, first reference/source order, task fallback/exclusions, CRLF/Unicode, legacy/suffixed/composite IDs and 000001/999999/1000000/10000000/5000-digit strings with numeric ordering. No formatter renumbering or int coercion. Compare pure and real filesystem readers while retaining independent expected results.
- [ ] Cover all deferred entry fields, statuses and duplicate entry-ID rejection, exact malformed/empty text behavior, actual nonexistent/empty/bad-UTF8 file distinctions, and unchanged read/defer/restore flows via existing tests. Pure None/bytes/path/subclass arguments reject before I/O.
- [ ] Cover complete verified v1/v2/default rows, every provenance/fingerprint field, selected evidence, unchanged legacy normalization and ordering, malformed JSON/shape and missing/unreadable file distinctions. Mutating one result's nested mapping must not alter a second parse or captured input. Keep original evidence references exactly attached to their row; do not infer current verification from status text.
- [ ] Add scoped purity tripwires after fixture setup for builtins.open, io.open/Path.open, Path.read_text/read_bytes, stat/is_file/exists and directory enumeration, plus relevant authority/provider entry points if imported. Call all three real parsers under the tripwires; no temporary-file parsing or process-global production monkeypatching.
- [ ] Run once the covering modules under tests/unit: `test_graph_source_parsers.py`, `test_canonical_requirements.py`, `test_deferred_scope.py`, `test_verified_fulfillment_ledger.py`, `test_spec_graph.py`, `test_spec_graph_audit.py`, `test_harness_main_deferred_scope.py`. Existing offline subprocess CLI tests are allowed; no installed CLI, provider, capacity, full-unit/global install or unchanged postcommit repeat. Later amendments get named focused covering evidence and exact chronology.
- [ ] Self-review no duplicated parsing policy, all wrapper/error/source-line behavior and honest observation-only documentation; diff-check and commit scoped files and full report. Root will provide fresh original-BASE review after DONE.

## Remaining integration

Graph assembly still reads policy artifacts, traceability, amendments, memory audit snapshots and RE/topology data through additional owners. These three extracted readers alone are not a captured-source graph builder. Complete source selection/authorization, graph sealing, producer/runtime/completion integration, lifecycle-aware memory and bounded repair remain required before live rollout.
