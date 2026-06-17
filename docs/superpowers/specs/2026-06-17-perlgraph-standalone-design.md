# PerlGraph Standalone Design

## Goal

Create a standalone TypeScript/Node structural analysis tool for Perl codebases, tentatively named `perlgraph`, that produces high-quality symbol, dependency, and call graph artifacts from Tree-sitter Perl parsing.

The tool is intentionally separate from Echelon. Echelon is the first consumer, not the owner of the core graph logic. The implementation should be shaped so the validated extractor and resolver work can later be contributed to `colbymchenry/codegraph` as Perl language support.

## Problem

CodeGraph gives Echelon useful structural evidence for supported languages, but current upstream and Echelon-vendored CodeGraph builds do not support Perl. Perl-heavy repositories therefore fall back to file scanning and LLM inspection, which is weaker for reverse engineering, verification, blast-radius analysis, and test targeting.

Perl also has real static-analysis hazards:

- package names do not always map cleanly to file paths
- runtime symbol table mutation can create or replace call targets
- object dispatch through `$obj->method` is often only partially inferable
- Moose, Moo, roles, `AUTOLOAD`, `eval`, and dynamic `require` patterns reduce certainty
- test files often encode behavior through conventions rather than explicit import graphs

The design therefore treats uncertainty as first-class graph metadata instead of pretending to produce a perfect static graph.

## Non-Goals

- No MCP server.
- No direct dependency on Echelon internals in the standalone tool.
- No promise of perfect runtime dispatch resolution.
- No full Moose/Moo meta-object model in the first production version.
- No execution of Perl code. Analysis is static only.

## Repository Shape

The standalone repository should be TypeScript/Node to stay close to CodeGraph's architecture and contribution path.

```text
perlgraph/
  package.json
  tsconfig.json
  src/
    cli/
      perlgraph.ts
    extraction/
      grammar.ts
      perl-extractor.ts
      tree-sitter-helpers.ts
    resolution/
      module-resolver.ts
      call-resolver.ts
      inheritance-resolver.ts
      method-confidence.ts
    output/
      schema.ts
      summary.ts
      writer.ts
    types.ts
  fixtures/
    procedural/
    modules/
    oo-basic/
    inheritance/
    tests/
    dynamic-patterns/
  tests/
    extraction/
    resolution/
    snapshots/
  docs/
    output-contract.md
    codegraph-upstream-notes.md
```

## CLI Contract

Primary command:

```bash
perlgraph analyze --repo-path /path/to/repo --output-path perlgraph-analysis.json
```

Useful options:

- `--summary-path <path>`: write compact summary JSON.
- `--include <glob>`: include only matching paths.
- `--exclude <glob>`: exclude matching paths.
- `--max-symbols <n>`: cap emitted symbols for large repositories.
- `--json`: print the analysis artifact to stdout instead of only writing a file.
- `--fail-on-parse-errors`: exit non-zero when any supported file fails to parse.

Default behavior should be fail-open for consumers like Echelon: parse what can be parsed, emit failed files in `index_stats`, and write unsupported or dynamic patterns explicitly.

## Supported Files

Day-one supported extensions:

- `.pl`
- `.pm`
- `.t`
- `.psgi`

The tool should also support extensionless Perl scripts only when they are explicitly passed on the command line or have a Perl shebang.

## Output Contract

The artifact should be intentionally CodeGraph-shaped while remaining standalone.

Top-level fields:

```json
{
  "schema_version": 1,
  "tool": "perlgraph",
  "generated_at": "2026-06-17T00:00:00Z",
  "repo_path": "/repo",
  "supported": true,
  "language_coverage": {
    ".pm": "supported",
    ".pl": "supported",
    ".t": "supported",
    ".psgi": "supported"
  },
  "symbols": [],
  "relationships": [],
  "call_graph": [],
  "module_graph": [],
  "unsupported_patterns": [],
  "index_stats": {}
}
```

### Symbols

Symbol kinds:

- `file`
- `package`
- `sub`
- `method`
- `test`
- `constant`
- `variable`

Each symbol should include:

- `qualified_name`
- `name`
- `kind`
- `file_path`
- `line_start`
- `line_end`
- `language: "perl"`
- `signature` when cheaply available
- `provenance`

### Relationships

Relationship kinds:

- `declares`
- `imports`
- `requires`
- `inherits`
- `uses_role`
- `calls`
- `tests`
- `references`

Each relationship should include:

- `source`
- `target`
- `kind`
- `file_path`
- `line_start`
- `confidence`
- `provenance`
- `notes` when confidence is below `high`

Confidence values:

- `high`: direct static target, such as `Package::sub()` with resolved package.
- `medium`: likely target, such as `$obj->method()` where constructor assignment or local package context points to one candidate.
- `low`: name match or convention-based candidate with multiple possible targets.
- `dynamic`: detected runtime behavior where static resolution is unsafe.

Example:

```json
{
  "source": "lib/My/App.pm::run",
  "target": "lib/My/Service.pm::execute",
  "kind": "calls",
  "file_path": "lib/My/App.pm",
  "line_start": 42,
  "confidence": "medium",
  "provenance": ["tree-sitter", "use-resolution", "constructor-assignment"],
  "notes": "Receiver inferred from my $svc = My::Service->new"
}
```

## Extraction Rules

### Packages

Extract `package Foo::Bar;` declarations as package symbols. A file may contain multiple packages. Symbols declared after a package statement belong to the current package until another package statement appears.

### Subs And Methods

Extract named `sub` declarations. Classify as:

- `sub` when called procedurally or package context is unclear.
- `method` when the first parameter convention, call sites, package role, or surrounding OO pattern indicates method use.

Anonymous subs should be emitted only when assigned to a named symbol or used in a detectable callback registration. Otherwise they are unsupported pattern evidence, not primary graph nodes.

### Dependencies

Extract:

- `use Foo::Bar`
- `require Foo::Bar`
- `require "path/file.pl"`
- `use parent`
- `use base`
- role-like declarations where statically visible

Resolve modules by Perl's conventional `Foo::Bar -> Foo/Bar.pm` mapping across repository roots such as `lib/`, `t/lib/`, `local/lib/`, and project root. The resolver should record unresolved imports rather than dropping them.

### Calls

High-confidence calls:

- `foo()` resolved to a sub in the current package or imported package.
- `Foo::Bar::baz()` resolved to package sub.
- `__PACKAGE__->method()` resolved to current package method.
- `Class->method()` resolved to package method when `Class` resolves.

Medium-confidence calls:

- `$obj->method()` when `$obj` was assigned from `Class->new`.
- `$self->method()` resolved to current package method when inside a method body.
- inherited method calls when `parent` or `base` is resolved.

Low-confidence calls:

- bare method names with multiple candidates.
- `$obj->method()` where receiver type is inferred from naming or local assignment only.
- imported functions from modules whose export list cannot be statically read.

Dynamic calls:

- symbolic references
- `AUTOLOAD`
- `eval` code strings
- dynamic `require`
- glob assignments that alter symbol tables

Dynamic calls should be represented as unsupported patterns or dynamic edges, not upgraded to ordinary static calls.

## Test Mapping

Test files are `.t` files and Perl files under conventional test directories. The tool should extract test symbols and relate tests to implementation via:

- `use_ok`
- `require_ok`
- direct `use` or `require`
- direct calls to implementation symbols
- filename conventions such as `t/my-service.t` matching `My::Service`

Convention-only links must be `low` confidence unless supported by imports or calls.

## Summary Artifact

`perlgraph-summary.json` should be compact enough for agents to read first:

```json
{
  "schema_version": 1,
  "tool": "perlgraph",
  "generated_at": "2026-06-17T00:00:00Z",
  "repo_path": "/repo",
  "index_state": "ready",
  "index_stats": {},
  "symbol_kinds": [],
  "relationship_kinds": [],
  "top_callers": [],
  "top_callees": [],
  "top_modules": [],
  "dynamic_risk": {
    "count": 0,
    "patterns": []
  }
}
```

`index_state` values:

