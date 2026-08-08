# Changelog

## 0.1.0 - 2026-07-15

First corpus-driven stabilization release for PerlGraph as an incubator for
future CodeGraph Perl support.

### Added

- Static AUTOLOAD accessor extraction with retained AUTOLOAD diagnostics.
- High-confidence `use parent` / `use base` inheritance extraction.
- Moose/Moo roles, attributes, required methods, modifier target evidence, and
  dedicated `moose_around_orig` diagnostics.
- Unambiguous implicit export resolution for local modules.
- Common DBI and Opta database receiver-flow inference.
- Bounded dynamic self-dispatch recovery from:
  - literal scalar method variables
  - ternary literal method variables
  - static loop lists
  - static arrays
  - static hash keys
  - multiline static map lists
  - can-guarded implicit loop dispatch
  - Moose modifier bodies
- Typeglob assignment diagnostics with literal target evidence.
- Dedicated diagnostic categories for dynamic eval-use and Moose around
  continuation dispatch.

### Changed

- Dynamic method diagnostics now ignore arrows inside strings and comments.
- Static loop cleanup is indentation-aware, so hash dereferences and inner
  blocks no longer clear outer loop evidence too early.
- Dynamic diagnostics now carry more target/evidence metadata where static
  evidence is strong, while preserving uncertainty for runtime Perl behavior.

### Corpus Baseline

Against the Opta Perl corpus in `/Users/michalbachorik/work/optaperl/sources`,
the current unsupported-pattern baseline is:

- `autoload`: 139
- `dynamic_method`: 32
- `dynamic_require`: 14
- `dynamic_use`: 1
- `eval_string`: 6
- `glob_assignment`: 4
- `moose_around_orig`: 1
- `moose_modifier`: 27
- `symbolic_ref`: 1

### Roadmap

Remaining work is tracked in GitHub issues #50 through #57:

- argument-sourced method-list inference
- static closure factories that install methods
- dynamic action/command dispatch classification
- runtime config setter classification
- dynamic require evidence improvements
- remaining AUTOLOAD accessor evidence
- string eval intent splitting
- non-self dynamic receiver dispatch evidence
