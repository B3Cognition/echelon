---
name: speckit.echelon.re-expand
description: "Expand spec coverage by filling gaps with orphan file clusters"
behavior:
  execution: isolated
  invocation: automatic
---

# Expand Specification Coverage

> **Bash Command Guidelines**: Never use multi-line bash. Chain commands with `&&`. **IMPORTANT**: Do NOT use bash `ls`, `find`, `cat`, `echo`, or `grep` for file exploration - always use the dedicated Glob, Read, and Grep tools instead. Reserve bash only for git commands, `mkdir`, and other system operations.

Iteratively expand specification coverage by analyzing orphan files and creating/expanding domains.

## Purpose

Run this command **after** `/speckit.echelon.re-verify` reveals coverage gaps. It will:

1. Load existing specs (don't regenerate)
2. Analyze remaining orphan files
3. Cluster orphans by similarity (imports, naming patterns)
4. Auto-create domains for high-confidence clusters
5. Expand reference-data domain with unmapped models
6. Re-calculate and display new coverage

## Prerequisites

1. Specs have been generated with `/speckit.echelon.re-specify`
2. Verification has been run with `/speckit.echelon.re-verify`
3. Coverage report exists showing orphan files/clusters

## User Input

$ARGUMENTS

## Workflow Position

```text
┌─────────────┐    ┌─────────────┐    ┌──────────┐    ┌──────────┐
│  reanalyze  │───▶│  respecify  │───▶│  verify  │───▶│  expand  │──┐
└─────────────┘    └─────────────┘    └──────────┘    └──────────┘  │
                                          ▲                       │
                                          │    Coverage < 80%     │
                                          └───────────────────────┘
                                          │
                                          ▼ Coverage ≥ 80%
                              ┌───────────────┐    ┌──────────┐    ┌───────────┐
                              │ reconstitute  │───▶│  replan  │───▶│  retasks  │
                              └───────────────┘    └──────────┘    └───────────┘
```

## Steps

### Step 1: Load Existing State

```bash
OVERVIEW_DIR="specs/000-re-overview"
ANALYSIS_FILE=".specify/echelon/re/analysis.json"
COVERAGE_REPORT="$OVERVIEW_DIR/coverage-report.md"

if [ ! -f "$COVERAGE_REPORT" ]; then
    echo "Error: Coverage report not found at $COVERAGE_REPORT"
    echo "Run /speckit.echelon.re-verify first"
    exit 1
fi

echo "Loading existing reverse-engineered specs from specs/..."
echo "Loading coverage report from $COVERAGE_REPORT..."
```

Read:

- Existing domain specs
- Coverage report with orphan files
- Orphan cluster suggestions

### Step 2: Identify Expansion Targets

From the coverage report, identify:

**High-confidence clusters** (auto-expand):

- Clusters with ≥3 files
- Clusters with confidence ≥70%
- Total size ≥20KB

**Reference data gaps**:

- Files in `sportdata/`, `models/`, `entities/` not in Domain 03
- Auto-add to reference-data-models domain

**Remaining orphans**:

- Files that don't fit any cluster
- Suggest adding to closest existing domain

### Step 3: Create New Domains

For each high-confidence cluster:

```python
for cluster in high_confidence_clusters:
    # Find next available domain number
    domain_num = next_available_domain_number()  # scans specs/[0-9][0-9][0-9]-*/
    domain_name = f"{domain_num:03d}-re-{cluster.suggested_name}"

    # Generate spec for this domain
    generate_domain_spec(
        folder=f"specs/{domain_name}",
        files=cluster.files,
        purpose=cluster.rationale
    )

    print(f"✓ Created specs/{domain_name} ({len(cluster.files)} files)")
```

### Step 4: Expand Existing Domains

For reference data and close-fit orphans:

```python
# Expand reference-data domain (find existing re-reference-data spec)
if unmapped_data_models:
    ref_data_domain = find_domain_by_pattern("re-reference-data")
    expand_domain(
        domain=ref_data_domain,
        files=unmapped_data_models
    )
    print(f"✓ Expanded {ref_data_domain} (+{len(unmapped_data_models)} files)")

# Add close-fit orphans to existing domains
for orphan, suggested_domain in close_fit_orphans:
    expand_domain(
        domain=suggested_domain,
        files=[orphan]
    )
```

### Step 5: Recalculate Coverage

```python
new_coverage = calculate_coverage()

print(f"")
print(f"Coverage after expansion:")
print(f"  Before: {old_coverage}% ({old_covered}/{total} files)")
print(f"  After:  {new_coverage}% ({new_covered}/{total} files)")
print(f"  Gain:   +{new_coverage - old_coverage}%")
```

### Step 6: Display Summary

```text
Expansion Complete
==================

New domains created:
  ✓ 015-search-discovery (4 files, 101KB)
  ✓ 016-cricket-scheduling (8 files, 95KB)

Domains expanded:
  ✓ 003-reference-data-models (+90 files)
  ✓ 001-core-framework (+5 files)

Coverage:
  Before: 33.2% (63/190 files)
  After:  86.8% (165/190 files)
  Gain:   +53.6%

Remaining orphans: 25 files
  - 15 small utilities (<5KB)
  - 10 test/demo files

Status: ✓ Above 80% threshold

Next: /speckit.echelon.re-verify (to confirm)
  Or: /speckit.echelon.re-constitute (to proceed)
```

### Step 7: Update Coverage Report

Regenerate `coverage-report.md` with new statistics.

## Domain Creation Rules

### When to Create New Domain

Create a new domain when orphan cluster has:

- **≥3 files** in the cluster
- **≥20KB total size**
- **≥70% confidence** (based on import/naming similarity)
- **Distinct purpose** (not overlapping with existing domains)

### When to Expand Existing Domain

Add orphans to existing domain when:

- File imports primarily from that domain
- File naming follows domain pattern
- File is small utility for that domain's functionality

### Domain Naming

New domains are numbered sequentially after existing domains:

```text
Existing: 001 through 014
New:      015-search-discovery
          016-cricket-scheduling
          017-external-integrations
```

## Cluster Detection Patterns

| Pattern | Suggested Domain |
| ------- | ---------------- |
| `View*.java`, `Show*.java` | search-discovery |
| `Cricket*.java`, `Match*.java` | cricket-scheduling |
| `*Client.java`, `*API.java` | external-integrations |
| `*Menu.java`, `*ComboBox.java` | ui-components |
| `Check*.java`, `Validate*.java` | data-validation |

## Integration with Workflow

The expand command fits into the iterative loop:

```bash
# Initial generation
/speckit.echelon.re-specify

# Check coverage
/speckit.echelon.re-verify
# Output: Coverage 33.2% - below threshold

# Expand coverage
/speckit.echelon.re-expand
# Output: Coverage 72.1% - still below threshold

# Check again
/speckit.echelon.re-verify
# Output: Coverage 72.1% - suggests more expansions

# Expand again
/speckit.echelon.re-expand
# Output: Coverage 86.8% - above threshold!

# Proceed to constitution
/speckit.echelon.re-constitute

# Then planning
/speckit.echelon.re-plan
```

## Notes

- Expansion preserves manually edited spec content
- New domains are appended, existing domains are updated
- Coverage report is regenerated after each expansion
- Multiple expansion rounds may be needed for large codebases
