# Source Topology Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish complete, exact, provider-neutral source topology for every configured workspace source so RE, delivery, artifact graphs, CLI users, and a later Graph Analyst share one auditable code-structure contract.

**Architecture:** CodeGraph and PerlGraph continue to produce native analysis artifacts, but both gain stable symbol keys, exact relationship endpoints, and explicit completeness/capability receipts. New `echelon.topology_*` modules validate and normalize those artifacts for bounded reads. New `harness.topology_*` modules stage and publish selected source snapshots under `re/topology/` through the existing RE publication lock and a shared rollback transaction. RE publishes topology with semantic RE; delivery keeps topology run-local until landing and reconciles it against the exact landed default-branch commit. Artifact graphs keep only source nodes and lightweight receipts.

**Tech Stack:** Python 3, dataclasses, `pathlib`, SHA-256, JSON, Typer, pytest, Node.js, TypeScript, Vitest, CodeGraph 1.4.1, PerlGraph, existing RE fingerprint/publication/locking infrastructure.

## File Responsibility Map

**Provider runtimes**

- `extension/scripts/node/codegraph/codegraph-adapter.js`: CodeGraph-native node/edge extraction and stable provider-local keys.
- `extension/scripts/node/codegraph/codegraph-bridge.js`: schema-2 artifact assembly, completeness counts, and removal of the symbol cap.
- `extension/scripts/node/perlgraph/src/identity/symbol-key.ts`: shared PerlGraph canonical locator and key generation.
- `extension/scripts/node/perlgraph/src/types.ts`: schema-2 PerlGraph types, capability states, and unresolved-edge diagnostics.
- `extension/scripts/node/perlgraph/src/analysis/analyze.ts`: exact endpoint resolution and complete/unsupported/empty claims.

**Provider-neutral topology domain**

- `src/echelon/topology_model.py`: immutable normalized records and ID helpers.
- `src/echelon/topology_provider.py`: native artifact validation, relationship mapping, search, explain, neighbors, and impact.
- `src/echelon/topology_registry.py`: canonical `re/topology/index.json` and receipt loading.
- `src/echelon/topology_audit.py`: live registry, hash, endpoint, count, source, and freshness reconciliation.
- `src/echelon/topology_cli.py`: deterministic text/JSON rendering and exit-code policy.

**Mutation and workflow wiring**

- `src/harness/publication_transaction.py`: shared path-safe stage/apply/rollback primitive extracted from RE publication.
- `src/harness/topology_publication.py`: selected-source canonical topology publication.
- `src/harness/topology_evidence.py`: RE/delivery provider receipt construction and exact snapshot capture.
- `src/harness/topology_promotion.py`: landed-only delivery reconciliation and non-fatal publication.
- `src/harness/re_publication.py`: one transaction containing semantic RE and refreshed topology operations.
- `src/harness/re_lifecycle.py`: explicit one-source semantic RE refresh without refreshing reusable siblings.
- `src/harness/land.py`: post-land topology reconciliation and status reporting.

**Public integration**

- `src/echelon/spec_graph.py` and `src/echelon/workspace_graph.py`: one canonical `source:<id>` identity and compact receipt links.
- `src/echelon/cli_app.py`: top-level `echelon topology` group and `echelon re refresh --source`.
- `extension/workflow/phases/verify-spec-2-codegraph.md`: delivery receipt finalization after both providers run.

## Global Constraints

- `source:<source-id>` is the only source node identity. Do not retain or accept `re-source:<source-id>`.
- Provider artifact `symbol_key` is `sha256:<hex>` over UTF-8 compact JSON `[normalized_source_relative_path, qualified_name, kind, signature_or_empty]`.
- Echelon exposes provider-scoped symbol IDs as `symbol:<source-id>:<provider>:<hex>`; source fingerprints never participate in IDs.
- A duplicate canonical locator is invalid even if line numbers differ. Line numbers are location metadata only.
- Traversable relationships require exact `source_key` and `target_key`. Unresolved provider observations live in diagnostics, not in the traversable relationship list.
- CodeGraph has no `--max-symbols` option or implicit symbol cap. Size warnings may report bytes/counts but never change output.
- `re/topology/index.json` is the only canonical topology authority. Existing graph files below `re/sources/<id>/` are legacy inputs to migrate during the next validated RE publication, not a second authority.
- Topology and semantic RE have independent generations and freshness results.
- Canonical publication uses configured source IDs and safe relative paths only. It never discovers arbitrary repositories recursively.
- Read commands never generate, repair, migrate, or publish topology.
- Full symbol/file graphs stay in provider artifacts and in bounded in-memory indexes. Spec/workspace artifact graphs contain only compact receipts and explicit exact evidence bridges.
- A normal no-FF land creates a new commit even when the source tree matches the verified feature commit. Never restamp pre-merge evidence as if it analyzed that merge commit. Promote directly only on exact commit/fingerprint equality; otherwise perform a bounded deterministic post-land recapture against default-branch `HEAD`.
- Post-land topology failure is reported but never changes a successful source merge into a failed land.
- This feature is deterministic Python/Node functionality. Do not add an LLM command skill or `SKILL_MAP` entry for `echelon topology`.

---

### Task 1: Make CodeGraph Output Complete And Exactly Addressable

**Files:**
- Modify: `extension/scripts/node/codegraph/codegraph-adapter.js`
- Modify: `extension/scripts/node/codegraph/codegraph-bridge.js`
- Modify: `extension/scripts/node/codegraph/integration-types.js`
- Modify: `tests/kernel/test_codegraph_integration_contract.py`
- Modify: `src/harness/codegraph_evidence.py`
- Modify: `src/harness/codegraph_evidence_mapper.py`
- Modify: `tests/unit/test_harness_main_codegraph_evidence.py`
- Modify: `tests/unit/test_codegraph_evidence_mapper.py`

**Interfaces:**
- Produces CodeGraph schema 2 with `tool: "codegraph"`, `tool_version: "1.4.1"`, `provider_status`, `complete`, `counts`, and `diagnostics`.
- Extends every symbol with `symbol_key: "sha256:<hex>"`.
- Replaces relationship display-name endpoints with required `source_key` and `target_key`; optional `source_name` and `target_name` remain display metadata.
- Produces exact `caller_key`/`callee_key`, `child_key`/`parent_key`, and exact impact keys in derived collections.
- Removes `DEFAULT_MAX_SYMBOLS`, `--max-symbols`, `truncateSymbols`, and the `maxSymbols` argument to `runBridge`.

- [ ] **Step 1: Write failing bridge contract tests**