- `ready`: supported files parsed and graph confidence is usable.
- `degraded`: parse failures or high dynamic-risk count.
- `empty`: no supported Perl files found.
- `failed`: fatal error prevented artifact generation.

## Echelon Integration Boundary

Echelon should consume `perlgraph` through its CLI only.

Future Echelon behavior:

1. Detect Perl files in a target repository.
2. Detect `perlgraph` on `PATH` or configured tool path.
3. Run `perlgraph analyze` into the active run or verification directory.
4. Write:
   - `perlgraph-analysis.json`
   - `perlgraph-summary.json`
   - `perlgraph-error.txt` on failure
5. Read `perlgraph-summary.json` first in agents.
6. Read `perlgraph-analysis.json` only for symbol-level evidence.

Echelon must not import PerlGraph internals or rely on its repository layout.

## CodeGraph Upstream Path

The standalone project should maintain `docs/codegraph-upstream-notes.md` describing how the design maps into CodeGraph:

- Perl grammar registration and extension mapping.
- `package` as namespace/module nodes.
- `sub` and inferred methods as function/method nodes.
- `use` and `require` as import/require relationships.
- `parent` and `base` as inheritance edges.
- direct calls and method calls as `calls` edges with confidence metadata.
- unsupported dynamic patterns as extraction diagnostics.

Upstream readiness criteria:

- Core extractor has no Echelon-specific path assumptions.
- Fixture corpus is small, license-clean, and focused.
- Snapshot tests document expected nodes and edges.
- Dynamic uncertainty is explicit and does not create false high-confidence edges.
- A subset can be ported into CodeGraph without changing Echelon.

## Testing Strategy

Unit tests:

- package extraction
- sub and method extraction
- module path resolution
- inheritance extraction
- procedural call resolution
- package-qualified call resolution
- object method confidence classification
- test-to-implementation mapping
- unsupported dynamic pattern detection

Snapshot tests:

- one snapshot per fixture repository
- stable ordering for symbols and relationships
- explicit confidence/provenance expectations

Fixture groups:

- procedural scripts with same-package calls
- modules under `lib/`
- multi-package files
- `use` and `require` variants
- OO constructor and method calls
- `parent` and `base`
- `.t` tests with `use_ok`, `require_ok`, direct imports, and direct calls
- dynamic constructs such as `AUTOLOAD`, `eval`, symbolic refs, and dynamic require

Quality gates:

- no false `high` confidence edges in fixtures
- unresolved imports are represented
- parse failures are reported with file paths
- summary artifact is valid when full analysis is valid

## Risks

### False Confidence

The biggest risk is producing plausible but wrong edges. The confidence model exists to prevent this. Unknown dynamic behavior should reduce confidence or become an unsupported pattern.

### Upstream Drift

CodeGraph internals may change while PerlGraph is incubated. Keep the standalone output stable for Echelon, and keep upstream notes descriptive rather than depending on private CodeGraph APIs.

### Fixture Bias

Perl style varies widely. Fixture coverage should include old procedural code, modern module code, and dynamic patterns early.

## Milestones

### M1: Standalone Parser And Symbol Graph

- CLI skeleton.
- Parse supported Perl file extensions.
- Emit file, package, sub, method, and test symbols.
- Emit summary artifact.
- Snapshot tests for basic fixtures.

### M2: Dependency Graph

- Resolve `use`, `require`, `parent`, and `base`.
- Emit module graph and relationship edges.
- Represent unresolved imports.

### M3: Call Graph With Confidence

- Resolve direct calls and package-qualified calls.
- Add object method inference for simple constructor assignment and `$self`.
- Emit confidence and provenance per call edge.
- Detect unsupported dynamic constructs.

### M4: Echelon Consumer Adapter

- Add Echelon-side detection and CLI invocation.
- Write run-local PerlGraph artifacts.
- Teach RE and verify-spec prompts to read summary first.

### M5: CodeGraph Contribution Preparation

- Review extractor and resolver boundaries against CodeGraph source layout.
- Produce an upstream issue or draft PR proposal.
- Port the smallest high-confidence subset first: grammar mapping, packages, subs, imports, direct calls, and fixtures.

