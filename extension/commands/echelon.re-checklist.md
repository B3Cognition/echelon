---
name: speckit.echelon.re-checklist
description: "Generate quality checklists for reverse-engineered specs - per-domain and summary"
behavior:
  execution: isolated
  invocation: automatic
---

# Generate Quality Checklists for Reverse-Engineered Specs

> **Bash Command Guidelines**: Never use multi-line bash. Chain commands with `&&`. **IMPORTANT**: Do NOT use bash `ls`, `find`, `cat`, `echo`, or `grep` for file exploration - always use the dedicated Glob, Read, and Grep tools instead. Reserve bash only for git commands, `mkdir`, and other system operations.

Generate quality review checklists for all reverse-engineered domain specifications.

## Purpose

This command generates **requirements quality checklists** - "unit tests for English" that validate whether the reverse-engineered specs are complete, clear, consistent, and ready for planning.

**Two types of checklists:**

1. **Per-domain checklists** (`NNN-re-{domain}/checklist.md`) - Domain-specific quality items
2. **Summary checklist** (`000-re-overview/checklist.md`) - Cross-domain and migration concerns

## Prerequisites

1. Domain specifications exist: `specs/NNN-re-{domain}/spec.md`
2. Validation has been run: `specs/000-re-overview/validation-report.md` exists (recommended)

## User Input

$ARGUMENTS

## Output Structure

```text
specs/
├── 000-re-overview/
│   ├── checklist.md              # OUTPUT: Cross-domain summary checklist
│   └── ...
│
├── {NNN}-re-core-framework/
│   ├── spec.md                   # Input
│   └── checklist.md              # OUTPUT: Domain-specific checklist
├── {NNN+1}-re-data-access/
│   ├── spec.md
│   └── checklist.md              # OUTPUT
└── ...
```

## Workflow Position

```text
reanalyze → respecify → verify/expand → validate → rechecklist → reconstitute
                                                      ↑
                                        Generates quality checklists
                                        (non-interactive, standardized)
```

## Steps

### Step 1: Locate Domain Specs

```bash
OVERVIEW_DIR="specs/000-re-overview"

# Find all reverse-engineered domain directories
DOMAINS=$(ls -d specs/[0-9][0-9][0-9]-re-*/ 2>/dev/null)

if [ -z "$DOMAINS" ]; then
    echo "Error: No reverse-engineered domain specifications found"
    echo "Run /speckit.echelon.re-specify first"
    exit 1
fi

echo "Found $(echo "$DOMAINS" | wc -l) domains to generate checklists for"
```

### Step 2: Load Context

For each domain, read:

- `spec.md` - Requirements and user stories
- `validation-report.md` (if exists) - Known issues

Build cross-domain index:

- All [NEEDS CLARIFICATION] items
- Cross-domain dependencies
- Entity definitions across domains
- Terminology usage

### Step 3: Generate Per-Domain Checklists

For each domain directory with spec.md:

```python
for domain_dir in domains:
    domain_name = os.path.basename(domain_dir)  # e.g., "003-re-core-framework"
    domain_num = domain_name.split('-')[0]      # e.g., "003"

    spec = read_file(f"{domain_dir}/spec.md")

    checklist = generate_domain_checklist(
        domain=domain_name,
        domain_num=domain_num,
        spec=spec
    )

    write_file(f"{domain_dir}/checklist.md", checklist)
    print(f"✓ Generated {domain_dir}/checklist.md")
```

### Step 4: Per-Domain Checklist Structure

Each domain `checklist.md` follows this structure:

