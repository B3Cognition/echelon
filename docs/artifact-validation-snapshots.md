# Artifact validation snapshots

Echelon exposes text-only validation functions for callers that have already
captured the bytes of ancillary artifacts as UTF-8 text:

- `source_contract_findings_text(derived_text, *, source_text, source_name)`
  checks Lexicon source metadata, exact source-text freshness, and declared
  FR/NFR/REQ/AC/ERR/ERROR identity equivalence. `source_name` is compared by
  basename and is never opened.
- `source_approved_terms_text(source_text)` extracts measurable identifier
  terms already owned by the source.
- `parse_glossary_terms(text)` parses the same glossary heading, bold-term,
  and plain-line forms accepted by the legacy glossary loader.
- `validate_spec_lexicon_texts(...)` applies the real Lexicon grammar and
  validity rules plus the source contract. Its result contains only
  `schema_version`, `artifact_type`, `artifact_sha256`, `source_sha256`,
  `glossary_sha256`, `ok`, and `findings`.
- `validate_evidence_inventory_text(text, *, required_seed_locators=())`
  applies the existing evidence-inventory JSON structure and declared-seed
  checks.

## Exact snapshot semantics

The text functions perform no filesystem reads or writes. Each non-null digest
is `SHA256(text.encode("utf-8"))` over the exact supplied text, including its
Unicode content and LF or CRLF line endings. A missing glossary is represented
by `glossary_text=None`, contributes no terms, and has a null digest. A supplied
empty glossary contributes no terms but has the SHA256 digest of empty bytes.

These functions validate captured text; they do not add paths, timestamps, or
publication authority. The evidence-inventory validator remains a structural
source-discovery check. Locator strings are opaque and do not declare or bind
requirement, acceptance-criterion, or error identities.

## Legacy Path compatibility

Existing Path APIs remain available. They read text using `Path.read_text`,
which performs universal-newline normalization, and then delegate rule
evaluation to the shared text algorithms. The spec Path gate continues to add
its artifact, source, and glossary path fields and continues to report digests
of the raw files. This preserves legacy behavior for CRLF files even though the
rule evaluation sees normalized newlines.

Consequently, a legacy Path report is not proof of an atomic immutable capture
and does not authorize managed publication. It may describe a mutable file
that was read separately for evaluation and hashing.

## Remaining integration

No managed run is activated by these APIs. A future managed candidate bundle
must capture and bind the exact source, projection, and optional glossary text;
define the source-inventory artifact scope and explicit associations; enforce
issue-occurrence and interval or qualified-reference policies; authenticate
canonical and staged bytes; complete semantic review; and durably publish the
authorized bundle. That integration must validate the captured snapshot rather
than trusting a separately reread legacy report.
