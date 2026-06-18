ARTIFACT: SPEC
TITLE: Word Frequency Counter Command-Line Tool

REQ: FR-001
GIVEN: a readable file path is provided as the input argument
WHEN: the tool is invoked
THEN: the tool MUST read the entire contents of that file as the input text
OUTPUT: the full character stream of the named file is available to the counting pipeline

REQ: FR-002
GIVEN: a single dash is provided as the input argument
WHEN: the tool is invoked
THEN: the tool MUST read the input text from standard input instead of from a file
OUTPUT: the character stream piped on standard input is available to the counting pipeline

REQ: FR-003
GIVEN: a byte stream acquired from the chosen input source
WHEN: the tool reads the input
THEN: the tool MUST decode the bytes as UTF-8 text before tokenization
OUTPUT: a sequence of Unicode characters decoded from the input bytes

REQ: FR-004
GIVEN: a decoded stream of Unicode characters
WHEN: the tool tokenizes the input
THEN: the tool MUST treat every maximal run of Unicode letter characters as one word and treat every other character as a delimiter between words
OUTPUT: an ordered sequence of word tokens with all non-letter characters discarded

REQ: FR-005
GIVEN: a sequence of word tokens
WHEN: the tool normalizes each token
THEN: the tool MUST convert each word token to lowercase before counting so that words differing only in letter case are counted as one word
OUTPUT: a sequence of lowercase word tokens

REQ: FR-006
GIVEN: a sequence of lowercase word tokens
WHEN: the tool aggregates the tokens
THEN: the tool MUST count the number of occurrences of each distinct word across the whole input
OUTPUT: a tally that maps each distinct word to its integer occurrence count

REQ: FR-007
GIVEN: a tally of distinct words and their occurrence counts
WHEN: the tool ranks the words
THEN: the tool MUST order the words by occurrence count from highest to lowest
OUTPUT: a list of words ordered by descending occurrence count

REQ: FR-008
GIVEN: two or more words that share the same occurrence count
WHEN: the tool orders those equally frequent words
THEN: the tool MUST place them in ascending order by their Unicode code point sequence
OUTPUT: a total ordering of words in which equal counts are resolved by ascending word order
CONSTRAINT: the resulting ordering is identical across operating systems and locale settings

REQ: FR-009
GIVEN: a ranked list of words and a requested count N
WHEN: the tool selects the result
THEN: the tool MUST keep only the first N words from the ranked list
OUTPUT: the top N words in ranked order

REQ: FR-010
GIVEN: an input whose number of distinct words is less than the requested count N
WHEN: the tool selects the result
THEN: the tool MUST return every distinct word as a successful run without raising an error
OUTPUT: the complete list of distinct words, fewer than N entries, with a success exit status

REQ: FR-011
GIVEN: an invocation that does not specify the count option
WHEN: the tool resolves its configuration
THEN: the tool MUST use a default count of ten for N
OUTPUT: a resolved count N equal to ten whenever the count option is omitted
CONSTRAINT: the default count equals 10

REQ: FR-012
GIVEN: a count option value supplied on the command line
WHEN: the tool validates its configuration
THEN: the tool MUST accept the count value only when it is an integer greater than zero
OUTPUT: a validated positive integer count, or a rejected invocation when the value is not a positive integer

REQ: FR-013
GIVEN: the selected top N words together with their counts
WHEN: the tool renders the result
THEN: the tool MUST write one line per word to standard output, each line carrying the word followed by one space and then its occurrence count
OUTPUT: one text line per reported word holding the word, a single space, and the integer count
CONSTRAINT: result lines are ordered from highest occurrence count to lowest

REQ: FR-014
GIVEN: any diagnostic or error message produced during a run
WHEN: the tool reports that message
THEN: the tool MUST direct every diagnostic and error message to standard error and keep standard output limited to result lines
OUTPUT: diagnostic text on standard error while standard output holds only result lines

REQ: FR-015
GIVEN: the completion state of a run
WHEN: the tool exits
THEN: the tool MUST return an exit status of zero on a successful run and a non-zero exit status on any input, argument, or read failure
OUTPUT: a process exit status of zero for success and non-zero for failure

REQ: FR-016
GIVEN: an input that contains no letters and therefore yields zero word tokens
WHEN: the tool produces the result
THEN: the tool MUST write no result lines and exit with a success status for that input
OUTPUT: an empty result accompanied by a success exit status

REQ: FR-017
GIVEN: an input of unbounded length
WHEN: the tool processes the input
THEN: the tool MUST build the word tally in a single pass over the input
OUTPUT: a completed tally produced by one traversal of the input
CONSTRAINT: peak working memory grows with the number of distinct words and not with the total input length

REQ: FR-018
GIVEN: the same input text and the same count N on two separate runs
WHEN: the tool runs on different machines or under different locale settings
THEN: the tool MUST produce identical output for both runs
OUTPUT: byte-for-byte identical result lines across repeated runs and platforms

REQ: FR-019
GIVEN: a downstream consumer that closes standard output before all result lines are written
WHEN: the tool attempts to write further output
THEN: the tool MUST stop writing and exit without printing a stack trace
OUTPUT: a clean termination with no stack trace when the output stream is closed early

ERROR: E-001
WHEN: the named input file does not exist or cannot be read
THEN: report the cause on standard error, write no result lines, and exit with a non-zero status
ERROR_CODE: NOINPUT

ERROR: E-002
WHEN: the supplied count option is not an integer greater than zero
THEN: report the rejected value on standard error, write no result lines, and exit with a non-zero status
ERROR_CODE: USAGE

ERROR: E-003
WHEN: the input bytes are not valid UTF-8 text
THEN: report the decoding failure on standard error, write no result lines, and exit with a non-zero status
ERROR_CODE: DECODE

AC: AC-001
GIVEN: a file whose contents are the words the fox the dog the the fox
WHEN: the tool runs on that file with a count of two
THEN: standard output holds two lines, the first being the word the with the number four and the second being the word fox with the number two

AC: AC-002
GIVEN: a file whose contents are the words The THE the
WHEN: the tool runs on that file with a count of one
THEN: standard output holds one line carrying the word the with the number three

AC: AC-003
GIVEN: a file in which the words banana and apple each occur exactly twice and no other word occurs more often
WHEN: the tool runs with a count of one
THEN: standard output holds the single line for apple because apple precedes banana in ascending order, and the same line is produced on every run

AC: AC-004
GIVEN: a file that contains only three distinct words
WHEN: the tool runs with a count of ten
THEN: standard output holds exactly three lines and the exit status is zero

AC: AC-005
GIVEN: a path that names a file which does not exist
WHEN: the tool runs on that path
THEN: an error message naming the missing path appears on standard error, standard output stays empty, and the exit status is non-zero

AC: AC-006
GIVEN: a file of zero length
WHEN: the tool runs on that file with any count
THEN: standard output stays empty and the exit status is zero

AC: AC-007
GIVEN: a count option value of zero
WHEN: the tool runs with that option
THEN: an error message appears on standard error, standard output stays empty, and the exit status is non-zero

AC: AC-008
GIVEN: a downstream reader that closes the pipe after reading the first line
WHEN: the tool writes its result into that pipe
THEN: the tool stops without printing a stack trace and signals no failure for the closed pipe

AC: AC-009
GIVEN: text supplied on standard input together with a single dash as the path argument
WHEN: the tool runs
THEN: the tool counts the piped text and writes the top words to standard output exactly as it would for a file holding the same contents