Add a Node subprocess test in `test_codegraph_integration_contract.py` that calls exported `assembleAnalysisOutput` with 10,001 valid synthetic symbols and asserts all 10,001 are emitted, `complete is True`, and `counts.discovered_symbols == counts.emitted_symbols == 10001`. Add static assertions that `--max-symbols`, `DEFAULT_MAX_SYMBOLS`, and `truncateSymbols` are absent.

```python
def test_bridge_emits_more_than_ten_thousand_symbols_without_truncation() -> None:
    script = """
const bridge = require(process.argv[1]);
const symbols = Array.from({length: 10001}, (_, i) => ({
  symbol_key: `sha256:${String(i).padStart(64, '0')}`,
  qualified_name: `f${i}`,
  name: `f${i}`,
  kind: 'function',
  file_path: `src/f${i}.ts`,
  line_start: 1,
  line_end: 1
}));
const out = bridge.assembleAnalysisOutput({
  repoPath: process.cwd(), symbols, relationships: [], callGraph: [],
  typeHierarchy: [], impactRadius: [], publicSymbols: symbols,
  indexStats: {}, extractionSummary: {languages: [], unsupported_languages: [], total_extracted: 10001}
});
if (out.symbols.length !== 10001 || !out.complete) process.exit(1);
"""
```

- [ ] **Step 2: Run the contract test and confirm current truncation/schema behavior fails**

Run: `pytest -q tests/kernel/test_codegraph_integration_contract.py -k 'ten_thousand or symbol_limit or endpoint'`

Expected: FAIL because completeness fields and exact keys are absent and the cap is still public.

- [ ] **Step 3: Add stable CodeGraph symbol keys in the adapter**

Normalize `file_path` to source-relative POSIX form, reject absolute/traversing paths, and hash the compact JSON locator with Node `crypto`. Build native node-ID to symbol-key/name maps once. Iterate native nodes for edges so duplicate qualified names in separate files remain distinct. Throw a contract error when two native nodes produce the same canonical locator.

```javascript
function symbolKey(node) {
    const locator = [
        normalizeSourcePath(node.filePath),
        String(node.qualifiedName),
        String(node.kind),
        node.signature == null ? '' : String(node.signature),
    ];
    return `sha256:${crypto.createHash('sha256')
        .update(JSON.stringify(locator), 'utf8').digest('hex')}`;
}
```

- [ ] **Step 4: Emit schema-2 exact endpoint collections and completeness claims**

Update `assembleAnalysisOutput` to filter hidden-source exclusions by `symbol_key`, not qualified name, and calculate discovered/emitted/excluded symbol and relationship counts. `complete` is true only when every in-scope symbol was emitted and every emitted relationship has two emitted endpoints. Preserve unresolved upstream observations in `diagnostics.unresolved_relationships` instead of inventing endpoints.

- [ ] **Step 5: Remove all symbol-cap parsing and execution**

Delete the option, usage text, validation, exported constant/function, warning, and `runBridge` parameter. Keep an informational output-size warning only after full JSON assembly, with no branch that slices symbols or edges.

- [ ] **Step 6: Move delivery summaries and evidence mapping to exact keys**

Validate schema 2 in `_analysis_is_usable`. Count display names in summaries but join test/call evidence through `symbol_key`, `caller_key`, and `callee_key`. Add two same-qualified-name symbols in different files and prove the evidence mapper follows only the exact caller/callee key pair.

- [ ] **Step 7: Run focused CodeGraph and mapping tests**

Run: `pytest -q tests/kernel/test_codegraph_integration_contract.py tests/unit/test_harness_main_codegraph_evidence.py tests/unit/test_codegraph_evidence_mapper.py`

Expected: PASS.

- [ ] **Step 8: Commit the complete CodeGraph contract**

```bash
git add extension/scripts/node/codegraph/codegraph-adapter.js extension/scripts/node/codegraph/codegraph-bridge.js extension/scripts/node/codegraph/integration-types.js tests/kernel/test_codegraph_integration_contract.py src/harness/codegraph_evidence.py src/harness/codegraph_evidence_mapper.py tests/unit/test_harness_main_codegraph_evidence.py tests/unit/test_codegraph_evidence_mapper.py
git commit -m "feat(topology): make codegraph output complete and exact"
```

### Task 2: Give PerlGraph The Same Identity And Capability Guarantees

**Files:**
- Create: `extension/scripts/node/perlgraph/src/identity/symbol-key.ts`
- Create: `extension/scripts/node/perlgraph/tests/symbol-key.test.ts`
- Modify: `extension/scripts/node/perlgraph/src/types.ts`
- Modify: `extension/scripts/node/perlgraph/src/extraction/perl-extractor.ts`
- Modify: `extension/scripts/node/perlgraph/src/resolution/call-resolver.ts`
- Modify: `extension/scripts/node/perlgraph/src/analysis/analyze.ts`
- Modify: `extension/scripts/node/perlgraph/src/output/writer.ts`
- Modify: `extension/scripts/node/perlgraph/tests/call-resolver.test.ts`
- Modify: `extension/scripts/node/perlgraph/tests/analyze.test.ts`
- Modify: `extension/scripts/node/perlgraph/tests/output-writer.test.ts`
- Modify: `extension/scripts/node/perlgraph/tests/golden-output.test.ts`
- Modify: `extension/scripts/node/perlgraph/tests/__snapshots__/golden-output.test.ts.snap`
- Modify: `tests/kernel/test_perlgraph_integration_contract.py`

**Interfaces:**
- Produces PerlGraph schema 2 with `tool_version`, `provider_status: ready|degraded|empty|unsupported`, `complete`, `counts`, and `capabilities`.
- Extends `PerlSymbol` with `symbol_key`.
- Extends traversable `PerlRelationship` with exact `source_key` and `target_key`.
- Adds `UnresolvedRelationship` diagnostics carrying names, source range, confidence, provenance, and notes without fake target keys.
- Changes `resolveCalls(calls, symbols, context)` to return `{ relationships, unresolved_relationships }`.

- [ ] **Step 1: Write failing key, duplicate-locator, and capability tests**

Cover path normalization, deterministic key generation, same qualified name in different files, duplicate locator rejection, no-Perl `unsupported`, Perl-files-with-no-symbols `empty`, parse diagnostics `degraded`, and healthy extraction `ready`.

```typescript
expect(symbolKey({
  file_path: 'lib/A.pm', qualified_name: 'A::run', kind: 'sub', signature: ''
})).toMatch(/^sha256:[0-9a-f]{64}$/);
```

- [ ] **Step 2: Run the PerlGraph tests and confirm schema-1 behavior fails**

