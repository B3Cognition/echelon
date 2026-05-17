---
name: speckit.echelon.re-validate
description: "Validate generated specs for quality, auto-resolve ambiguities from code"
behavior:
  execution: isolated
  invocation: automatic
---

# Validate: Quality Check with Auto-Resolution

> **Bash Command Guidelines**: Never use multi-line bash. Chain commands with `&&`. **IMPORTANT**: Do NOT use bash `ls`, `find`, `cat`, `echo`, or `grep` for file exploration - always use the dedicated Glob, Read, and Grep tools instead. Reserve bash only for git commands, `mkdir`, and other system operations.

Validate generated specifications for quality issues and auto-resolve ambiguities by checking source code.

## Purpose

This command runs **after** specs are generated (`respecify` + `verify/expand`) and **before** checklists (`rechecklist`). It:

1. Checks specs for quality issues (ambiguity, duplication, underspecification, inconsistency)
2. Attempts to auto-resolve issues by examining source code (code is truth)
3. **Loops until resolution threshold met** (default 80%) or max iterations reached
4. Updates specs with clarifications where resolvable
5. Flags truly unresolvable items with `[NEEDS CLARIFICATION: ...]`

```text
┌───────────┐   ┌─────────────────┐   ┌───────────────────┐   ┌─────────────┐   ┌───────────────┐
│ respecify │──▶│ verify + expand │──▶│     validate      │──▶│ rechecklist │──▶│ reconstitute  │
└───────────┘   │ (until ≥80%     │   │ (until ≥80%       │   └─────────────┘   └───────────────┘
                │  coverage)      │   │  resolved or max  │
                └─────────────────┘   │  iterations)      │
                                      └─────────┬─────────┘
                                                │
                                      ┌─────────▼─────────┐
                                      │ Resolution Loop:  │
                                      │ 1. Detect issues  │
                                      │ 2. Auto-resolve   │
                                      │ 3. Check rate     │
                                      │ 4. Deeper search  │
                                      │    if below 80%   │
                                      └───────────────────┘
```

## Resolution Loop

The validate command runs iteratively to maximize auto-resolution:

```text
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Iteration 1 │────▶│  Iteration 2 │────▶│  Iteration 3 │
│  Basic scan  │     │  Deep search │     │  Extended    │
│  + resolve   │     │  + resolve   │     │  patterns    │
└──────────────┘     └──────────────┘     └──────────────┘
       │                    │                    │
       ▼                    ▼                    ▼
  Rate: 65%            Rate: 78%            Rate: 85% ✓
  Continue...          Continue...          Threshold met!
```

**Loop termination conditions:**
- Resolution rate ≥ threshold (default 80%)
- Max iterations reached (default 3)
- No new resolutions in last iteration (convergence) — **Precondition**: You may only claim convergence if the current iteration used a deeper strategy than the previous one. Claiming "no new resolutions" in iteration 1 without attempting iteration 2's deeper strategy is invalid.

**Iteration strategies:**
| Iteration | Strategy | Scope |
|-----------|----------|-------|
| 1 | Basic scan | Constants, configs, direct matches |
| 2 | Deep search | Function bodies, test assertions, comments |
| 3 | Extended patterns | Cross-file analysis, naming conventions, related modules |

## Prerequisites

1. reverse-engineered specs exist in `specs/` (e.g., `specs/NNN-re-{domain}/`)
2. Analysis exists at `.specify/echelon/re/analysis.json`
3. Coverage threshold met (run `verify` first)

## User Input

$ARGUMENTS

## Quality Detection Taxonomy

### A. Ambiguity Detection

**Vague qualifiers without metrics:**
- "fast", "scalable", "secure", "intuitive", "robust", "efficient"
- **Auto-resolve**: Search code for actual values (timeouts, limits, thresholds)
- **Example**: "fast response" → search for timeout constants → "response within 500ms"

