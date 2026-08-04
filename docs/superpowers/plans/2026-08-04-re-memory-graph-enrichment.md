# RE Memory and Graph Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mine rich published RE artifacts into MemPalace and expose stable, typed RE source and decision topology in spec and workspace graphs.

**Architecture:** Extend the curated RE snapshot loader with artifact-specific metadata, then enrich linked RE artifacts during spec graph construction. Workspace graph composition remains generic and deduplicates the new stable node identities through its existing merge path.

**Tech Stack:** Python 3.11, pytest, Echelon artifact graph JSON, MemPalace artifact miner.

## Global Constraints

- Parse stable structured inputs into semantic nodes; represent prose as typed artifacts.
- Preserve published paths and hashes as canonical artifact identity.
- Do not infer components or contracts from arbitrary Markdown headings.
- Graph construction remains useful when MemPalace is unavailable.
- Malformed optional ADR or CodeGraph content does not fail graph construction.
- Existing graph fields and node behavior remain backward compatible.

---

### Task 1: Curate and Classify Rich RE Memory Artifacts

**Files:**
- Modify: `src/echelon/mempalace_re.py`
- Test: `tests/unit/test_mempalace_re.py`

**Interfaces:**
- Consumes: published paths below `re/sources` and `re/workspace`.
- Produces: `load_re_artifact_snapshots(project_root: Path) -> list[ReArtifactSnapshot]` with artifact-specific `artifact_kind` and `room` metadata.

- [ ] **Step 1: Extend the fixture and write failing snapshot-selection tests**

Add source `architecture.md`, `contracts.md`, `components.md`, `adrs/ADR-001-boundary.md`, `codegraph-summary.json`, and workspace `codegraph-summary.json` to `write_re_workspace`. Assert they appear in snapshot order, raw `codegraph-analysis.json` remains excluded, and metadata maps to:

```python
expected = {
    "re/sources/api/architecture.md": ("re-architecture", "re-source-architecture"),
    "re/sources/api/contracts.md": ("re-contracts", "re-source-contracts"),
    "re/sources/api/components.md": ("re-components", "re-source-components"),
    "re/sources/api/adrs/ADR-001-boundary.md": ("re-decision", "re-source-decisions"),
    "re/sources/api/codegraph-summary.json": ("re-codegraph-summary", "re-source-codegraph"),
    "re/workspace/codegraph-summary.json": ("re-codegraph-summary", "re-workspace-codegraph"),
}
```

- [ ] **Step 2: Run the focused test and verify RED**

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_mempalace_re.py::test_load_re_artifact_snapshots_selects_curated_re_outputs
```

Expected: FAIL because rich source artifacts and CodeGraph summaries are not curated and existing snapshots use the generic kind.

- [ ] **Step 3: Implement path classification**

Add the rich filenames to source/workspace selection and introduce this exact helper:

```python
def _re_artifact_classification(relative_to_re: Path) -> tuple[str, str]:
    """Return deterministic artifact kind and MemPalace room for a curated path."""
```

Use the exact kind/room mapping from Step 1. Keep all pre-existing paths on `reverse-engineering` and their current rooms.

- [ ] **Step 4: Write and verify cleanup behavior RED/GREEN**

Extend `test_mine_re_memory_deletes_existing_re_drawers_before_refresh` with metadata kinds `re-architecture`, `re-contracts`, `re-components`, `re-decision`, and `re-codegraph-summary`. First verify they are not deleted; then change `_cleanup_existing_re_drawers` to delete any drawer whose scope is `reverse-engineering` or whose kind is one of the supported RE kinds.

- [ ] **Step 5: Run MemPalace RE tests**

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_mempalace_re.py
```

Expected: PASS.

---

### Task 2: Add Stable RE Source and Decision Topology to Spec Graphs

**Files:**
- Modify: `src/echelon/spec_graph.py`
- Test: `tests/unit/test_spec_graph.py`

**Interfaces:**
- Consumes: hash-verified paths returned by `_linked_re_artifacts(root, spec_dir)`.
- Produces: `ReverseEngineeringSource` and `Decision` nodes, typed RE artifact properties, semantic edges, and existing `STORED_AS` edges.

- [ ] **Step 1: Write a failing graph-topology test**

