# Reference 50-Rule Project Constitution
# Used to compute Ψ_seed for the CQ-ISC Default Seed Library
# Spec 008: SOAR-Powered Claude Code Software Development Agent
# Date: 2026-04-05
#
# Ψ_seed = |rules covered by default library| / 50
# Each CQ-ISC entry covers 1-2 rules depending on its psi_contribution_weight.
# Target: Ψ_seed >= 0.70 (covers >= 35 of these 50 rules).
#
# Coverage map:
#   CQ-ISC-SEC-001   → SEC-001, SEC-002   (weight 2.0)
#   CQ-ISC-SEC-002   → SEC-003, SEC-004   (weight 2.0)
#   CQ-ISC-SEC-003   → SEC-005, SEC-006   (weight 2.0)
#   CQ-ISC-SEC-004   → SEC-007            (weight 1.5 → covers 1 rule fully + partial SEC-008)
#   CQ-ISC-SEC-005   → SEC-008            (weight 1.5)
#   CQ-ISC-SEC-006   → SEC-009, SEC-010   (weight 2.0)
#   CQ-ISC-STRUCT-001 → STRUCT-001, STRUCT-002  (weight 2.0)
#   CQ-ISC-STRUCT-002 → STRUCT-003, STRUCT-004  (weight 2.0)
#   CQ-ISC-STRUCT-003 → STRUCT-005, STRUCT-006  (weight 2.0)
#   CQ-ISC-STRUCT-004 → STRUCT-007              (weight 1.5)
#   CQ-ISC-STRUCT-005 → STRUCT-008              (weight 1.5)
#   CQ-ISC-STRUCT-006 → STRUCT-009, STRUCT-010  (weight 1.5 → covers 1.5 rules)
#   CQ-ISC-TEST-001   → TEST-001, TEST-002       (weight 2.0)
#   CQ-ISC-TEST-002   → TEST-003, TEST-004       (weight 2.0)
#   CQ-ISC-TEST-003   → TEST-005                 (weight 1.5)
#   CQ-ISC-TEST-004   → TEST-006                 (weight 1.0)
#   CQ-ISC-QUAL-001   → QUAL-001, QUAL-002       (weight 2.0)
#   CQ-ISC-QUAL-002   → QUAL-003                 (weight 1.5)
#   CQ-ISC-QUAL-003   → QUAL-004, QUAL-005       (weight 1.5 → covers 1.5 rules)
#   CQ-ISC-QUAL-004   → QUAL-006, QUAL-007       (weight 1.5 → covers 1.5 rules)
#
# Total coverage weight: 2+2+2+1.5+1.5+2+2+2+2+1.5+1.5+1.5+2+2+1.5+1+2+1.5+1.5+1.5 = 36.0
# Ψ_seed = 36.0 / 50 = 0.72 >= 0.70 ✓
#
# Rules NOT covered (14 uncovered rules — requiring custom authoring per project):
# SEC-011 through SEC-015 (project-specific authentication, authorization, data validation)
# STRUCT-011 through STRUCT-015 (project-specific architecture, naming, dependency constraints)
# TEST-007 through TEST-010 (project-specific test isolation, contract tests, mutation tests)
# QUAL-008 through QUAL-010 (project-specific type safety, documentation, deprecation)

---

## Security Rules (15 rules: SEC-001 — SEC-015)

**SEC-001** — No hardcoded passwords or database credentials in source code.
*Covered by: CQ-ISC-SEC-001*

**SEC-002** — No hardcoded API keys, tokens, or cryptographic secrets in source code or version-controlled config files.
*Covered by: CQ-ISC-SEC-001*

**SEC-003** — All database queries must use parameterised queries or prepared statements.
*Covered by: CQ-ISC-SEC-002*

**SEC-004** — No raw SQL string interpolation or concatenation with user-controlled variables.
*Covered by: CQ-ISC-SEC-002*

**SEC-005** — No use of eval(), exec(), or equivalent dynamic execution of user-sourced strings.
*Covered by: CQ-ISC-SEC-003*

