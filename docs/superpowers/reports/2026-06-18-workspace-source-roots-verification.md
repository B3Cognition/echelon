# Workspace Source Roots Verification

## Scope

Implemented deterministic workspace/source-root model across discovery, RE analysis, harness target detection, harness state, and user documentation.

## Verified Commands

- `python -m pytest tests/unit/test_workspace_model.py tests/unit/test_workspace_git_preflight.py tests/unit/test_target_detection.py tests/unit/test_cli_harness_run.py tests/unit/test_harness_single_repo_unchanged.py tests/unit/test_harness_target_state.py tests/unit/test_ralph_outer.py tests/unit/test_polyrepo_target_docs.py tests/kernel/test_codegraph_integration_contract.py tests/integration/test_squad_controller.py tests/integration/test_workspace_source_roots_e2e.py -q`
  - Result: `217 passed in 14.45s`
- `bash tests/integration/re/test-discover-repos.sh`
  - Result: `26 passed, 0 failed`
- `bash tests/integration/re/test-run-analysis-polyrepo.sh`
  - Result: `45 passed, 0 failed`

## Behavior Guarantees

- Single repo remains `sources: [.]`.
- Polyrepo workspace uses child source roots and does not classify the workspace root as implementation code.
- Branchless polyrepo workspaces are blocked before new squad or harness runs.
- RE prefers `workspace-manifest.json` and keeps `repos-manifest.json` compatibility.
- Harness prompt context includes explicit workspace and source root paths.