Run: `npm test --prefix extension/scripts/node/perlgraph -- --run tests/symbol-key.test.ts tests/analyze.test.ts tests/call-resolver.test.ts`

- [ ] **Step 3: Add the shared TypeScript locator helper and key symbols after extraction**

Use the same compact JSON locator algorithm as CodeGraph. Sort symbols by `(file_path, line_start, kind, qualified_name, symbol_key)` after key assignment. Reject duplicate locators before relationship resolution.

- [ ] **Step 4: Separate resolved relationships from unresolved diagnostics**

Resolve package/module/call endpoints through exact symbol indexes. A traversable edge must reference two known symbol keys. External modules, dynamic calls, ambiguous calls, and unresolved imports become `unresolved_relationships` entries and retain provider-native confidence/provenance.

- [ ] **Step 5: Emit explicit provider capability and count claims**

Schema 2 reports discovered/emitted file, symbol, relationship, unresolved, parse-failure, and dynamic-pattern counts. `complete` means no extraction truncation; it may remain true for a capability-aware `unsupported`, `empty`, or `degraded` artifact. `provider_status` communicates evidence quality separately.

- [ ] **Step 6: Update summaries and golden output**

Top callers/callees retain display names but derive counts from exact call keys. Confidence audit includes both traversable edges and bounded unresolved diagnostics. Update the committed snapshot intentionally.

- [ ] **Step 7: Run typecheck, runtime tests, and Python integration contracts**

Run: `npm run typecheck --prefix extension/scripts/node/perlgraph`

Run: `npm test --prefix extension/scripts/node/perlgraph`

Run: `pytest -q tests/kernel/test_perlgraph_integration_contract.py tests/unit/test_harness_main_perlgraph_evidence.py`

Expected: PASS.

- [ ] **Step 8: Commit the PerlGraph contract**

```bash
git add extension/scripts/node/perlgraph tests/kernel/test_perlgraph_integration_contract.py
git commit -m "feat(topology): add exact perlgraph identities"
```

### Task 3: Implement The Provider-Neutral Topology Model And Traversal

**Files:**
- Create: `src/echelon/topology_model.py`
- Create: `src/echelon/topology_provider.py`
- Create: `tests/unit/test_topology_model.py`
- Create: `tests/unit/test_topology_provider.py`

**Interfaces:**
- Produces immutable `TopologySource`, `TopologyFile`, `TopologySymbol`, `TopologyRelationship`, `TopologyReceipt`, `TopologySearchResult`, `TopologyTraversalStep`, and `TopologyTraversalResult`.
- Produces `load_provider_artifact(path: Path, *, provider: str, source_id: str) -> LoadedTopologyProvider`.
- Produces `PublishedTopology.receipt`, `search`, `explain`, `neighbors`, and `impact` with canonically ordered bounded results.
- Normalizes relationships to `CONTAINS`, `DECLARES`, `IMPORTS`, `REQUIRES`, `CALLS`, `EXTENDS`, `IMPLEMENTS`, `USES_ROLE`, `TESTS`, `REFERENCES`, `INSTANTIATES`, `DECORATES`, or `OTHER`.

- [ ] **Step 1: Write failing model and provider-validation tests**

Use compact schema-2 CodeGraph and PerlGraph fixtures. Assert exact exposed IDs, no absolute paths, immutable records, duplicate symbol-key rejection, recomputed locator-key equality, missing endpoint rejection, duplicate relationship rejection, count mismatch rejection, and unsupported/empty PerlGraph acceptance.

```python
assert symbol.id == f"symbol:api:codegraph:{symbol.symbol_key.removeprefix('sha256:')}"
assert relationship.type == "CALLS"
assert relationship.source_id in topology.nodes_by_id
assert relationship.target_id in topology.nodes_by_id
```

- [ ] **Step 2: Run the new tests and confirm the modules are absent**

Run: `pytest -q tests/unit/test_topology_model.py tests/unit/test_topology_provider.py`

- [ ] **Step 3: Implement immutable normalized records and ID/path helpers**

Reject unsafe source IDs, provider names, absolute paths, `..`, backslashes after normalization, malformed hashes, and unknown capability states. File IDs are `file:<source-id>:<source-relative-path>`; provider symbol IDs are source/provider scoped as defined globally.

- [ ] **Step 4: Implement explicit native relationship maps**

CodeGraph `extends` and PerlGraph `inherits` both map to `EXTENDS`; every known kind receives an explicit mapping test. Unknown native kinds map to `OTHER`, retain `provider_kind`, and are excluded from default impact traversal.

- [ ] **Step 5: Build deterministic indexes and selector resolution**

Index nodes by exact ID, key, qualified name, basename, and source-relative path. Exact IDs win. A non-exact selector succeeds only with one candidate and raises `TopologyNodeResolutionError` with at most ten ordered candidates otherwise.

- [ ] **Step 6: Implement bounded search and traversal**

Default limits are 50 results/edges and maximum accepted limit is 500. Default impact depth is 3 and maximum is 10. Results carry topology generation from the loaded canonical index, source fingerprint, provider receipt hash, traversed paths, and `truncated`.

Use these exact public method signatures:

```text
receipt(source_id: str) -> TopologyReceipt
search(source_id: str | None, query: str, types: frozenset[str], limit: int) -> TopologySearchResult
explain(source_id: str | None, node: str) -> TopologyExplainResult
neighbors(source_id: str | None, node: str, direction: str, relations: frozenset[str], limit: int) -> TopologyTraversalResult
impact(source_id: str | None, node: str, max_depth: int, relations: frozenset[str]) -> TopologyTraversalResult
```

- [ ] **Step 7: Run focused model/provider tests**

Run: `pytest -q tests/unit/test_topology_model.py tests/unit/test_topology_provider.py`

Expected: PASS.

- [ ] **Step 8: Commit the provider-neutral read model**

```bash
git add src/echelon/topology_model.py src/echelon/topology_provider.py tests/unit/test_topology_model.py tests/unit/test_topology_provider.py
git commit -m "feat(topology): add provider neutral read model"
```

### Task 4: Define The Canonical Registry And Live Audit

**Files:**
- Create: `src/echelon/topology_registry.py`
- Create: `src/echelon/topology_audit.py`
- Create: `tests/unit/test_topology_registry.py`
- Create: `tests/unit/test_topology_audit.py`
- Modify: `src/harness/re_fingerprint.py`
- Modify: `src/harness/re_lifecycle.py`
- Modify: `tests/unit/test_re_fingerprint.py`
- Modify: `tests/unit/test_re_lifecycle.py`

