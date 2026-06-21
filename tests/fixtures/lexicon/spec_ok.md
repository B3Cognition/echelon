ARTIFACT: SPEC
TITLE: Lexicon fixture spec

REQ: REQ-001
GIVEN: a valid input document
WHEN: the parser processes the document
THEN: the system MUST return a structured parse tree
OUTPUT: a parse tree object
EXAMPLE: AC-001

REQ: REQ-002
GIVEN: the parse tree is produced
WHEN: the cross-doc gate runs
THEN: the system MUST confirm all requirements are covered
OUTPUT: a coverage report
EXAMPLE: AC-002

AC: AC-001
GIVEN: a valid input document
WHEN: the parser processes the document
THEN: a parse tree is returned with all expected nodes

AC: AC-002
GIVEN: the parse tree is produced
WHEN: the cross-doc gate runs
THEN: the coverage report shows all requirements are covered
