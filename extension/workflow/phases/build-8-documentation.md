# Phase: build-8-documentation
# Source: Documentation Currency Gate
# Read by: speckit-echelon-commander (COMMANDER) after all phase groups complete and before build finalization

## Documentation Currency Gate

After all implementation phase groups complete and before `build-8-finalize`, dispatch speckit-echelon-tech-writer (TECH WRITER).

Context pack:

- `{spec_dir}/spec.md`
- `{spec_dir}/tasks.md`
- `{spec_dir}/verification-summary.md` if present
- `{spec_dir}/gap-report.md` if present
- `{spec_dir}/progress-report.md` if present
- `{spec_dir}/traceability-matrix.md` if present
- repo-root `README.md` if present
- repo-root `CHANGELOG.md` if present
- changed files from the build worktree

Use the Agent tool:

- **subagent_type:** `speckit-echelon-tech-writer`
- **prompt:**

  ```xml
  <context>
  [include spec.md, tasks.md, verification summary/gap/progress/traceability reports when present, README.md when present, CHANGELOG.md when present, and changed-file summary]
  </context>

  <instructions>
  You are TECH WRITER. Read agents/build/tech-writer.md for your complete protocol.
  Decide whether documentation updates are required. If required, update repo-root README.md and CHANGELOG.md. Always write {spec_dir}/documentation-impact-report.md with machine-readable frontmatter. Return journal entries in echelon_result.journal_entries.
  </instructions>
  ```

- **description:** "speckit-echelon-tech-writer (TECH WRITER): README/CHANGELOG currency before build finalization"

speckit-echelon-tech-writer (TECH WRITER) must:

1. Write `{spec_dir}/documentation-impact-report.md`.
2. Update or create `README.md` and `CHANGELOG.md` when documentation impact is required.
3. Use Keep a Changelog-style `[Unreleased]` entries when `CHANGELOG.md` is created or updated.
4. Return `echelon_result.verdict: DONE`.

If TECH WRITER returns BLOCKED or omits `documentation-impact-report.md`, route to rework before `build-8-finalize`.
