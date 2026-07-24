# Phase: build-8-documentation
# Source: Documentation Currency Gate
# Read by: speckit-echelon-commander (COMMANDER) after all phase groups complete and before build finalization

## Documentation Currency Gate

After all implementation phase groups complete and before `build-8-finalize`, dispatch speckit-echelon-tech-writer (TECH WRITER).

Use the Ralph-owned context pack:

- Read `build_slice_context_index_file` and use
  `agent_context_files.TECH_WRITER` as the prepared TECH WRITER context pack.
- Use explicit documentation verifier output already provided by Ralph when
  returning from documentation verification failure.
- Do not compile a separate context pack by searching spec reports, README,
  CHANGELOG, or changed files.

Use the Agent tool:

- **subagent_type:** `speckit-echelon-tech-writer`
- **prompt:**

  ```xml
  <context>
  [include agent_context_files.TECH_WRITER from build_slice_context_index_file]
  </context>

  <instructions>
  You are TECH WRITER. Read agents/build/tech-writer.md for your complete protocol.
  Decide whether documentation updates are required. Give every Ralph-supplied delivery_change_id a version-2 documented_changes disposition backed by repository evidence. If docs-verification-report.md contains structured repair findings, address every blocking finding before returning DONE. If required, update repo-root README.md and CHANGELOG.md. Treat README.md as a first-run manual for a first-time local user: include install, minimal configuration, first dry run, first real run, expected output, troubleshooting, and development commands when evidence supports them. Always write {spec_dir}/documentation-impact-report.md with machine-readable frontmatter. Return journal entries in echelon_result.journal_entries.
  </instructions>
  ```

- **description:** "speckit-echelon-tech-writer (TECH WRITER): README/CHANGELOG currency before build finalization"

speckit-echelon-tech-writer (TECH WRITER) must:

1. Write `{spec_dir}/documentation-impact-report.md`.
2. Update or create `README.md` and `CHANGELOG.md` when documentation impact is required.
3. Make a newly created or substantially rewritten `README.md` a first-run local manual, not just a product overview.
4. Use Keep a Changelog-style `[Unreleased]` entries when `CHANGELOG.md` is created or updated.
5. Return `echelon_result.verdict: DONE`.

After TECH WRITER returns DONE, route to `build-8-verify-docs`. If DOCS VERIFIER returns FAIL or BLOCKED, dispatch TECH WRITER again with `docs-verification-report.md` as mandatory repair context before finalization.
