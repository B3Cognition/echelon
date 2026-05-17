---
name: speckit.echelon.re-analyze
description: "Extract structured data from codebase into analysis.json"
behavior:
  execution: isolated
  invocation: automatic
scripts:
  sh: ../../scripts/bash/re/run-analysis.sh
---

# Reanalyze Codebase

> **Bash Command Guidelines**: Never use multi-line bash. Chain commands with `&&`. **IMPORTANT**: Do NOT use bash `ls`, `find`, `cat`, `echo`, or `grep` for file exploration - always use the dedicated Glob, Read, and Grep tools instead. Reserve bash only for git commands, `mkdir`, and other system operations.

Extract structured data from the current codebase for reverse engineering.

## Purpose

This command runs extraction scripts to gather:
- File structure (extensions, entry points, file counts)
- Dependencies (package.json, requirements.txt, etc.)
- Git history (recent commits, contributors, hotspots)
- Configuration files (CI/CD, Docker, k8s, databases)

## Prerequisites

1. You are in the root of the codebase to analyze
2. Git is available (for history extraction)
3. jq is installed (for JSON processing)

## User Input

$ARGUMENTS

## Steps

### Step 1: Check Prerequisites

Verify we're in a valid project directory:

```bash
if [ ! -d ".git" ] && [ ! -f "package.json" ] && [ ! -f "pyproject.toml" ] && [ ! -f "go.mod" ] && [ ! -f "Cargo.toml" ]; then
    echo "Warning: This doesn't appear to be a project root directory"
    echo "No .git, package.json, pyproject.toml, go.mod, or Cargo.toml found"
fi
```

**Polyrepo prerequisite check**: When multiple repos are detected, analysis markers live inside per-repo subdirectories, not the workspace root. Check for both patterns before concluding analysis is missing:

- **Root marker** (single-repo): `.specify/echelon/re/analysis.json`
- **Sub-repo markers** (polyrepo): `.specify/echelon/re/{repo-name}/analysis.json` for each repo listed in `.specify/echelon/re/repos-manifest.json`

If `repos-manifest.json` exists and `repo_count > 1`, treat missing root-level `analysis.json` as expected — proceed to check per-repo files instead.

### Step 2: Create Output Directory

```bash
OUTPUT_DIR=".specify/echelon/re"
mkdir -p "$OUTPUT_DIR"
echo "Output directory: $OUTPUT_DIR"
```

### Step 2.5: Run Repo Discovery

Run `discover-repos.sh` to detect whether this workspace contains multiple repos:

```bash
"$EXTENSION_PATH/scripts/bash/re/discover-repos.sh" ".specify/echelon/re/repos-manifest.json"
```

Read the resulting `repos-manifest.json`:

- If `repo_count == 1` — a single repo in a subdirectory.
- If `repo_count > 1` — multiple repos detected (polyrepo workspace).

In either case, pass the manifest to `run-analysis.sh` which handles both scenarios.

### Step 3: Run Extraction Scripts

Resolve layered config and export script-friendly env vars, then run extraction:

```bash
eval "$(specify extension config resolve echelon --format env --prefix ECHELON_CFG_RE_)" && "$EXTENSION_PATH/scripts/bash/re/run-analysis.sh" "$OUTPUT_DIR" "$OUTPUT_DIR/repos-manifest.json"
```

The script will:
1. Extract per-repo data into `.specify/echelon/re/{repo-name}/analysis.json` for each repo in the manifest.
2. If `repo_count > 1`, also produce `.specify/echelon/re/cross-repo.json` with cross-repo dependency and integration data.

### Step 4: Display Summary

After running the extraction, display a summary:

```text
Analysis complete! ({N} repo(s))

Per-repo analysis:
  - .specify/echelon/re/{repo-name}/analysis.json
  - .specify/echelon/re/{repo-name}/structure.json
  - .specify/echelon/re/{repo-name}/dependencies.json
  - .specify/echelon/re/{repo-name}/git-history.json
  - .specify/echelon/re/{repo-name}/configs.json

Aggregate:
  - .specify/echelon/re/analysis.json       (aggregate summary)
  - .specify/echelon/re/repos-manifest.json (repo list)
  - .specify/echelon/re/cross-repo.json     (only if repo_count > 1)
```

### Step 5: Next Steps

Display to the user:

```text
Next step: Run /speckit.echelon.re-specify to generate domain specifications.
```

## Output

The command creates `.specify/echelon/re/analysis.json` containing:

```json
{
  "extracted_at": "2026-03-09T12:00:00Z",
  "metadata": {
    "total_files": 523,
    "total_lines": 187420,
    "thresholds": { "files": 500, "lines": 100000 }
  },
  "structure": {
    "file_counts": {"ts": 180, "js": 12, "md": 8},
    "entry_points": ["package.json"],
    "total_files": 523
  },
  "dependencies": [...],
  "git_history": {
    "commits": [...],
    "contributors": [...],
    "hotspots": [...]
  },
  "configs": [...]
}
```

## Next Steps

After analysis completes, run:

- `/speckit.echelon.re-specify` - Generate spec.md from analysis
- Or `/speckit.echelon.re-extract` - Run full pipeline

## Structural Intelligence (CodeGraph)

`run-analysis.sh` automatically runs the CodeGraph bridge when Node.js and `scripts/node/codegraph-bridge.js` are available. If successful, it produces `.specify/echelon/re/codegraph-analysis.json` alongside `analysis.json`.

**If `.specify/echelon/re/codegraph-analysis.json` was produced**, mention it in the output summary:
- Total symbols extracted: `.index_stats.total_symbols`
- Languages covered: keys of `.language_coverage` where value is `"supported"`
- Index state: `.index_stats.index_state` (`"ready"` or `"degraded"`)

**If the file was not produced** (Node.js unavailable, bridge missing, or extraction failed): note this and continue — downstream commands fall back to file-level analysis automatically.

## Notes

- The analysis is non-destructive and only reads from your codebase
- Large repositories may take longer to process due to Git history extraction
- If jq is not installed, the extraction script will report an error. You MUST attempt to run the script first — you may only report jq as missing if the script returned an error indicating jq is unavailable
- The `.specify/echelon/re/` directory can be safely deleted to re-run analysis
- Analysis results are cached until source files change