**Interfaces:**
- Produces `TopologyIndex`, `TopologySourceRecord`, `TopologyProviderReceipt`, and `TopologyArtifactReceipt` parsers.
- Produces `load_topology_index(project_root: Path) -> TopologyIndex | None` and `load_published_topology(project_root: Path, source_ids: Iterable[str] = ()) -> PublishedTopology`.
- Produces `audit_topology(project_root: Path, source_id: str | None = None) -> TopologyAuditReport`.
- Moves `resolve_re_fingerprint_profile(project_root)` into `harness.re_fingerprint` as the one shared profile resolver.

- [ ] **Step 1: Write failing registry schema and path-safety tests**

Use this authoritative shape:

```json
{
  "schema_version": 1,
  "generation": 3,
  "published_at": "2026-08-04T12:00:00+00:00",
  "sources": {
    "api": {
      "source_path": "sources/api",
      "source_fingerprint": {"value": "0000000000000000000000000000000000000000000000000000000000000000", "kind": "git", "dirty": false, "profile_hash": "1111111111111111111111111111111111111111111111111111111111111111", "git_head": "0123456789abcdef0123456789abcdef01234567"},
      "receipt": {"path": "re/topology/sources/api/receipt.json", "sha256": "sha256:2222222222222222222222222222222222222222222222222222222222222222"},
      "providers": {
        "codegraph": {
          "status": "ready",
          "complete": true,
          "artifacts": {
            "analysis": {"path": "re/topology/sources/api/codegraph-analysis.json", "sha256": "sha256:3333333333333333333333333333333333333333333333333333333333333333"},
            "summary": {"path": "re/topology/sources/api/codegraph-summary.json", "sha256": "sha256:4444444444444444444444444444444444444444444444444444444444444444"}
          }
        },
        "perlgraph": {
          "status": "unsupported",
          "complete": true,
          "artifacts": {
            "analysis": {"path": "re/topology/sources/api/perlgraph-analysis.json", "sha256": "sha256:5555555555555555555555555555555555555555555555555555555555555555"},
            "summary": {"path": "re/topology/sources/api/perlgraph-summary.json", "sha256": "sha256:6666666666666666666666666666666666666666666666666666666666666666"}
          }
        }
      }
    }
  }
}
```

Assert every source artifact is contained below its exact `re/topology/sources/<source-id>/` directory, with safe source IDs, sorted provider/artifact maps, receipt/index generation equality, configured source path equality, and exact hashes.

The source receipt elaborates tool versions, capabilities, counts, diagnostics,
and provenance for exactly the providers and artifacts already named by the
index source row. It has this exact ownership shape:

```json
{
  "schema_version": 1,
  "generation": 3,
  "source_id": "api",
  "source_path": "sources/api",
  "source_fingerprint": {"value": "0000000000000000000000000000000000000000000000000000000000000000", "kind": "git", "dirty": false, "profile_hash": "1111111111111111111111111111111111111111111111111111111111111111", "git_head": "0123456789abcdef0123456789abcdef01234567"},
  "analyzed_commit": "0123456789abcdef0123456789abcdef01234567",
  "provenance": {"kind": "re", "run_id": "re-20260804-120000"},
  "providers": {
    "codegraph": {
      "status": "ready",
      "complete": true,
      "artifact_schema_version": 2,
      "tool_version": "1.4.1",
      "capabilities": ["symbols", "relationships", "calls", "types"],
      "counts": {"symbols": 12, "relationships": 9},
      "diagnostics": [],
      "artifacts": {
        "analysis": {"path": "re/topology/sources/api/codegraph-analysis.json", "sha256": "sha256:3333333333333333333333333333333333333333333333333333333333333333"},
        "summary": {"path": "re/topology/sources/api/codegraph-summary.json", "sha256": "sha256:4444444444444444444444444444444444444444444444444444444444444444"}
      }
    }
  }
}
```

- [ ] **Step 2: Write failing audit matrix tests**

Cover status `current`, `degraded`, `stale`, and `invalid`; missing index; malformed JSON; hash drift; source removed from workspace config; source path changed; provider schema error; duplicate key; unresolved traversable endpoint; count mismatch; dirty source; and fingerprint mismatch.

- [ ] **Step 3: Run tests and confirm registry/audit modules are absent**

Run: `pytest -q tests/unit/test_topology_registry.py tests/unit/test_topology_audit.py`

- [ ] **Step 4: Implement strict registry parsing and provider loading**

The index is the discovery authority. Receipt files may elaborate provider counts/diagnostics, but cannot introduce a provider or artifact path absent from the index source row. Return ordered immutable mappings and wrap all malformed/path/hash failures in `TopologyRegistryError`.

- [ ] **Step 5: Centralize the RE fingerprint profile resolver**

Move the config-to-`ReFingerprintProfile` logic without changing serialized profile hashes. Update lifecycle imports and prove existing fingerprints remain byte-identical.

- [ ] **Step 6: Implement live audit with three exit classes**

`TopologyAuditReport.exit_code` is `0` for current and all usable providers complete, `1` for usable but degraded/incomplete/stale, and `2` for unavailable/malformed/ambiguous/unsafe. Historical stale artifacts remain loadable only when structural/hash validation passes.

- [ ] **Step 7: Run registry, audit, fingerprint, and workspace model tests**

Run: `pytest -q tests/unit/test_topology_registry.py tests/unit/test_topology_audit.py tests/unit/test_re_fingerprint.py tests/unit/test_re_lifecycle.py tests/unit/test_workspace_model.py`

Expected: PASS.

- [ ] **Step 8: Commit the registry and audit**

```bash
git add src/echelon/topology_registry.py src/echelon/topology_audit.py src/harness/re_fingerprint.py src/harness/re_lifecycle.py tests/unit/test_topology_registry.py tests/unit/test_topology_audit.py tests/unit/test_re_fingerprint.py tests/unit/test_re_lifecycle.py
git commit -m "feat(topology): define canonical registry and audit"
```

### Task 5: Extract A Shared Rollback Transaction And Publish Topology Atomically

**Files:**
- Create: `src/harness/publication_transaction.py`
- Create: `src/harness/topology_publication.py`
- Create: `tests/unit/test_publication_transaction.py`
- Create: `tests/unit/test_topology_publication.py`
- Modify: `src/harness/re_publication.py`
- Modify: `tests/unit/test_re_publication.py`
- Modify: `src/harness/re_lock.py`
- Modify: `tests/unit/test_re_lock.py`

