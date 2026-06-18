# Mental Model

> Domain: command-line word-frequency counter. Entities are conceptual data
> objects in the counting pipeline, kept implementation-neutral.

## Core Entities

### Input Text
- **Description:** The raw character stream to be analyzed — the contents of the named file (or stdin).
- **Key attributes:** source identifier (path / "stdin"), encoding, size.
- **Relationships:** tokenized into many Tokens.
- **Lifecycle:** opened → read (whole or streamed) → consumed → closed.

### Token (Word Occurrence)
- **Description:** One individual occurrence of a word produced by applying the tokenization rule to the Input Text.
- **Key attributes:** surface form, normalized form (after case/Unicode folding).
- **Relationships:** many Tokens map to one Word Entry (by normalized form).
- **Lifecycle:** emitted by tokenizer → normalized → folded into a Word Entry's count → discarded.

### Tokenization Rule
- **Description:** The configurable policy defining what counts as a word: word-character set, delimiters, case folding, Unicode normalization.
- **Key attributes:** delimiter definition, case sensitivity flag, normalization form, stop-word policy.
- **Relationships:** governs how Input Text becomes Tokens.
- **Lifecycle:** resolved once at startup from defaults + user options; constant during a run.

### Word Entry (Frequency Record)
- **Description:** A distinct normalized word together with its accumulated frequency.
- **Key attributes:** normalized word form, frequency (integer count), optional representative surface form.
- **Relationships:** aggregates many Tokens; participates in the Ranking.
- **Lifecycle:** created on first occurrence → incremented on each further occurrence → ranked → possibly emitted in result.

### Frequency Tally
- **Description:** The complete collection of Word Entries — the full distinct-word → count mapping for the Input Text.
- **Key attributes:** number of distinct words, total token count.
- **Relationships:** contains all Word Entries; input to Ranking.
- **Lifecycle:** built during the single pass over Tokens; finalized when input is exhausted.

### Ranking / Top-N Result
- **Description:** The ordered subset of Word Entries selected and sorted for output: highest frequency first, tie-break applied, truncated to N.
- **Key attributes:** N (requested size), sort order (frequency desc, then tie-break), actual size (≤ N).
- **Relationships:** derived from Frequency Tally; rendered to Output.
- **Lifecycle:** computed after the tally is complete → rendered → released.

### Output Report
- **Description:** The rendered, human- (and ideally machine-) readable listing of the Top-N Result.
- **Key attributes:** line format (word + count), ordering, destination (stdout).
- **Relationships:** serialization of the Ranking.
- **Lifecycle:** produced once at the end; written to stdout.

### Run Configuration
- **Description:** The resolved set of user inputs governing a single invocation: input source, N, and tokenization options.
- **Key attributes:** input path, N value, case/normalization/stop-word flags, output format.
- **Relationships:** parameterizes every other entity.
- **Lifecycle:** parsed from command-line arguments at startup; validated; constant thereafter.

## Relationships

| Entity A | Relationship | Entity B | Cardinality | Notes |
|----------|--------------|----------|-------------|-------|
| Input Text | is split into | Token | one-to-many | governed by Tokenization Rule |
| Tokenization Rule | governs | Token production | one-to-many | resolved from Run Configuration |
| Token | folds into | Word Entry | many-to-one | grouping key = normalized form |
| Word Entry | belongs to | Frequency Tally | many-to-one | tally = all distinct words |
| Frequency Tally | is ranked into | Top-N Result | one-to-one (derives) | sort + tie-break + truncate to N |
| Top-N Result | is rendered as | Output Report | one-to-one | to stdout |
| Run Configuration | parameterizes | all entities | one-to-many | one config per invocation |

## Concept Map

```
 Run Configuration ──parameterizes──> [ whole pipeline ]
        │
        ▼
   Input Text ──(Tokenization Rule)──> Token* ──normalize──> Word Entry*
                                                                 │ aggregate
                                                                 ▼
                                                        Frequency Tally
                                                                 │ sort by freq desc,
                                                                 │ tie-break, take N
                                                                 ▼
                                                          Top-N Result ──render──> Output Report (stdout)
```

## Behavioral Patterns

**Primary workflow (single happy path):**
1. Parse arguments → resolve Run Configuration (input source, N, options); validate N is a positive integer and the source is readable.
2. Read Input Text (single streaming pass is sufficient and memory-friendly).
3. For each Token: normalize (case fold / Unicode form per rule), optionally drop stop words, increment its Word Entry in the Frequency Tally.
4. After input exhausted: sort Word Entries by frequency descending, apply tie-break (e.g., word ascending) for determinism, truncate to N.
5. Render Output Report to stdout.

**Key state transition — N vs. distinct-word count:**
- If distinct words ≥ N → emit exactly N entries.
- If distinct words < N → emit all entries (fewer than N); this is success, not an error.

**Boundary / error flows:**
- Missing or unreadable file → error to stderr, non-zero exit, no partial top-N.
- Empty input (or all-delimiter input) → zero Word Entries → emit empty result (and exit success) or an explicit "no words" notice — a decision to record.
- N ≤ 0 or non-integer → argument validation error to stderr, non-zero exit.
- Ties at the N boundary → tie-break rule fully determines who makes the cut; output must be deterministic across runs and platforms.