Create a published source manifest plus attached architecture, contracts, components, ADR, and CodeGraph summary. Assert source and decision nodes, typed artifact properties, and these edges:

```text
spec:001-demo USES_RE_SOURCE re-source:api
re-source:api DESCRIBED_BY artifact:.../architecture.md
re-source:api DECLARES_CONTRACTS_IN artifact:.../contracts.md
re-source:api CATALOGS_COMPONENTS_IN artifact:.../components.md
re-source:api SUMMARIZED_BY artifact:.../codegraph-summary.json
re-source:api HAS_DECISION decision:api:adrs/ADR-001-boundary.md
decision:api:adrs/ADR-001-boundary.md DOCUMENTED_BY artifact:.../ADR-001-boundary.md
```

- [ ] **Step 2: Run the topology test and verify RED**

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_spec_graph.py::test_build_spec_graph_models_linked_re_source_topology
```

Expected: FAIL because only generic Artifact nodes exist.

- [ ] **Step 3: Implement deterministic RE descriptors and topology**

Add a frozen internal descriptor carrying source ID, source-relative path, artifact kind, and edge type. After `_add_policy_artifacts`, add `_add_re_topology`. Use IDs `re-source:<source-id>` and `decision:<source-id>:<source-relative-ADR-path>`. Read optional manifest metadata defensively and enrich existing Artifact nodes with `re_artifact_kind` and `re_source_id`.

- [ ] **Step 4: Add ADR and CodeGraph resilience tests**

Write tests for an ADR without a heading and a CodeGraph summary with an unfamiliar JSON schema. Implement ADR title fallback to filename stem and keep CodeGraph as a summary Artifact without entity expansion.

- [ ] **Step 5: Verify MemPalace drawer linkage for rich artifacts**

Extend the RE memory graph adapter test so an architecture snapshot plans one drawer. Assert an architecture Artifact `STORED_AS` edge and drawer `artifact_kind == "re-architecture"`.

- [ ] **Step 6: Run spec graph tests**

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_spec_graph.py
```

Expected: PASS.

---

### Task 3: Verify Workspace Composition and Refresh OptaSearch Consumers

**Files:**
- Test: `tests/unit/test_workspace_graph.py`
- Modify only if required: `src/echelon/workspace_graph.py`
- Runtime outputs: OptaSearch MemPalace and canonical graph files.

**Interfaces:**
- Consumes: member artifact graphs containing stable RE source and decision IDs.
- Produces: one merged workspace node per shared RE source/decision with `member_specs` provenance.

- [ ] **Step 1: Write a workspace deduplication test**

Build two member graphs attached to the same RE source and ADR. Assert one `re-source:api` node, one `decision:api:adrs/ADR-001-boundary.md` node, and `member_specs == ["001-alpha", "002-beta"]` after composition.

- [ ] **Step 2: Run RED/GREEN through existing generic composition**

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_workspace_graph.py::test_workspace_graph_deduplicates_re_source_topology
```

If generic merge fails, minimally extend `_merge_shared_node` for the two new node types. Do not change existing Artifact or drawer handling.

- [ ] **Step 3: Run focused integration verification**

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_mempalace_re.py tests/unit/test_spec_graph.py tests/unit/test_workspace_graph.py tests/unit/test_published_re_context.py
```

Expected: PASS.

- [ ] **Step 4: Run full repository verification**

```bash
tests/run-all.sh
```

Expected: `OVERALL: PASS` with zero failures.

- [ ] **Step 5: Refresh and audit OptaSearch RE memory**

From `/Users/michalbachorik/work/optasearch`:

```bash
echelon re memory refresh
echelon re memory audit
```

Expected: rich snapshots are mined and no expected drawer is missing or stale. Report MemPalace runtime unavailability without changing publication.

- [ ] **Step 6: Rebuild attached spec and workspace graphs**

Discover canonical specs containing `re-context.json`, run the repository graph-build command for each, then rebuild the workspace graph. Verify JSON contains `ReverseEngineeringSource`, `Decision`, typed Artifact properties, and rich-artifact `STORED_AS` edges.

- [ ] **Step 7: Review final diffs**

```bash
git diff --check
git status --short
```

Expected: Echelon source/test diffs have no whitespace errors; OptaSearch publication changes remain distinguishable from generated memory/graph output.