**Interfaces:**
- Produces `PublicationOperation(final: PurePosixPath, staged: PurePosixPath | None)` and `PublicationTransaction`.
- Produces `apply_publication_transaction(transaction, *, fault_hook=None)` and `rollback_publication_transaction(transaction)`.
- Produces `TopologySnapshotCandidate` and `publish_topology_snapshots(workspace_root, candidates, *, owner_id, owner_run_dir, expected_generation=None)`.
- Preserves the existing `re/.locks/publish.lock`, `re/.staging/<owner>/rollback-journal.json`, replacement, and recovery semantics.

- [ ] **Step 1: Pin existing RE transaction behavior with characterization tests**

Add focused assertions for operation ordering, staged replacement, deletion, expected generation conflict, failure after backup, failure after replacement, exact rollback bytes, unsafe journal path rejection, and stale lock recovery.

- [ ] **Step 2: Extract the path-safe transaction primitive without behavior changes**

Move `_Transaction`, operation parsing, journal writing, apply, rollback, atomic JSON write, and safe relative-path validation from `re_publication.py`. Keep RE-specific candidate staging and post-write index validation in `re_publication.py`.

- [ ] **Step 3: Run all RE publication/lock tests after extraction**

Run: `pytest -q tests/unit/test_re_publication.py tests/unit/test_re_lock.py tests/unit/test_publication_transaction.py`

Expected: PASS before topology mutation is added.

- [ ] **Step 4: Write failing selected-source topology publication tests**

Publish two sources, update one source, and assert the untouched source directory/receipt hash is preserved while generation increments once. Cover provider-independent publication, unsupported PerlGraph, no usable providers, hash mismatch, duplicate locator, expected-generation conflict, and rollback preserving the previous index/source bytes.

- [ ] **Step 5: Implement staged topology publication**

Validate candidates fully before replacement. Stage `sources/<id>/receipt.json` plus available provider analysis/summary files, calculate hashes from staged bytes, merge untouched source rows from the current valid index, and replace selected source directories plus `topology/index.json` in one journal.

- [ ] **Step 6: Serialize topology with the existing publication lock**

Use `RePublishLock` so semantic RE and topology-only delivery reconciliation cannot race. A blocked promotion is a recoverable topology failure; an RE publication remains strict. Generalize lock wording from “RE publication” to “workspace artifact publication” without changing lock location.

- [ ] **Step 7: Run publication and rollback tests**

Run: `pytest -q tests/unit/test_publication_transaction.py tests/unit/test_topology_publication.py tests/unit/test_re_publication.py tests/unit/test_re_lock.py`

Expected: PASS.

- [ ] **Step 8: Commit atomic topology publication**

```bash
git add src/harness/publication_transaction.py src/harness/topology_publication.py src/harness/re_publication.py src/harness/re_lock.py tests/unit/test_publication_transaction.py tests/unit/test_topology_publication.py tests/unit/test_re_publication.py tests/unit/test_re_lock.py
git commit -m "feat(topology): publish snapshots atomically"
```

### Task 6: Make RE Produce And Publish Canonical Topology

**Files:**
- Create: `src/harness/topology_evidence.py`
- Create: `tests/unit/test_topology_evidence.py`
- Modify: `extension/scripts/bash/re/run-analysis.sh`
- Modify: `src/harness/re_publication.py`
- Modify: `src/harness/re_registry.py`
- Modify: `src/harness/re_artifacts.py`
- Modify: `tests/unit/test_re_publication.py`
- Modify: `tests/unit/test_re_registry.py`
- Modify: `tests/unit/test_re_artifacts.py`
- Modify: `tests/kernel/test_codegraph_integration_contract.py`
- Modify: `tests/kernel/test_perlgraph_integration_contract.py`

**Interfaces:**
- Produces `build_topology_snapshot_candidate(source_id, source_path, fingerprint, provider_artifacts, provenance) -> TopologySnapshotCandidate`.
- RE run-local provider files remain at `runs/<re-run>/re/sources/<id>/*graph*.json`.
- Current RE publication moves refreshed provider artifacts to `re/topology/sources/<id>/`, not `re/sources/<id>/`.
- Semantic source manifests no longer register current CodeGraph/PerlGraph analysis or summary as semantic RE children.

- [ ] **Step 1: Write failing RE publication tests for separated authorities**

Publish a refreshed source containing both providers. Assert semantic files remain under `re/sources/api/`, provider files exist only under `re/topology/sources/api/`, both index generations validate, and the topology/semantic fingerprints match at publication time without sharing an identity or generation field.

- [ ] **Step 2: Add receipt construction and capability tests**

Build receipts from healthy CodeGraph, unsupported PerlGraph, degraded PerlGraph, provider error files, and malformed outputs. Require source ID/path, full `SourceFingerprint`, analyzed commit, provider schema/tool versions, completeness, artifact hashes, counts, diagnostics, and provenance such as `{kind: "re", run_id: "re-20260804-120000"}`.

- [ ] **Step 3: Implement one receipt builder for RE and delivery**

The builder consumes explicit provider paths and never searches outside its run directory. It validates native artifacts through `echelon.topology_provider`, turns missing/error artifacts into unavailable receipts, and requires at least one usable provider for a publishable candidate.

- [ ] **Step 4: Wire RE extraction outputs into the shared contract**

Keep `run-analysis.sh` responsible for invoking the installed Node providers, but remove shell-specific schema assumptions from summary aggregation. Use provider-emitted summaries and schema-2 status/count fields. Both standalone and polyrepo source directories must have the same file contract.

- [ ] **Step 5: Add topology operations to the same RE publication transaction**

For refreshed/empty sources, stage topology candidates before the journal is prepared. Reused topology rows remain untouched. Removed workspace sources remove both semantic and topology source directories. The semantic and topology indexes replace in the same rollback transaction.

- [ ] **Step 6: Migrate legacy graph files during the next RE publication**

When reusing an older semantic source directory, exclude legacy `codegraph-*` and `perlgraph-*` files from the new semantic copy. Move misplaced schema-2 artifacts when they validate and match the published source fingerprint. Upgrade schema-1 artifacts only when every canonical locator is unique and every display-name relationship resolves to exactly one endpoint; otherwise leave topology stale/unavailable and require `echelon re refresh --source <id>`. Never guess through the duplicate-qualified-name case. Legacy registry reads remain possible until that source is republished.

- [ ] **Step 7: Run RE, provider, and registry regressions**

Run: `pytest -q tests/unit/test_topology_evidence.py tests/unit/test_re_publication.py tests/unit/test_re_registry.py tests/unit/test_re_artifacts.py tests/kernel/test_codegraph_integration_contract.py tests/kernel/test_perlgraph_integration_contract.py`

Expected: PASS.

- [ ] **Step 8: Commit RE topology production**

