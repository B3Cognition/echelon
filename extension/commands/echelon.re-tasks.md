---
name: speckit.echelon.re-tasks
description: "Generate per-domain tasks.md files from specifications and plans"
behavior:
  execution: isolated
  invocation: automatic
---

# Generate Per-Domain Task Breakdowns

> **Bash Command Guidelines**: Never use multi-line bash. Chain commands with `&&`. **IMPORTANT**: Do NOT use bash `ls`, `find`, `cat`, `echo`, or `grep` for file exploration - always use the dedicated Glob, Read, and Grep tools instead. Reserve bash only for git commands, `mkdir`, and other system operations.

Create `tasks.md` files for each domain, breaking down the plan into actionable tasks.

## Purpose

This command generates **per-domain task breakdowns**:

- Each domain gets its own `tasks.md` alongside `spec.md` and `plan.md`
- Tasks follow the spec-kit template format
- Tasks are ordered by dependency within the domain
- Enables `/speckit.implement` and `/speckit.taskstoissues` per domain

## Prerequisites

1. Domain specifications exist: `specs/NNN-re-{domain}/spec.md`
2. Domain plans exist: `specs/NNN-re-{domain}/plan.md`
3. Constitution exists: `specs/000-re-overview/constitution.md`

## User Input

$ARGUMENTS

## Output Structure

```text
specs/
├── 000-re-overview/                  # Shared strategic artifacts
│   └── constitution.md               # Coding standards
│
├── {NNN}-re-core-framework/
│   ├── spec.md                       # What to build
│   ├── plan.md                       # How to build it
│   └── tasks.md                      # OUTPUT: Task breakdown
├── {NNN+1}-re-data-access/
│   ├── spec.md
│   ├── plan.md
│   └── tasks.md                      # OUTPUT
└── ...
```

## Steps

### Step 1: Locate Artifacts

```bash
OVERVIEW_DIR="specs/000-re-overview"
CONSTITUTION="$OVERVIEW_DIR/constitution.md"
TASKS_TEMPLATE=".specify/templates/tasks-template.md"

if [ ! -f "$CONSTITUTION" ]; then
    echo "Error: Constitution not found at $CONSTITUTION"
    exit 1
fi

# Find all migration domain directories with plans
DOMAINS=$(ls -d specs/[0-9][0-9][0-9]-re-*/ 2>/dev/null)

MISSING_PLANS=0
for domain in $DOMAINS; do
    if [ ! -f "$domain/plan.md" ]; then
        echo "Error: No plan.md in $domain"
        MISSING_PLANS=$((MISSING_PLANS + 1))
    fi
done

if [ "$MISSING_PLANS" -gt 0 ]; then
    echo "Error: $MISSING_PLANS domain(s) missing plan.md"
    echo "Run /speckit.echelon.re-plan first to generate plans"
    exit 1
fi
```

### Step 2: Load Shared Context

**From constitution.md**:

- Coding standards (for task descriptions)
- Quality gates (for checkpoint criteria)
- Testing requirements (for test tasks)

**From tasks-template.md**:

- Task format with IDs and dependencies
- Checkpoint structure
- Parallel-safe marking

### Step 3: Generate Tasks for Each Domain

For each domain directory with spec.md and plan.md:

```python
for domain_dir in domains:
    domain_name = os.path.basename(domain_dir)
    domain_num = domain_name.split('-')[0]  # e.g., "001"

    spec = read_file(f"{domain_dir}/spec.md")
    plan = read_file(f"{domain_dir}/plan.md")

    tasks = generate_domain_tasks(
        domain=domain_name,
        domain_num=domain_num,
        spec=spec,
        plan=plan,
        constitution=constitution
    )

    write_file(f"{domain_dir}/tasks.md", tasks)
    print(f"✓ Generated {domain_dir}/tasks.md")
```

### Step 4: Domain Tasks Structure

Each domain `tasks.md` follows this structure:

