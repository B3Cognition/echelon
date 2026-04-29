# Polyrepo Multi-Target Harness Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow a spec created at a polyrepo root (P) to drive independent harness runs against one or more sub-repos (A, B, C), each producing its own commits and PR in its own remote.

**Architecture:** Spec frontmatter declares `targets:` (relative paths to sub-repos). The CLI detects "orchestrator mode" when P has no local `echelon.yml` and the spec has targets, then shells out to each sub-repo's harness in parallel. Sub-repos find the spec via walk-up discovery. The squad writes `targets:` automatically during `echelon run` by reading revenge analysis; a manual `echelon spec target` command handles overrides.

**Tech Stack:** Python (existing harness codebase), pytest, YAML frontmatter in spec markdown files.

---

## Context

A polyrepo root (P) contains multiple git repos (A, B, C) with their own remote origins. Specs are authored at P level (cross-repo analysis via revenge). Implementation runs inside individual repos. Previously, running `echelon harness run` from P failed with "mirror does not exist" because P has no harness init of its own, and even when run from a sub-repo the spec was not found.

No changes to the sub-repo `echelon harness init` flow — it already works correctly when run inside A or B.

---

## Design

### 1. Spec `targets:` frontmatter

A spec's leading YAML frontmatter block gains an optional `targets:` list. Paths are relative to the directory containing the spec folder.

```markdown
---
targets:
  - og-platform
  - fet-frontend-libs
---
```

**Rules:**
- `targets:` is optional. Absence means single-repo mode (current behaviour, unchanged).
- Paths are resolved relative to the spec's parent directory at parse time.
- Invalid / non-existent paths are caught at run time with a clear error before any sub-run starts.
- A sub-repo is "ready" when it contains `.specify/extensions/echelon/echelon.yml`. Missing init produces a clear actionable message: `✗ og-platform: not initialised — run 'echelon harness init' inside og-platform first`.

### 2. Walk-up spec discovery

`coordinator.py`'s `_build_reentry_prompt` currently globs `{base_dir}/specs/{spec_id}-*`. This is extracted into a helper `find_spec_dir(spec_id, start_dir)` that:

1. Checks `{start_dir}/specs/{spec_id}-*`
2. If not found, walks up one level and repeats
3. Stops when it crosses a git boundary (a directory containing `.git`) or reaches filesystem root
4. Returns the first match, or `None`

This allows `cd og-platform && echelon harness run 024` to find a spec that lives in the polyrepo parent.

**The git-boundary stop condition** prevents accidentally finding an unrelated spec in a grandparent project.

### 3. P-level orchestrator mode

In `_cmd_harness_run`, after the existing "no echelon.yml" check, a second path handles orchestration:

```
if no local echelon.yml:
    find spec via walk-up
    if spec not found → exit with current error
    read targets from spec frontmatter
    if no targets → exit with error: "no echelon.yml and spec has no targets"
    validate all targets are initialised
    launch one subprocess per target in parallel
    stream output prefixed [target-name]
    exit 0 only if all subprocesses exit 0
```

Each subprocess call forwards the original args verbatim:
```
echelon harness run <spec_id> [strategy=…] [mode=…] [free-text…]
```

Subprocesses run with their CWD set to the resolved target path. Output is streamed line-by-line with a `[<target-name>] ` prefix so the user can follow both runs simultaneously.

### 4. Squad target detection during `echelon run`

The `echelon.run` squad command's SCOUT phase reads the revenge analysis output from `.specify/extensions/revenge/` (when present at P level) to identify which repos are touched by the new spec. CARTOGRAPHER writes the detected repos as `targets:` frontmatter into the spec file.

Fallback behaviour when revenge output is absent or ambiguous:
- Squad explicitly asks the user: "Which repos does this spec target? (found: og-platform, fet-frontend-libs, …)"
- User can name one, several, or none (for single-repo specs)

The frontmatter is written as the last step of `echelon run` spec generation, before the squad hands off to the user.

### 5. `echelon spec target` command

```
echelon spec target <spec_id> <repo> [repo…]
```

Reads the spec's frontmatter, replaces (or creates) the `targets:` list with the provided repos, writes the file in-place. Prints the updated frontmatter as confirmation.

```
$ echelon spec target 024 og-platform
Updated specs/024-psd-import-filter-support/spec.md
  targets:
    - og-platform
```

If `spec_id` matches multiple spec folders (ambiguous prefix), the command lists the matches and exits without writing.

---

## File Structure

| File | Change |
|---|---|
| `src/harness/coordinator.py` | Extract `find_spec_dir()` helper with walk-up logic |
| `src/harness/spec_frontmatter.py` | New: parse/write spec YAML frontmatter (`targets`, future fields) |
| `src/echelon/cli.py` | Add orchestrator mode in `_cmd_harness_run`; add `spec target` subcommand |
| `src/echelon/orchestrator.py` | New: `run_multi_target()` — parallel subprocess launcher with prefixed output |
| `tests/harness/test_spec_frontmatter.py` | New: frontmatter parse/write unit tests |
| `tests/harness/test_find_spec_dir.py` | New: walk-up discovery unit tests |
| `tests/echelon/test_orchestrator.py` | New: multi-target parallel run tests (subprocess mocked) |
| `tests/echelon/test_cli_spec_target.py` | New: `echelon spec target` CLI unit tests |
| Extension command `echelon.run.md` | Update SCOUT/CARTOGRAPHER phase to write `targets:` |

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| P has no echelon.yml, spec has no targets | Exit with: `✗ Harness not initialised. Run 'echelon harness init' or add targets: to your spec.` |
| Target path does not exist | Exit before any sub-run: `✗ Target 'og-platform' not found relative to spec.` |
| Target not initialised (no echelon.yml) | Exit before any sub-run: `✗ og-platform: run 'echelon harness init' inside og-platform first.` |
| One sub-run fails, other succeeds | Report both outcomes; exit non-zero. Do not cancel the successful run. |
| Walk-up crosses git boundary without finding spec | Fall through to original "not initialised" error. |
| `echelon spec target` — ambiguous spec_id | List matches, exit 1, write nothing. |

---

## Testing Strategy

### Unit tests (no Docker, no git)

- `test_spec_frontmatter.py`: parse frontmatter with targets, without targets, malformed YAML, missing block, write targets in-place preserving existing body
- `test_find_spec_dir.py`: found locally, found one level up, found two levels up, stops at git boundary, not found returns None
- `test_cli_spec_target.py`: single target, multiple targets, ambiguous spec_id, spec with no existing frontmatter

### Integration tests (subprocess mocked)

- `test_orchestrator.py`: both targets succeed → exit 0; one fails → exit 1; output prefixed correctly; args forwarded verbatim; targets validated before launch

### Regression tests

- `test_harness_single_repo_unchanged.py`: existing single-repo run path (spec without `targets:`, local echelon.yml present) is untouched by this change — same behaviour as before
- `test_find_spec_dir_local_preferred.py`: local spec takes precedence over parent-level spec of same id

### Manual smoke test (documented, not automated)

```
# One-time setup per sub-repo
cd og-platform && echelon harness init && cd ..

# Set targets on existing spec
echelon spec target 024 og-platform

# Run from polyrepo root
echelon harness run 024 strategy=codegen max_outer=2
# Expected: [og-platform] lines interleaved in output, PR in og-platform
```

---

## Non-Goals

- Specs that touch shared files across A and B simultaneously (cross-repo coordination within one agent run) — out of scope.
- P-level harness init (P itself as a git repo with its own mirror) — not needed.
- Automatic sub-repo discovery (scanning P for repos) — targets are always explicit.
- Docker or CI changes — none required.
