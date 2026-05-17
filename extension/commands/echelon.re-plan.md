---
name: speckit.echelon.re-plan
description: "Generate per-domain plan.md files from specifications and constitution"
behavior:
  execution: isolated
  invocation: automatic
---

# Generate Per-Domain Implementation Plans

> **Bash Command Guidelines**: Never use multi-line bash. Chain commands with `&&`. **IMPORTANT**: Do NOT use bash `ls`, `find`, `cat`, `echo`, or `grep` for file exploration - always use the dedicated Glob, Read, and Grep tools instead. Reserve bash only for git commands, `mkdir`, and other system operations.

Create `plan.md` files for each domain specification, using the constitution and strategic artifacts for guidance.

## Purpose

This command generates **per-domain implementation plans**:

- Each domain (`NNN-re-{domain}/`) gets its own `plan.md`
- Plans are informed by the constitution (target stack, principles)
- Plans reference the strategic artifacts (strategy, risks, gaps)
- Enables parallel team work on different domains

## Prerequisites

1. Domain specifications exist: `specs/NNN-re-{domain}/spec.md`
2. Constitution exists: `specs/000-re-overview/constitution.md`
3. Strategic artifacts exist (recommended):
   - `migration-strategy.md` - for 6R recommendation
   - `risk-matrix.md` - for domain-specific risks
   - `gap-analysis.md` - for skills/infrastructure needs

## User Input

$ARGUMENTS

## Output Structure

```text
specs/
├── 000-re-overview/                  # Shared strategic artifacts
│   ├── constitution.md               # Target stack, principles
│   ├── migration-strategy.md         # 6R analysis, waves
│   ├── risk-matrix.md                # Risk assessment
│   └── gap-analysis.md               # Gaps to address
│
├── {NNN}-re-core-framework/
│   ├── spec.md                       # Input: what to build
│   └── plan.md                       # OUTPUT: how to build it
├── {NNN+1}-re-data-access/
│   ├── spec.md
│   └── plan.md                       # OUTPUT
├── {NNN+2}-re-reference-data/
│   ├── spec.md
│   └── plan.md                       # OUTPUT
└── ...
```

## Steps

### Step 1: Locate Artifacts

```bash
OVERVIEW_DIR="specs/000-re-overview"
CONSTITUTION="$OVERVIEW_DIR/constitution.md"
STRATEGY="$OVERVIEW_DIR/migration-strategy.md"

if [ ! -f "$CONSTITUTION" ]; then
    echo "Error: Constitution not found at $CONSTITUTION"
    echo "Run /speckit.echelon.re-constitute first"
    exit 1
fi

# Find all reverse-engineered domain directories
DOMAINS=$(ls -d specs/[0-9][0-9][0-9]-re-*/ 2>/dev/null)

if [ -z "$DOMAINS" ]; then
    echo "Error: No reverse-engineered domain specifications found"
    echo "Run /speckit.echelon.re-specify first"
    exit 1
fi

echo "Found $(echo "$DOMAINS" | wc -l) reverse-engineered domains to process"
```

### Step 2: Load Shared Context

Read once and cache for all domains:

**From constitution.md**:
- Target technology stack
- Architectural principles
- Coding standards
- Quality gates

**From migration-strategy.md** (MUST load if file exists — verify with Glob before skipping):
- 6R recommendation per domain
- Migration wave assignment
- Rollback strategy

**From risk-matrix.md** (MUST load if file exists — verify with Glob before skipping):
- Domain-specific risks
- Mitigation strategies

**From gap-analysis.md** (MUST load if file exists — verify with Glob before skipping):
- Skills gaps affecting this domain
- Infrastructure dependencies

### Step 2.5: Load Structural Intelligence (REQUIRED if available)

Check whether `.specify/echelon/re/codegraph-analysis.json` exists.

**If it exists — read it now and extract the following before Step 3. Do not skip.**

```
CG.impact_map     = for each symbol in impact_radius[]: { symbol, affected_count: len(affected[]), depth }
                    sorted by affected_count descending
CG.top_impact     = CG.impact_map[:20]  (top 20 highest-impact symbols)
CG.coupled_pairs  = call_graph[] entries where caller file ≠ callee file, grouped by file pair,
                    sorted by pair call count descending (top file pairs = tightly coupled)
CG.dep_order      = relationships[] where kind in ["extends","implements","imports"],
                    as edges: target must be implemented before source
CG.index_state    = index_stats.index_state
```

Print before Step 3:
```
[CodeGraph] Impact map: {len(CG.impact_map)} symbols | Top coupled pair: {CG.coupled_pairs[0]} | Dep edges: {len(CG.dep_order)} | state: {CG.index_state}
```

**If the file does not exist**: set CG = null.

### Step 3: Generate Plan for Each Domain

For each domain directory:

```python
for domain_dir in domains:
    domain_name = os.path.basename(domain_dir)  # e.g., "003-re-core-framework"
    spec_file = f"{domain_dir}/spec.md"
    plan_file = f"{domain_dir}/plan.md"

    # Load domain-specific context
    spec = read_file(spec_file)
    six_r = get_6r_recommendation(domain_name, strategy)
    risks = get_domain_risks(domain_name, risk_matrix)
    gaps = get_domain_gaps(domain_name, gap_analysis)

    # Generate plan
    plan = generate_domain_plan(
        domain=domain_name,
        spec=spec,
        constitution=constitution,
        six_r=six_r,
        risks=risks,
        gaps=gaps
    )

    # Save
    write_file(plan_file, plan)
    print(f"✓ Generated {plan_file}")
```

