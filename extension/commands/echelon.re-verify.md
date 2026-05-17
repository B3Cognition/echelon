---
name: speckit.echelon.re-verify
description: "Verify spec coverage against codebase and identify gaps"
behavior:
  execution: isolated
  invocation: automatic
---

# Verify Specification Coverage

> **Bash Command Guidelines**: Never use multi-line bash. Chain commands with `&&`. **IMPORTANT**: Do NOT use bash `ls`, `find`, `cat`, `echo`, or `grep` for file exploration - always use the dedicated Glob, Read, and Grep tools instead. Reserve bash only for git commands, `mkdir`, and other system operations.

Verify that generated specifications cover the codebase comprehensively and identify gaps.

## Purpose

Run this command **after** generating specs with `/speckit.echelon.re-specify` to:

1. Verify all source files are covered by a domain spec
2. Identify orphan files not documented in any spec
3. Cluster orphans to suggest new domains
4. Generate actionable gap report

## Prerequisites

1. reverse-engineered specs exist in `specs/` (e.g., `specs/NNN-re-{domain}/`)
2. Analysis exists at `.specify/echelon/re/analysis.json`

## User Input

$ARGUMENTS

## Steps

### Step 1: Load File Inventory

First check `.specify/echelon/re/repos-manifest.json` for repo count, then read `.specify/echelon/re/analysis.json` to get the total source file count:

```python
# Check manifest for repo count (aggregate analysis.json is always present)
manifest = read(".specify/echelon/re/repos-manifest.json")  # if exists
repo_count = manifest.get("repo_count", 1) if manifest else 1

# Get total source file count from aggregate analysis metadata
analysis = read(".specify/echelon/re/analysis.json")
total_files = analysis["metadata"]["total_files"]
```

Then enumerate source file paths from disk using the Glob tool (analysis.json stores counts only, not file paths).

**Load extensions from config**: Run `specify extension config resolve echelon --format json`, then read `source_extensions` from the resolved object (or use built-in defaults). Build glob patterns `**/*.{ext}` for each extension across all languages.

**Default extensions** (if no config found):

- TypeScript: `ts, tsx`
- JavaScript: `js, jsx, mjs, cjs`
- Python: `py, pyw`
- Go: `go`
- Rust: `rs`
- Java: `java`
- Kotlin: `kt, kts`
- C#: `cs`
- Ruby: `rb, rake`
- PHP: `php`
- Swift: `swift`
- C: `c, h`
- C++: `cpp, hpp, cc, hh, cxx, hxx`
- Perl: `pl, pm`
- Delphi: `pas, dpr, dfm`
- Groovy: `groovy, gvy`

**Exclude directories**: `node_modules/`, `vendor/`, `dist/`, `build/`, `__pycache__/`, `target/`, `.venv/`, `venv/`

Assign the resulting list of paths to `file_inventory`.

### Step 2: Extract Files Referenced in Specs

Scan all generated specs for file references:

```text
Use the Glob tool to find all migration spec folders: specs/[0-9][0-9][0-9]-re-*/
Then read the matched spec files and extract file references using these patterns:
- `path/to/file.ext:123`
- `path/to/file.ext`
```

Build list of files covered by specs:

- Files mentioned in "Source Evidence" sections
- Files mentioned in "Source Files Analyzed" headers
- Files mentioned in entity definitions

### Step 3: Calculate Coverage

```text
covered_files = files mentioned in any spec
orphan_files = file_inventory - covered_files

coverage_percent = (len(covered_files) / total_files) × 100
```

### Step 4: Categorize Orphans

Group orphan files by priority:

**High Priority (>50KB)**:
- Large files likely represent missed domains
- Should trigger new domain creation

**Medium Priority (20-50KB)**:
- Significant files that should be documented
- May fit into existing domains

**Low Priority (<20KB)**:
- Small utilities, helpers
- May be intentionally excluded

**Reference Data**:
- Files in `sportdata/`, `models/`, `entities/` directories
- Should expand reference-data domain

### Step 5: Detect Orphan Clusters

Group related orphans by:

1. **Import similarity** - files that import each other
2. **Naming patterns** - `View*.java`, `Cricket*.java`, `*Dialog.java`
3. **Directory proximity** - files in same subdirectory

For each cluster:

- Calculate confidence score (0-1)
- Suggest domain name based on common patterns
- List all files in cluster

### Step 5.5: Polyrepo Coverage Calculation