**Unresolved placeholders:**
- `TODO`, `TBD`, `???`, `[TBD]`, `<placeholder>`
- **Auto-resolve**: Search code for implementation details
- **Flag if unresolvable**: `[NEEDS CLARIFICATION: {placeholder context}]`

### B. Underspecification Detection

**Missing acceptance criteria:**
- User stories without clear success conditions
- **Auto-resolve**: Search tests for assertions, validation rules

**Incomplete entity definitions:**
- Entities missing field types, constraints, relationships
- **Auto-resolve**: Read source class/type definitions

**Missing error handling:**
- Requirements without failure scenarios
- **Auto-resolve**: Search for try/catch, error handlers, exception types

### C. Duplication Detection

**Near-duplicate requirements:**
- Similar requirements across domains
- **Auto-resolve**: Consolidate into shared domain or cross-reference

**Repeated entity definitions:**
- Same entity described in multiple specs
- **Auto-resolve**: Reference primary definition, remove duplicates

### D. Inconsistency Detection

**Terminology drift:**
- Same concept named differently across specs
- **Auto-resolve**: Normalize to canonical term from code

**Conflicting requirements:**
- Contradictory statements about same feature
- **Auto-resolve**: Check code for actual implementation
- **Flag if unresolvable**: `[NEEDS CLARIFICATION: conflicting requirements]`

**Data type mismatches:**
- Field described with different types in different places
- **Auto-resolve**: Check source type definitions

### E. Coverage Gaps

**Requirements without source evidence:**
- Claims not backed by code references
- **Auto-resolve**: Search for supporting code, add references
- **Flag if no evidence**: `[NEEDS CLARIFICATION: no source evidence found]`

**Orphan source references:**
- Code paths not captured in requirements
- **Auto-resolve**: Add missing requirements

## Steps

### Step 1: Load Context and Configuration

```bash
ANALYSIS_FILE=".specify/echelon/re/analysis.json"
OVERVIEW_DIR="specs/000-re-overview"

if [ ! -f "$ANALYSIS_FILE" ]; then
    echo "Error: Analysis file not found"
    exit 1
fi

CONFIG_JSON="$(specify extension config resolve echelon --format json)"
```

Load configuration (or use defaults):

```yaml
# From resolved config (defaults + echelon-re-config.yml + local-config.yml + env)
workflow:
  resolution_threshold: 80    # Target: 80% of findings auto-resolved
  max_validate_iterations: 3  # Max loop iterations
```

Load:

- All domain specs (`specs/NNN-re-{domain}/spec.md`)
- Overview (`specs/000-re-overview/overview.md`)
- Analysis data (`.specify/echelon/re/analysis.json`)

### Step 1.5: Load Structural Intelligence (REQUIRED if available)

Check whether `.specify/echelon/re/codegraph-analysis.json` exists.

**If it exists — read it now. Do not defer this to later steps.**

Extract and name the following for use in Steps 2, 3, and 4:

```
CG.symbols_by_name   = index of symbols[] keyed by name (lowercase) and qualified_name
CG.exported_symbols  = symbols[] where is_exported=true (the public API surface)
CG.index_state       = index_stats.index_state
CG.total_symbols     = length of symbols[]
CG.supported_langs   = keys of language_coverage where value = "supported"
```

Print before Step 2:
```
[CodeGraph] {CG.total_symbols} symbols indexed | public API: {len(CG.exported_symbols)} exported | languages: {CG.supported_langs} | state: {CG.index_state}
```

**If the file does not exist**: set CG = null.

### Step 2: Build Semantic Model

For each domain spec, extract:

```text
Domain Model:
  - domain_id: "001-core-framework"
  - requirements: [FR-001.001, FR-001.002, ...]
  - user_stories: [US-001.1, US-001.2, ...]
  - entities: [{name, fields, relationships}, ...]
  - source_references: [{file, line, context}, ...]
```

Build cross-domain index:
- Terminology map (term → occurrences)
- Entity index (entity → domains)
- Requirement coverage (requirement → source files)

