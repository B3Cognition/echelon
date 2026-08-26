# SOURCE: spec.md
# SOURCE_SHA256: 902c3af380d3ba2f8440fb987dbc9d3b9e70967b35afc79019da205060784650
ARTIFACT: SPEC
TITLE: SUE Challenge Script v1 question-answer dialogue tier

REQ: FR-001
GIVEN: an operator command invocation
WHEN: the challenge script parses its arguments
THEN: the challenge script MUST accept exactly 1 positional argument naming the specification file to challenge
OUTPUT: a parsed run configuration holding the specification path
DEPENDS: none
EXAMPLE: AC-001

REQ: FR-002
GIVEN: an operator command invocation
WHEN: the challenge script parses its arguments
THEN: the challenge script MUST accept a question-count option defaulting to 15 that caps round-1 questions
OUTPUT: a parsed run configuration holding the question cap
DEPENDS: FR-001
EXAMPLE: AC-020

REQ: FR-003
GIVEN: an operator command invocation
WHEN: the challenge script parses its arguments
THEN: the challenge script MUST accept a model-command option defaulting to claude that names exactly 1 challenge model command line
OUTPUT: a parsed run configuration holding the model command
DEPENDS: FR-001
EXAMPLE: AC-021

REQ: FR-004
GIVEN: an operator command invocation
WHEN: the challenge script parses its arguments
THEN: the challenge script MUST accept a timeout option defaulting to 300 seconds that bounds each model call
OUTPUT: a parsed run configuration holding the per-call timeout
DEPENDS: FR-001
EXAMPLE: AC-017

REQ: FR-005
GIVEN: a specification path that is missing or unreadable
WHEN: the challenge script starts a run
THEN: the challenge script MUST exit with code 1 before launching any model call
OUTPUT: exit code 1 plus 1 diagnostic line
DEPENDS: FR-001
EXAMPLE: AC-013

REQ: FR-006
GIVEN: a specification directory that is not writable for the report
WHEN: the challenge script starts a run
THEN: the challenge script MUST exit with code 1 before launching any model call
OUTPUT: exit code 1 plus 1 diagnostic line
DEPENDS: FR-001
EXAMPLE: AC-019

REQ: FR-007
GIVEN: a model-command option value
WHEN: the challenge script parses the option
THEN: the challenge script MUST split the value into words per shell quoting conventions treating the leading word as the executable
OUTPUT: an argument vector whose leading word is the executable to check
DEPENDS: FR-003
EXAMPLE: AC-014

REQ: FR-008
GIVEN: a validated run configuration
WHEN: a challenge run executes
THEN: the challenge script MUST perform exactly 2 logical model calls
OUTPUT: round-1 output plus round-2 output
DEPENDS: FR-005, FR-006
EXAMPLE: AC-001

REQ: FR-009
GIVEN: validated round-2 answers
WHEN: the challenge script filters, ranks, or renders
THEN: the challenge script MUST perform exactly 0 further model calls
OUTPUT: findings plus report produced by local computation only
DEPENDS: FR-008
EXAMPLE: AC-001

REQ: FR-010
GIVEN: a model subprocess about to launch
WHEN: the challenge script starts the subprocess
THEN: the challenge script MUST set the subprocess working directory to a newly created neutral temporary directory
OUTPUT: a subprocess running outside the repository directory
DEPENDS: FR-008
EXAMPLE: AC-012

REQ: FR-011
GIVEN: a running model subprocess
WHEN: the subprocess exceeds its timeout budget
THEN: the challenge script MUST end the call, classifying it as a parse failure
OUTPUT: a parse-failure signal routed to the retry path
DEPENDS: FR-004, FR-008
EXAMPLE: AC-017

REQ: FR-012
GIVEN: a model-command executable that cannot be found
WHEN: the challenge script checks command availability
THEN: the challenge script MUST exit with code 2, printing exactly 1 installation pointer
OUTPUT: exit code 2 plus 1 installation pointer message
DEPENDS: FR-007
EXAMPLE: AC-014

REQ: FR-013
GIVEN: a corrective retry about to launch
WHEN: the retry subprocess starts
THEN: the challenge script MUST grant the retry a fresh timeout budget equal to the configured timeout
OUTPUT: a retry subprocess with a full timeout budget
DEPENDS: FR-004, FR-011
EXAMPLE: AC-016

