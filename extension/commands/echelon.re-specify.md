---
name: speckit.echelon.re-specify
description: "Synthesize multiple detailed specifications from analysis data"
behavior:
  execution: isolated
  invocation: automatic
---

# Generate Specifications from Analysis

> **Bash Command Guidelines**: Never use multi-line bash. Chain commands with `&&`. **IMPORTANT**: Do NOT use bash `ls`, `find`, `cat`, `echo`, or `grep` for file exploration - always use the dedicated Glob, Read, and Grep tools instead. Reserve bash only for git commands, `mkdir`, and other system operations.

Synthesize **multiple detailed specifications** from the extracted analysis data, organized by functional domain and ordered by implementation dependency.

## Purpose

This command reads the analysis.json created by `/speckit.echelon.re-analyze` and generates:

1. **Overview document** (`specs/000-re-overview/overview.md`) - migration summary with dependency graph
2. **Domain specifications** (`specs/NNN-re-{domain}/spec.md`) - detailed specs for each functional area
3. **Auto-numbered from highest existing** - detects existing specs and continues numbering
4. **Ordered by dependency** - foundational components first, high-level features last

## Prerequisites

1. Analysis has been run: `.specify/echelon/re/analysis.json` exists
2. Spec-kit is initialized in the project (`.specify/` directory exists)

## User Input

$ARGUMENTS

## Output Structure

Specs are created directly in `specs/` folder, compatible with existing spec-kit specs.

```text
specs/
├── {existing specs...}               # Pre-existing specs (untouched)
│
├── 000-re-overview/                  # Strategic overview (fixed ID 000)
│   ├── overview.md                   # Migration summary, dependency graph
│   └── traceability.md               # Source-to-spec mapping
│
├── {start_id}-re-{domain}/           # Numbered from highest existing + 1
│   └── spec.md                       # Detailed spec with 5-10 user stories
├── {start_id+1}-re-{domain}/
│   └── spec.md
└── ...
```

**Naming convention**: All reverse-engineered specs use `NNN-re-{domain}` format.

## Steps

### Step 1: Verify Prerequisites

```bash
ANALYSIS_FILE=".specify/echelon/re/analysis.json"
MANIFEST_FILE=".specify/echelon/re/repos-manifest.json"
SPEC_TEMPLATE=".specify/templates/spec-template.md"

# Check manifest first to determine mode
if [ -f "$MANIFEST_FILE" ]; then
    REPO_COUNT=$(jq '.repo_count' "$MANIFEST_FILE")
    echo "Found manifest: $REPO_COUNT repo(s)"
fi

# Validate analysis exists (aggregate analysis.json is always generated)
if [ ! -f "$ANALYSIS_FILE" ]; then
    echo "Error: Analysis file not found at $ANALYSIS_FILE"
    echo "Run /speckit.echelon.re-analyze first"
    exit 1
fi
```

### Step 1.5: Polyrepo Detection

Check for `.specify/echelon/re/repos-manifest.json`:

- If the file **does not exist** or `repo_count == 1` — proceed with single-repo flow.
- If `repo_count > 1` — activate multi-repo processing:

  1. **Process each repo independently**: For each repo listed in `repos-manifest.json`, read its `.specify/echelon/re/{repo-name}/analysis.json` and identify its functional domains using the same heuristics as the single-repo flow. **Per-repo depth overrides:** Resolve config once with `specify extension config resolve echelon --format json` and check `polyrepo.repos.{repo-name}.depth.level`. If present, use that depth level for this repo instead of top-level `depth.level`. This allows GOLDDIGGER to set full depth for small repos while keeping signatures depth for large ones.

  2. **Generate per-repo specs** with repo-prefixed IDs: `NNN-re-{repo}-{domain}`. Example:
     - `005-re-payments-core-model/spec.md`
     - `006-re-payments-data-access/spec.md`
     - `007-re-inventory-api-layer/spec.md`

  3. **Generate cross-repo overview**: After processing all repos, create `specs/000-re-overview/cross-repo-map.md` from `.specify/echelon/re/cross-repo.json`. This file documents:
     - Cross-repo dependency edges (which repo calls which)
     - Shared libraries and their consumers
     - Integration points and API contracts between repos

  4. **Add "Repository Map" section** to `specs/000-re-overview/overview.md`:

     ```markdown
     ## Repository Map

     | Repo | Domains | Files | Key Dependencies |
     |------|---------|-------|-----------------|
     | {repo-a} | {N} | {count} | {repo-b}, {shared-lib} |
     | {repo-b} | {N} | {count} | {shared-lib} |
     ...

     Cross-repo integration points: {N}
     See: [cross-repo-map.md](cross-repo-map.md)
     ```

