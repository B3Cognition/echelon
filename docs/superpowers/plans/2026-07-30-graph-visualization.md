# Graph Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic DOT export and an offline interactive viewer for persisted Echelon artifact graphs.

**Architecture:** A focused `echelon.graph_visualization` module loads and validates persisted graph JSON, applies endpoint-safe lenses, renders DOT, and produces HTML from a packaged Cytoscape.js bundle. Top-level CLI commands resolve the spec root, run the existing read-only graph audit, render output, and never build or mine data.

**Tech Stack:** Python 3.11+, Typer, Cytoscape.js 3.34.0, browser HTML/CSS/JavaScript, pytest.

## Global Constraints

- Preserve `spec-artifact-graph.json` as the only graph authority.
- Do not build, refresh, or mine from `view` or `export`.
- Use the existing graph audit and exit-code semantics.
- Produce deterministic output from identical graph and audit inputs.
- Keep Cytoscape.js offline and include its MIT license.
- Preserve unrelated in-progress workspace changes.

---

### Task 1: Deterministic Graph Rendering

**Files:**
- Create: `src/echelon/graph_visualization.py`
- Create: `tests/unit/test_graph_visualization.py`

**Interfaces:**
- Consumes: persisted graph JSON and `SpecGraphAuditReport`.
- Produces: `load_graph_document`, `filter_graph`, `render_graph_dot`, and `render_graph_html`.

- [x] Write tests for malformed graph rejection, endpoint-safe lens filtering,
      deterministic DOT ordering/escaping, and safe HTML embedding.
- [x] Run `python -m pytest -q tests/unit/test_graph_visualization.py` and
      verify the tests fail because the module is absent.
- [x] Implement the minimal loader, lens selector, DOT renderer, and HTML data
      adapter.
- [x] Re-run the test file and verify it passes.

### Task 2: Offline Cytoscape Viewer

**Files:**
- Create: `src/echelon/assets/cytoscape-3.34.0.min.js`
- Create: `src/echelon/assets/licenses/CYTOSCAPE.md`
- Modify: `pyproject.toml`
- Modify: `src/echelon/graph_visualization.py`
- Test: `tests/unit/test_graph_visualization.py`

**Interfaces:**
- Consumes: packaged Cytoscape bundle and graph/audit JSON.
- Produces: a single offline HTML file with search, lenses, neighbourhood
  selection, audit findings, details, and viewport controls.

- [x] Add failing tests that require embedded Cytoscape source, no remote
      script URLs, all lens controls, audit status, and escaped JSON.
- [x] Vendor Cytoscape.js 3.34.0 and record its MIT license.
- [x] Add Echelon package-data entries and implement the interactive page.
- [x] Run renderer tests and build a wheel to verify assets are packaged.

### Task 3: CLI Commands And Real-Workspace Verification

**Files:**
- Modify: `src/echelon/cli_app.py`
- Modify: `tests/unit/test_cli_graph.py`
- Modify: `docs/superpowers/specs/2026-07-28-spec-artifact-graph-design.md`

**Interfaces:**
- Produces:
  - `echelon graph view <spec> [--lens] [--output] [--no-open]`
  - `echelon graph export <spec> [--format dot] [--lens] [--output]`

- [x] Add failing CLI tests for stdout/file DOT export, HTML output and browser
      opening, audit exit codes, invalid lens/format handling, and no mining.
- [x] Implement both commands using the rendering module and existing audit.
- [x] Run graph, CLI, and integration tests.
- [x] Exercise both commands on `md_distribution` and `optasearch`, validate
      generated HTML, and render one DOT export to SVG with Graphviz.
- [x] Commit only graph visualization files and graph-specific CLI hunks.

### Task 4: Operator Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents: publication, MemPalace reconciliation, graph build/audit, and
  visualization/export commands.

- [x] Verify every documented command and option against current CLI help.
- [x] Document independent RE, spec, and evidence publication timing.
- [x] Document the normal memory-refresh and graph-refresh sequence.
- [x] Explain hash-based stale-state detection and read-only viewer behavior.
- [x] Add the memory and graph commands to the README command reference.
