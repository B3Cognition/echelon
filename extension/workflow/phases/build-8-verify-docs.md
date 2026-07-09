# Phase: build-8-verify-docs
# Source: Documentation Convergence Gate
# Read by: speckit-echelon-commander (COMMANDER) after TECH WRITER and before build finalization

## Documentation Verification

After speckit-echelon-tech-writer (TECH WRITER) writes README.md, CHANGELOG.md, and `{spec_dir}/documentation-impact-report.md`, dispatch speckit-echelon-docs-verifier (DOCS VERIFIER).

Context pack:

- `{spec_dir}/spec.md`
- `{spec_dir}/tasks.md`
- `{spec_dir}/documentation-impact-report.md`
- repo-root `README.md`
- repo-root `CHANGELOG.md`
- package/app metadata when present
- safe harness smoke evidence when present
- changed files from the build worktree

Use the Agent tool:

- **subagent_type:** `speckit-echelon-docs-verifier`
- **prompt:**

  ```xml
  <context>
  [include spec.md, tasks.md, documentation-impact-report.md, README.md, CHANGELOG.md, package/app metadata, safe harness smoke evidence when present, and changed-file summary]
  </context>

  <instructions>
  You are DOCS VERIFIER. Read agents/build/docs-verifier.md for your complete protocol.
  Verify whether README.md works as a first-run local manual, CHANGELOG.md records only actual completed changes, and documentation-impact-report.md honestly reflects the docs. Write {spec_dir}/docs-verification-report.md with structured repair findings. Return verdict PASS only when docs are adequate. Return verdict FAIL when TECH WRITER must repair docs. Return verdict BLOCKED only when required inputs are missing or unreadable.
  </instructions>
  ```

- **description:** "speckit-echelon-docs-verifier (DOCS VERIFIER): first-run README and documentation quality verification"

DOCS VERIFIER must:

1. Write `{spec_dir}/docs-verification-report.md`.
2. Run `python -m harness verify-docs <worktree-path> <spec-dir>` from the target repository root and use its `docs-verification-report.md` as the authoritative finding list.
3. Check README.md for first-run manual completeness using project understanding and safe harness smoke evidence when present.
4. Check CHANGELOG.md for Keep a Changelog-style completed-change entries, not roadmap or planned-work bullets.
5. Check `{spec_dir}/documentation-impact-report.md` against the actual README/CHANGELOG state.
6. Include YAML frontmatter in `docs-verification-report.md` with `verdict`, `readme_first_run_manual`, `changelog_valid`, `impact_report_valid`, `project_evidence_checked`, `evidence_items_checked`, and `blocking_findings`.
7. Return `echelon_result.verdict: PASS` when all documentation is adequate.
8. Return `echelon_result.verdict: FAIL` with structured repair findings when TECH WRITER must repair docs.
9. Return `echelon_result.verdict: BLOCKED` only when required inputs cannot be read.

Routing:

- `PASS` routes to `build-8-finalize`.
- `FAIL` routes to `build-8-documentation` with `docs-verification-report.md` as mandatory repair context.
- `BLOCKED` routes to `build-8-documentation` so TECH WRITER can repair missing docs when possible.

This phase is the documentation convergence loop. The deterministic Ralph documentation gate remains the final enforcement point, but this phase gives TECH WRITER structured repair findings before finalization.
