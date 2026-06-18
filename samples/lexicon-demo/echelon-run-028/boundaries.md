# System Boundaries

> Domain: single-process command-line word-frequency tool. The system is small,
> so boundaries are primarily the seams between processing stages and the edges
> where it touches the operating environment.

## Internal Boundaries

### Argument / Configuration boundary
- **Responsibility:** Parse and validate the command line; resolve the Run Configuration (input source, N, tokenization options, output format). Reject invalid input before any processing.
- **Interfaces:** Consumes raw argv; produces a validated configuration object for the rest of the pipeline.
- **Data ownership:** All user-supplied parameters and their defaults; validation rules (N positive integer, source resolvable).

### Input / Reading boundary
- **Responsibility:** Acquire the Input Text from the chosen source and decode bytes to characters per the encoding decision.
- **Interfaces:** Receives a source identifier from configuration; emits a character stream to the tokenizer.
- **Data ownership:** File handle / stream lifecycle, encoding handling, EOF detection.

### Tokenization / Normalization boundary
- **Responsibility:** Convert the character stream into normalized Tokens per the Tokenization Rule (delimiters, case folding, Unicode normalization, optional stop-word removal).
- **Interfaces:** Consumes characters; emits normalized word tokens.
- **Data ownership:** The tokenization rule and the definition of "word" — the single most behaviour-defining seam.

### Aggregation boundary
- **Responsibility:** Accumulate token occurrences into the Frequency Tally (distinct word → count).
- **Interfaces:** Consumes tokens; owns the in-memory tally; exposes it to ranking when input is exhausted.
- **Data ownership:** The complete distinct-word → frequency mapping; total/distinct counts.

### Ranking boundary
- **Responsibility:** Sort by frequency descending, apply the deterministic tie-break, truncate to N (or fewer).
- **Interfaces:** Consumes the finalized tally; emits the ordered Top-N Result.
- **Data ownership:** Sort order policy, tie-break policy, N-boundary inclusion rule.

### Output / Rendering boundary
- **Responsibility:** Format and write the Top-N Result to stdout in the chosen format.
- **Interfaces:** Consumes the ranked result; writes to the output stream.
- **Data ownership:** Line format, ordering of rendered output, output destination.

## External Boundaries

### Filesystem (input file)
- **Type:** infrastructure (OS file I/O)
- **Dependency strength:** hard (the named file is the primary input per the request)
- **Data flow:** inbound — file contents read into the tool.
- **Failure impact:** Missing / unreadable / permission-denied file → tool must fail fast with a clear stderr message and non-zero exit; no top-N produced.

### Standard input (stdin)
- **Type:** infrastructure (OS stream)
- **Dependency strength:** optional (idiomatic CLI alternative to a file argument; decision to support is open)
- **Data flow:** inbound — piped text into the tool.
- **Failure impact:** If unsupported and a user pipes data, they get no result; if supported, enables composition with other tools.

### Standard output (stdout)
- **Type:** infrastructure (OS stream)
- **Dependency strength:** hard (the result destination)
- **Data flow:** outbound — the Top-N report.
- **Failure impact:** Broken pipe (e.g., downstream `head` closes early) must be handled gracefully, not crash with a stack trace.

### Standard error (stderr)
- **Type:** infrastructure (OS stream)
- **Dependency strength:** hard (diagnostics and error reporting)
- **Data flow:** outbound — error and warning messages, kept separate from stdout so results stay machine-parseable.
- **Failure impact:** If diagnostics leak to stdout, they corrupt the parseable result stream.

### Process exit code
- **Type:** infrastructure (OS contract)
- **Dependency strength:** hard (how callers/scripts detect success vs. failure)
- **Data flow:** outbound — 0 on success, non-zero on error.
- **Failure impact:** Wrong codes break shell pipelines and CI usage.

### Locale / encoding environment
- **Type:** infrastructure (environment)
- **Dependency strength:** soft (influences case folding, sorting, and byte→character decoding)
- **Data flow:** inbound configuration signal.
- **Failure impact:** Locale-dependent case folding or sort order makes output non-reproducible across machines — argues for a fixed, documented behaviour rather than locale-driven.

## Trust Boundaries

- **Input validation:** Occurs at the Argument/Configuration boundary (N is a positive integer; source identifier well-formed) and at the Input/Reading boundary (file exists and is readable). All user input is untrusted until validated.
- **No authn/authz:** Single-user local CLI; no authentication or authorization surfaces.
- **Untrusted content:** The input *file contents* are fully untrusted and arbitrary (binary bytes, enormous files, adversarial Unicode). The tool must not assume well-formed text — it must degrade gracefully (e.g., on invalid encoding) rather than crash or exhaust memory. This is the main security-relevant boundary.
- **Resource boundary:** A pathologically large or unique-word-dense file is a denial-of-resource concern; the aggregation boundary owns the memory-growth risk (distinct-word set, not total tokens, drives memory).