REQ: FR-014
GIVEN: the specification text
WHEN: the challenge script builds the round-1 prompt
THEN: the challenge script MUST include the line-numbered specification text plus the question-generation instruction
OUTPUT: a round-1 prompt with exactly 2 elements
DEPENDS: FR-008
EXAMPLE: AC-001

REQ: FR-015
GIVEN: the round-1 prompt under construction
WHEN: the question-generation instruction is written
THEN: the instruction MUST request at most N questions targeting the 5 weakness categories
OUTPUT: an instruction naming the question cap plus the 5 categories
DEPENDS: FR-002, FR-014
EXAMPLE: AC-020

REQ: FR-016
GIVEN: raw round-1 output
WHEN: the challenge script validates it
THEN: the challenge script MUST verify each question carries 1 unique identifier, 1 question text, 1 target, integer line references, plus 1 category
OUTPUT: a validated question list or a parse-failure signal
DEPENDS: FR-014
EXAMPLE: AC-001

REQ: FR-017
GIVEN: round-1 output that fails validation
WHEN: validation completes
THEN: the challenge script MUST classify the output as a parse failure
OUTPUT: a parse-failure signal consuming 1 retry attempt
DEPENDS: FR-016
EXAMPLE: AC-015

REQ: FR-018
GIVEN: specification text being embedded in a prompt
WHEN: either prompt is built
THEN: the challenge script MUST prefix every line with its line number starting at 1
OUTPUT: line-numbered specification text
DEPENDS: FR-014
EXAMPLE: AC-009

REQ: FR-019
GIVEN: valid round-1 output with more than N questions
WHEN: validation completes
THEN: the challenge script MUST keep only the first N questions in returned order, recording a truncation note
OUTPUT: a question list of exactly N entries plus a truncation note
DEPENDS: FR-002, FR-016
EXAMPLE: AC-020

REQ: FR-020
GIVEN: valid round-1 output with 0 questions
WHEN: the run continues
THEN: the challenge script MUST complete the run without round 2, producing a zero-question report
OUTPUT: a report recording 0 questions plus exit code 0
DEPENDS: FR-016
EXAMPLE: AC-006

REQ: FR-021
GIVEN: validated round-1 questions
WHEN: the challenge script builds the round-2 prompt
THEN: the challenge script MUST include exactly 2 content blocks holding the line-numbered specification text plus the question identifiers with their texts
OUTPUT: a round-2 prompt with exactly 2 content blocks
DEPENDS: FR-016, FR-018
EXAMPLE: AC-011

REQ: FR-022
GIVEN: the round-2 prompt under construction
WHEN: content is added
THEN: the prompt MUST NOT contain round-1 categories, targets, line references, or reasoning
OUTPUT: a round-2 prompt free of round-1 rationale
DEPENDS: FR-021
EXAMPLE: AC-011

REQ: FR-023
GIVEN: the round-2 prompt under construction
WHEN: the answering instruction is written
THEN: the instruction MUST direct the model to answer each question from the specification text alone with exactly 1 verdict per question
OUTPUT: an answering instruction naming the 3 verdicts
DEPENDS: FR-021
EXAMPLE: AC-004

REQ: FR-024
GIVEN: raw round-2 output
WHEN: the challenge script validates it
THEN: the challenge script MUST verify each answer carries 1 question identifier, 1 verdict, 1 answer text, plus integer evidence line references
OUTPUT: a validated answer list or a parse-failure signal
DEPENDS: FR-021
EXAMPLE: AC-004

REQ: FR-025
GIVEN: validated round-1 identifiers plus round-2 answers
WHEN: identifier bijection is checked
THEN: the challenge script MUST classify any missing, duplicate, or unknown identifier as a parse failure
OUTPUT: a bijection-clean answer list or a parse-failure signal
DEPENDS: FR-016, FR-024
EXAMPLE: AC-018

REQ: FR-026
GIVEN: raw model output
WHEN: the challenge script extracts JSON
THEN: the challenge script MUST extract exactly 1 JSON object, tolerating surrounding text plus code fences
OUTPUT: exactly 1 extracted JSON object
DEPENDS: FR-008
EXAMPLE: AC-016

