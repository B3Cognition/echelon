ARTIFACT: SPEC
TITLE: Minimal fixture spec for structural gate tests

REQ: FR-001
GIVEN: a valid input document
WHEN: the structural gate runs
THEN: the system MUST return a clean gate result
OUTPUT: a StructuralReport with ok=True
EXAMPLE: AC-001

AC: AC-001
GIVEN: a valid input document
WHEN: the structural gate runs
THEN: the report has ok=True and an empty findings list