### Step 4: Domain Plan Structure

Each domain `plan.md` follows this structure:

```markdown
# Implementation Plan: {Domain Name}

**Domain**: {NNN}-{domain-name}
**Created**: {DATE}
**Status**: Draft
**Spec**: [spec.md](spec.md)
**Constitution**: [constitution.md](../constitution.md)

---

## 1. Summary

### What We're Building

{Brief description from spec overview}

### 6R Recommendation

**{Refactor/Rebuild/Replatform/etc.}**: {rationale from migration-strategy.md}

### Primary Requirement

{Most important user story or requirement from spec}

### Technical Approach

{High-level approach based on constitution principles}

---

## 2. Technical Context

### Target Stack (from Constitution)

| Component | Technology | Notes |
|-----------|------------|-------|
| Language  | {from constitution} | {domain-specific notes} |
| Framework | {from constitution} | {domain-specific notes} |
| Database  | {from constitution} | {domain-specific notes} |

### Dependencies

| Dependency | Type | Status |
|------------|------|--------|
| {domain NNN} | Upstream | {ready/in-progress/blocked} |
| {library} | External | {available/needs setup} |

### Domain-Specific Risks

| Risk | Score | Mitigation |
|------|-------|------------|
| {from risk-matrix.md} | {L×I} | {strategy} |

---

## 3. Architecture

### Component Design

{How this domain's components are structured}

### Integration Points

| Integration | With | Protocol | Notes |
|-------------|------|----------|-------|
| {integration} | {domain/system} | {REST/event/etc.} | {notes} |

### Data Model

{Key entities and relationships for this domain}

---

## 4. Implementation Approach

**If CG ≠ null:** Before writing phases, derive task ordering from structural data:
1. From `CG.dep_order`: any symbol in this domain that appears as a target of `extends`/`implements`/`imports` edges MUST be implemented in Phase 1.
2. From `CG.top_impact`: symbols in this domain that appear in `CG.top_impact` (high affected_count) should be implemented before symbols that depend on them.
3. From `CG.coupled_pairs`: if this domain is tightly coupled with another domain (appears in top coupled pairs), flag the integration point in Phase 3.

**If CG = null:** use standard dependency ordering below.

### Phase 1: Foundation

- Set up domain structure
- Implement core interfaces
- **If CG ≠ null**: implement all symbols from this domain that appear as `dep_order` targets first
- **Exit Criteria**: {criteria}

### Phase 2: Core Logic

- Implement main functionality from spec
- **If CG ≠ null**: prioritize symbols from `CG.top_impact` that belong to this domain (high downstream impact)
- Unit tests for each component
- **Exit Criteria**: {criteria}

### Phase 3: Integration

- Connect to dependent domains
- Integration tests
- **Exit Criteria**: {criteria}

### Phase 4: Polish

- Error handling
- Logging and monitoring
- Documentation
- **Exit Criteria**: {criteria}

---

## 5. Testing Strategy

### Unit Tests

- Target coverage: {from constitution}%
- Key areas: {list}

### Integration Tests

- Test points: {list}

### Acceptance Criteria

From spec user stories:

- [ ] US-{NNN}.1 - {scenario}
- [ ] US-{NNN}.2 - {scenario}

---

## 6. Gaps to Address

From gap-analysis.md:

| Gap | Category | Action |
|-----|----------|--------|
| {gap} | Skills/Infrastructure/Feature | {action} |

---

## 7. Open Questions

- [ ] {question 1}
- [ ] {question 2}

---

## Related

- [Specification](spec.md)
- [Constitution](../constitution.md)
- [Migration Strategy](../migration-strategy.md)
- [Risk Matrix](../risk-matrix.md)
```

### Step 5: Display Summary

```text
Per-Domain Plans Generated
===========================

Generated plans for {N} domains:
  ✓ 001-core-framework/plan.md
  ✓ 002-data-access/plan.md
  ✓ 003-reference-data/plan.md
  ...

Each plan includes:
  - 6R recommendation (from migration-strategy.md)
  - Target stack (from constitution.md)
  - Domain-specific risks (from risk-matrix.md)
  - Gaps to address (from gap-analysis.md)
  - Phased implementation approach

Next steps:
  1. Review each domain plan
  2. Fill in Open Questions sections
  3. Run /speckit.echelon.re-tasks (generates per-domain tasks)

Implementation order (from dependency graph):
  Wave 1: 001-core-framework, 002-data-access
  Wave 2: 003-reference-data, 004-business-logic
  Wave 3: 005-ui-components
  ...
```

## Integration with Spec-Kit

Each domain's `plan.md` is compatible with:

- `/speckit.tasks` - Can run on individual domain
- `/speckit.implement` - Guided implementation
- `/speckit.clarify` - Identify underspecified areas

## Parallel Development

With per-domain plans:

1. **Wave 1 teams** can start on foundation domains
2. **Wave 2 teams** can plan ahead using their specs
3. **All teams** share the same constitution (consistency)
4. **Dependency tracking** is explicit in each plan

## Notes

- Plans are generated in dependency order
- Each plan references the shared constitution
- Blocked dependencies are flagged
- Plans can be regenerated without losing manual edits (TODO sections preserved)