```markdown
# Tasks: {Domain Name}

**Domain**: {NNN}-{domain-name}
**Created**: {DATE}
**Spec**: [spec.md](spec.md)
**Plan**: [plan.md](plan.md)

---

## Task Format

- `[D.P.S]` = Domain.Phase.Sequence (e.g., `[001.1.1]`)
- `→ [D.P.S]` = Depends on task
- `⚡ Parallel` = Can run alongside other parallel tasks
- `🔒 Sequential` = Must complete before next

---

## Phase 1: Foundation

### [001.1.1] Set up domain structure 🔒

**Description**: Create directory structure and initial files for {domain}

**Acceptance**:
- [ ] Directory structure matches plan
- [ ] Base interfaces defined
- [ ] Initial tests scaffold in place

**Effort**: S

---

### [001.1.2] Implement core interfaces → [001.1.1] ⚡

**Description**: Define TypeScript/Java/etc. interfaces for domain entities

**Acceptance**:
- [ ] All entities from spec have interfaces
- [ ] Interfaces follow constitution naming standards
- [ ] JSDoc/JavaDoc comments added

**Effort**: M

---

### [001.1.3] Set up database schema → [001.1.1] ⚡

**Description**: Create migration files for domain tables

**Acceptance**:
- [ ] Migration files created
- [ ] Indexes defined per plan
- [ ] Rollback tested

**Effort**: M

---

## ✓ Checkpoint: Foundation Complete

**Verify before continuing**:
- [ ] All Phase 1 tasks complete
- [ ] Tests passing
- [ ] Code review approved

---

## Phase 2: Core Implementation

### [001.2.1] Implement {Entity}Service → [001.1.2] 🔒

**Description**: Core service logic for {entity} from spec US-001.1

**Links**: US-001.1

**Acceptance**:
- [ ] CRUD operations implemented
- [ ] Business rules from spec enforced
- [ ] Unit tests at {constitution.coverage}% coverage

**Effort**: L

---

### [001.2.2] Implement {Entity}Repository → [001.1.3], [001.2.1] 🔒

**Description**: Data access layer for {entity}

**Acceptance**:
- [ ] Repository pattern implemented
- [ ] Queries optimized
- [ ] Integration tests passing

**Effort**: M

---

[Continue for each user story/requirement from spec...]

---

## ✓ Checkpoint: Core Implementation Complete

**Verify before continuing**:
- [ ] All user stories from spec addressed
- [ ] Coverage meets constitution threshold
- [ ] No critical issues open

---

## Phase 3: Integration

### [001.3.1] Integrate with {upstream domain} → [001.2.x] 🔒

**Description**: Connect to {002-data-access} services

**Acceptance**:
- [ ] API calls working
- [ ] Error handling for upstream failures
- [ ] Integration tests passing

**Effort**: M

---

## ✓ Checkpoint: Integration Complete

**Verify before continuing**:
- [ ] Cross-domain integration tested
- [ ] Performance acceptable
- [ ] Monitoring in place

---

## Phase 4: Polish

### [001.4.1] Add comprehensive error handling ⚡

**Acceptance**:
- [ ] All error paths handled
- [ ] User-friendly error messages
- [ ] Errors logged appropriately

**Effort**: M

---

### [001.4.2] Add logging and monitoring ⚡

**Acceptance**:
- [ ] Key operations logged
- [ ] Metrics exposed
- [ ] Alerts configured

**Effort**: S

---

### [001.4.3] Documentation 🔒

**Acceptance**:
- [ ] API documentation complete
- [ ] README updated
- [ ] Architecture decision notes

**Effort**: S

---

## ✓ Final Checkpoint: Domain Complete

**Verify**:
- [ ] All tasks complete
- [ ] All tests passing
- [ ] Documentation complete
- [ ] Ready for next wave domains

---

## Summary

| Phase | Tasks | Effort |
|-------|-------|--------|
| 1. Foundation | {count} | {total} |
| 2. Core | {count} | {total} |
| 3. Integration | {count} | {total} |
| 4. Polish | {count} | {total} |
| **Total** | {count} | {total} |

**Critical Path**: [001.1.1] → [001.1.2] → [001.2.1] → [001.2.2] → [001.3.1]

---

## Cross-Domain Dependencies

| This Domain Needs | From Domain | Status |
|-------------------|-------------|--------|
| {service/data} | {NNN-domain} | {ready/in-progress/blocked} |

| Other Domains Need | From This Domain |
|--------------------|------------------|
| {service/data} | {NNN-domain} |
```

### Step 5: Task ID Convention

Task IDs follow the pattern `[DDD.P.S]`:

- **DDD**: Domain number (001, 002, etc.)
- **P**: Phase number (1-4 typically)
- **S**: Sequence within phase

Examples:
- `[001.1.1]` - Domain 01, Phase 1, Task 1
- `[003.2.4]` - Domain 03, Phase 2, Task 4

This enables:
- Cross-domain dependency references
- Clear task ordering
- Easy filtering by domain/phase

### Step 6: Display Summary

```text
Per-Domain Tasks Generated
===========================

Generated tasks for {N} domains:
  ✓ 001-core-framework/tasks.md   ({X} tasks)
  ✓ 002-data-access/tasks.md      ({Y} tasks)
  ✓ 003-reference-data/tasks.md   ({Z} tasks)
  ...

Total: {total} tasks across {N} domains

Task breakdown:
  - Phase 1 (Foundation): {count} tasks
  - Phase 2 (Core): {count} tasks
  - Phase 3 (Integration): {count} tasks
  - Phase 4 (Polish): {count} tasks

Next steps:
  1. Review each domain's tasks.md
  2. Adjust effort estimates
  3. Use /speckit.taskstoissues to create GitHub issues
  4. Use /speckit.implement to start implementation

Cross-domain dependencies identified:
  - 002-data-access depends on 001-core-framework
  - 003-reference-data depends on 002-data-access
  ...
```

## Integration with Spec-Kit

Each domain's `tasks.md` is compatible with:

| Command | Usage |
|---------|-------|
| `/speckit.implement` | Run on domain folder for guided implementation |
| `/speckit.taskstoissues` | Create GitHub issues from domain tasks |
| `/speckit.analyze` | Validate spec/plan/tasks consistency |

### Creating Issues Per Domain

```bash
# Create issues for one domain
cd specs/project-migration/001-core-framework
/speckit.taskstoissues

# Or specify domain
/speckit.taskstoissues --path specs/project-migration/001-core-framework
```

## Effort Sizing

| Size | Description | Typical Duration |
|------|-------------|------------------|
| XS | Trivial change | < 1 hour |
| S | Small task | 1-4 hours |
| M | Medium task | 4-8 hours |
| L | Large task | 1-2 days |
| XL | Very large | 3-5 days |

## Notes

- Tasks are derived from plan phases and spec user stories
- Each user story should map to at least one task
- Checkpoints ensure quality gates from constitution
- Cross-domain dependencies are tracked explicitly
- Effort estimates are initial - adjust based on team velocity

## Post-Completion (Optional)

After retasks completes, you may invoke `speckit.analyze` for consistency analysis across generated spec/plan/tasks.