If `.specify/echelon/re/repos-manifest.json` exists and `repo_count > 1`:

1. **Per-repo coverage**: For each repo, calculate coverage independently:

   ```text
   repo_coverage = (files in repo mapped to its specs) / (total files in repo) × 100
   ```

2. **Aggregate coverage**: Sum covered and total across all repos:

   ```text
   aggregate_coverage = (sum of covered_files across all repos) / (sum of total_files across all repos) × 100
   ```

3. **Flag repos below threshold**: Any individual repo whose coverage falls below the threshold (default 80%) is flagged as a warning — even if aggregate coverage is above threshold.

4. **Per-repo breakdown table**: Include in the coverage report (see Step 6 below).

### Step 6: Generate Coverage Report

Output markdown report:

```markdown
# Coverage Verification Report

**Project**: {project-name}
**Verified**: {DATE}
**Specs Location**: specs/

## Coverage Summary

| Metric | Value | Status |
|--------|-------|--------|
| Total Source Files | {total} | - |
| Files in Specs | {covered} | - |
| Orphan Files | {orphans} | - |
| **Coverage** | **{percent}%** | {✓ or ❌} |

[If repo_count > 1:]

## Per-Repository Coverage

| Repository | Total Files | Covered | Coverage | Status |
|------------|-------------|---------|----------|--------|
| {repo-a} | {total_a} | {covered_a} | {pct_a}% | {✓ or ⚠️} |
| {repo-b} | {total_b} | {covered_b} | {pct_b}% | {✓ or ⚠️} |
| ... | ... | ... | ... | ... |
| **Aggregate** | **{grand_total}** | **{total_covered}** | **{agg_pct}%** | {✓ or ❌} |

Repos below threshold ({threshold}%): {list of flagged repo names, or "none"}

## Coverage by Domain

| Domain | Files | % |
|--------|-------|---|
| 001-{name} | {n}/{total_for_domain} | {%} |
...

## High-Priority Orphans (>50KB)

| File | Size | Suggested Domain |
|------|------|------------------|
| {path} | {KB}KB | {suggestion} |
...

## Orphan Clusters Detected

### Cluster 1: {suggested-name} ({n} files, {KB}KB)

**Confidence**: {HIGH/MEDIUM/LOW}
**Recommendation**: Create new domain OR expand existing domain

Files:
- {file1}
- {file2}
...

## Recommended Actions

1. **{Action}**: {Description}
   - Expected coverage gain: +{n}%

2. ...

## Next Steps

Run `/speckit.echelon.re-expand` to auto-fill gaps
```

### Step 7: Save Report

Write the coverage report to `specs/000-re-overview/coverage-report.md`.

### Step 8: Display Summary

```text
Coverage Verification Complete
==============================

Coverage: {percent}% ({covered}/{total} files)
Status: {✓ Above threshold | ❌ Below 80% threshold}

Orphan files: {count}
  - High priority: {count} (>50KB)
  - Medium priority: {count} (20-50KB)
  - Low priority: {count} (<20KB)

Clusters detected: {count}
  - {cluster1}: {files} files ({confidence})
  - {cluster2}: {files} files ({confidence})

Recommended actions:
  1. {action1}
  2. {action2}

Report saved to: {path}

Next: /speckit.echelon.re-specify --expand
```

## Cluster Detection Patterns

### Import-Based Clustering

Files that share imports belong together:

```python
# If files A and B both import "cricket" modules
# They likely belong to same domain
```

### Naming Pattern Clustering

| Pattern | Suggested Domain |
|---------|------------------|
| `View*.java`, `Show*.java` | search-discovery |
| `Cricket*.java`, `Match*.java` | cricket-scheduling |
| `Check*.java`, `Validate*.java` | data-validation |
| `*Dialog.java`, `*Panel.java` | Infer from prefix |
| `*Menu.java`, `*ComboBox.java` | ui-components |

### Directory Clustering

Files in same directory often belong together:

```text
sportdata/Cricket*.java → cricket domain OR expand reference-data
src/reports/*.java → reporting domain
```

## Exit Criteria

| Coverage | Action |
|----------|--------|
| ≥80% | ✓ Verification passed |
| 60-79% | ⚠️ Warning, suggest expansions |
| <60% | ❌ Major gaps, require expansion |

## Notes

- Run verify after every respecify to track progress
- Coverage improves iteratively with `--expand`
- Some files (tests, demos) may be intentionally excluded
- High-priority orphans indicate missed domains
