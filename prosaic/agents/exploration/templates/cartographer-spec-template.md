# <Feature Name> — Specification

> <One-paragraph summary of what this system does and why it exists.>

## User Scenarios & Testing

<!-- Include one scenario per materially distinct user goal. Do not split one
product obligation into separate usage, testing, and documentation scenarios. -->

### Scenario 1: <Descriptive Name>

**As a** <actor>,
**I want to** <goal>,
**So that** <business value>.

#### Acceptance Criteria

- **AC-001**: Given <precondition>, when <action>, then <observable outcome that verifies the applicable FR-NNN>.
- **AC-002**: Given <materially distinct error or boundary condition>, when <action>, then <observable outcome that verifies the applicable FR-NNN>.

<!-- Each AC is a verification path for one canonical formal requirement. Omit
duplicate criteria and omit error or boundary criteria that do not materially
apply. -->

### Scenario 2: <Descriptive Name>
<!-- Omit this section when no distinct second user goal exists. -->

## Functional Requirements

### <Domain Area> (from boundaries.md)

- **FR-001**: <requirement statement>
  - **User Story:** Scenario N
  - **Priority:** MVP

<!-- Express each distinct observable product obligation in one canonical formal
requirement. Tests, documentation, ACs, and success criteria may verify or
summarize it, but must not duplicate it as another obligation. -->

<!-- Put measurable boundaries directly on the ID-bearing requirement line,
only when supported by user input, verified evidence, domain rules, the
constitution, or established boundaries. Use symbolic comparator syntax. For
example:
- **FR-021**: The system MUST return an empty result when no records match. Constraint: `result_count = 0`.
- **FR-022**: The system MUST limit each page. Constraint: `page_size <= 50 items`.
- **FR-023**: The system MUST NOT expose records outside the requesting user's authorized scope.
The examples show syntax, not a quota. Preserve unknown values and omit
unsupported prohibitions instead of inventing requirements for a quality score.
-->

### <Domain Area>
<!-- Omit this section when no distinct second domain area exists. -->

## Non-Functional Requirements

<!-- Include only quality constraints grounded in the request, constitution,
domain evidence, or a material identified risk. Do not add an NFR merely to populate
a category. -->

- **NFR-001**: <performance requirement>
  - **Category:** Performance
  - **Measurable Target:** <target>

## Key Entities

<!-- When no distinct domain entity with meaningful attributes, relationships,
or lifecycle exists, retain this heading and state that no domain entities are
required. Do not promote actors, outputs, or test fixtures to entities merely
to populate the template. -->

### <Entity Name>
- **Attributes:** <business-level attributes>
- **Relationships:** <connections with cardinality>
- **Lifecycle:** <states and transitions>
- **Constraints:** <business validation rules>

## Success Criteria

### MVP Success
- [ ] <measurable outcome>
- [ ] <measurable outcome>

### Full Product Success
<!-- Omit this subsection when no post-MVP capability is defined. -->
- [ ] <measurable outcome distinct from MVP success>

## Scope

### In Scope (MVP)
- <feature/capability>

### In Scope (Post-MVP)
<!-- Omit this subsection when no post-MVP scope is supported by the request. -->
- <feature/capability>

### Explicitly Out of Scope
- <feature/capability> — <reason for exclusion>

## Open Questions
<!-- Unresolved unknowns that may affect requirements -->

| ID | Question | Impact | Source |
|----|----------|--------|--------|
| OQ-001 | <question from unknowns.md> | <which requirements are affected> | <unknowns.md ref> |

## Assumptions in Effect
<!-- Assumptions from DISCOVER that these requirements depend on -->

| ID | Assumption | Status | Requirements Affected |
|----|-----------|--------|----------------------|
| A-001 | <from assumptions.md> | <validated/unvalidated> | FR-001, FR-002 |

## Glossary Additions
<!-- Any new terms introduced by WHAT that were not in DISCOVER's glossary -->