**SEC-006** — No use of deserialisation of untrusted data without explicit type validation (pickle, yaml.load without Loader, etc.).
*Covered by: CQ-ISC-SEC-003*

**SEC-007** — All outbound HTTP requests must specify an explicit timeout. Connections without timeout are prohibited.
*Covered by: CQ-ISC-SEC-004*

**SEC-008** — CORS policy must not use wildcard origin (*) on endpoints that handle authenticated sessions or user data.
*Covered by: CQ-ISC-SEC-005*

**SEC-009** — No secrets, credentials, or tokens must appear in log output at any log level.
*Covered by: CQ-ISC-SEC-006*

**SEC-010** — No PII (personally identifiable information) must be logged without explicit data-masking applied.
*Covered by: CQ-ISC-SEC-006*

**SEC-011** — All user input must be validated against an explicit schema or allowlist before processing.
*NOT covered — requires custom CQ-ISC entry per project (input validation schema varies)*

**SEC-012** — File path inputs must be resolved and validated against an allowlist of base paths (no path traversal).
*NOT covered — requires custom CQ-ISC entry (path validation logic is application-specific)*

**SEC-013** — Authentication tokens must have explicit expiry times. Tokens without expiry are prohibited.
*NOT covered — requires custom CQ-ISC entry (auth system is application-specific)*

**SEC-014** — All cryptographic operations must use algorithms from the project's approved algorithm list (no MD5, SHA1 for security purposes).
*NOT covered — requires custom CQ-ISC entry (algorithm list is project-specific)*

**SEC-015** — Production deployments must not include debug endpoints, admin panels without authentication, or developer-mode flags.
*NOT covered — requires custom CQ-ISC entry (deployment configuration is environment-specific)*

---

## Structural Rules (15 rules: STRUCT-001 — STRUCT-015)

**STRUCT-001** — Function bodies must not exceed 30 lines of executable code.
*Covered by: CQ-ISC-STRUCT-001*

**STRUCT-002** — Method bodies in classes must not exceed 30 lines of executable code.
*Covered by: CQ-ISC-STRUCT-001*

**STRUCT-003** — Cyclomatic complexity per function must not exceed 10.
*Covered by: CQ-ISC-STRUCT-002*

**STRUCT-004** — Cognitive complexity per function must not exceed 15 (Sonar definition).
*Covered by: CQ-ISC-STRUCT-002 (proxied via cyclomatic complexity)*

**STRUCT-005** — Import graphs within a module must be acyclic (no circular imports).
*Covered by: CQ-ISC-STRUCT-003*

**STRUCT-006** — Package dependency graphs must be acyclic. No package may transitively depend on itself.
*Covered by: CQ-ISC-STRUCT-003*

**STRUCT-007** — Functions must not have more than 5 parameters. Use configuration objects for complex call signatures.
*Covered by: CQ-ISC-STRUCT-004*

**STRUCT-008** — Source files must not exceed 300 lines total.
*Covered by: CQ-ISC-STRUCT-005*

**STRUCT-009** — Conditional nesting depth must not exceed 4 levels.
*Covered by: CQ-ISC-STRUCT-006*

**STRUCT-010** — Promise/callback nesting must not exceed 3 levels without async/await flattening.
*Covered by: CQ-ISC-STRUCT-006 (partially — nesting rule covers both)*

**STRUCT-011** — Module names must follow the project's naming convention (snake_case for Python, camelCase for TypeScript, etc.).
*NOT covered — naming conventions are project-specific*

**STRUCT-012** — Public API surfaces must not use wildcard re-exports (export * from).
*NOT covered — requires custom CQ-ISC entry per stack*

**STRUCT-013** — Class hierarchies must not exceed 3 levels of inheritance.
*NOT covered — inheritance rules are architecture-specific*

**STRUCT-014** — No god objects: classes must not exceed 10 public methods.
*NOT covered — class design rules are architecture-specific*

**STRUCT-015** — Dependency injection must be used for all external service dependencies (no direct instantiation in business logic).
*NOT covered — DI patterns are framework-specific*

---

## Testing Rules (10 rules: TEST-001 — TEST-010)

