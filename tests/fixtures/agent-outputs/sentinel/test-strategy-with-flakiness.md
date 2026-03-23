# Test Strategy

## Test Pyramid
- Unit: 70%
- Integration: 20%
- E2E: 10%

## Flakiness Management

### Detection Protocol
Run new tests with `--repeat-each=5` before merge.

### Quarantine Process
```typescript
test.fixme(true, 'Flaky - Issue #NNN');
```

### Root Cause Taxonomy
- race-condition
- network-timing
- state-leak
- animation-render
- data-dependency

### Stability Targets
- Flaky rate: < 5%
- Critical journey pass rate: 100%

### Review Cadence
Review quarantined tests weekly — fix or remove.
