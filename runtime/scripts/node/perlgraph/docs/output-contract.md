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

## Resolved Static Patterns

PerlGraph resolves these patterns when the target symbol or module is visible
in the repository:

- `use`, `require`, `use parent`, and `use base` module dependencies
- static `require "My/Module.pm"` and static quoted-string concatenations
- Moose/Moo `extends`, `with`, `requires`, and `has` declarations
- direct package calls such as `My::Service::run()` and `My::Service->new()`
- `$self->method` / `$class->method` in the current package
- inherited `$self->method` / `$class->method`, including transitive static parents
- role-provided `$self->method` / `$class->method` from static Moose/Moo roles
- local receiver flow from `Class->new`, static class aliases, and simple local
  factory subs that return `Class->new`

## Diagnostic Patterns

These patterns remain evidence of uncertainty unless a narrower static rule
explicitly resolves them:

- `AUTOLOAD`
- AUTOLOAD dispatch maps
- dynamic `require $module`
- string `eval`
- typeglob assignment
- symbolic references
- dynamic method names such as `$obj->$method()`
- symbolic method receivers such as `${$pkg}->method()`
- Moose/Moo method modifiers such as `before`, `after`, and `around`

## Provenance

Common provenance values:

- `tree-sitter`: source parsed with tree-sitter-perl
- `line-scan`: lightweight extraction from source text
- `module-resolution`: module target checked against repository files
- `name-resolution`: lexical/package call matched a known symbol
- `self-method-resolution`: `$self` / `$class` matched the current package
- `inheritance-method-resolution`: method matched a static parent chain
- `role-method-resolution`: method matched a static Moose/Moo role
- `local-constructor-flow`: receiver type inferred from local constructor flow
- `moose-moo-role`, `moose-moo-attribute`, `moose-moo-requires`: explicit
  framework rules, not generic Perl inference