```bash
git add src/harness/topology_evidence.py extension/scripts/bash/re/run-analysis.sh src/harness/re_publication.py src/harness/re_registry.py src/harness/re_artifacts.py tests/unit/test_topology_evidence.py tests/unit/test_re_publication.py tests/unit/test_re_registry.py tests/unit/test_re_artifacts.py tests/kernel/test_codegraph_integration_contract.py tests/kernel/test_perlgraph_integration_contract.py
git commit -m "feat(re): publish canonical source topology"
```

### Task 7: Unify Source Identity In Spec And Workspace Artifact Graphs

**Files:**
- Modify: `src/echelon/spec_graph.py`
- Modify: `src/echelon/workspace_graph.py`
- Modify: `src/echelon/workspace_graph_audit.py`
- Modify: `src/echelon/graph_traversal.py`
- Modify: `tests/unit/test_spec_graph.py`
- Modify: `tests/unit/test_workspace_graph.py`
- Modify: `tests/unit/test_workspace_graph_audit.py`
- Modify: `tests/unit/test_graph_traversal.py`

**Interfaces:**
- Removes all `re-source:<id>` nodes and `USES_RE_SOURCE` edges.
- Uses `spec:<spec> USES_SOURCE source:<id>`.
- Uses `source:<id> DESCRIBED_BY artifact:<spec-id>:<workspace-path>` and `source:<id> HAS_DECISION decision:<source-id>:<source-relative-path>`.
- Adds only lightweight `HAS_TOPOLOGY_RECEIPT` artifact links; no file/symbol nodes are copied into artifact graphs.

- [ ] **Step 1: Write failing one-identity graph tests**

Build a spec graph linked to published semantic RE/topology and then compose the workspace graph. Assert exactly one `source:api` node, zero `re-source:` IDs, canonical edge names, and no `TopologySymbol`/`TopologyFile` nodes.

- [ ] **Step 2: Add source ownership conflict tests**

A member spec graph may contribute `source:api` only when `source_id` and normalized `path` match workspace configuration. Mismatched path/type/source ID must fail composition and audit with stable conflict findings. Identical canonical properties merge.

- [ ] **Step 3: Run focused graph tests and confirm current reserved-ID behavior fails**

Run: `pytest -q tests/unit/test_spec_graph.py tests/unit/test_workspace_graph.py tests/unit/test_workspace_graph_audit.py`

- [ ] **Step 4: Replace RE-specific source nodes and relationships**

Create `SourceRoot` nodes directly from canonical workspace configuration. Attach publication status, semantic fingerprint, topology fingerprint, and receipt paths as properties only after validating source identity. Map all non-decision semantic RE artifacts through `DESCRIBED_BY`.

- [ ] **Step 5: Teach workspace composition to merge canonical source members**

Replace the blanket `source:` reservation rejection with exact canonical-source validation. Workspace-owned properties win only for derived workspace metadata; conflicting member-owned identity properties are errors, not silently overwritten.

- [ ] **Step 6: Update graph traversal aliases and impact relations**

Keep `source` resolving to `SourceRoot`; add `Spec USES_SOURCE SourceRoot`, source-to-receipt/artifact, and source-to-decision relations without traversing full provider topology.

- [ ] **Step 7: Run all graph regressions**

Run: `pytest -q tests/unit/test_spec_graph.py tests/unit/test_workspace_graph.py tests/unit/test_workspace_graph_audit.py tests/unit/test_spec_graph_audit.py tests/unit/test_graph_read.py tests/unit/test_graph_traversal.py tests/unit/test_cli_graph_consumption.py`

Expected: PASS.

- [ ] **Step 8: Commit source identity unification**

```bash
git add src/echelon/spec_graph.py src/echelon/workspace_graph.py src/echelon/workspace_graph_audit.py src/echelon/graph_traversal.py tests/unit/test_spec_graph.py tests/unit/test_workspace_graph.py tests/unit/test_workspace_graph_audit.py tests/unit/test_graph_traversal.py
git commit -m "refactor(graph): unify canonical source identity"
```

### Task 8: Expose Audit-Aware Topology CLI Commands