REQ: FR-027
GIVEN: raw model output with no extractable JSON object
WHEN: extraction completes
THEN: the challenge script MUST classify the output as a parse failure
OUTPUT: a parse-failure signal
DEPENDS: FR-026
EXAMPLE: AC-015

REQ: FR-028
GIVEN: the first parse failure in a round
WHEN: recovery starts
THEN: the challenge script MUST issue exactly 1 corrective retry appending a corrective instruction naming the validation failure
OUTPUT: 1 retry subprocess with the corrected prompt
DEPENDS: FR-017, FR-025, FR-027
EXAMPLE: AC-016

REQ: FR-029
GIVEN: a first failure that was a timeout
WHEN: the corrective retry is built
THEN: the retry MUST re-issue the same prompt with 0 appended corrective text
OUTPUT: 1 retry subprocess with the unchanged prompt
DEPENDS: FR-011, FR-028
EXAMPLE: AC-017

REQ: FR-030
GIVEN: the second parse failure in the same round
WHEN: recovery is exhausted
THEN: the challenge script MUST exit with code 3 after saving the raw output into the debug dump directory beside the specification
OUTPUT: exit code 3 plus saved raw output
DEPENDS: FR-028
EXAMPLE: AC-015

REQ: FR-031
GIVEN: a round-2 failure ending the run
WHEN: the run aborts
THEN: the challenge script MUST NOT re-run round 1
OUTPUT: 0 additional round-1 calls
DEPENDS: FR-030
EXAMPLE: AC-015

REQ: FR-032
GIVEN: validated answers
WHEN: deterministic assembly starts
THEN: the challenge script MUST partition answers into exactly 2 groups holding findings plus audit entries
OUTPUT: a findings list plus an audit list
DEPENDS: FR-024, FR-025
EXAMPLE: AC-004

REQ: FR-033
GIVEN: the findings list
WHEN: findings are ranked
THEN: the challenge script MUST place all CONTRADICTED findings before all UNANSWERABLE findings preserving round-1 order within each class
OUTPUT: an ordered findings list
DEPENDS: FR-032
EXAMPLE: AC-004

REQ: FR-034
GIVEN: a successful run
WHEN: the report is written
THEN: the challenge script MUST write exactly 1 report file in the specification directory replacing any previous report
OUTPUT: exactly 1 report file beside the challenged specification
DEPENDS: FR-032
EXAMPLE: AC-003

REQ: FR-035
GIVEN: the report under construction
WHEN: sections are rendered
THEN: the report MUST contain exactly 3 sections in order holding header, findings, plus audit appendix
OUTPUT: a report with 3 ordered sections
DEPENDS: FR-034
EXAMPLE: AC-002

REQ: FR-036
GIVEN: the report header under construction
WHEN: the header is rendered
THEN: the header MUST state the specification path, run date, question count, finding count, plus any truncation note
OUTPUT: a header with 4 base facts
DEPENDS: FR-035
EXAMPLE: AC-002

REQ: FR-037
GIVEN: a finding being rendered
WHEN: the findings section is written
THEN: each entry MUST state the verdict, the question, the target requirement identifier, plus the evidence
OUTPUT: findings entries with 4 elements each
DEPENDS: FR-033, FR-035
EXAMPLE: AC-004

REQ: FR-038
GIVEN: audit entries
WHEN: the audit appendix is rendered
THEN: the appendix MUST list every ANSWERED question with its answering lines inside exactly 1 collapsed section
OUTPUT: a collapsed audit appendix
DEPENDS: FR-032, FR-035
EXAMPLE: AC-008

REQ: FR-039
GIVEN: cited evidence line numbers
WHEN: evidence is rendered
THEN: the report MUST quote exactly 1 line of specification text per cited number, stating the named gap for UNANSWERABLE findings
OUTPUT: quoted evidence lines plus named gaps
DEPENDS: FR-018, FR-037
EXAMPLE: AC-009

REQ: FR-040
GIVEN: a written report
WHEN: the run finishes
THEN: the challenge script MUST print a terminal summary stating finding counts per verdict class plus the top 3 findings
OUTPUT: a terminal summary plus exit code 0
DEPENDS: FR-034
EXAMPLE: AC-005

