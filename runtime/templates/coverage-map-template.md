# Coverage Map Template

Use this template for `coverage-map.md`.

NEVER use `manual` as Coverage Type or Automation Status. Use `automated`, `deferred-automation`, or `escalate`.

Declare individual uppercase hyphenated Test Case IDs, such as `UT-001` or
`E2E-COL-001`. Write one case ID and one type per row; repeat requirement IDs
when multiple cases cover the same requirement. Every canonical requirement
(`FR-*`, `NFR-*`, and any other formal requirement ID) not deferred through the
owner-controlled deferred-scope ledger must occur in at least one row. Where one acceptance criterion operationalizes a formal requirement,
put both IDs in the same Requirement ID cell (for example, `FR-001, AC-001`)
so the one test obligation covers both without duplicated work. Do not
use symbolic ranges or placeholders (`E-VIS-001..004`, `C-HTTP-001..N`, `TBD`):
enumerate each required case explicitly. Preserve the seven-column schema.

## Coverage Table

| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |
|----------------|--------------|-----------|-------------------|---------------|----------|--------------|
| FR-001, AC-001 | UT-001 | unit | deferred-automation | deferred-automation | Planned unit assertion | Implement |
| FR-001, AC-001 | E2E-001 | e2e | deferred-automation | deferred-automation | Planned browser assertion | Implement |

Replace these illustrative rows with the actual requirements and cases. Choose
one type (`unit`, `integration`, `e2e`, or `contract`) per row, not a list of options.

## Gap Analysis

| Requirement ID | Gap | Risk | Required Action | Owner |
|----------------|-----|------|-----------------|-------|
|                |     |      |                 |       |

## Escalations

| Requirement ID | Reason Automation Is Infeasible | Options For User | Status |
|----------------|---------------------------------|------------------|--------|
|                |                                 |                  |        |

## Browser App Gates

| Gate | Required | Coverage Evidence |
|------|----------|-------------------|
| Playwright E2E critical journeys | yes/no | |
| Smoke serving check | yes/no | |
| Visual validation task | yes/no | |
