# Unknowns

> Greenfield. The deceptive part of this domain: the *happy path is trivial*
> (split, count, sort, take N), so almost all real risk lives in under-specified
> edge definitions. The known unknowns below are the questions that, left
> unanswered, cause a "correct" tool to produce results the user considers wrong.

## Known Unknowns

### U-001: What exactly is a "word"?
- **Why it matters:** Defines the entire output. Apostrophes (`don't`), hyphens (`co-op`), digits (`COVID-19`, `3.14`), underscores (`user_id`), and accented letters each have to fall on one side of the word/delimiter line. This is the highest-impact unknown.
- **Who can answer:** user (product decision), informed by reference architectures.
- **Priority:** must-resolve-before-WHAT
- **Related assumptions:** A-001, A-002, A-005

### U-002: What is the input contract — file only, also stdin, multiple files?
- **Why it matters:** Changes the argument interface and the reading boundary. Supporting stdin makes the tool composable in Unix pipelines; supporting multiple files raises "aggregate vs. per-file" questions.
- **Who can answer:** user.
- **Priority:** must-resolve-before-WHAT
- **Related assumptions:** A-006

### U-003: How is N supplied, and is there a default?
- **Why it matters:** Positional argument vs. named option (e.g., `-n`); whether omitting N defaults (commonly 10) or is an error. Affects the CLI contract and validation rules.
- **Who can answer:** user.
- **Priority:** must-resolve-before-WHAT
- **Related assumptions:** A-008

### U-004: What is the expected input scale?
- **Why it matters:** Determines whether single-pass in-memory aggregation is sufficient or whether very large / streaming inputs (bigger than memory, or with millions of distinct words) must be handled. Memory is driven by *distinct* word count, not total size.
- **Who can answer:** user / experimentation (benchmark on representative corpus).
- **Priority:** should-resolve-before-HOW
- **Related assumptions:** A-010

### U-005: Exact output format — words only, or words with counts? Field order? Machine-readable mode?
- **Why it matters:** The request says "prints the top N most frequent words," which is ambiguous on whether counts are shown. Format also decides pipeline-friendliness (e.g., an optional structured/columnar mode).
- **Who can answer:** user.
- **Priority:** should-resolve-before-HOW
- **Related assumptions:** A-009

### U-006: Behaviour on degenerate inputs — empty file, all-punctuation, decode failure?
- **Why it matters:** Defines exit codes and messages for empty result, unreadable file, and non-UTF-8 / binary content. Affects robustness and scriptability.
- **Who can answer:** user / domain convention.
- **Priority:** should-resolve-before-HOW
- **Related assumptions:** A-005, A-015, A-016

## Potential Unknown Unknowns

- **Area:** Unicode word segmentation and normalization.
  - **Why suspicious:** A naive "letters vs. non-letters" split silently mishandles scripts without spaces (Chinese, Japanese, Thai), combining marks, ligatures, and locale-specific casing (e.g., Turkish dotless-i). The tool can appear correct on English and be quietly wrong on real-world multilingual text. The "word" concept itself does not exist uniformly across languages.
  - **Recommended investigation:** Have INVESTIGATOR test candidate tokenization against multilingual fixtures (CJK, accented Latin, RTL) and check normalization (precomposed vs. decomposed forms collapsing). Decide explicit scope: "ASCII/whitespace-delimited languages only" is a legitimate, honest limitation if stated.

- **Area:** Tie-break and sort stability interaction with large equal-frequency clusters.
  - **Why suspicious:** Real text has long tails where hundreds of words share frequency 1 or 2. At the N boundary this means an arbitrary cut unless the tie-break is total and deterministic. Subtle bugs hide here (e.g., platform-dependent sort, non-total ordering) and only surface on specific inputs.
  - **Recommended investigation:** INVESTIGATOR should construct inputs with deliberate frequency ties straddling the Nth position and verify cross-platform deterministic output.

- **Area:** Stream/pipe lifecycle and partial-output behaviour.
  - **Why suspicious:** When composed in a pipeline (e.g., piped into `head`), the downstream consumer may close the pipe early, raising broken-pipe conditions that crash naive implementations with an ugly traceback and non-zero exit. Easy to miss because it never happens in unit tests.
  - **Recommended investigation:** INVESTIGATOR should test the tool inside real shell pipelines that close stdout early, and verify graceful handling.