### Step 2: Load Configuration

Resolve depth configuration using `specify extension config resolve echelon --format json` (or use built-in defaults):

```yaml
depth:
  level: signatures  # metadata, signatures, logic, full
  max_lines_per_file: 500
  priority_patterns:
    - "**/main.*"
    - "**/*Service.*"
    - "**/*Controller.*"
```

**Depth Level Determines Analysis Richness:**

| Level | Source Code Reading | What Gets Extracted |
|-------|---------------------|---------------------|
| `metadata` | None | File structure, dependencies, git history only |
| `signatures` | Declarations only | Function/method signatures, class interfaces, types |
| `logic` | Key functions | Business logic, validation rules, error handling |
| `full` | Complete files | Full data flow, all edge cases, test assertions |

Display current depth:

```text
Analysis depth: {level}
Max lines per file: {max_lines_per_file}
```

### Step 3: Load Analysis Data

Read `.specify/echelon/re/analysis.json` to extract:

- `metadata` - codebase size (total_files, total_lines)
- `structure.file_counts` - dominant languages/tech stack
- `structure.entry_points` - main files to examine
- `dependencies` - external packages and their purposes
- `git_history.commits` - recent development activity
- `git_history.hotspots` - frequently changed files (core functionality)
- `configs` - CI/CD, Docker, infrastructure

### Step 3.5: Load Structural Intelligence (REQUIRED if available)

Check whether `.specify/echelon/re/codegraph-analysis.json` exists.

**If it exists — you MUST read it and extract the following before Step 4. Do not skip this step.**

Read the file and produce a named summary called **CG** for use in Step 4 and Step 5:

```
CG.hub_functions     = symbols in call_graph[] with 3+ unique callers (sort by incoming call count desc)
CG.cross_file_pairs  = call_graph[] entries where caller file_path ≠ callee file_path
CG.modules           = group symbols[] by file_path, sorted by symbol count desc (top 20 files)
CG.inheritance       = type_hierarchy[] entries (child → parent relationships)
CG.domain_clusters   = for each file in CG.modules: list all qualified_names, count outgoing cross-file calls
CG.index_state       = index_stats.index_state ("ready" | "degraded")
CG.total_symbols     = index_stats.total_symbols (or length of symbols[])
```

Print a one-line summary before Step 4:
```
[CodeGraph] {CG.total_symbols} symbols | {len(CG.cross_file_pairs)} cross-file calls | {len(CG.hub_functions)} hub functions | state: {CG.index_state}
```

If `CG.index_state` is `"degraded"`: note that structural data covers less than 50% of files — treat as supplementary signal only.

**If the file does not exist**: set CG = null and proceed with directory-only analysis in Step 4.

### Step 4: Identify Functional Domains

**If CG ≠ null (CodeGraph data available):** Use CG as the primary signal for domain boundaries. Directory structure is a secondary confirmation only.

1. **From CG.hub_functions**: Each hub function (3+ callers) is likely a domain API boundary. Group its callers by file — files that call the same hub are likely in the same domain.
2. **From CG.cross_file_pairs**: Compute call density between file pairs. File pairs with 5+ mutual cross-file calls belong in the same domain.
3. **From CG.inheritance**: Classes sharing a common ancestor (same parent in type_hierarchy[]) belong in the same domain.
4. **From CG.domain_clusters**: Files with the most symbols are likely domain cores — name domains after these files' directories.
5. Cross-confirm with directory structure below — if CG groupings disagree with directory names, note the discrepancy in the spec.

**If CG = null:** proceed with directory and pattern analysis only:

**Directory-based domains:**

- `models/`, `entities/`, `schema/` → Data Model domain
- `db/`, `database/`, `persistence/` → Data Access domain
- `auth/`, `security/`, `identity/` → Authentication domain
- `api/`, `routes/`, `controllers/`, `handlers/` → API Layer domain
- `services/`, `business/`, `core/` → Business Logic domain
- `ui/`, `views/`, `forms/`, `components/` → User Interface domain
- `utils/`, `common/`, `shared/` → Utilities domain
- `tests/`, `spec/` → (used for extraction, not a domain)

