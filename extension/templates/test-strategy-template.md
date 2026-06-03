# Test Strategy Template

Use this template for `test-strategy.md`.

## Metadata

- Spec:
- Sentinel:
- Date:
- Inputs reviewed:

## Stack Detection

- is_browser_app: true/false
- Detected indicators:
- E2E framework:
- Visual validation:
- requires_e2e_setup: true/false
- package_manager: npm/pnpm/yarn/pip/cargo/none

## Testability Deficiency

Omit this section only when all testability sub-metrics are >= 0.70.

| Metric | Score | Weak Requirements | Amendment Recommendation |
|--------|-------|-------------------|--------------------------|
| hard_constraint_ratio | | | |
| constraint_density | | | |
| negative_space_coverage | | | |

## Test Pyramid

| Layer | Target Ratio | Components / Requirements | Rationale |
|-------|--------------|----------------------------|-----------|
| Unit | | | |
| Integration | | | |
| E2E | | | |
| Contract | | | |

## Component Test Approach

| Component | Test Layer(s) | Primary Risks | Required Fixtures |
|-----------|---------------|---------------|-------------------|
|           |               |               |                   |

## Boundary And Data Strategy

| Boundary / Entity | Boundary Values | Error Cases | Test Data Strategy |
|-------------------|-----------------|-------------|--------------------|
|                   |                 |             |                    |

## CI/CD Pipeline

| Stage | Commands / Gates | Target Duration | Blocks Merge / Deploy |
|-------|------------------|-----------------|-----------------------|
| Pre-commit | | | |
| PR/Merge | | | |
| Post-merge | | | |
| Pre-deploy | | | |
| Post-deploy | | | |

## Flakiness Management

| Policy | Value |
|--------|-------|
| Repeat count for new tests | |
| Quarantine marker | |
| Flaky rate target | |
| Critical journey pass target | |
| Review cadence | |