**If CG ≠ null:** augment the semantic model now:
- For each domain spec, scan its requirements for function/class names. Look up each name in `CG.symbols_by_name`. Record as `CG_MATCHED` (found) or `CG_MISSING` (not found in extracted symbols).
- Add to the cross-domain index: `symbol_coverage` = count of requirements with at least one CG_MATCHED symbol ÷ total requirements with named code artifacts.
- Flag any requirement that references a symbol NOT in `CG.exported_symbols` (i.e., non-exported) — this may indicate a missing public API or a spec error.

### Step 3: Run Detection Passes

**MANDATORY**: You MUST execute ALL five detection passes (A through E). Process one detection category at a time to manage context. Skipping a pass is not permitted — each pass detects a distinct category of quality issue.

#### Pass A: Ambiguity Detection

For each spec, scan for:

1. **Vague qualifiers** (fast, scalable, secure, etc.)

   ```text
   Found: "System must be fast" in FR-02.003

   Auto-resolve attempt:
     Search code for: timeout, latency, threshold, milliseconds
     Found: RESPONSE_TIMEOUT = 500 in config/settings.py:42

   Resolution: "System must respond within 500ms"
   ```

2. **Unresolved placeholders**

   ```text
   Found: "Authentication method: TBD" in FR-01.005

   Auto-resolve attempt:
     Search code for: auth, authenticate, login, session, jwt, oauth
     Found: OAuth2 implementation in auth/oauth_handler.py

   Resolution: "Authentication method: OAuth2"
   ```

#### Pass B: Underspecification Detection

For each user story without acceptance criteria:

```text
Found: US-03.2 missing acceptance scenarios

Auto-resolve attempt:
  Search tests for: test_*domain_name*, *_spec.py, *.test.ts
  Found: test_order_validation.py with 5 test cases

Resolution: Extract test assertions as acceptance criteria
  - Given valid order, When submitted, Then order ID returned
  - Given empty cart, When submitted, Then ValidationError raised
```

For each entity with incomplete definition:

```text
Found: Entity "Order" missing field constraints

Auto-resolve attempt:
  Search code for: class Order, interface Order, type Order
  Found: models/order.py:15-45

Resolution: Extract field types and constraints from source
  - id: UUID (required, unique)
  - status: Enum["pending", "confirmed", "shipped"]
  - total: Decimal (required, >= 0)
```

#### Pass C: Duplication Detection

Compare requirements across domains:

```text
Found: Similar requirements
  - FR-01.003: "Validate user input before processing"
  - FR-04.007: "Input validation required before save"

Resolution:
  - Keep FR-01.003 (more specific)
  - Update FR-04.007 to reference: "See FR-01.003 for input validation"
```

#### Pass D: Inconsistency Detection

Check terminology across specs:

```text
Found: Terminology drift
  - 001-core: "Customer" entity
  - 003-billing: "Client" entity
  - Both refer to same concept

Auto-resolve attempt:
  Search code for canonical term
  Found: class Customer in models/, no "Client" class

Resolution: Normalize to "Customer" throughout
```

#### Pass E: Coverage Gaps

For each requirement, verify source evidence:

```text
Found: FR-05.002 has no source reference

Auto-resolve attempt:
  Search for keywords: "export", "report", "generate"
  Found: reports/export_handler.py:78-120

Resolution: Add source reference
  - Source: reports/export_handler.py:78
```

### Step 4: Apply Resolutions and Check Threshold

For each resolved finding:

1. **Update the spec file** with the resolution
2. **Add source evidence** for the resolution
3. **Log the change** in validation report

For each unresolved finding:

1. **Add `[NEEDS CLARIFICATION: ...]` marker** at the location
2. **Include context** about what was searched
3. **Log as requiring human input**

### Step 5: Check Resolution Rate and Loop