**Files:**
- Create: `src/echelon/topology_cli.py`
- Create: `tests/unit/test_cli_topology.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `tests/unit/test_cli_typer_app.py`

**Interfaces:**
- Adds `echelon topology audit [--source <id>] [--json]`.
- Adds `echelon topology list-sources [--json]`.
- Adds `echelon topology search <query> [--source <id>] [--type <type>] [--limit <n>] [--json]`.
- Adds `echelon topology explain <node> [--source <id>] [--json]`.
- Adds `echelon topology neighbors <node> [--source <id>] [--direction in|out|both] [--relation <type>] [--limit <n>] [--json]`.
- Adds `echelon topology impact <node> [--source <id>] [--max-depth <n>] [--relation <type>] [--json]`.

- [ ] **Step 1: Write failing Typer discovery/help tests**

Assert `topology` is a visible top-level group, every command is listed, JSON flags are boolean, repeatable type/relation filters parse, invalid bounds return usage exit 2, and no legacy LLM dispatcher is called.

- [ ] **Step 2: Write failing deterministic output/exit tests**

Cover all-source search ordering, source-scoped search, exact explain, ambiguous selector candidates, neighbors directions, impact paths, truncation, current/degraded/stale/unavailable audits, and byte-identical repeated JSON output after removing generated timestamps.

- [ ] **Step 3: Implement text/JSON renderers outside `cli_app.py`**

`topology_cli.py` owns command services and JSON-ready payloads. `cli_app.py` stays a thin Typer adapter. Every result row includes source ID, provider, exact node ID, source-relative path, topology generation, current/stale status, and truncation where applicable.

- [ ] **Step 4: Preserve audit-aware exit behavior on every read**

Successful data rendering does not erase stale/degraded exit 1. Malformed/unavailable/unsafe/ambiguous reads print a bounded diagnostic and exit 2. Text goes to stdout for usable results and stderr for fatal errors.

- [ ] **Step 5: Run CLI and topology read tests**

Run: `pytest -q tests/unit/test_cli_topology.py tests/unit/test_cli_typer_app.py tests/unit/test_topology_provider.py tests/unit/test_topology_audit.py`

Expected: PASS.

- [ ] **Step 6: Commit the topology CLI**

```bash
git add src/echelon/topology_cli.py src/echelon/cli_app.py tests/unit/test_cli_topology.py tests/unit/test_cli_typer_app.py
git commit -m "feat(cli): add source topology commands"
```

### Task 9: Capture Delivery Receipts And Reconcile Only Landed Topology

**Files:**
- Create: `src/harness/verify_evidence_discovery.py`
- Create: `src/harness/topology_promotion.py`
- Create: `tests/unit/test_verify_evidence_discovery.py`
- Create: `tests/unit/test_topology_promotion.py`
- Modify: `src/harness/topology_evidence.py`
- Modify: `src/harness/codegraph_evidence.py`
- Modify: `src/harness/perlgraph_evidence.py`
- Modify: `src/harness/__main__.py`
- Modify: `extension/workflow/phases/verify-spec-2-codegraph.md`
- Modify: `src/echelon/mempalace_spec_evidence.py`
- Modify: `src/harness/land.py`
- Modify: `tests/unit/test_harness_main_codegraph_evidence.py`
- Modify: `tests/unit/test_harness_main_perlgraph_evidence.py`
- Modify: `tests/unit/test_land.py`

**Interfaces:**
- Produces run-local `topology-receipt.json` after both delivery providers run.
- Produces `discover_verify_evidence_runs(workspace_root, spec_id, *, required_files) -> tuple[Path, ...]` for both evidence publication and topology reconciliation.
- Produces `reconcile_landed_topology(workspace_root, spec_id, target_root, default_head, *, evidence_run=None) -> TopologyPromotionResult`.
- Preserves `land(spec_id: str, *, project_dir: Path, gitops: Any, state_dir: Path | None = None, options: LandOptions | None = None) -> bool` returning `True` after a successful merge even when topology reconciliation fails.

- [ ] **Step 1: Write failing delivery receipt tests**

Set `ECHELON_WORKSPACE_ROOT`, `ECHELON_SOURCE_ID`, and `ECHELON_SOURCE_ROOT`; run both existing evidence commands; assert the final receipt records target source ID, analyzed feature commit, full source fingerprint, provider versions/status/counts/completeness, exact artifact hashes, verify scope, spec ID, and run directory provenance.

- [ ] **Step 2: Extract strict shared verify-run discovery**

Move the safe standalone/nested run selection logic from `mempalace_spec_evidence.py` into `harness.verify_evidence_discovery`. Require state/spec identity match and containment below workspace `runs/`; sort by recorded completion time then path, not arbitrary filesystem traversal.

- [ ] **Step 3: Finalize the receipt deterministically after both providers**

Add `python -m harness write-topology-evidence-receipt "{project_root}" "{verify_run_dir}" "{spec_dir}"` after the PerlGraph command in `verify-spec-2-codegraph.md`. The command always writes a receipt, including unavailable/unsupported provider rows, and updates verify state with `topology_evidence: ready|degraded|unavailable`.

- [ ] **Step 4: Write failing landed-only reconciliation tests**

Cover unlanded spec rejection, unknown/ambiguous source mapping, stale verify scope, exact fast-forward commit promotion, no-FF merge commit mismatch, fingerprint mismatch, malformed provider, unsupported PerlGraph with healthy CodeGraph, and generation conflict. Assert no canonical mutation on every rejected case.

- [ ] **Step 5: Implement exact fast-path promotion and merge-commit recapture**

When `receipt.analyzed_commit == default_head` and recomputed fingerprint equals the receipt, publish validated run-local provider bytes directly. When a no-FF/squash merge changes commit identity, do not restamp those bytes. Invoke the same bounded deterministic provider capture against checked-out default `HEAD`, build a new receipt with provenance `{kind: "land-reconciliation", evidence_run: "verify-spec-909-20260804-120000"}`, then publish that exact snapshot.

- [ ] **Step 6: Make post-land failure non-fatal and recoverable**

Call reconciliation only after merge/push/default checkout and landed status mutation. Cover ordinary branch, already-merged, PR, and branchless-idempotent landing paths through one helper. Catch topology lock/provider/validation/publication failures, log `topology: stale|unavailable`, preserve the successful land result, and print the concrete affected source in `next: echelon re refresh --source <source-id>`.

- [ ] **Step 7: Run delivery, evidence, land, and publication tests**

Run: `pytest -q tests/unit/test_verify_evidence_discovery.py tests/unit/test_topology_promotion.py tests/unit/test_harness_main_codegraph_evidence.py tests/unit/test_harness_main_perlgraph_evidence.py tests/unit/test_land.py tests/unit/test_land_cli.py tests/unit/test_mempalace_spec_evidence.py tests/unit/test_topology_publication.py`

Expected: PASS.

- [ ] **Step 8: Commit landed topology reconciliation**

```bash
git add src/harness/verify_evidence_discovery.py src/harness/topology_promotion.py src/harness/topology_evidence.py src/harness/codegraph_evidence.py src/harness/perlgraph_evidence.py src/harness/__main__.py extension/workflow/phases/verify-spec-2-codegraph.md src/echelon/mempalace_spec_evidence.py src/harness/land.py tests/unit/test_verify_evidence_discovery.py tests/unit/test_topology_promotion.py tests/unit/test_harness_main_codegraph_evidence.py tests/unit/test_harness_main_perlgraph_evidence.py tests/unit/test_land.py
git commit -m "feat(delivery): reconcile topology after landing"
```

### Task 10: Add Explicit One-Source Semantic RE Reconciliation

**Files:**
- Modify: `src/harness/re_planner.py`
- Modify: `src/harness/re_lifecycle.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `tests/unit/test_re_planner.py`
- Modify: `tests/unit/test_re_lifecycle.py`
- Modify: `tests/unit/test_cli_re_lifecycle.py`
- Modify: `tests/unit/test_cli_typer_app.py`
- Modify: `src/harness/land.py`
- Modify: `tests/unit/test_land.py`

**Interfaces:**
- Adds `echelon re refresh --source <source-id>`.
- Adds `target_source: str = ""` and `force_selected_refresh: bool = False` keyword parameters to `ReLifecycleController.run`.
- Adds `force_selected_refresh: bool = False` to `build_re_execution_plan` without changing ordinary `echelon re run --re-policy changed` behavior.
- Produces independent post-land `topology` and `semantic RE` status lines.

- [ ] **Step 1: Write the regression for the current blanket-refresh bug**

Create three current published sources and request one-source refresh. Assert only the selected source has `action == "refresh"`; siblings are `reuse`, not `refresh`; dependent workspace synthesis/publication remains true; forbidden source roots prevent analysis from reading excluded siblings.

- [ ] **Step 2: Remove lifecycle-wide replacement of reusable sources**

Delete the block that rewrites every `reuse` action to `refresh` when any publication exists. Move explicit force semantics into the planner: `refresh-all` refreshes all selected sources; `force_selected_refresh=True` refreshes only selected non-empty available sources; ordinary `changed` refreshes only stale sources.

- [ ] **Step 3: Add the thin Typer and legacy execution adapters**

