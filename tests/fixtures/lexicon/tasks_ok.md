ARTIFACT: TASKS
TITLE: Lexicon fixture tasks

TASK: T-001
PHASE: build
COMPLEXITY: standard
PARALLEL: no
REQ: REQ-001
DEPENDS: none
ACCEPTANCE: the parser returns a parse tree with all expected nodes
TEST: a test asserts the returned tree is not None and has child nodes

TASK: T-002
PHASE: build
COMPLEXITY: standard
PARALLEL: no
REQ: REQ-002
DEPENDS: T-001
ACCEPTANCE: the coverage report shows all requirements are covered
TEST: a test asserts the coverage report contains no uncovered requirements