```python
# Calculate resolution rate
total_findings = resolved_count + unresolved_count
resolution_rate = (resolved_count / total_findings) * 100 if total_findings > 0 else 100

# Check loop termination conditions
if resolution_rate >= resolution_threshold:
    print(f"✓ Resolution threshold met: {resolution_rate:.1f}% >= {resolution_threshold}%")
    proceed_to_next_step()

elif iteration >= max_iterations:
    print(f"⚠️ Max iterations reached ({max_iterations})")
    print(f"  Resolution rate: {resolution_rate:.1f}% (below {resolution_threshold}% threshold)")
    print(f"  {unresolved_count} items require human input")
    proceed_to_next_step()

elif new_resolutions_this_iteration == 0:
    print(f"⚠️ No new resolutions in iteration {iteration} (convergence)")
    print(f"  Resolution rate: {resolution_rate:.1f}%")
    proceed_to_next_step()

else:
    # Continue to next iteration with deeper strategy
    iteration += 1
    print(f"Resolution rate: {resolution_rate:.1f}% - below threshold, trying deeper analysis...")
    run_iteration(iteration)
```

**Iteration escalation strategies:**

| Iteration | Strategy | What it adds |
|-----------|----------|--------------|
| 1 | **Basic** | Search constants, configs, direct term matches |
| 2 | **Deep** | Search function bodies, test assertions, docstrings |
| 3 | **Extended** | Cross-file analysis, naming patterns, related modules |

```text
Iteration 1 (Basic):
  - Search for: TIMEOUT, MAX_*, MIN_*, *_LIMIT
  - Look in: config/, constants/, settings.*

Iteration 2 (Deep):
  - Search for: function parameters, return types, assertions
  - Look in: tests/, **/*_test.*, **/*.spec.*
  - Extract: Given/When/Then from test names

Iteration 3 (Extended):
  - Search for: similar function names, related modules
  - Look in: entire codebase with relaxed matching
  - Infer: from naming conventions and patterns
```

### Step 6: Generate Validation Report

Output to `specs/000-re-overview/validation-report.md`:

```markdown
# Validation Report

**Generated**: {DATE}
**Specs Validated**: {count}
**Total Findings**: {count}
**Auto-Resolved**: {count}
**Requires Human Input**: {count}

## Summary by Category

| Category | Found | Resolved | Remaining |
|----------|-------|----------|-----------|
| Ambiguity | {n} | {n} | {n} |
| Underspecification | {n} | {n} | {n} |
| Duplication | {n} | {n} | {n} |
| Inconsistency | {n} | {n} | {n} |
| Coverage Gaps | {n} | {n} | {n} |

## Structural Symbol Coverage (CodeGraph)

<!-- Include this section ONLY if CG ≠ null -->
**Only include if `.specify/echelon/re/codegraph-analysis.json` was loaded.**

| Metric | Value |
|--------|-------|
| Total symbols indexed | {CG.total_symbols} |
| Exported (public API) symbols | {len(CG.exported_symbols)} |
| Requirements with matched symbols | {symbol_coverage}% |
| Requirements referencing non-exported symbols | {count} |
| Index state | {CG.index_state} |

### Symbols Not Found in Specs (top 10 by caller count)
List up to 10 symbols from CG.exported_symbols that are NOT referenced by any spec requirement.
These are public API surface points missing from specifications.

| Symbol | Kind | File | Incoming Calls |
|--------|------|------|---------------|
| {qualified_name} | {kind} | {file_path} | {count} |

## Auto-Resolutions Applied

### Ambiguity Fixes

| Location | Original | Resolution | Source |
|----------|----------|------------|--------|
| FR-02.003 | "fast response" | "within 500ms" | config/settings.py:42 |

### Underspecification Fixes

| Location | Issue | Resolution | Source |
|----------|-------|------------|--------|
| US-03.2 | Missing criteria | Added 5 scenarios | test_order.py |

### Terminology Normalizations

| Original | Normalized | Occurrences Fixed |
|----------|------------|-------------------|
| Client | Customer | 12 |

## Items Requiring Human Input

| ID | Location | Issue | Context | Searched |
|----|----------|-------|---------|----------|
| H1 | FR-01.005 | Auth method unclear | OAuth2 found but not confirmed | auth/*.py |
| H2 | US-04.3 | Business rule unknown | No test coverage | tests/*.py |

## Quality Metrics

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Requirements with source evidence | {n}% | {n}% | +{n}% |
| User stories with acceptance criteria | {n}% | {n}% | +{n}% |
| Entity definitions complete | {n}% | {n}% | +{n}% |
| Ambiguous terms | {n} | {n} | -{n} |

## Next Steps

{If remaining items > 0}:
  - Review [NEEDS CLARIFICATION] markers in specs
  - Provide decisions for H1, H2, ... items above
  - Re-run /speckit.echelon.re-validate after updates

{If remaining items = 0}:
  - All specs validated successfully
  - Proceed to /speckit.echelon.re-constitute
```