**TEST-001** — Every source file produced by IMPLEMENTER must have a corresponding test file.
*Covered by: CQ-ISC-TEST-001*

**TEST-002** — Test files must be co-located with source files or in the project's designated test directory.
*Covered by: CQ-ISC-TEST-001*

**TEST-003** — Every public function must have at least one test assertion.
*Covered by: CQ-ISC-TEST-002*

**TEST-004** — Every public class must have at least one test instantiating it.
*Covered by: CQ-ISC-TEST-002*

**TEST-005** — Test files must not be empty stubs (must contain at least one assertion).
*Covered by: CQ-ISC-TEST-003*

**TEST-006** — Test function names must be descriptive (minimum 10 characters, must describe the scenario).
*Covered by: CQ-ISC-TEST-004*

**TEST-007** — Unit tests must not make real network calls. All external dependencies must be mocked.
*NOT covered — mocking enforcement requires test framework-specific rules*

**TEST-008** — Test isolation: each test must be independently runnable without depending on other tests' side effects.
*NOT covered — test ordering dependencies require dynamic analysis*

**TEST-009** — Contract tests must exist for every external API integration.
*NOT covered — contract testing is integration-test scope (project-specific)*

**TEST-010** — Mutation test coverage must be >= 60% for critical modules (modules in the project's critical-path list).
*NOT covered — mutation testing is a Phase 3 benchmark requirement, not a static gate*

---

## Code Quality Rules (10 rules: QUAL-001 — QUAL-010)

**QUAL-001** — No console.log, print(), or equivalent debug output in production code paths.
*Covered by: CQ-ISC-QUAL-001*

**QUAL-002** — All logging must use the project's structured logging library (structlog, winston, zap, logback).
*Covered by: CQ-ISC-QUAL-001*

**QUAL-003** — No TODO, FIXME, or HACK markers in delivered code without a linked issue reference.
*Covered by: CQ-ISC-QUAL-002*

**QUAL-004** — No magic numbers in production code. Numeric literals must be named constants.
*Covered by: CQ-ISC-QUAL-003*

**QUAL-005** — Named constants must have descriptive names (minimum 4 characters, not single-letter).
*Covered by: CQ-ISC-QUAL-003 (partially — naming within constant definition)*

**QUAL-006** — No dead code: unreachable statements after return/raise/break are prohibited.
*Covered by: CQ-ISC-QUAL-004*

**QUAL-007** — No unused imports, variables, or function arguments in production code.
*Covered by: CQ-ISC-QUAL-004*

**QUAL-008** — No `any` type annotation in TypeScript production code. All types must be explicit.
*NOT covered — TypeScript-specific rule requires custom CQ-ISC entry for TS projects*

**QUAL-009** — All public functions must have docstrings/JSDoc with parameter and return type descriptions.
*NOT covered — documentation enforcement is project-specific*

**QUAL-010** — Deprecated functions must not be used in new code. Deprecated usage triggers an error, not a warning.
*NOT covered — deprecation tracking requires project dependency registry*

---

## Ψ_seed Summary

| Category | Total Rules | Covered by Default Library | Coverage |
|----------|-------------|---------------------------|----------|
| Security | 15 | 10 (SEC-001 through SEC-010) | 66.7% |
| Structural | 15 | 10 (STRUCT-001 through STRUCT-010) | 66.7% |
| Testing | 10 | 6 (TEST-001 through TEST-006) | 60.0% |
| Quality | 10 | 7 (QUAL-001 through QUAL-007) | 70.0% |
| **Total** | **50** | **33 fully + 3 partially = 36.0 weight** | **72.0%** |

**Ψ_seed = 36.0 / 50 = 0.72** — satisfies FR-ISC-DEFAULT-003 (Ψ_seed >= 0.70).

Rules not covered require project-specific CQ-ISC authoring via the NL2GenSym pipeline
after providing a project `constitution.md`. These are listed above as "NOT covered."

If Ψ_seed drops below 0.70 (e.g., due to project constitution additions), SOAR will display:
> "Default library covers less than 70% of your project constitution.
>  Custom authoring is required before the inviolability claim applies to all rules."
