# PerlGraph

PerlGraph is a static structural graph extractor for Perl repositories. It
parses Perl files, extracts packages and subs, resolves module dependencies,
and emits confidence-aware call graph artifacts.

## Usage

```bash
npm install
npm run build
node dist/cli/perlgraph.js analyze \
  --repo-path /path/to/repo \
  --output-path perlgraph-analysis.json \
  --summary-path perlgraph-summary.json
```

## Status

The project is an incubator for future CodeGraph Perl support. The core graph
output is standalone and has no Echelon dependency.

The `0.1.0` line is the first corpus-driven stabilization release. It has been
tested against the Opta Perl corpus under
`/Users/michalbachorik/work/optaperl/sources` and now resolves many common Perl
patterns while keeping genuinely dynamic behavior visible as diagnostics.

Current Opta corpus diagnostic baseline:

- `autoload`: 139
- `dynamic_method`: 32
- `dynamic_require`: 14
- `dynamic_use`: 1
- `eval_string`: 6
- `glob_assignment`: 4
- `moose_around_orig`: 1
- `moose_modifier`: 27
- `symbolic_ref`: 1

PerlGraph intentionally does not erase these diagnostics just to look clean.
They are evidence for downstream tools that static analysis should not
overclaim.

## Supported Evidence

PerlGraph currently extracts or annotates:

- packages, subs, methods, module dependencies, inheritance, roles, exports, and
  call relationships
- Moose/Moo roles, attributes, required methods, modifiers, and around
  continuation diagnostics
- static `use parent` / `use base` inheritance targets
- unambiguous implicit exports from local modules
- common DBI and Opta database receiver flows
- static AUTOLOAD accessor targets while retaining AUTOLOAD uncertainty
- bounded `$self->$method` dispatch from literal scalars, static loops, static
  arrays, static hash keys, static multiline maps, guarded `->can($_)` loops,
  and Moose modifier bodies
- typeglob diagnostics with literal target evidence
- separated diagnostics for dynamic require, dynamic eval-use, string eval,
  symbolic references, and dynamic dispatch

## Roadmap

Remaining corpus-backed work is tracked in GitHub:

- [#50 Infer argument-sourced method lists from local call sites](https://github.com/B3Cognition/perlgraph/issues/50)
- [#51 Model static closure factories that install reader methods](https://github.com/B3Cognition/perlgraph/issues/51)
- [#52 Classify dynamic action and command dispatch patterns](https://github.com/B3Cognition/perlgraph/issues/52)
- [#53 Classify runtime config setter dispatch separately](https://github.com/B3Cognition/perlgraph/issues/53)
- [#54 Improve dynamic require diagnostics with local class evidence](https://github.com/B3Cognition/perlgraph/issues/54)
- [#55 Audit remaining AUTOLOAD diagnostics for additional accessor evidence](https://github.com/B3Cognition/perlgraph/issues/55)
- [#56 Split remaining string eval diagnostics by intent](https://github.com/B3Cognition/perlgraph/issues/56)
- [#57 Model non-self dynamic receiver dispatch evidence](https://github.com/B3Cognition/perlgraph/issues/57)

## Install Notes

`tree-sitter-perl@1.1.2` declares an optional peer on `tree-sitter@^0.22.0`,
but its generated parser uses Tree-sitter ABI 15. PerlGraph therefore pins the
parser runtime with an npm override to `tree-sitter@0.25.0`, which preserves
real `tree-sitter-perl` parsing and keeps npm dependency resolution healthy.

On Node 26, native `tree-sitter@0.25.0` builds may require C++20 explicitly:

```sh
CXXFLAGS=-std=c++20 npm install
CXXFLAGS=-std=c++20 npm ci
```

If your compiler defaults need GNU extensions, use `CXXFLAGS=-std=gnu++20`
instead.