**Pattern-based domains:**

- Files with `*Form*`, `*View*`, `*Screen*` → UI components
- Files with `*Service*`, `*Manager*`, `*Handler*` → Business logic
- Files with `*Repo*`, `*DAO*`, `*Store*` → Data access
- Files with `*Export*`, `*Import*`, `*Report*` → Integration/Reporting

**Language-specific patterns:**

- Delphi: `.dfm`/`.fmx` files indicate forms, `*Obj.pas` indicate business objects
- TypeScript/JS: Look at `package.json` workspaces, barrel exports
- Python: Look at `__init__.py` exports, module structure
- Go: Package directories with related functionality

### Step 5: Determine Domain Dependencies

**If CG ≠ null:** derive domain dependencies directly from CG.cross_file_pairs — if domain A's files call domain B's functions, A depends on B. This is more reliable than import analysis.

**If CG = null:** use import analysis:

1. **Import analysis** - which domains import from which
2. **Entity relationships** - which domains reference shared entities
3. **Call flow** - entry points → services → data access

Create dependency ordering (topological sort):

```text
Level 1 (Foundation):
  - Core Data Model (entities, types, constants)
  - Configuration/Environment

Level 2 (Infrastructure):
  - Data Access Layer (database, persistence)
  - External Integrations (APIs, services)

Level 3 (Business Logic):
  - Domain Services
  - Business Rules

Level 4 (Application):
  - API/Controllers
  - User Interface
  - Workflows

Level 5 (Output):
  - Reporting
  - Export/Import
  - Analytics
```

### Step 6: Generate Overview Document

Create `000-overview.md` containing:

```markdown
# {Project Name} Migration Overview

**Generated**: {DATE}
**Source**: {original tech stack}
**Target**: [NEEDS CLARIFICATION: target stack]

## Migration Scope

- **Total Source Files**: {count}
- **Total Lines of Code**: {count}
- **Identified Domains**: {count}
- **Estimated Specifications**: {count}

## Dependency Graph

{Mermaid or ASCII diagram showing domain dependencies}

## Domain Summary

| # | Domain | Purpose | Files | Dependencies |
|---|--------|---------|-------|--------------|
| 001 | {name} | {brief purpose} | {count} | None |
| 002 | {name} | {brief purpose} | {count} | 001 |
...

## Implementation Order

Recommended implementation sequence based on dependencies:

### Phase 1: Foundation
- 001-{domain}: {why first}
- 002-{domain}: {why early}

### Phase 2: Core Features
- 003-{domain}: {rationale}
...

## Tech Stack Migration Notes

| Current | Consideration |
|---------|---------------|
| {tech} | {migration note} |
...
```

### Step 7: Generate Domain Specifications

For **each identified domain**, create a detailed specification:

**Directory**: `specs/{NNN}-re-{domain-name}/spec.md`

**Required sections:**

#### 7.1 Header with Estimation Hints

```markdown
# Specification: {Domain Name}

**Domain**: {NNN}-{domain-name}
**Created**: {DATE}
**Status**: Draft (reverse-engineered)
**Dependencies**: {list of prerequisite domain numbers}

## Overview

{2-3 sentences describing this domain's purpose and scope}

**Source Files Analyzed**: {list of key files}

## Complexity Estimation

| Metric | Value | Implication |
|--------|-------|-------------|
| **Files** | {count} | {Small: <10, Medium: 10-30, Large: >30} |
| **Lines of Code** | {count} | Scope indicator |
| **Git Commits (6 mo)** | {count} | {High churn = active/complex area} |
| **Contributors** | {count} | {Many = knowledge spread, Few = specialist knowledge} |
| **Hotspot Score** | {Low/Medium/High} | Based on change frequency |

### Complexity Signals

**From Git History:**
- {X} commits in last 6 months → {Active development / Stable}
- {Y} unique contributors → {Knowledge spread / Concentrated}
- {Z} bug-fix commits (keywords: fix, bug, issue) → {Potential edge cases}

**From Code Structure:**
- {Cyclomatic complexity indicators if detectable}
- {Number of external dependencies}
- {Integration points with other domains}

**Estimated Complexity**: {Low/Medium/High/Very High}

**Rationale**: {1-2 sentences explaining the estimate based on signals above}
```