### Step 7: Display Summary

```text
Validation Complete
===================

Iterations: {iteration_count}/{max_iterations}
Resolution rate: {resolution_rate}% (threshold: {resolution_threshold}%)

Specs validated: {count}
Total findings: {count}

Auto-resolved: {resolved_count}
  - Ambiguities fixed: {n}
  - Underspecifications filled: {n}
  - Duplications consolidated: {n}
  - Inconsistencies normalized: {n}
  - Coverage gaps filled: {n}

Resolution by iteration:
  - Iteration 1 (Basic):    {n} resolved
  - Iteration 2 (Deep):     {n} resolved
  - Iteration 3 (Extended): {n} resolved

Requires human input: {remaining_count}
  - See [NEEDS CLARIFICATION] markers in specs
  - Review validation-report.md for details

Quality improvement:
  - Source evidence: {before}% → {after}%
  - Acceptance criteria: {before}% → {after}%
  - Complete entities: {before}% → {after}%

{If resolution_rate >= threshold}:
  ✓ Resolution threshold met ({resolution_rate}% >= {threshold}%)
  Ready for rechecklist

{If resolution_rate < threshold AND iteration = max}:
  ⚠️ Resolution rate {resolution_rate}% below threshold
  {remaining_count} items require human input
  Proceeding to rechecklist (will include unresolved items)

Next: /speckit.echelon.re-checklist
```

## Auto-Resolution Strategies

### Strategy 1: Code Search

When finding is ambiguous, search source code:

```text
Search Order:
1. Exact term match in constants/config
2. Related terms in function signatures
3. Test assertions for behavior
4. Comments/docstrings for intent
```

### Strategy 2: Test Mining

Extract acceptance criteria from tests:

```text
Test Pattern → Requirement Pattern:
- test_X_when_Y_then_Z → Given Y, When X, Then Z
- @pytest.mark.parametrize → Multiple scenarios
- expect(...).toBe(...) → Specific acceptance value
```

### Strategy 3: Type Inference

Extract entity definitions from types:

```text
Source → Spec Mapping:
- TypeScript interface → Entity with typed fields
- Python dataclass → Entity with typed fields
- SQL CREATE TABLE → Entity with constraints
- Pydantic model → Entity with validation rules
```

### Strategy 4: Error Pattern Mining

Extract failure scenarios:

```text
Error Pattern → Edge Case:
- try/except blocks → Failure scenarios
- throw new Error → Error conditions
- validation rules → Invalid input cases
- HTTP status codes → API error responses
```

## Configuration

Validate behavior can be configured in `echelon-re-config.yml`:

```yaml
validate:
  auto_resolve: true           # Attempt auto-resolution
  update_specs: true           # Apply resolutions to spec files
  require_confirmation: false  # Prompt before each update
  max_findings: 100            # Stop after N findings
  categories:
    ambiguity: true
    underspecification: true
    duplication: true
    inconsistency: true
    coverage_gaps: true
```

## Notes

- Validate is **non-destructive by default** - creates backup before updating
- Auto-resolutions include source references for traceability
- `[NEEDS CLARIFICATION]` markers are searchable across all specs
- Run validate multiple times as specs are refined
- Integrate with `/speckit.analyze` after plan/tasks generation for full consistency check
