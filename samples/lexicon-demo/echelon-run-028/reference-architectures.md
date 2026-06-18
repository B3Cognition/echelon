# Reference Architectures

> Greenfield domain research. Word-frequency-with-top-N is the canonical
> Knuth/McIlroy "word count problem" (Bentley's 1986 *Programming Pearls*
> column). Below are four well-documented reference implementations spanning the
> minimalist, the programmatic, the library-grade, and the cross-language corpus.

## 1. McIlroy's Unix pipeline (the canonical minimal solution)
- **Source:** Doug McIlroy's reply to Knuth, *Programming Pearls* (1986); summarized at https://leancrew.com/all-this/2011/12/more-shell-less-egg/ and https://franklinchen.com/blog/2011/12/08/revisiting-knuth-and-mcilroys-word-count-programs/
- **Relevance:** Solves *exactly* this problem — "list the N most-used words by frequency." It is the reference definition of correct behaviour.
- **Key entities:** stream of characters → one-word-per-line stream → sorted words → counted runs → frequency-sorted list → top N.
- **Boundaries:** Each pipeline stage is a boundary: `tr -cs A-Za-z '\n'` (tokenize: complement+squeeze non-letters to newlines), `tr A-Z a-z` (case fold), `sort`, `uniq -c` (aggregate), `sort -rn` (rank by frequency desc), `sed Nq` (truncate to N).
- **Patterns used:** Unix pipe composition; small single-purpose stages; tokenization-by-delimiter-complement.
- **Lessons:** (+) Defines the canonical tokenization (alphabetic runs) and case-folding defaults. (+) Single streaming pass conceptually. (−) Tie-break is whatever `sort` does — *not* explicitly deterministic across locales; our tool should specify a total tie-break. (−) ASCII-only (`A-Za-z`) — silently wrong on non-ASCII text.

## 2. Programmatic counter implementations (Ben Hoyt's "Counting Words" study)
- **Source:** https://benhoyt.com/writings/count-words/ (performance comparison of word-count-top-N across Python, Go, C++, C, AWK, Rust, etc.)
- **Relevance:** Same problem implemented imperatively; documents the standard in-memory algorithm and its performance/correctness trade-offs.
- **Key entities:** input stream → normalized tokens → hash-map of word→count (the tally) → partial sort / heap for top-N → output.
- **Boundaries:** read+decode, normalize (lowercase), split on whitespace, increment map, select top-N (full sort vs. heap of size N), print.
- **Patterns used:** Hash-map aggregation; "optimal" variant uses a bounded heap to get top-N without fully sorting all distinct words; case-normalize before counting.
- **Lessons:** (+) For top-N specifically, a size-N heap avoids sorting the whole tally — relevant if N ≪ distinct words and inputs are large. (+) Memory is bounded by *distinct* words, not input size. (−) The "simple whitespace split" variant differs from McIlroy's alphabetic-run split on punctuation/contractions — proof that the tokenization rule is a real, observable decision.

## 3. `wordfreq` library (tokenization/normalization rigor)
- **Source:** https://pypi.org/project/wordfreq/ ; Unicode tokenization per UAX-29.
- **Relevance:** Represents the *correct-for-real-text* end of the spectrum — how a serious tool handles multilingual tokenization and normalization, even though it targets frequency *lookup* rather than per-file counting.
- **Key entities:** locale-aware tokenizer → normalized tokens (NFC/NFKC, case fold) → frequency data.
- **Boundaries:** explicit, configurable tokenization boundary; Unicode normalization boundary; per-language strategy (CJK via segmentation libraries, ligature/combining-mark handling for Arabic/Hebrew).
- **Patterns used:** Unicode Annex #29 text segmentation; normalization-before-counting; language-specific tokenizers.
- **Lessons:** (+) Naive letter-splitting breaks on CJK (no spaces), combining marks, and ligatures — quantifies the U-001/unknown-unknown risk. (+) Normalization must precede counting to collapse equivalent encodings. (−) Full Unicode correctness is heavyweight; for a minimal CLI it is legitimate to scope to whitespace/punctuation-delimited scripts *if stated explicitly*.

## 4. Rosetta Code "Word frequency" (cross-language corpus)
- **Source:** https://rosettacode.org/wiki/Word_frequency ; also Baeldung's Unix recipe https://www.baeldung.com/linux/n-most-frequent-words-in-file
- **Relevance:** Dozens of independent implementations of *this exact task* across languages — a consensus sample of how the problem is conventionally solved.
- **Key entities:** consistent across implementations — tokenize, fold case, tally in a map, sort by count desc, take N.
- **Boundaries:** same five-stage shape (read → tokenize → tally → rank → print) recurs everywhere.
- **Patterns used:** Map-based tally + descending sort by count + truncate; near-universal default of case-insensitive, regex/alphabetic tokenization.
- **Lessons:** (+) Confirms the canonical pipeline shape and the case-insensitive default as domain invariants. (−) Implementations diverge precisely on tokenization regex and tie-break — reinforcing that these must be *decided and specified*, not left implicit.

## Common Patterns Across References (likely domain invariants)

1. **Five-stage pipeline:** read+decode → tokenize/normalize → aggregate into a distinct-word tally → rank by frequency descending → truncate to N and print. Every reference shares this shape.
2. **Case-insensitive by default:** fold case before counting (McIlroy, Hoyt, Rosetta majority).
3. **Single conceptual pass to build the tally;** memory bounded by *distinct* word count, not total tokens.
4. **Top-N = sort-by-count-descending then take N**, with the option to use a bounded heap when N ≪ distinct words.
5. **Counts are integers (absolute frequency),** not proportions, unless explicitly requested.

## Divergence Points (likely design decisions for our tool)

- **Tokenization rule:** alphabetic-run (McIlroy) vs. whitespace-split (some Hoyt variants) vs. Unicode-segmentation (`wordfreq`). → ties to U-001 / A-001. **Must decide.**
- **Tie-break ordering:** unspecified (McIlroy's bare `sort`) vs. explicit lexicographic secondary key. → ties to A-003. Choose an explicit, total, locale-independent rule for determinism.
- **Unicode/multilingual scope:** ASCII-only vs. full UAX-29. → ties to the Unicode unknown-unknown. Pick a scope and *state the limitation*.
- **Output content:** words-only vs. word+count; plain vs. structured. → ties to U-005 / A-009.
- **Input contract:** file-only vs. file-or-stdin vs. multiple files. → ties to U-002 / A-006.
