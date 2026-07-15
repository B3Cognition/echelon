# PerlGraph Output Contract

PerlGraph emits a CodeGraph-shaped JSON artifact for Perl repositories.

## Analysis

Required top-level fields:

- `schema_version`: currently `1`
- `tool`: always `perlgraph`
- `generated_at`: ISO timestamp
- `repo_path`: absolute analyzed repository path
- `supported`: true when supported Perl files were found
- `language_coverage`: supported Perl extensions
- `symbols`: file, package, sub, method, test, constant, and variable symbols
- `relationships`: imports, requires, inherits, calls, tests, and references
- `call_graph`: compact calls-only edge list
- `module_graph`: Perl module dependency edges
- `unsupported_patterns`: dynamic constructs that reduce confidence
- `parse_failures`: per-file extraction failures captured during fail-open analysis
- `index_stats`: counts and index state

## Confidence

- `high`: direct static target
- `medium`: likely target inferred from local context
- `low`: name or convention-based candidate
- `dynamic`: runtime behavior that cannot be safely resolved statically

Consumers must not treat low-confidence or dynamic edges as proof of behavior.
