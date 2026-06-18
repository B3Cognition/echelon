# Assumptions

> Greenfield project. Each assumption is tagged with its source (user statement,
> reference architecture, or domain standard) and a validation method. Several
> "critical" assumptions are actually *open product decisions* the user must
> confirm before WHAT — they are the highest-leverage clarifications.

## Critical Assumptions

### A-001: Definition of a "word" (tokenization rule)
- **Statement:** A word is a maximal run of letter characters; runs of non-letters (whitespace, punctuation, digits) act as delimiters and are discarded.
- **Basis:** Canonical McIlroy/Knuth solution and most reference tools default to alphabetic-run tokenization (reference-architecture).
- **Risk if wrong:** This single choice changes *every* count and the entire result. E.g., whether `don't`, `co-op`, `3.14`, `user_id`, or `café` are one token, several, or dropped. Misalignment with user intent makes the tool "wrong" while passing its own tests.
- **Validation method:** Ask the user directly; provide 2–3 worked examples (`"don't"`, `"co-op"`, `"COVID-19"`) showing tokenization under each candidate rule and have them pick. Resolve before WHAT.
- **Status:** unvalidated

### A-002: Case-insensitive counting (case folding on)
- **Statement:** Counting is case-insensitive by default — `The`, `the`, and `THE` are the same word, normalized to lowercase.
- **Basis:** Default of McIlroy's pipeline (`tr A-Z a-z`) and most word-frequency tools (reference-architecture).
- **Risk if wrong:** If the user wants case-sensitive counts (e.g., distinguishing proper nouns), default folding produces incorrect results.
- **Validation method:** Confirm with user; offer a case-sensitive flag if there's any doubt. Cheap to make configurable.
- **Status:** unvalidated

### A-003: Deterministic tie-break exists and is specified
- **Statement:** When two words share a frequency, they are ordered by the word ascending (lexicographic) as the secondary sort key, so output is fully deterministic.
- **Basis:** Common reference-tool convention; required for reproducible output and testability (reference-architecture, standard).
- **Risk if wrong:** Without a defined tie-break, results are non-deterministic across runs/platforms at equal frequencies and at the N-boundary (which words make the cut becomes arbitrary) — breaking tests and user trust.
- **Validation method:** Specify the rule in the spec; write acceptance tests with deliberate ties at and across the N boundary.
- **Status:** unvalidated

### A-004: Behaviour when distinct words < N
- **Statement:** If the input has fewer than N distinct words, the tool prints all of them (fewer than N) and exits successfully — it is not an error.
- **Basis:** Standard CLI expectation (like `head -n`); domain convention.
- **Risk if wrong:** Erroring or padding would surprise users and break scripted pipelines.
- **Validation method:** Acceptance test with N greater than distinct-word count; confirm exit 0 and partial list.
- **Status:** unvalidated

### A-005: Input encoding is UTF-8
- **Statement:** The input file is decoded as UTF-8 by default.
- **Basis:** Dominant modern text encoding (standard).
- **Risk if wrong:** Legacy-encoded files (e.g., Latin-1) or binary files produce mojibake or decode errors; wrong counts for non-ASCII text.
- **Validation method:** Confirm target inputs are UTF-8; define behaviour on decode failure (error vs. lossy replacement). Test with a non-ASCII fixture.
- **Status:** unvalidated

## Standard Assumptions

- **A-006: Single named input file.** The primary input is one file path supplied on the command line, as stated in the request. *(Source: user. Validate: confirm whether multiple files / globbing / stdin are also in scope — see U-002.)*
- **A-007: Results go to stdout, diagnostics to stderr.** Standard CLI stream discipline so output stays pipeable. *(Source: standard. Validate: confirm acceptable.)*
- **A-008: N is a required, user-supplied positive integer.** Provided as an argument/option each run. *(Source: user — "top N". Validate: decide whether N has a default, e.g., 10, if omitted — see U-003.)*
- **A-009: Output format is one word + its count per line, highest first.** A simple, human- and machine-readable listing. *(Source: reference-architecture. Validate: confirm format and field order; decide whether counts are shown — the phrase "prints the top N most frequent words" could mean words only.)*
- **A-010: Single-pass, in-memory aggregation is acceptable.** Typical inputs fit in memory; one streaming read suffices. *(Source: domain norm. Validate: confirm no requirement for files larger than memory — see U-004.)*
- **A-011: No stop-word removal by default.** All words counted; common-word filtering is not implied by the request. *(Source: reference-architecture. Validate: confirm.)*

## Low-Risk Assumptions

- **A-012:** Reproducible, locale-independent behaviour is preferred over locale-driven case/sort, so output is identical across machines.
- **A-013:** No persistence — the tool computes and prints, storing nothing between runs.
- **A-014:** No network access required; purely local computation.
- **A-015:** Exit code 0 on success, non-zero on any input/argument/IO error.
- **A-016:** Empty or all-delimiter input yields an empty (zero-word) result with a success exit, rather than an error. *(Borderline — worth a quick confirm.)*
