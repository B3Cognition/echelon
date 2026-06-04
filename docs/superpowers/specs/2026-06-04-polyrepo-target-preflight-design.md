# Polyrepo Target Preflight Design

Date: 2026-06-04

## Problem

Echelon supports polyrepo specifications through `echelon spec target`, but harness build currently depends on the spec already containing `targets:` frontmatter. If a spec was created for a polyrepo root and the target was not recorded, harness can fall back to the wrapper repo. In the observed `001-opta-points-perf-fix` run, the LLM found the correct nested implementation repo and committed work there, but the harness state machine still treated the wrapper repo as the build target and ended as `build_incomplete`.

That failure mode is unsafe because implementation target selection happens inside prompt execution instead of deterministic orchestration. The system needs to decide the target before build starts, record it in the spec, and make harness/resume/land operate against that target.

## Goals

- Use all repos in a polyrepo as source/context for understanding and planning.
- Require exactly one implementation target repo for normal harness build specs.
- Preserve existing explicit `targets:` behavior as the source of truth.
- Add deterministic target inference when `targets:` is missing.
- In `semi` mode, recommend the target and require user confirmation.
- In `banzai` mode, write `targets:` automatically only when confidence is high.
- Block instead of guessing when target confidence is low or tied.
- Ensure harness build/resume/land use the target repo, branch, and commit rather than the wrapper repo.

## Non-Goals

- Do not make an LLM agent responsible for final target selection.
- Do not silently build multiple repos for a normal implementation spec.
- Do not automatically update wrapper submodule pointers unless a separate landing policy explicitly allows it.
- Do not replace `echelon spec target`; this design makes it safer and more useful.

## Target Model

The spec frontmatter remains authoritative:

```yaml
---
targets:
  - rbf-opta-points
---
```

For normal specs, `targets` must contain exactly one repo. Multi-target specs are a separate mode and must be explicit. A missing `targets` value in a detected polyrepo is no longer treated as permission to build the wrapper repo.

## Preflight Flow

Harness run performs target preflight before single-repo harness initialization checks:

1. Find the spec directory and read spec frontmatter.
2. Detect whether the project root contains multiple git repos or configured sub-repos.
3. If `targets:` exists:
   - Validate every target path exists under the polyrepo root.
   - Validate each target is harness-initialized or report the exact `echelon harness init` command.
   - For normal specs, reject zero targets or more than one target.
   - Dispatch harness run inside the target repo.
4. If `targets:` is missing and the root is single-repo:
   - Continue current single-repo behavior.
5. If `targets:` is missing and the root is polyrepo:
   - Run deterministic target detection.
   - Apply mode-specific behavior.

## Target Detection

Target detection is Python-owned and deterministic. It scores each candidate repo using evidence from the spec directory and repository layout:

- File paths mentioned in `spec.md`, `plan.md`, `tasks.md`, `research.md`, and contracts.
- Repo names, package names, service names, and directory names referenced in requirements.
- Source symbols, classes, functions, or module paths referenced by tasks and acceptance criteria.
- Existing implementation files matching planned change locations.
- Test paths or framework markers implied by the plan.
- Negative evidence when references clearly belong to a different repo.

The detector emits a report such as:

```json
{
  "recommended_target": "rbf-opta-points",
  "confidence": 0.92,
  "candidates": [
    {
      "repo": "rbf-opta-points",
      "confidence": 0.92,
      "evidence": [
        "tasks.md references src/lib/sdapi/services/shared-promise.ts",
        "spec.md references OptaPoints service behavior",
        "repo contains matching package and source paths"
      ]
    }
  ],
  "decision": "recommend"
}
```

The confidence threshold for automatic action is configurable, defaulting to `0.80`.

## Mode Behavior

### Semi Mode

If confidence is at or above threshold, harness stops before build and prints the recommendation:

```text
Likely implementation target: rbf-opta-points (confidence 0.92)
Evidence:
- tasks.md references src/lib/sdapi/services/shared-promise.ts
- rbf-opta-points contains the referenced source files

Confirm with:
  echelon spec target 001-opta-points-perf-fix rbf-opta-points
Then rerun:
  echelon harness run 001-opta-points-perf-fix
```

If confidence is below threshold or tied, harness blocks and asks the user to set the target explicitly with `echelon spec target`.

Semi mode never writes `targets:` automatically.

### Banzai Mode

If confidence is at or above threshold, harness writes the target into spec frontmatter and continues:

```yaml
targets:
  - rbf-opta-points
```

The write is recorded in console output and run history. If confidence is below threshold or tied, banzai mode blocks rather than guessing.

## Harness Build Behavior

Once a target is known, harness build runs inside the target repo. The build state records:

- `polyrepo_root`
- `target_repo_path`
- `target_repo_name`
- `target_branch`
- `target_commit`
- `wrapper_repo_path`, if applicable
- whether wrapper submodule pointer updates are pending

Build prompts should receive the target repo as the project root. They may read polyrepo context artifacts when supplied, but writes and git operations are scoped to the target repo unless explicitly configured otherwise.

## Resume Behavior

Harness resume inspects both the run worktree and the recorded target repo. If a run timed out after committing work in the target repo, resume reports:

```text
Implementation commit preserved:
  repo:   rbf-opta-points
  branch: 001-opta-points-perf-fix
  commit: 6132709
```

Resume continues from that target branch and does not ask the user to manually discover or salvage nested repo work.

## Land Behavior

Land operates on the target repo branch. It should:

- verify the target branch exists and contains the implementation commits
- merge or rebase the target repo default branch according to land policy
- run configured final verification
- push the target branch or open a PR

Wrapper repo submodule pointer updates are handled separately:

- If configured to update wrapper pointers, land stages and commits the submodule pointer in the wrapper repo.
- If not configured, land reports the pending pointer change and leaves the wrapper repo untouched.

## Error Handling

Harness blocks with clear remediation when:

- no target is set in a polyrepo and detection confidence is too low
- more than one target is present for a normal single-target spec
- the target path does not exist
- the target repo has no harness configuration
- a target branch/commit exists outside harness state after a timeout

All block messages include the exact command the user should run next.

## Tests

Focused tests should cover:

- spec with no `targets:` in single-repo mode keeps current behavior
- spec with explicit target dispatches harness inside that repo
- semi mode high-confidence detection recommends and stops
- semi mode low-confidence detection blocks
- banzai mode high-confidence detection writes `targets:` and continues
- banzai mode low-confidence detection blocks
- missing target harness init gives exact guidance
- resume reports preserved target repo commit after `build_incomplete`
- land uses target repo branch rather than wrapper repo branch
- wrapper submodule pointer is not committed unless configured

## Migration

Existing specs without `targets:` continue to work in single-repo projects. Existing polyrepo specs without `targets:` will now stop before build and ask for target confirmation in semi mode. Users can run:

```bash
echelon spec target <spec_id> <repo>
```

to make the target explicit.

## Design Decisions

- The default confidence threshold is `0.80`.
- Normal implementation specs are single-target by default.
- Multi-target build remains explicit and separate from inferred single-target behavior.
