# Mental Model Code

## Entity Graph

| Entity | Defined In | Depends On | Used By | Notes |
|--------|------------|------------|---------|-------|
| <entity> | <file / module> | <dependencies> | <consumers> | <notes> |

## Contract Map

| Contract | Side A | Side B | Must Match | Verification |
|----------|--------|--------|------------|--------------|
| <contract> | <producer> | <consumer> | <value, interface, invariant> | <check> |

## Data Flow

| Flow | Source | Path | Sink | Failure Points |
|------|--------|------|------|----------------|
| <flow> | <origin> | <ordered steps> | <destination> | <risks> |

## Invariants

| Invariant | Evidence | Status | Check |
|-----------|----------|--------|-------|
| <invariant> | <files / contracts> | PASS / VIOLATION / UNKNOWN | <how verified> |

## Invariant Violations

| Violation | Evidence | Impact | Alert |
|-----------|----------|--------|-------|
| <violation> | <source> | <what can break> | <ENGINEERING MANAGER alert text> |

## Impact Traces

| Change Target | Direct Dependents | Indirect Dependents | Breakage Risk |
|---------------|-------------------|---------------------|---------------|
| <file / entity> | <direct> | <indirect> | LOW / MEDIUM / HIGH |
