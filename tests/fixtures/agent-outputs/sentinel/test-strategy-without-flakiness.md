# Test Strategy

## Test Pyramid
- Unit: 70%
- Integration: 20%
- E2E: 10%

## CI/CD Pipeline
1. Pre-commit: lint, type check
2. PR/Merge: full unit + integration
3. Post-merge: e2e tests