#### 6.2 User Stories (5-10 per domain)

Go **deep** - each domain should have multiple granular user stories:

```markdown
## User Scenarios & Testing

### US-{NNN}.1 - {Specific Action} (Priority: P1)

As a {specific role}, I need to {specific action with detail} so that {specific outcome}.

**Why this priority**: {Extracted from code - is this a core path or edge case?}

**Source Evidence**:
- File: `{path/to/file.ext}:{line}` - {what this reveals}
- Test: `{test file}` - {what behavior is tested}

**Acceptance Scenarios**:

1. **Given** {specific precondition from code}, **When** {action from code flow}, **Then** {outcome from code/tests}
2. **Given** {error condition found in code}, **When** {trigger}, **Then** {error handling behavior}
3. **Given** {edge case from tests}, **When** {action}, **Then** {expected behavior}

**Technical Notes**:
- Current implementation: {brief description of how code does this}
- Key functions: `{functionName}`, `{otherFunction}`
- Data flow: {entity} → {service} → {output}
```

#### 6.3 Functional Requirements

Extract detailed requirements from the code:

```markdown
## Requirements

### Functional Requirements

**{Capability Category}**
- **FR-{NNN}.001**: System MUST {specific capability extracted from code}
  - Source: `{file}:{line}` - {evidence}
- **FR-{NNN}.002**: System MUST {validation rule found in code}
  - Source: `{file}:{line}` - {evidence}

**{Another Category}**
- **FR-{NNN}.010**: System MUST {behavior}
...
```

#### 6.4 Key Entities (for this domain)

```markdown
### Key Entities

#### {EntityName}

**Purpose**: {what it represents}
**Source**: `{file path}`

| Attribute | Type | Description | Constraints |
|-----------|------|-------------|-------------|
| {field} | {type} | {purpose} | {validation rules} |
...

**Relationships**:
- Has many: {related entity}
- Belongs to: {parent entity}

**Behaviors**:
- {method}: {what it does}
```

#### 6.5 Edge Cases and Error Handling

```markdown
### Edge Cases

Extract from code and tests:

- **{Condition}**: {How code handles it} (Source: `{file}`)
- **{Error scenario}**: {Error message/behavior} (Source: `{file}`)
```

#### 6.6 Success Criteria

```markdown
## Success Criteria

- **SC-{NNN}.001**: {Measurable outcome extracted from tests/code}
- **SC-{NNN}.002**: {Performance requirement if found}
```

### Step 8: Depth-Aware Analysis Process

For each domain, perform analysis based on configured depth level.

**CRITICAL: The depth level determines how much source code you actually read.**

---

#### Context Management Strategy

**If `context_management: progressive` (recommended):**

Process domains one at a time to avoid context overflow:

```text
For each domain:
  1. READ source files for this domain only
  2. EXTRACT structured data immediately:
     - Function signatures → compact notation
     - Validation rules → bullet points
     - Entity fields → table format
     - Error handling → list of scenarios
  3. DISCARD raw source code from context
  4. GENERATE spec.md from extracted data only
  5. SAVE spec to file
  6. CLEAR domain context before next domain
```

**Extract-then-discard pattern example:**

```text
READ: src/services/OrderService.ts (847 lines)

EXTRACT immediately:
  Functions:
    - createOrder(cart: Cart, customer: Customer): Order
    - validateOrder(order: Order): ValidationResult
    - calculateTotal(items: Item[], discount?: Discount): Money

  Validation rules:
    - Cart must have at least 1 item
    - Customer must have verified email
    - Discount code must be valid and not expired

  Error scenarios:
    - EmptyCartError: "Cannot create order with empty cart"
    - InvalidCustomerError: "Customer email not verified"
    - ExpiredDiscountError: "Discount code {code} has expired"

DISCARD raw source (847 lines freed)
KEEP extracted data (15 lines)
```

**If `context_management: hold_all`:**

For small codebases only. Read all files, hold in context, generate all specs at once. Requires lower `max_lines_per_file` (300-500).

---

#### Depth Level: `metadata` (No Source Reading)

Extract specifications from analysis.json only:

- File names and directory structure → infer domain purpose
- Import statements → identify dependencies
- Git hotspots → prioritize frequently changed areas
- Package dependencies → identify technologies used

