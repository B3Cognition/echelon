# Tasks: Lexicon fixture tasks

## Phase: build

- [ ] T-001 complexity=standard phase=build req=REQ-001 depends=none

  **Title:** Parse the document
  **Description:** Implement the parser.
  **Test:** a test asserts the returned tree is not None and has child nodes
  **Acceptance Criteria:**
  - [ ] the parser returns a parse tree with all expected nodes

- [ ] T-002 complexity=standard phase=build req=REQ-002 depends=T-001

  **Title:** Check coverage
  **Description:** Implement coverage gate.
  **Test:** a test asserts the coverage report contains no uncovered requirements
  **Acceptance Criteria:**
  - [ ] the coverage report shows all requirements are covered
