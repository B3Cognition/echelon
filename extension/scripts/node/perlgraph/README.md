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

The project is an incubator for future CodeGraph Perl support. The core graph output is standalone and has no Echelon dependency.

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