**User stories**: Infer from file/function names and structure
**Requirements**: Derive from dependency patterns and configs
**Entities**: List class/file names without field details

---

#### Depth Level: `signatures` (Read Declarations)

Everything from `metadata`, plus **read source code declarations**:

**8.1 Read Function/Method Signatures**

For each key file in the domain, read:

```text
- Function names and parameters
- Method signatures with types
- Class/interface definitions
- Exported constants and enums
- Type definitions and interfaces
```

**What to extract:**

- Parameter names reveal expected inputs
- Return types reveal outputs
- Method names reveal capabilities
- Type definitions reveal data structure

**8.2 Read Public Interfaces**

```text
- API route definitions (paths, methods)
- Exported module interfaces
- Public class methods
- Configuration schemas
```

**User stories**: Derive from public method signatures
**Requirements**: Infer from parameter validation types
**Entities**: Extract from type/class definitions with field names

---

#### Depth Level: `logic` (Read Function Bodies)

Everything from `signatures`, plus **read function implementations**:

**8.3 Read Business Logic**

For key functions (prioritized by hotspots), read the implementation:

```text
- Validation rules (if statements, guards)
- Business calculations and transformations
- State transitions and workflows
- Error handling and edge cases
```

**What to extract:**

- Conditional logic → business rules and constraints
- Validation code → input requirements
- Error messages → failure scenarios
- Data transformations → processing logic

**8.4 Read Test Assertions**

```text
- Test case names → expected behaviors
- Setup/teardown → preconditions
- Assertions → success criteria
- Mock data → example inputs/outputs
```

**User stories**: Extract from test names and documented behaviors
**Requirements**: Extract from validation logic and error handling
**Entities**: Include field constraints and validation rules

---

#### Depth Level: `full` (Complete File Reading)

Everything from `logic`, plus **read entire source files**:

**8.5 Complete Source Analysis**

For all files in the domain:

```text
- All code paths and branches
- Internal helper functions
- Private methods and their logic
- Comments and documentation
- Configuration and constants
```

**8.6 Deep Data Flow Analysis**

```text
- Trace data from input to output
- Map all entity relationships
- Document all state changes
- Extract all error scenarios
```

**8.7 Cross-Domain Dependencies**

```text
- How this domain calls other domains
- Shared entities and their usage
- Event/message flows between domains
```

**User stories**: Comprehensive with all edge cases
**Requirements**: Complete with all validation rules and constraints
**Entities**: Full schema with relationships, constraints, and behaviors

---

#### Priority File Handling

Files matching `priority_patterns` (e.g., `*Service.*`, `*Controller.*`) are always read at the current depth level, even if they would otherwise be skipped.

#### Max Lines Limit

When reading files, respect `max_lines_per_file` limit:
- Read most important sections first (exports, public methods)
- Truncate with `[... truncated at {N} lines]` marker
- Note in spec if file was truncated

#### Language-Specific Pattern Recognition

Use `language_patterns` from configuration to extract richer semantics. When reading source code, look for language-specific markers:

**Java example:**
```text
Source: @Service public class OrderService { @Transactional public Order createOrder(...) }

Extract:
  - Service component (Spring)
  - Transaction boundary on createOrder
  - Business logic method: createOrder
```

**TypeScript example:**
```text
Source: @Controller() export class OrderController { @Post() @UseGuards(AuthGuard) async create(@Body() dto: CreateOrderDto) }

Extract:
  - API controller (NestJS)
  - POST endpoint
  - Requires authentication (UseGuards)
  - Input validation via DTO
```

**Delphi example:**
```text
Source: TOrderForm = class(TForm) ... TADOQuery ... procedure SaveOrder;

Extract:
  - UI Form (TForm)
  - Database access (TADOQuery)
  - User action: SaveOrder
```

**Pattern categories to recognize:**

| Category | What It Reveals |
|----------|-----------------|
| **Persistence annotations** | Database entities, table mappings |
| **API decorators** | Endpoints, HTTP methods, routes |
| **Validation markers** | Input constraints, required fields |
| **Transaction markers** | Transaction boundaries, consistency requirements |
| **DI annotations** | Service boundaries, dependencies |
| **Error patterns** | Exception types, error scenarios |

**How to apply:**

