# Phase: build-8-verify-docs
# Source: Documentation Convergence Gate
# Read by: echelon.commander (COMMANDER) after TECH WRITER and before build finalization

## Documentation Verification

After echelon.tech-writer (TECH WRITER) writes README.md, CHANGELOG.md, and `{spec_dir}/documentation-impact-report.md`, dispatch echelon.docs-verifier (DOCS VERIFIER).

Use the Ralph-owned context pack:

- Read `build_slice_context_index_file` and use
  `agent_context_files.DOCS_VERIFIER` as the prepared DOCS VERIFIER context pack.
- Use explicit TECH WRITER outputs already provided by Ralph as verification
  inputs.
- Do not compile a separate context pack by searching spec files, README,
  CHANGELOG, package metadata, smoke evidence, or changed files.

Use the Agent tool:

- **subagent_type:** `echelon.docs-verifier`
- **prompt:**

  ```xml
  <context>
  [include agent_context_files.DOCS_VERIFIER from build_slice_context_index_file]
  </context>

  <instructions>
  You are DOCS VERIFIER. Read subagents/echelon.docs-verifier.md for your complete protocol.
  Independently inspect every delivery_change_id and cited implementation evidence. Verify whether README.md works as a first-run local manual, CHANGELOG.md records only actual completed changes, and documentation-impact-report.md honestly and completely maps the delivery inventory to the docs. When user runnability is required, compare README sandbox and local commands with the current passing immutable report, require truthful disclosure of an `unverified` local journey, and cite its evidence_sha256. Write a version-2 {spec_dir}/docs-verification-report.md with reviewed_change_ids, uncovered_change_ids, unsupported_claims, runnability_evidence_sha256, runnability_commands_current, and structured repair findings. Return verdict PASS only when docs are adequate and the runnability evidence is current. Return verdict FAIL when TECH WRITER must repair docs. Return verdict BLOCKED only when required inputs are missing or unreadable.
  </instructions>
  ```

- **description:** "echelon.docs-verifier (DOCS VERIFIER): first-run README and documentation quality verification"

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
10. Never return PASS for required runnability when the report is missing,
    failed, stale, or provisional.
11. Never return PASS when README omits a declared local journey instruction or
    claims an `unverified` local journey passed.

Routing:

- `PASS` routes to `build-8-finalize`.
- `FAIL` routes to `build-8-documentation` with `docs-verification-report.md` as mandatory repair context.
- `BLOCKED` routes to `build-8-documentation` so TECH WRITER can repair missing docs when possible.

This phase is the documentation convergence loop. The deterministic Ralph documentation gate remains the final enforcement point, but this phase gives TECH WRITER structured repair findings before finalization.