`echelon re refresh --source api` invokes the same controller/publication path as RE run with `target_source="api"`, policy `target-only`, and `force_selected_refresh=True`. Reject missing, ambiguous, unsafe, or undeclared source selectors before creating a run. A declared empty source is valid: use `skip-empty`, synthesize workspace context, and publish capability-aware empty/unsupported topology without dispatching semantic extraction.

- [ ] **Step 4: Test publication and no-work semantics**

A selected source refresh publishes semantic RE plus topology and resynthesizes workspace artifacts. Sibling semantic/topology receipts remain byte-identical. If the selected source disappears, fail without mutating either index.

- [ ] **Step 5: Report independent landed freshness**

After topology reconciliation, calculate semantic status with `published_source_is_current` and topology status with `audit_topology(project_root, source_id=source_id)`. Print both statuses even when one is current and the other stale.

- [ ] **Step 6: Run RE CLI/lifecycle/planner and land tests**

Run: `pytest -q tests/unit/test_re_planner.py tests/unit/test_re_lifecycle.py tests/unit/test_cli_re_lifecycle.py tests/unit/test_cli_typer_app.py tests/unit/test_re_publication.py tests/unit/test_land.py`

Expected: PASS.

- [ ] **Step 7: Commit targeted RE reconciliation**

```bash
git add src/harness/re_planner.py src/harness/re_lifecycle.py src/echelon/cli.py src/echelon/cli_app.py src/harness/land.py tests/unit/test_re_planner.py tests/unit/test_re_lifecycle.py tests/unit/test_cli_re_lifecycle.py tests/unit/test_cli_typer_app.py tests/unit/test_land.py
git commit -m "feat(re): refresh one source explicitly"
```

### Task 11: Prove Scale, Backfill OptaSearch, And Document The Contract

**Files:**
- Create: `tests/performance/test_topology_scale.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-08-04-source-topology-foundation-design.md`

**Interfaces:**
- Exercises at least 31,000 symbols and 65,000 relationships without a committed large fixture.
- Documents canonical storage, freshness independence, CLI commands, landing behavior, and recovery.
- Uses `/Users/michalbachorik/work/optasearch` as a manual real-workspace acceptance sample only; automated tests do not hardcode local paths.

- [ ] **Step 1: Add a generated scale/performance test**

Generate schema-2 artifacts in `tmp_path` with 31,000 symbols, 65,000 exact relationships, and duplicated qualified names across distinct files. Publish, audit, search, explain, neighbors, and depth-3 impact. Assert complete counts, deterministic bounded output, no selector collision for exact IDs, and no full-graph copy into artifact graphs.

- [ ] **Step 2: Run provider and Python scale checks**

Run: `pytest -q tests/performance/test_topology_scale.py`

Run: `pytest -q tests/kernel/test_codegraph_integration_contract.py -k ten_thousand`

Expected: PASS without truncation or excessive result payloads.

- [ ] **Step 3: Run the full focused regression suite**

Run: `pytest -q tests/unit/test_topology_model.py tests/unit/test_topology_provider.py tests/unit/test_topology_registry.py tests/unit/test_topology_audit.py tests/unit/test_topology_publication.py tests/unit/test_topology_evidence.py tests/unit/test_topology_promotion.py tests/unit/test_cli_topology.py tests/unit/test_spec_graph.py tests/unit/test_workspace_graph.py tests/unit/test_re_publication.py tests/unit/test_re_lifecycle.py tests/unit/test_land.py`

Run: `npm run typecheck --prefix extension/scripts/node/perlgraph && npm test --prefix extension/scripts/node/perlgraph`

Run: `bash scripts/bash/dry-run.sh`

- [ ] **Step 4: Reinstall Echelon from this checkout**

Run: `bash scripts/install.sh`

- [ ] **Step 5: Backfill representative OptaSearch sources through normal RE publication**

Run from `/Users/michalbachorik/work/optasearch`:

```bash
echelon re refresh --source optapulse-platform
echelon re refresh --source pressbox-search-soccer-api
echelon re refresh --source optasearch-pro
```

This covers the largest historical CodeGraph artifacts, duplicate qualified names, and an unsupported/empty provider source without introducing a separate migration command.

- [ ] **Step 6: Exercise the public CLI against OptaSearch**

Run:

```bash
echelon topology audit --json
echelon topology list-sources --json
echelon topology search resolve --source optapulse-platform --limit 20 --json
echelon topology search controller --source pressbox-search-soccer-api --limit 20 --json
echelon topology audit --source optasearch-pro --json
```

Confirm audit exit 0/1 matches provider capability, exact IDs disambiguate duplicated qualified names, and no `re-source:` identity appears in refreshed spec/workspace graphs.

- [ ] **Step 7: Demonstrate stale/current independence**

Make a temporary uncommitted source edit in one OptaSearch source, run topology audit and confirm stale exit 1 while historical queries remain labeled stale, then revert only that temporary acceptance-test edit. Verify semantic RE status is reported independently.

- [ ] **Step 8: Update user-facing documentation and close the design**

Document `re/topology/`, provider statuses, audit exit codes, each `echelon topology` subcommand, `echelon re refresh --source`, run-local delivery evidence, exact-commit promotion, no-FF recapture, and non-fatal recovery. Change the approved design status to `Implemented` only after all verification passes.

- [ ] **Step 9: Run the broad Python suite**

Run: `pytest -q`

Expected: PASS. If environment-only Docker/browser tests are unavailable, record the exact skipped command and still run every topology/RE/land suite above.

- [ ] **Step 10: Commit scale coverage and documentation**

```bash
git add tests/performance/test_topology_scale.py README.md CHANGELOG.md docs/superpowers/specs/2026-08-04-source-topology-foundation-design.md
git commit -m "docs(topology): document source topology workflow"
```

## Final Verification

- [ ] Run `git status --short` and confirm only intentional files remain.
- [ ] Run `rg -n "re-source:|USES_RE_SOURCE|DEFAULT_MAX_SYMBOLS|max-symbols|truncateSymbols" src extension tests` and confirm no live contract retains removed identities or caps; historical design/plan mentions are allowed.
- [ ] Run `pytest -q`.
- [ ] Run `npm run typecheck --prefix extension/scripts/node/perlgraph`.
- [ ] Run `npm test --prefix extension/scripts/node/perlgraph`.
- [ ] Run `bash scripts/bash/dry-run.sh`.
- [ ] Run the OptaSearch CLI acceptance commands from Task 11 and save the important counts/statuses in the implementation close-out.
- [ ] Request a code review using `superpowers:requesting-code-review` before merge/push.