1. Detect primary language(s) from `analysis.json` file counts
2. Load corresponding patterns from `language_patterns` config
3. When reading source, scan for these patterns
4. Translate patterns to spec artifacts:
   - `@Entity` → Add to Key Entities section
   - `@RestController` + `@GetMapping` → Add to API endpoints
   - `@Valid` + constraints → Add to Functional Requirements
   - `throw new ...Exception` → Add to Edge Cases

### Step 9: Save Specifications

**Step 9.1: Detect highest existing spec ID**

Use Glob to find existing specs and determine starting ID:

```python
# Find all existing spec folders in specs/
existing_specs = glob("specs/[0-9][0-9][0-9]-*/")

# Extract IDs and find highest
highest_id = 0
for spec_dir in existing_specs:
    id_part = spec_dir.split("/")[-2][:3]  # e.g., "002" from "002-feature/"
    if id_part.isdigit():
        highest_id = max(highest_id, int(id_part))

# Start domain specs from next available ID
start_id = highest_id + 1

print(f"Existing specs: {len(existing_specs)}, highest ID: {highest_id:03d}")
print(f"Migration specs will start from: {start_id:03d}")
```

**Step 9.2: Create overview folder**

```bash
mkdir -p "specs/000-re-overview"
# Save overview.md and traceability.md here
```

**Step 9.3: Save domain specs**

```python
for i, domain in enumerate(domains_ordered_by_dependency):
    domain_id = start_id + i
    domain_folder = f"specs/{domain_id:03d}-re-{domain.name}"

    mkdir -p domain_folder
    write_file(f"{domain_folder}/spec.md", domain.spec_content)

    print(f"✓ {domain_id:03d}-re-{domain.name}/spec.md")
```

### Step 10: Generate Traceability Matrix

Create `traceability.md` showing source file to specification mapping:

```markdown
# Source-to-Spec Traceability

**Generated**: {DATE}
**Total Source Files**: {count}
**Covered Files**: {covered_count} ({percentage}%)

## Coverage Summary

| Domain | Files | Coverage | Key Requirements |
|--------|-------|----------|------------------|
| 003-re-core-framework | 12 | Full | FR-003.001-015 |
| 004-re-data-access | 8 | Full | FR-004.001-010 |
| 005-re-reference-data | 45 | Partial | FR-005.001-008 |
| - (Orphan) | 15 | None | - |

## File-to-Domain Mapping

| Source File | Domain | Depth | Requirements | User Stories |
|-------------|--------|-------|--------------|--------------|
| src/services/OrderService.ts | 007-re-orders | logic | FR-007.001-005 | US-007.1-3 |
| src/models/Order.ts | 007-re-orders | signatures | FR-007.006 | US-007.1 |
| src/utils/helpers.ts | - | - | - | - |
| src/legacy/old_module.js | - | - | - | - |

## Orphan Files (Not Covered)

Files not mapped to any domain specification:

| File | Reason | Suggested Domain |
|------|--------|------------------|
| src/utils/helpers.ts | Utility functions | Consider: re-shared-utilities |
| src/legacy/old_module.js | Appears unused | Consider: Retire |
| tests/fixtures/*.json | Test data | N/A (test support) |

## Requirement Traceability

| Requirement | Source Evidence | Test Coverage |
|-------------|-----------------|---------------|
| FR-05.001 | OrderService.ts:45-67 | order.test.ts |
| FR-05.002 | OrderService.ts:89-102 | order.test.ts |
| FR-05.003 | OrderValidator.ts:12-34 | - (no test) |
```

**Purpose of traceability.md:**
- Audit trail: Which source files informed which requirements
- Gap identification: Orphan files not covered by any spec
- Test coverage hints: Which requirements have test evidence
- Review aid: Reviewers can verify spec accuracy against source

### Step 11: Display Summary

```text
Multi-specification generation complete!

Overview:
  ✓ specs/000-re-overview/overview.md
  ✓ specs/000-re-overview/traceability.md

Domain Specifications ({N} domains, starting from ID {start_id}):
  ✓ {start_id}-re-core-framework/spec.md
  ✓ {start_id+1}-re-data-access/spec.md
  ✓ {start_id+2}-re-reference-data/spec.md
  ...

Implementation order:
  Start with lowest migration ID (foundation), work up to higher numbers

Next steps:
  - Review each spec for accuracy
  - Items marked [NEEDS CLARIFICATION: ...] require input
  - Run /speckit.echelon.re-verify to check coverage
  - Run /speckit.echelon.re-constitute to generate strategic artifacts
```