```markdown
# Quality Checklist: {Domain Name}

**Domain**: {NNN}-re-{domain-name}
**Created**: {DATE}
**Spec**: [spec.md](spec.md)

**Purpose**: Validate requirements quality before planning phase.

---

## Source Evidence Quality

- [ ] CHK-{NNN}-001 - Are all functional requirements backed by source file references? [Traceability]
- [ ] CHK-{NNN}-002 - Are source:line references accurate and verifiable? [Accuracy]
- [ ] CHK-{NNN}-003 - Is the "Source Evidence" section present for each user story? [Completeness]

## Requirements Completeness

- [ ] CHK-{NNN}-004 - Are all user stories complete with acceptance scenarios? [Completeness]
- [ ] CHK-{NNN}-005 - Are functional requirements specific and actionable? [Clarity]
- [ ] CHK-{NNN}-006 - Are non-functional requirements defined (performance, security)? [Coverage]
- [ ] CHK-{NNN}-007 - Are success criteria measurable? [Measurability]

## Entity Definitions

- [ ] CHK-{NNN}-008 - Are all entities defined with attributes and types? [Completeness]
- [ ] CHK-{NNN}-009 - Are entity relationships documented? [Completeness]
- [ ] CHK-{NNN}-010 - Are field constraints and validation rules specified? [Clarity]

## Edge Cases & Error Handling

- [ ] CHK-{NNN}-011 - Are error scenarios documented with expected behavior? [Coverage]
- [ ] CHK-{NNN}-012 - Are boundary conditions addressed? [Edge Cases]
- [ ] CHK-{NNN}-013 - Are failure recovery requirements defined? [Coverage]

## Clarification Items

- [ ] CHK-{NNN}-014 - Are all [NEEDS CLARIFICATION] items actionable? [Clarity]
- [ ] CHK-{NNN}-015 - Is context provided for unresolved ambiguities? [Completeness]

## Domain Dependencies

- [ ] CHK-{NNN}-016 - Are upstream dependencies clearly listed? [Completeness]
- [ ] CHK-{NNN}-017 - Are integration points with other domains documented? [Coverage]

---

## Review Summary

| Category | Items | Checked |
|----------|-------|---------|
| Source Evidence | 3 | _/3 |
| Completeness | 4 | _/4 |
| Entity Definitions | 3 | _/3 |
| Edge Cases | 3 | _/3 |
| Clarifications | 2 | _/2 |
| Dependencies | 2 | _/2 |
| **Total** | **17** | **_/17** |

**Reviewer**: _______________
**Date**: _______________
**Status**: [ ] Approved [ ] Needs Revision
```

### Step 5: Generate Summary Checklist

Create `000-re-overview/checklist.md` with cross-domain concerns:

```markdown
# Quality Checklist: Reverse-Engineered Summary

**Project**: {project-name}
**Created**: {DATE}
**Domains**: {count} specifications reviewed

**Purpose**: Cross-domain quality validation for reverse-engineered specifications.

---

## Coverage Quality

- [ ] CHK-000-001 - Is file coverage ≥80% of source codebase? [Coverage]
- [ ] CHK-000-002 - Are orphan files intentionally excluded or documented? [Completeness]
- [ ] CHK-000-003 - Are all major functional areas represented as domains? [Coverage]

## Domain Boundaries

- [ ] CHK-000-004 - Are domain boundaries clearly defined without overlap? [Clarity]
- [ ] CHK-000-005 - Is each domain cohesive (single responsibility)? [Consistency]
- [ ] CHK-000-006 - Are shared concepts assigned to appropriate domains? [Clarity]

## Cross-Domain Consistency

- [ ] CHK-000-007 - Is terminology consistent across all domain specs? [Consistency]
- [ ] CHK-000-008 - Are shared entities defined once and referenced elsewhere? [Consistency]
- [ ] CHK-000-009 - Are cross-domain dependencies acyclic? [Consistency]

## Dependency Graph

- [ ] CHK-000-010 - Is the dependency graph documented in overview.md? [Completeness]
- [ ] CHK-000-011 - Are dependency directions correct (foundation → features)? [Accuracy]
- [ ] CHK-000-012 - Is implementation order derivable from dependencies? [Clarity]

## Clarification Summary

- [ ] CHK-000-013 - Are [NEEDS CLARIFICATION] items catalogued? [Completeness]
- [ ] CHK-000-014 - Is clarification context sufficient for resolution? [Clarity]
- [ ] CHK-000-015 - Are critical clarifications prioritized? [Clarity]

## Migration Scenarios

- [ ] CHK-000-016 - Are data migration requirements identified per domain? [Coverage]
- [ ] CHK-000-017 - Are rollback/recovery scenarios defined? [Edge Cases]
- [ ] CHK-000-018 - Are parallel-run requirements documented (if applicable)? [Coverage]
- [ ] CHK-000-019 - Are cutover criteria specified? [Completeness]

## Legacy Context

- [ ] CHK-000-020 - Are legacy constraints and limitations captured? [Completeness]
- [ ] CHK-000-021 - Are "why it was built this way" rationales documented? [Context]
- [ ] CHK-000-022 - Are technical debt items identified? [Coverage]

## Strategic Alignment

- [ ] CHK-000-023 - Do domain specs align with overview.md summary? [Consistency]
- [ ] CHK-000-024 - Are all domains referenced in the dependency graph? [Completeness]
- [ ] CHK-000-025 - Is coverage report consistent with domain file lists? [Accuracy]

---

## Per-Domain Review Status

| Domain | Checklist | Status | Reviewer |
|--------|-----------|--------|----------|
| {NNN}-re-{name} | [checklist.md]({NNN}-re-{name}/checklist.md) | [ ] Pending | ___ |
| {NNN+1}-re-{name} | [checklist.md]({NNN+1}-re-{name}/checklist.md) | [ ] Pending | ___ |
| ... | ... | ... | ... |

## Aggregate Statistics

| Metric | Value |
|--------|-------|
| Total domains | {count} |
| Total [NEEDS CLARIFICATION] items | {count} |
| File coverage | {percent}% |
| Domains with complete checklists | _/{count} |

---

## Review Summary

| Category | Items | Checked |
|----------|-------|---------|
| Coverage Quality | 3 | _/3 |
| Domain Boundaries | 3 | _/3 |
| Cross-Domain Consistency | 3 | _/3 |
| Dependency Graph | 3 | _/3 |
| Clarification Summary | 3 | _/3 |
| Migration Scenarios | 4 | _/4 |
| Legacy Context | 3 | _/3 |
| Strategic Alignment | 3 | _/3 |
| **Total** | **25** | **_/25** |

**Reviewer**: _______________
**Date**: _______________
**Status**: [ ] Approved for Planning [ ] Needs Revision

---

## Next Steps

After checklist review:

1. Address any unchecked items or document exceptions
2. Resolve critical [NEEDS CLARIFICATION] items
3. Run `/speckit.echelon.re-constitute` to generate strategic artifacts
4. Run `/speckit.echelon.re-retarget` to fill target decisions
```

