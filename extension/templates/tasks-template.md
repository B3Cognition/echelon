# Tasks: {Feature Name}

**Spec:** [spec.md](spec.md)
**Plan:** [plan.md](plan.md)

---

## Task Row Contract

Every executable task MUST start with one top-level canonical row:

```markdown
- [ ] T-001 [P] complexity=standard phase=foundation req=FR-001 depends=none
```

Rules:
- `T-###` is the stable task ID.
- `[P]` is optional and means parallel-safe within the same phase.
- `complexity` is one of `trivial`, `standard`, `complex`.
- `phase` is a lowercase token such as `foundation`, `core`, `integration`, `polish`.
- `req` is one or more `FR-*` IDs separated by commas, or `INFRA` for infrastructure.
- `depends` is `none` or comma-separated `T-###` IDs.
- Acceptance criteria checkboxes are nested under the task and MUST NOT be used as task counters.
- **Test:** is a one-line description of how the task is verified (required when the tasks gate is enabled).

---

## Phase: Foundation

- [ ] T-001 [P] complexity=standard phase=foundation req=INFRA depends=none

  **Title:** Establish project structure

  **Files:**
  - `{path}` - {purpose}

  **Description:**
  {Specific work to complete.}

  **Test:** {How this task is verified.}

  **Acceptance Criteria:**
  - [ ] {Criterion}

  **Test Tasks:**
  - [ ] {Specific test to add or run}

---

## Phase: Core

- [ ] T-002 complexity=standard phase=core req=FR-001 depends=T-001

  **Title:** Implement primary requirement

  **Files:**
  - `{path}` - {purpose}

  **Description:**
  {Specific work to complete.}

  **Test:** {How this task is verified.}

  **Acceptance Criteria:**
  - [ ] FR-001 acceptance scenarios pass

  **Test Tasks:**
  - [ ] {Specific test to add or run}

---

## Summary

| Phase | Tasks | Notes |
| --- | ---: | --- |
| foundation | {count} | {notes} |
| core | {count} | {notes} |