## Domain Detection Heuristics

### Common Domain Patterns

| Domain          | Directory Patterns                                   | File Patterns                                | Indicators                   |
|-----------------|------------------------------------------------------|----------------------------------------------|------------------------------|
| Core Data Model | `models/`, `entities/`, `types/`, `schema/`          | `*Model.*`, `*Entity.*`, `*Type.*`           | Type definitions, interfaces |
| Data Access     | `db/`, `database/`, `repositories/`, `persistence/`  | `*Repo.*`, `*DAO.*`, `*Store.*`              | SQL, ORM calls               |
| Authentication  | `auth/`, `security/`, `identity/`                    | `*Auth.*`, `*Login.*`, `*Session.*`          | Token handling, permissions  |
| API Layer       | `api/`, `routes/`, `controllers/`, `handlers/`       | `*Controller.*`, `*Handler.*`, `*Route.*`    | HTTP methods, endpoints      |
| Business Logic  | `services/`, `domain/`, `core/`, `business/`         | `*Service.*`, `*Manager.*`, `*UseCase.*`     | Business rules               |
| User Interface  | `ui/`, `views/`, `forms/`, `components/`, `pages/`   | `*Form.*`, `*View.*`, `*Screen.*`, `*Page.*` | UI framework imports         |
| Integration     | `integrations/`, `external/`, `clients/`             | `*Client.*`, `*API.*`, `*Integration.*`      | External API calls           |
| Reporting       | `reports/`, `export/`, `analytics/`                  | `*Report.*`, `*Export.*`, `*Analytics.*`     | Data aggregation             |
| Configuration   | `config/`, `settings/`                               | `*Config.*`, `*Settings.*`, `*.env*`         | Environment variables        |

### Language-Specific Detection

**Delphi/Pascal:**

- Forms: `.dfm`, `.fmx` files → UI domain
- Data modules: `TDataModule` → Data Access domain
- Objects: `*Obj.pas`, `*Object.pas` → Business Logic domain
- Types: `*Types.pas`, `*Consts.pas` → Core Data Model domain

**TypeScript/JavaScript:**

- `package.json` workspaces → domain boundaries
- Barrel exports (`index.ts`) → public interfaces
- `*.dto.ts`, `*.entity.ts` → Data Model domain
- `*.controller.ts`, `*.resolver.ts` → API Layer domain

**Python:**

- `__init__.py` exports → public interface
- `models.py` → Data Model domain
- `views.py`, `api.py` → API Layer domain
- `services.py` → Business Logic domain

**Go:**

- Package directories → domain boundaries
- `*_handler.go` → API Layer
- `*_service.go` → Business Logic
- `*_repository.go` → Data Access

## Quality Checklist (Depth-Aware)

Verify each domain spec meets the quality bar for the configured depth level:

### Depth: `metadata`

- [ ] 3-5 user stories inferred from structure
- [ ] File references (no line numbers)
- [ ] Entity names listed
- [ ] Dependencies identified
- [ ] Items needing clarification marked

### Depth: `signatures`

- [ ] 5-8 user stories from public interfaces
- [ ] Source evidence cited (file references)
- [ ] Entity definitions with field names and types
- [ ] API endpoints documented
- [ ] Clear dependency links to other domains
- [ ] Items needing clarification marked

### Depth: `logic` (Recommended)

- [ ] 5-10 granular user stories with acceptance criteria
- [ ] Source evidence cited (file:line references)
- [ ] Acceptance scenarios extracted from code/tests
- [ ] Entity definitions with attributes, types, and constraints
- [ ] Validation rules documented
- [ ] Edge cases from error handling code
- [ ] Measurable success criteria
- [ ] Clear dependency links to other domains
- [ ] Items needing clarification marked

### Depth: `full`

- [ ] 8-15 comprehensive user stories
- [ ] Complete source evidence with line references
- [ ] Detailed acceptance scenarios from all code paths
- [ ] Entity definitions with full schema and behaviors
- [ ] All validation rules and business constraints
- [ ] All edge cases and error scenarios
- [ ] Data flow documented across domain boundaries
- [ ] Performance considerations noted
- [ ] Clear dependency links with interaction patterns
- [ ] Items needing clarification marked