REQ: FR-041
GIVEN: answers where every verdict is ANSWERED
WHEN: the report is rendered
THEN: the findings section MUST state that 0 findings were produced
OUTPUT: a clean-specification report plus exit code 0
DEPENDS: FR-032, FR-035
EXAMPLE: AC-007

REQ: FR-042
GIVEN: any challenge run
WHEN: the run finishes on any path
THEN: the challenge script MUST NOT modify the challenged specification file
OUTPUT: an unchanged specification file
DEPENDS: FR-001
EXAMPLE: AC-010

REQ: FR-043
GIVEN: an operator-supplied model command
WHEN: model calls launch
THEN: the challenge script MUST execute the supplied command in place of the default
OUTPUT: stubbed runs with 0 live model calls
DEPENDS: FR-003, FR-007
EXAMPLE: AC-021

REQ: FR-044
GIVEN: the repository test suite
WHEN: unit tests run
THEN: the deliverable MUST include automated unit tests covering the 7 deterministic behavior groups runnable with 0 live model access
OUTPUT: a passing offline unit test suite
DEPENDS: FR-043
EXAMPLE: AC-022

REQ: FR-045
GIVEN: a challenge run
WHEN: the challenge script reads input
THEN: the challenge script MUST read only command-line arguments plus the challenged specification file
OUTPUT: 0 orchestration configuration reads
DEPENDS: FR-001
EXAMPLE: AC-021

REQ: NFR-001
GIVEN: any terminating run
WHEN: wall-clock time is measured
THEN: the run MUST finish within 4 timeout budgets plus 60 seconds
OUTPUT: a bounded run duration
DEPENDS: FR-011, FR-013
EXAMPLE: AC-017

REQ: NFR-002
GIVEN: a fresh repository checkout
WHEN: the challenge script plus unit tests execute
THEN: the challenge script MUST run with 0 additional installed components beyond the standard runtime plus the model command
OUTPUT: a working run on a fresh checkout
DEPENDS: FR-044, FR-045
EXAMPLE: AC-022

REQ: NFR-003
GIVEN: the script usage text
WHEN: an operator reads it
THEN: the usage text MUST contain exactly 1 disclosure that specification content is sent to the model provider
OUTPUT: 1 egress disclosure statement
DEPENDS: FR-003
EXAMPLE: AC-021

REQ: NFR-004
GIVEN: identical validated answers assembled twice
WHEN: the 2 report bodies are compared
THEN: the 2 report bodies MUST be identical outside the run-date field
OUTPUT: byte-identical report bodies excluding run date
DEPENDS: FR-032, FR-036
EXAMPLE: AC-003

REQ: NFR-005
GIVEN: a non-zero exit
WHEN: the challenge script terminates
THEN: the challenge script MUST print exactly 1 diagnostic line naming the failure class to the error stream
OUTPUT: 1 diagnostic line per failure
DEPENDS: FR-005, FR-012, FR-030
EXAMPLE: AC-013

AC: AC-001
GIVEN: a readable specification with an available model command
WHEN: the operator runs the challenge script
THEN: exactly 2 model calls occur, the challenge report is written into the specification directory, with exit code 0

AC: AC-002
GIVEN: a completed challenge run
WHEN: the operator opens the challenge report
THEN: the report header states exactly 4 facts holding the specification path, the run date, the question count, plus the finding count

AC: AC-003
GIVEN: a challenge report exists from a previous run
WHEN: the operator reruns the challenge script
THEN: exactly 1 report file remains, holding only the new run content

AC: AC-004
GIVEN: round 2 returned mixed verdicts
WHEN: the report is assembled
THEN: the findings section holds exactly 2 verdict classes ordered with all CONTRADICTED entries before all UNANSWERABLE entries

AC: AC-005
GIVEN: a run completes with at least 1 finding
WHEN: the run finishes
THEN: the terminal summary states the finding count per verdict class, listing the top 3 findings in rank order

AC: AC-006
GIVEN: round 1 returns a valid empty question list
WHEN: the run continues
THEN: round 2 is skipped, the report records exactly 0 questions with 0 findings, with exit code 0