### Step 6: Display Summary

```text
Quality Checklists Generated
=============================

Per-Domain Checklists:
  ✓ 003-re-core-framework/checklist.md   (17 items)
  ✓ 004-re-data-access/checklist.md      (17 items)
  ✓ 005-re-reference-data/checklist.md   (17 items)
  ...

Summary Checklist:
  ✓ 000-re-overview/checklist.md         (25 items)

Total: {N} domain checklists + 1 summary checklist

Checklist categories:
  - Source Evidence Quality
  - Requirements Completeness
  - Entity Definitions
  - Edge Cases & Error Handling
  - Cross-Domain Consistency
  - Migration Scenarios
  - Legacy Context

Next steps:
  1. Review per-domain checklists with domain experts
  2. Review summary checklist for cross-cutting concerns
  3. Address unchecked items or document exceptions
  4. Proceed to /speckit.echelon.re-constitute
```

## Checklist Philosophy

**"Unit Tests for Requirements"**

These checklists validate the REQUIREMENTS, not the implementation:

- **Completeness**: Are all necessary requirements present?
- **Clarity**: Are requirements unambiguous and specific?
- **Consistency**: Do requirements align with each other?
- **Measurability**: Can requirements be objectively verified?
- **Coverage**: Are all scenarios/edge cases addressed?
- **Traceability**: Are requirements linked to source evidence?

## Customization

The checklist items can be customized in `echelon-re-config.yml` (with optional `local-config.yml` overrides and env via `specify extension config resolve echelon`):

```yaml
rechecklist:
  per_domain_items:
    source_evidence: true
    completeness: true
    entities: true
    edge_cases: true
    clarifications: true
    dependencies: true
  summary_items:
    coverage: true
    boundaries: true
    consistency: true
    dependencies: true
    clarifications: true
    migration: true
    legacy: true
    alignment: true
```

## Integration with Extract

When running `/speckit.echelon.re-extract`, checklists are generated automatically after validation:

```text
extract pipeline:
  reanalyze → respecify → verify/expand → validate → rechecklist → reconstitute
```

The extract summary will include:

```text
Quality Checklists:
  ✓ {N} per-domain checklists generated
  ✓ Summary checklist at 000-re-overview/checklist.md

  Review checklists before proceeding to planning phase.
```

## Notes

- Checklists are non-interactive (standardized for reverse-engineering)
- Per-domain checklists focus on spec quality within the domain
- Summary checklist focuses on cross-domain and migration concerns
- Checklists complement (not replace) the automated `validate` command
- Review is recommended but not blocking for subsequent commands