## Coverage Verification & Iterative Refinement

### Full Pipeline Workflow

The complete reverse-engineering workflow:

```text
┌───────────┐   ┌───────────┐   ┌──────────┐   ┌─────────────┐   ┌───────────────┐   ┌────────┐   ┌─────────┐
│ reanalyze │──▶│ respecify │──▶│ validate │──▶│ rechecklist │──▶│ reconstitute  │──▶│ replan │──▶│ retasks │
└───────────┘   └─────┬─────┘   └──────────┘   └─────────────┘   └───────────────┘   └────────┘   └─────────┘
                    │
                    ▼
          ┌─────────────────┐
          │ Coverage < 80%? │
          └────────┬────────┘
                   │ YES
                   ▼
          ┌──────────────┐     ┌────────────────┐
          │   verify     │────▶│    expand      │
          │ (find gaps)  │     │ (fill gaps)    │
          └──────────────┘     └───────┬────────┘
                                       │
                                Coverage OK? ──▶ continue to validate
```

**Commands in order:**

| #   | Command                              | Purpose                                      |
| --- | ------------------------------------ | -------------------------------------------- |
| 1   | `/speckit.echelon.re-analyze`       | Extract codebase data to analysis.json       |
| 2   | `/speckit.echelon.re-specify`     | Generate domain specs with coverage tracking |
| 3   | `/speckit.echelon.re-verify`        | Check coverage, identify gaps                |
| 4   | `/speckit.echelon.re-expand`        | Fill gaps (repeat 3-4 until satisfied)       |
| 5   | `/speckit.echelon.re-validate`      | Quality check specs, auto-resolve from code  |
| 6   | `/speckit.echelon.re-checklist`   | Generate quality checklists                  |
| 7   | `/speckit.echelon.re-constitute`  | Generate constitution with legacy analysis   |
| 8   | `/speckit.echelon.re-plan`        | Generate implementation plan                 |
| 9   | `/speckit.echelon.re-tasks`       | Generate task breakdown                      |

Or use `/speckit.echelon.re-extract` to run the full pipeline at once.

### Coverage Verification Loop

```text
┌──────────────┐     ┌──────────────┐     ┌────────────────┐
│ respecify    │────▶│   verify     │────▶│    expand      │
│ (initial)    │     │ (find gaps)  │     │ (fill gaps)    │
└──────────────┘     └──────────────┘     └───────┬────────┘
                                                  │
                                           Coverage OK?
                                           ├── NO → repeat verify+expand
                                           └── YES → done
```

### Coverage Tracking

After generating specs, calculate coverage:

```text
Coverage = (files mapped to domains) / (total source files) × 100%

Target: ≥80% coverage
```

If coverage is below 80%, the command will:

1. List orphan files (not covered by any spec)
2. Cluster orphans by similarity (imports, naming patterns)
3. Suggest new domains for orphan clusters
4. Offer to expand existing domains

### Expansion Workflow

Use the separate `expand` command for iterative refinement:

```bash
# Initial generation
/speckit.echelon.re-specify

# Check coverage and identify gaps
/speckit.echelon.re-verify

# Fill gaps with orphan clusters
/speckit.echelon.re-expand
```

The `expand` command will:

1. Load existing specs (don't regenerate)
2. Analyze remaining orphan files
3. Auto-create domains for high-confidence clusters
4. Expand reference-data domain with unmapped models
5. Re-calculate coverage

### Example Iteration

```bash
# Run 1: Initial generation
/speckit.echelon.re-specify
# Coverage: 33.2% (63/190 files)
# ⚠️ Below 80% threshold

# Run 2: Verify gaps
/speckit.echelon.re-verify
# Suggests: cricket-scheduling, search-discovery domains

# Run 3: Expand coverage
/speckit.echelon.re-expand
# Added: 015-search-discovery, 016-cricket-scheduling
# Expanded: 003-reference-data-models (+90 files)
# Coverage: 86.8% (165/190)
# ✓ Above threshold
```

## Notes

- **Depth over breadth** - fewer domains with rich detail is better than many shallow specs
- **Evidence-based** - every user story and requirement should cite source code
- **Implementation-ordered** - numbering reflects build order, not importance
- **Agent-agnostic** - any AI coding assistant can follow this process
- **Iterative refinement** - generate, verify, expand, repeat until coverage target met
