# Coverage Map Template

Use this template for `coverage-map.md`.

NEVER use `manual` as Coverage Type or Automation Status. Use `automated`, `deferred-automation`, or `escalate`.

Declare individual uppercase hyphenated Test Case IDs, such as `UT-001` or
`E2E-COL-001`. Comma, slash, and semicolon separated lists are supported. Do not
use symbolic ranges or placeholders (`E-VIS-001..004`, `C-HTTP-001..N`, `TBD`):
enumerate each required case explicitly. Preserve the seven-column schema.

## Coverage Table

| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |
|----------------|--------------|-----------|-------------------|---------------|----------|--------------|
|                |              | unit/integration/e2e/contract | automated/deferred-automation/escalate | automated/deferred-automation/escalate | | |

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