AC: AC-007
GIVEN: every round-2 verdict is ANSWERED
WHEN: the report is assembled
THEN: the findings section states that exactly 0 findings were produced, with the audit appendix holding every question, with exit code 0

AC: AC-008
GIVEN: a question received an ANSWERED verdict
WHEN: the report is rendered
THEN: that question appears in the audit appendix with its quoted answering lines inside exactly 1 collapsed section the reader can expand

AC: AC-009
GIVEN: a round-2 answer cites evidence line numbers
WHEN: the report renders that answer
THEN: the report quotes exactly 1 line of text per cited number as read from the specification file

AC: AC-010
GIVEN: any challenge run
WHEN: the run finishes with any exit code
THEN: the challenged specification file received exactly 0 writes, leaving its content unchanged

AC: AC-011
GIVEN: a stub model command that records its prompt
WHEN: round 2 executes
THEN: the recorded prompt holds exactly 2 content blocks with exactly 0 round-1 categories, targets, line tags, or reasoning

AC: AC-012
GIVEN: a stub model command that records its working directory
WHEN: either round executes
THEN: the recorded directory is exactly 1 newly created temporary directory outside the repository

AC: AC-013
GIVEN: a specification path that does not exist or cannot be read
WHEN: the operator runs the challenge script
THEN: the exit code is 1 with exactly 0 model calls launched

AC: AC-014
GIVEN: the model command executable cannot be found
WHEN: the operator runs the challenge script
THEN: the exit code is 2, the message includes exactly 1 installation pointer, with 0 reports written

AC: AC-015
GIVEN: a round output fails validation on both the initial call plus the corrective retry
WHEN: the second failure occurs
THEN: the exit code is 3, the raw output is saved into the debug dump directory, with 0 reports written

AC: AC-016
GIVEN: a round first output is invalid while its retry output is valid
WHEN: the run continues
THEN: exactly 2 subprocess invocations occurred for that round, with the run completing at exit code 0

AC: AC-017
GIVEN: a model call exceeds its timeout budget of at most 300 seconds by default
WHEN: the timeout expires
THEN: the call is classified as a parse failure, exactly 1 retry is issued, with a second failure ending the run at exit code 3

AC: AC-018
GIVEN: round-2 answers with a missing, duplicate, or unknown question identifier
WHEN: validation runs
THEN: the output is classified as a parse failure consuming exactly 1 corrective retry

AC: AC-019
GIVEN: the specification directory is not writable
WHEN: the operator runs the challenge script
THEN: the exit code is 1 with exactly 0 model calls launched

AC: AC-020
GIVEN: valid round-1 output holding more than N questions
WHEN: validation runs
THEN: exactly N questions remain in returned order, with the report header carrying 1 truncation note

AC: AC-021
GIVEN: a stub executable configured as the model command
WHEN: a full challenge run executes
THEN: the run completes end-to-end using exactly 0 live model calls

AC: AC-022
GIVEN: the repository automated test suite
WHEN: the challenge script unit tests run
THEN: all tests pass with exactly 0 network calls plus exactly 0 live model commands installed

AC: AC-023
GIVEN: exactly 1 manual live acceptance run against the designated acceptance target
WHEN: the run completes
THEN: a report exists whose findings overlap at least 1 of the 3 named known issues, within at most 3 total attempts

ERROR: ERR-001
WHEN: the specification path is missing or unreadable
THEN: reject the run with exit code 1 before any model call
ERROR_CODE: EXIT-1

ERROR: ERR-002
WHEN: the specification directory is not writable
THEN: reject the run with exit code 1 before any model call
ERROR_CODE: EXIT-1

ERROR: ERR-003
WHEN: the model-command executable is not found
THEN: reject the run with exit code 2 printing exactly 1 installation pointer
ERROR_CODE: EXIT-2

ERROR: ERR-004
WHEN: model output stays unusable after exactly 1 corrective retry in either round
THEN: abort with exit code 3 saving the raw output to the debug dump directory
ERROR_CODE: EXIT-3

ERROR: ERR-005
WHEN: a model call exceeds its timeout
THEN: recover through the parse-failure path with exactly 1 retry then exit code 3 on a second failure
ERROR_CODE: EXIT-3
