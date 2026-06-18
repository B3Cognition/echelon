# Overview: Word Frequency Counter Command-Line Tool

**Feature**: `028-word-frequency-counter`
**Status**: Planned
**Spec format**: Lexicon controlled grammar (`spec.md` is an `ARTIFACT: SPEC` document — validated by the deterministic `lexicon` hard gate, not free-form markdown).

> This is the first file to read. It is the human-readable companion to the
> machine-validated `spec.md`. Where `spec.md` is terse and gate-checked, this
> document explains *what the tool does*, *why each contested decision was made*,
> and *what is deliberately out of scope*.

## 1. What the feature does

A single-process command-line utility that reads a UTF-8 text file (or standard
input), counts how often each word occurs, and prints the **top N most frequent
words** — highest frequency first — one word and its count per line to standard
output. It is the canonical Knuth/McIlroy "word count" problem with the edge
cases pinned down so the result is reproducible.

The pipeline is the five-stage shape every reference implementation shares:

```
read + UTF-8 decode → tokenize + lowercase → tally distinct words
   → rank by count (desc), tie-break ascending → truncate to N → print
```

## 2. Key design decisions (resolved unknowns)

The happy path is trivial; the risk lives entirely in edge definitions. These are
the decisions that turn a "self-consistent but arguably wrong" tool into a
specified one. Each was resolved with a reference-architecture-backed default
under `banzai` autonomy (no human in the loop); each is revisitable.

| Decision | Choice (this spec) | Why | Trace |
|----------|--------------------|-----|-------|
| **What is a "word"?** | A maximal run of **Unicode letters**; every non-letter (whitespace, punctuation, **digits**, apostrophes, hyphens, underscores) is a delimiter | Canonical McIlroy/Rosetta default; total and testable. Consequence: `don't` → `don` + `t`, `COVID-19` → `covid`, `3.14` drops entirely | FR-004; U-001 / A-001 |
| **Case sensitivity** | Case-**insensitive**; fold to lowercase before counting | Default of McIlroy's pipeline and the majority of reference tools | FR-005; A-002 |
| **Tie-break** | Equal counts ordered **ascending by Unicode code point**; total, locale-independent | Closes McIlroy's non-deterministic `sort` gap; makes output reproducible and the N-boundary deterministic | FR-008; A-003 |
| **Distinct words < N** | Print all of them, exit 0 — not an error | Matches `head -n` expectation; avoids breaking scripted pipelines | FR-010; A-004 |
| **How N is supplied** | A count option, **default 10** when omitted; must be an integer > 0 | `head`-like ergonomics; default keeps the tool usable with no flags | FR-011, FR-012; U-003 / A-008 |
| **Output content** | `word<space>count`, one per line, highest first | "Prints the top N words" is ambiguous on counts; showing counts is the standard, more useful reading | FR-013; U-005 / A-009 |
| **Encoding** | UTF-8; invalid bytes → clean decode error + non-zero exit (no traceback) | Dominant modern encoding; erroring beats silent mojibake | FR-003, E-003; A-005 |
| **Input contract** | One file path argument; a single `-` reads standard input | Idiomatic, composable in pipelines; multiple files / globbing out of scope | FR-001, FR-002; U-002 / A-006 |

## 3. Primary constraints

- **Determinism (FR-018, FR-008):** identical input + identical N ⇒ byte-for-byte
  identical output across machines and locales. This is a correctness property,
  not a nicety — it is what makes the tool testable.
- **Memory (FR-017):** peak memory grows with the count of **distinct** words, not
  total input size; the tally is built in a single pass.
- **Stream discipline (FR-014):** results to standard output, diagnostics to
  standard error, so output stays machine-parseable.
- **Robust process contract (FR-015, FR-019):** exit 0 on success, non-zero on any
  failure; a downstream consumer that closes the pipe early (e.g. piping into
  `head`) terminates cleanly with no stack trace.

## 4. Error behaviour

| Condition | Outcome | Code |
|-----------|---------|------|
| File missing / unreadable | message to stderr, no output, non-zero exit | `NOINPUT` (E-001) |
| N not a positive integer | usage error to stderr, no output, non-zero exit | `USAGE` (E-002) |
| Input not valid UTF-8 | decode error to stderr, no output, non-zero exit | `DECODE` (E-003) |
| Empty / all-delimiter input | no output, exit 0 (success) | — (FR-016) |

## 5. Scope

**MVP (must-have):** read a file, UTF-8 decode, letter-run tokenize, case-fold,
tally, rank with deterministic tie-break, truncate to N (default 10), print
`word count` lines, correct exit codes, the three error paths above, and the
empty-input and fewer-than-N cases. Requirements FR-001..FR-018 and E-001..E-003.

**Should-have:** standard-input via `-` (FR-002) and graceful broken-pipe handling
(FR-019) — included here because they make the tool composable, but a first build
could defer them without breaking the core promise.

**Explicitly out of scope (deferred or excluded):**
- Multiple input files, directory globbing, recursive search.
- Stop-word removal (A-011) — all words are counted.
- Relative frequencies / proportions — counts are absolute integers only.
- **Scriptio-continua languages** (Chinese, Japanese, Thai) and full UAX-29
  segmentation. The "maximal run of letters" rule does not segment languages that
  do not use spaces; this is a stated, honest limitation, not a silent bug. A
  future iteration may adopt Unicode word segmentation.
- Unicode normalization (precomposed vs. decomposed forms) is **not** performed in
  the MVP — `café` written two ways may count as two words. Flagged for HOW.

## 6. Open items carried into HOW (for ARCHITECT / planning)

- **Input scale (U-004):** the single-pass in-memory tally is assumed sufficient.
  If inputs with hundreds of millions of *distinct* words are expected, a bounded
  top-N heap (size N) avoids fully sorting the tally — an optimisation decision for
  HOW, not a requirement change.
- **Unicode normalization (U-005 follow-on):** whether to apply NFC before counting
  so equivalent encodings collapse. Out of MVP scope; recorded for a later revision.
- **Flag spelling:** the exact name of the count option (e.g. `-n` / `--number` /
  `--top`) is left to ARCHITECT; the spec fixes only its meaning and default.

## 7. Entity model (summary)

The spec operates over: **Input Text** → **Token** (word occurrence) → **Word
Entry** (distinct word + count) → **Frequency Tally** (all word entries) →
**Top-N Result** (ranked, tie-broken, truncated) → **Output Report** (stdout
lines). See `mental-model.md` for the full relationship map and `glossary.md` for
term definitions and disambiguations.
