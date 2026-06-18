# Domain Glossary

> Domain: text frequency analysis / command-line word counting.
> All terms kept implementation-neutral (no languages, frameworks, or data structures).

## Terms

### Word
- **Definition:** A maximal contiguous run of characters that the tool treats as a single countable token, per the tool's tokenization rule.
- **Context:** The unit of counting. Everything the tool reports is a count of words.
- **Disambiguation:** "Word" is *defined by the tokenization rule*, not by natural language. Under an alphabetic-run rule, `don't` may become two tokens (`don`, `t`); under a Unicode-segmentation rule it may stay one. The chosen rule must be stated explicitly because it changes every output.
- **Source:** user, reference-architecture

### Token / Tokenization
- **Definition:** A token is the output of *tokenization* — the process of splitting raw input text into words. The tokenization rule decides delimiters, what characters are "inside" a word, and what is discarded.
- **Context:** The first transformation in the pipeline; defines the universe of countable items.
- **Disambiguation:** Distinct from "word" in that tokenization is the *process/rule*, word is the *result*. Distinct from "term" in NLP (no stemming/lemmatization implied).
- **Source:** standard, reference-architecture

### Frequency (Word Frequency)
- **Definition:** The number of times a given word occurs in the input.
- **Context:** The metric ranked to produce the result.
- **Disambiguation:** Absolute count (an integer), not relative frequency (a proportion) unless explicitly requested. "Top N" ranks by this count descending.
- **Source:** user

### Count
- **Definition:** Synonym for absolute frequency: integer occurrences of a word.
- **Context:** The number printed alongside each reported word.
- **Disambiguation:** "Word count" colloquially can mean *total tokens in the document* (as in `wc -w`); here it means *per-word occurrence count*. This overload is dangerous — see Overloaded Terms.
- **Source:** user, standard

### Top N
- **Definition:** The N words with the highest frequency, in descending frequency order, where N is a user-supplied positive integer.
- **Context:** The core deliverable: "prints the top N most frequent words."
- **Disambiguation:** Requires a defined behaviour when distinct-word-count < N (return fewer) and when frequencies tie at the Nth position (tie-break rule decides who is included).
- **Source:** user

### Tie / Tie-breaking
- **Definition:** The situation where two or more words share the same frequency, and the rule that decides their relative order (and, at the N boundary, inclusion).
- **Context:** Determines output determinism. A common rule is alphabetical ascending as the secondary sort key.
- **Disambiguation:** Without a defined tie-break, output is non-deterministic for equal-frequency words — a correctness, not cosmetic, concern.
- **Source:** reference-architecture, standard

### Case folding (normalization)
- **Definition:** Treating different letter cases of the same word as equal (e.g., `The` and `the`) by normalizing case before counting.
- **Context:** A pre-count normalization step that materially changes counts.
- **Disambiguation:** Case-*insensitive* counting (default in most reference tools) vs. case-*sensitive* (each casing distinct). Separate from Unicode normalization.
- **Source:** reference-architecture

### Unicode normalization
- **Definition:** Converting equivalent character encodings (e.g., precomposed vs. combining-mark sequences) into a canonical form so visually identical strings compare equal.
- **Context:** Affects whether accented/composed words collapse correctly during counting.
- **Disambiguation:** Distinct from case folding (which handles case) and from encoding (which handles bytes→characters).
- **Source:** standard (Unicode Annex #15/#29)

### Delimiter / Separator
- **Definition:** Characters that break the input into words (whitespace, punctuation, digits, depending on the rule).
- **Context:** The complement of "word characters" in the tokenization rule.
- **Source:** standard

### Stop words
- **Definition:** Very common words (e.g., "the", "a", "of") that some tools exclude from frequency results as noise.
- **Context:** Optional filtering; many minimal tools do NOT remove them.
- **Disambiguation:** Excluding stop words is a *product decision*, not a default of frequency counting. Must be explicit.
- **Source:** reference-architecture

### Input source
- **Definition:** The text the tool reads — a named file per the request, with standard input (stdin) as a common idiomatic alternative for CLI tools.
- **Context:** Defines the external boundary the tool reads from.
- **Source:** user

### Encoding
- **Definition:** The mapping from input bytes to characters (commonly UTF-8 by default for modern text tools).
- **Context:** Must be decided before tokenization; wrong assumption corrupts non-ASCII text.
- **Source:** standard

## Overloaded Terms

| Term | Context A | Meaning A | Context B | Meaning B |
|------|-----------|-----------|-----------|-----------|
| Count / "word count" | This tool | Per-word occurrence frequency | `wc -w` convention | Total number of tokens in the whole document |
| Frequency | This tool (default) | Absolute integer occurrences | Linguistics / `wordfreq` | Relative proportion (count ÷ total) |
| Word | Alphabetic-run tokenizer | Maximal run of letters | Unicode word-segmentation / whitespace split | Segment per UAX-29 / run between whitespace (may include digits, apostrophes) |
| Top | "Top N by frequency" | Highest-frequency words | "Top of file" | Positional, unrelated |
| N | This request | Count of words to report | Some tools | A threshold frequency cutoff (report words occurring ≥ N times) |
