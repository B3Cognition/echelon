# Task 1 Report: Version And Audit The Requirement Projection

## Outcome

Implemented the requirement projection versioning slice without changing graph schema version `1` or the canonical requirement authority. Requirement nodes now carry canonical `source_text`, `source_path`, and one-based `source_line`, and persisted graph payloads now declare `node_projection_version = 2`.

## Files Changed

- `src/echelon/spec_graph.py`
- `src/echelon/spec_graph_audit.py`
- `tests/unit/test_spec_graph.py`
- `tests/unit/test_spec_graph_audit.py`
- `tests/unit/test_workspace_graph.py`

## TDD Evidence

1. Added failing assertions for `node_projection_version`, requirement source metadata, workspace composition preservation, and projection-staleness audit behavior.
2. Ran the focused suite and observed the expected red state: missing `node_projection_version` and requirement source fields caused 3 failures.
3. Implemented the minimal projection and audit changes.
4. Re-ran the focused suite to green.

## Implementation Notes

- Added `NODE_PROJECTION_VERSION = 2` and emitted it from `SpecArtifactGraph.to_dict()`.
- Preserved `GRAPH_SCHEMA_VERSION = 1`.
- Projected canonical requirement metadata from `extract_canonical_requirements(...)` onto each `Requirement` node:
  - `source_text`
  - `source_path`
  - `source_line`
- Added rebuildable audit detection for stale requirement projections through `graph_projection_stale`.
- Treated missing `node_projection_version` as implicit projection version `1`.
- Emitted a single graph-level stale finding when the stored projection version or requirement source metadata is outdated.

## Verification

- Focused tests:
  - `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_spec_graph.py tests/unit/test_spec_graph_audit.py tests/unit/test_workspace_graph.py -q`
  - Result: `75 passed`

## Self-Review

Reviewed the final diff against the task brief:

- Scope stayed within Task 1 files plus the required report.
- Graph schema version remained `1`.
- Audit freshness is rebuildable/stale, not structural invalidation.
- No later graph-read or traversal behavior was introduced.

## Concerns

- The worktree did not contain its own `.venv`, so verification used the repository-managed environment at `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python`. This matched the project’s Python 3.11 environment and did not affect test coverage.
