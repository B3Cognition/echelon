# PerlGraph Standalone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone TypeScript/Node `perlgraph` CLI that parses Perl repositories and emits confidence-aware symbol, dependency, and call graph JSON artifacts.

**Architecture:** The implementation lives in a separate `perlgraph` repository and exposes a CLI plus focused extraction, resolution, and output modules. The graph core has no Echelon dependency and is shaped for an eventual CodeGraph contribution: deterministic snapshots, CodeGraph-like artifact fields, and explicit confidence/provenance on uncertain Perl edges.

**Tech Stack:** TypeScript, Node.js 20+, `commander`, `tree-sitter`, `tree-sitter-perl`, `fast-glob`, `picomatch`, Vitest.

---

## File Structure

Create a new standalone repository at `perlgraph/`.

- Create: `perlgraph/package.json` - npm scripts, runtime dependencies, CLI bin.
- Create: `perlgraph/tsconfig.json` - TypeScript compiler configuration.
- Create: `perlgraph/src/types.ts` - shared artifact, symbol, relationship, confidence, and diagnostic types.
- Create: `perlgraph/src/output/writer.ts` - stable JSON writing and summary rendering.
- Create: `perlgraph/src/extraction/files.ts` - repository file discovery and Perl file detection.
- Create: `perlgraph/src/extraction/perl-extractor.ts` - Tree-sitter-backed package/sub/test/dependency extraction.
- Create: `perlgraph/src/resolution/module-resolver.ts` - `Foo::Bar` to `Foo/Bar.pm` repository resolution.
- Create: `perlgraph/src/resolution/call-resolver.ts` - direct, qualified, and simple method call graph edges.
- Create: `perlgraph/src/analysis/analyze.ts` - orchestrates file discovery, extraction, resolution, and artifact assembly.
- Create: `perlgraph/src/cli/perlgraph.ts` - command line entrypoint.
- Create: `perlgraph/tests/fixtures/*` - small Perl repositories for snapshots.
- Create: `perlgraph/tests/*.test.ts` - Vitest unit and snapshot tests.
- Create: `perlgraph/docs/output-contract.md` - JSON contract for consumers.
- Create: `perlgraph/docs/codegraph-upstream-notes.md` - mapping to CodeGraph contribution concepts.

Implementation order:

1. Scaffold repo and typed output contract.
2. Add file discovery and CLI shell.
3. Extract symbols and dependencies.
4. Resolve module dependencies.
5. Resolve call graph with confidence.
6. Add dynamic pattern diagnostics.
7. Add documentation and upstream notes.

---

### Task 1: Repository Scaffold And Artifact Types

**Files:**
- Create: `perlgraph/package.json`
- Create: `perlgraph/tsconfig.json`
- Create: `perlgraph/src/types/tree-sitter-perl.d.ts`
- Create: `perlgraph/src/types.ts`
- Create: `perlgraph/tests/types.test.ts`

- [ ] **Step 1: Create package metadata**

Create `perlgraph/package.json`:

```json
{
  "name": "perlgraph",
  "version": "0.1.0",
  "private": true,
  "description": "Tree-sitter based structural graph extraction for Perl repositories",
  "type": "module",
  "bin": {
    "perlgraph": "./dist/cli/perlgraph.js"
  },
  "scripts": {
    "build": "tsc",
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "tsc --noEmit",
    "lint": "tsc --noEmit"
  },
  "dependencies": {
    "commander": "^14.0.2",
    "fast-glob": "^3.3.3",
    "picomatch": "^4.0.3",
    "tree-sitter": "^0.22.4",
    "tree-sitter-perl": "^1.1.2"
  },
  "devDependencies": {
    "@types/node": "^20.19.30",
    "typescript": "^5.0.0",
    "vitest": "^2.1.9"
  },
  "engines": {
    "node": ">=20.0.0"
  }
}
```

- [ ] **Step 2: Create TypeScript config**

Create `perlgraph/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "rootDir": "src",
    "outDir": "dist",
    "strict": true,
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true,
    "skipLibCheck": true,
    "declaration": true,
    "sourceMap": true
  },
  "include": ["src/**/*.ts"],
  "exclude": ["dist", "node_modules"]
}
```

- [ ] **Step 3: Define artifact types**

Create `perlgraph/src/types/tree-sitter-perl.d.ts`:

```ts
declare module 'tree-sitter-perl' {
  import type Parser from 'tree-sitter';
  const language: Parser.Language;
  export = language;
}
```

Then create `perlgraph/src/types.ts`:

```ts
export type Confidence = 'high' | 'medium' | 'low' | 'dynamic';

export type SymbolKind =
  | 'file'
  | 'package'
  | 'sub'
  | 'method'
  | 'test'
  | 'constant'
  | 'variable';

export type RelationshipKind =
  | 'declares'
  | 'imports'
  | 'requires'
  | 'inherits'
  | 'uses_role'
  | 'calls'
  | 'tests'
  | 'references';

export type IndexState = 'ready' | 'degraded' | 'empty' | 'failed';

export interface SourceRange {
  file_path: string;
  line_start: number;
  line_end: number;
}

export interface PerlSymbol extends SourceRange {
  qualified_name: string;
  name: string;
  kind: SymbolKind;
  language: 'perl';
  signature?: string;
  provenance: string[];
}

export interface PerlRelationship {
  source: string;
  target: string;
  kind: RelationshipKind;
  file_path: string;
  line_start: number;
  confidence: Confidence;
  provenance: string[];
  notes?: string;
}

export interface UnsupportedPattern {
  kind: 'autoload' | 'eval_string' | 'symbolic_ref' | 'dynamic_require' | 'glob_assignment';
  file_path: string;
  line_start: number;
  snippet: string;
  notes: string;
}

export interface ParseFailure {
  file_path: string;
  error: string;
}

export interface IndexStats {
  total_files: number;
  parsed_files: number;
  failed_files: number;
  symbol_count: number;
  relationship_count: number;
  dynamic_pattern_count: number;
  index_state: IndexState;
}

export interface ModuleGraphEntry {
  source_module: string;
  target_module: string;
  source_file: string;
  target_file?: string;
  kind: 'use' | 'require' | 'parent' | 'base';
  confidence: Confidence;
}

export interface PerlGraphAnalysis {
  schema_version: 1;
  tool: 'perlgraph';
  generated_at: string;
  repo_path: string;
  supported: boolean;
  language_coverage: Record<string, 'supported'>;
  symbols: PerlSymbol[];
  relationships: PerlRelationship[];
  call_graph: Array<Pick<PerlRelationship, 'source' | 'target' | 'confidence' | 'provenance'>>;
  module_graph: ModuleGraphEntry[];
  unsupported_patterns: UnsupportedPattern[];
  index_stats: IndexStats;
}

export interface PerlGraphSummary {
  schema_version: 1;
  tool: 'perlgraph';
  generated_at: string;
  repo_path: string;
  index_state: IndexState;
  index_stats: IndexStats;
  symbol_kinds: Array<{ kind: SymbolKind; count: number }>;
  relationship_kinds: Array<{ kind: RelationshipKind; count: number }>;
  top_callers: Array<{ symbol: string; outgoing_calls: number }>;
  top_callees: Array<{ symbol: string; incoming_calls: number }>;
  top_modules: Array<{ module: string; outgoing_dependencies: number }>;
  dynamic_risk: {
    count: number;
    patterns: Array<{ kind: UnsupportedPattern['kind']; count: number }>;
  };
}
```

- [ ] **Step 4: Add type smoke test**

Create `perlgraph/tests/types.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import type { PerlGraphAnalysis } from '../src/types.js';

describe('PerlGraphAnalysis type contract', () => {
  it('accepts the minimum valid analysis payload', () => {
    const payload: PerlGraphAnalysis = {
      schema_version: 1,
      tool: 'perlgraph',
      generated_at: '2026-06-17T00:00:00.000Z',
      repo_path: '/repo',
      supported: false,
      language_coverage: {
        '.pl': 'supported',
        '.pm': 'supported',
        '.t': 'supported',
        '.psgi': 'supported'
      },
      symbols: [],
      relationships: [],
      call_graph: [],
      module_graph: [],
      unsupported_patterns: [],
      index_stats: {
        total_files: 0,
        parsed_files: 0,
        failed_files: 0,
        symbol_count: 0,
        relationship_count: 0,
        dynamic_pattern_count: 0,
        index_state: 'empty'
      }
    };

    expect(payload.tool).toBe('perlgraph');
    expect(payload.index_stats.index_state).toBe('empty');
  });
});
```

- [ ] **Step 5: Install dependencies**

Run:

```bash
cd perlgraph
npm install
```

Expected: `package-lock.json` is created and installation exits with code 0.

- [ ] **Step 6: Run initial checks**

Run:

```bash
cd perlgraph
npm run typecheck
npm test
```

Expected: both commands pass.

- [ ] **Step 7: Commit scaffold**

Run:

```bash
cd perlgraph
git add package.json package-lock.json tsconfig.json src/types/tree-sitter-perl.d.ts src/types.ts tests/types.test.ts
git commit -m "feat: scaffold perlgraph artifact contract"
```

Expected: commit succeeds.

---

### Task 2: Output Writer And Summary Renderer

**Files:**
- Create: `perlgraph/src/output/writer.ts`
- Create: `perlgraph/tests/output-writer.test.ts`

- [ ] **Step 1: Write failing summary test**

Create `perlgraph/tests/output-writer.test.ts`:

```ts
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { renderSummary, writeJsonAtomic } from '../src/output/writer.js';
import type { PerlGraphAnalysis } from '../src/types.js';

function analysis(): PerlGraphAnalysis {
  return {
    schema_version: 1,
    tool: 'perlgraph',
    generated_at: '2026-06-17T00:00:00.000Z',
    repo_path: '/repo',
    supported: true,
    language_coverage: { '.pm': 'supported', '.pl': 'supported', '.t': 'supported', '.psgi': 'supported' },
    symbols: [
      { qualified_name: 'My::App', name: 'My::App', kind: 'package', language: 'perl', file_path: 'lib/My/App.pm', line_start: 1, line_end: 1, provenance: ['tree-sitter'] },
      { qualified_name: 'My::App::run', name: 'run', kind: 'sub', language: 'perl', file_path: 'lib/My/App.pm', line_start: 3, line_end: 8, provenance: ['tree-sitter'] }
    ],
    relationships: [
      { source: 'My::App::run', target: 'My::Service::execute', kind: 'calls', file_path: 'lib/My/App.pm', line_start: 5, confidence: 'high', provenance: ['tree-sitter'] },
      { source: 'My::App', target: 'My::Service', kind: 'imports', file_path: 'lib/My/App.pm', line_start: 2, confidence: 'high', provenance: ['use-resolution'] }
    ],
    call_graph: [
      { source: 'My::App::run', target: 'My::Service::execute', confidence: 'high', provenance: ['tree-sitter'] }
    ],
    module_graph: [
      { source_module: 'My::App', target_module: 'My::Service', source_file: 'lib/My/App.pm', target_file: 'lib/My/Service.pm', kind: 'use', confidence: 'high' }
    ],
    unsupported_patterns: [
      { kind: 'eval_string', file_path: 'lib/My/App.pm', line_start: 7, snippet: 'eval $code', notes: 'String eval cannot be statically resolved' }
    ],
    index_stats: {
      total_files: 1,
      parsed_files: 1,
      failed_files: 0,
      symbol_count: 2,
      relationship_count: 2,
      dynamic_pattern_count: 1,
      index_state: 'ready'
    }
  };
}

describe('output writer', () => {
  it('renders compact summary counts', () => {
    const summary = renderSummary(analysis());

    expect(summary.symbol_kinds).toEqual([
      { kind: 'package', count: 1 },
      { kind: 'sub', count: 1 }
    ]);
    expect(summary.relationship_kinds).toEqual([
      { kind: 'calls', count: 1 },
      { kind: 'imports', count: 1 }
    ]);
    expect(summary.top_callers).toEqual([{ symbol: 'My::App::run', outgoing_calls: 1 }]);
    expect(summary.top_callees).toEqual([{ symbol: 'My::Service::execute', incoming_calls: 1 }]);
    expect(summary.dynamic_risk.patterns).toEqual([{ kind: 'eval_string', count: 1 }]);
  });

  it('writes stable pretty JSON', async () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'perlgraph-'));
    const out = path.join(dir, 'analysis.json');

    try {
      await writeJsonAtomic(out, analysis());
      const text = readFileSync(out, 'utf8');
      expect(text.endsWith('\n')).toBe(true);
      expect(JSON.parse(text).tool).toBe('perlgraph');
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd perlgraph
npm test -- tests/output-writer.test.ts
```

Expected: FAIL because `src/output/writer.ts` does not exist.

- [ ] **Step 3: Implement output writer**

Create `perlgraph/src/output/writer.ts`:

```ts
import { mkdir, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import type {
  PerlGraphAnalysis,
  PerlGraphSummary,
  RelationshipKind,
  SymbolKind,
  UnsupportedPattern
} from '../types.js';

function countBy<T extends string>(values: T[]): Array<{ key: T; count: number }> {
  const counts = new Map<T, number>();
  for (const value of values) {
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([key, count]) => ({ key, count }))
    .sort((a, b) => b.count - a.count || a.key.localeCompare(b.key));
}

export function renderSummary(analysis: PerlGraphAnalysis): PerlGraphSummary {
  const symbolKinds = countBy(analysis.symbols.map((symbol) => symbol.kind));
  const relationshipKinds = countBy(analysis.relationships.map((relationship) => relationship.kind));
  const callers = countBy(analysis.call_graph.map((edge) => edge.source));
  const callees = countBy(analysis.call_graph.map((edge) => edge.target));
  const modules = countBy(analysis.module_graph.map((edge) => edge.source_module));
  const dynamicPatterns = countBy(analysis.unsupported_patterns.map((pattern) => pattern.kind));

  return {
    schema_version: 1,
    tool: 'perlgraph',
    generated_at: analysis.generated_at,
    repo_path: analysis.repo_path,
    index_state: analysis.index_stats.index_state,
    index_stats: analysis.index_stats,
    symbol_kinds: symbolKinds.map(({ key, count }) => ({ kind: key as SymbolKind, count })),
    relationship_kinds: relationshipKinds.map(({ key, count }) => ({ kind: key as RelationshipKind, count })),
    top_callers: callers.slice(0, 25).map(({ key, count }) => ({ symbol: key, outgoing_calls: count })),
    top_callees: callees.slice(0, 25).map(({ key, count }) => ({ symbol: key, incoming_calls: count })),
    top_modules: modules.slice(0, 25).map(({ key, count }) => ({ module: key, outgoing_dependencies: count })),
    dynamic_risk: {
      count: analysis.unsupported_patterns.length,
      patterns: dynamicPatterns.map(({ key, count }) => ({ kind: key as UnsupportedPattern['kind'], count }))
    }
  };
}

export async function writeJsonAtomic(filePath: string, payload: unknown): Promise<void> {
  const dir = path.dirname(filePath);
  await mkdir(dir, { recursive: true });
  const tempPath = `${filePath}.tmp`;
  const json = `${JSON.stringify(payload, null, 2)}\n`;
  await writeFile(tempPath, json, 'utf8');
  await rename(tempPath, filePath);
}
```

- [ ] **Step 4: Run output tests**

Run:

```bash
cd perlgraph
npm test -- tests/output-writer.test.ts
```

Expected: PASS.

- [ ] **Step 5: Run all checks**

Run:

```bash
cd perlgraph
npm run typecheck
npm test
```

Expected: both pass.

- [ ] **Step 6: Commit output writer**

Run:

```bash
cd perlgraph
git add src/output/writer.ts tests/output-writer.test.ts
git commit -m "feat: render perlgraph summary artifacts"
```

Expected: commit succeeds.

---

### Task 3: Perl File Discovery

**Files:**
- Create: `perlgraph/src/extraction/files.ts`
- Create: `perlgraph/tests/file-discovery.test.ts`
- Create fixture files under `perlgraph/tests/fixtures/file-discovery/`

- [ ] **Step 1: Write failing file discovery tests**

Create `perlgraph/tests/file-discovery.test.ts`:

```ts
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { discoverPerlFiles, isPerlFile } from '../src/extraction/files.js';

describe('Perl file discovery', () => {
  it('recognizes Perl extensions and shebang scripts', () => {
    expect(isPerlFile('lib/My/App.pm')).toBe(true);
    expect(isPerlFile('script/run.pl')).toBe(true);
    expect(isPerlFile('t/app.t')).toBe(true);
    expect(isPerlFile('app.psgi')).toBe(true);
    expect(isPerlFile('bin/tool', '#!/usr/bin/env perl\nprint 1;\n')).toBe(true);
    expect(isPerlFile('README.md')).toBe(false);
  });

  it('discovers supported files while ignoring common generated directories', async () => {
    const root = path.join(tmpdir(), `perlgraph-files-${Date.now()}`);
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      mkdirSync(path.join(root, 't'), { recursive: true });
      mkdirSync(path.join(root, 'local/lib'), { recursive: true });
      mkdirSync(path.join(root, 'node_modules/x'), { recursive: true });
      mkdirSync(path.join(root, 'bin'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/App.pm'), 'package My::App;\n1;\n');
      writeFileSync(path.join(root, 't/app.t'), 'use Test::More;\n');
      writeFileSync(path.join(root, 'app.psgi'), 'sub { [200, [], []] };\n');
      writeFileSync(path.join(root, 'bin/tool'), '#!/usr/bin/env perl\nprint 1;\n');
      writeFileSync(path.join(root, 'local/lib/Generated.pm'), 'package Generated;\n1;\n');
      writeFileSync(path.join(root, 'node_modules/x/Bad.pm'), 'package Bad;\n1;\n');

      const files = await discoverPerlFiles(root);
      expect(files.map((file) => file.relativePath).sort()).toEqual([
        'app.psgi',
        'bin/tool',
        'lib/My/App.pm',
        't/app.t'
      ]);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd perlgraph
npm test -- tests/file-discovery.test.ts
```

Expected: FAIL because `src/extraction/files.ts` does not exist.

- [ ] **Step 3: Implement file discovery**

Create `perlgraph/src/extraction/files.ts`:

```ts
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import fg from 'fast-glob';
import picomatch from 'picomatch';

export interface PerlFile {
  absolutePath: string;
  relativePath: string;
  content: string;
}

const PERL_EXTENSIONS = new Set(['.pl', '.pm', '.t', '.psgi']);
const DEFAULT_IGNORES = [
  '**/.git/**',
  '**/node_modules/**',
  '**/local/**',
  '**/vendor/**',
  '**/dist/**',
  '**/build/**',
  '**/blib/**',
  '**/_build/**',
  '**/.carton/**'
];

export function isPerlFile(filePath: string, content = ''): boolean {
  const ext = path.extname(filePath).toLowerCase();
  if (PERL_EXTENSIONS.has(ext)) return true;
  const firstLine = content.split(/\r?\n/, 1)[0] ?? '';
  return firstLine.startsWith('#!') && /\bperl\b/.test(firstLine);
}

export async function discoverPerlFiles(
  repoPath: string,
  options: { include?: string[]; exclude?: string[] } = {}
): Promise<PerlFile[]> {
  const entries = await fg('**/*', {
    cwd: repoPath,
    dot: false,
    onlyFiles: true,
    ignore: [...DEFAULT_IGNORES, ...(options.exclude ?? [])],
    unique: true
  });

  const includeMatchers = (options.include ?? []).map((pattern) => picomatch(pattern));
  const files: PerlFile[] = [];

  for (const relativePath of entries.sort()) {
    if (includeMatchers.length > 0 && !includeMatchers.some((matches) => matches(relativePath))) {
      continue;
    }
    const absolutePath = path.join(repoPath, relativePath);
    const content = await readFile(absolutePath, 'utf8');
    if (!isPerlFile(relativePath, content)) continue;
    files.push({ absolutePath, relativePath, content });
  }

  return files;
}
```

- [ ] **Step 4: Run file discovery tests**

Run:

```bash
cd perlgraph
npm test -- tests/file-discovery.test.ts
```

Expected: PASS.

- [ ] **Step 5: Run all checks**

Run:

```bash
cd perlgraph
npm run typecheck
npm test
```

Expected: both pass.

- [ ] **Step 6: Commit file discovery**

Run:

```bash
cd perlgraph
git add src/extraction/files.ts tests/file-discovery.test.ts
git commit -m "feat: discover perl source files"
```

Expected: commit succeeds.

---

### Task 4: Symbol And Dependency Extraction

**Files:**
- Create: `perlgraph/src/extraction/perl-extractor.ts`
- Create: `perlgraph/tests/perl-extractor.test.ts`

- [ ] **Step 1: Write failing extractor tests**

Create `perlgraph/tests/perl-extractor.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { extractPerlFile } from '../src/extraction/perl-extractor.js';

const SOURCE = `package My::App;
use strict;
use warnings;
use My::Service;
use parent 'My::Base';

sub new {
  my ($class) = @_;
  return bless {}, $class;
}

sub run {
  my ($self) = @_;
  return My::Service::execute();
}

package My::App::Util;

sub helper {
  return 1;
}
`;

describe('Perl extractor', () => {
  it('extracts packages, subs, methods, and dependencies', () => {
    const result = extractPerlFile('lib/My/App.pm', SOURCE);

    expect(result.symbols.map((symbol) => [symbol.kind, symbol.qualified_name, symbol.line_start])).toEqual([
      ['file', 'lib/My/App.pm', 1],
      ['package', 'My::App', 1],
      ['method', 'My::App::new', 7],
      ['method', 'My::App::run', 12],
      ['package', 'My::App::Util', 17],
      ['sub', 'My::App::Util::helper', 19]
    ]);

    expect(result.dependencies).toEqual([
      { source_module: 'My::App', target_module: 'strict', source_file: 'lib/My/App.pm', kind: 'use', line_start: 2 },
      { source_module: 'My::App', target_module: 'warnings', source_file: 'lib/My/App.pm', kind: 'use', line_start: 3 },
      { source_module: 'My::App', target_module: 'My::Service', source_file: 'lib/My/App.pm', kind: 'use', line_start: 4 },
      { source_module: 'My::App', target_module: 'My::Base', source_file: 'lib/My/App.pm', kind: 'parent', line_start: 5 }
    ]);
  });

  it('detects dynamic patterns', () => {
    const result = extractPerlFile('lib/Dynamic.pm', [
      'package Dynamic;',
      'our $AUTOLOAD;',
      'sub AUTOLOAD { }',
      'eval $code;',
      'require $module;',
      '*{caller() . "::x"} = sub { 1 };'
    ].join('\\n'));

    expect(result.unsupported_patterns.map((pattern) => pattern.kind)).toEqual([
      'autoload',
      'eval_string',
      'dynamic_require',
      'glob_assignment'
    ]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd perlgraph
npm test -- tests/perl-extractor.test.ts
```

Expected: FAIL because `src/extraction/perl-extractor.ts` does not exist.

- [ ] **Step 3: Implement pragmatic extractor**

Create `perlgraph/src/extraction/perl-extractor.ts`:

```ts
import Parser from 'tree-sitter';
import Perl from 'tree-sitter-perl';
import type { PerlSymbol, UnsupportedPattern } from '../types.js';

export interface ExtractedDependency {
  source_module: string;
  target_module: string;
  source_file: string;
  kind: 'use' | 'require' | 'parent' | 'base';
  line_start: number;
}

export interface ExtractedCall {
  caller: string;
  expression: string;
  file_path: string;
  line_start: number;
}

export interface ExtractedPerlFile {
  symbols: PerlSymbol[];
  dependencies: ExtractedDependency[];
  calls: ExtractedCall[];
  unsupported_patterns: UnsupportedPattern[];
}

const parser = new Parser();
parser.setLanguage(Perl);

function parsePerl(content: string): Parser.Tree {
  return parser.parse(content);
}

function lineEnd(lines: string[], startIndex: number): number {
  for (let index = startIndex + 1; index < lines.length; index += 1) {
    if (/^\s*sub\s+\w+/.test(lines[index] ?? '') || /^\s*package\s+[\w:]+/.test(lines[index] ?? '')) {
      return index;
    }
  }
  return lines.length;
}

function classifySub(name: string, body: string): 'sub' | 'method' {
  if (name === 'new') return 'method';
  if (/\bmy\s*\(\s*\$(?:self|class)\s*\)/.test(body)) return 'method';
  if (/\$(?:self|class)\s*->/.test(body)) return 'method';
  return 'sub';
}

function unquote(value: string): string {
  return value.replace(/^['"]|['"]$/g, '');
}

function dependencyTarget(line: string): string | undefined {
  const quoted = line.match(/['"]([^'"]+)['"]/);
  if (quoted) return quoted[1];
  const bare = line.match(/\b(?:use|require)\s+([A-Za-z_][\w:]*)/);
  return bare?.[1];
}

export function extractPerlFile(filePath: string, content: string): ExtractedPerlFile {
  parsePerl(content);
  const lines = content.split(/\r?\n/);
  const symbols: PerlSymbol[] = [{
    qualified_name: filePath,
    name: filePath,
    kind: 'file',
    language: 'perl',
    file_path: filePath,
    line_start: 1,
    line_end: lines.length,
    provenance: ['file-discovery']
  }];
  const dependencies: ExtractedDependency[] = [];
  const calls: ExtractedCall[] = [];
  const unsupported_patterns: UnsupportedPattern[] = [];
  let currentPackage = 'main';
  let currentSub: string | undefined;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? '';
    const lineNumber = index + 1;

    const packageMatch = line.match(/^\s*package\s+([A-Za-z_][\w:]*)\s*;/);
    if (packageMatch) {
      currentPackage = packageMatch[1]!;
      symbols.push({
        qualified_name: currentPackage,
        name: currentPackage,
        kind: 'package',
        language: 'perl',
        file_path: filePath,
        line_start: lineNumber,
        line_end: lineNumber,
        provenance: ['tree-sitter', 'line-scan']
      });
      currentSub = undefined;
      continue;
    }

    const subMatch = line.match(/^\s*sub\s+([A-Za-z_]\w*)/);
    if (subMatch) {
      const name = subMatch[1]!;
      const endLine = lineEnd(lines, index);
      const body = lines.slice(index, endLine).join('\n');
      const kind = classifySub(name, body);
      const qualifiedName = `${currentPackage}::${name}`;
      symbols.push({
        qualified_name: qualifiedName,
        name,
        kind,
        language: 'perl',
        file_path: filePath,
        line_start: lineNumber,
        line_end: endLine,
        signature: `sub ${name}`,
        provenance: ['tree-sitter', 'line-scan']
      });
      currentSub = qualifiedName;
      if (name === 'AUTOLOAD') {
        unsupported_patterns.push({
          kind: 'autoload',
          file_path: filePath,
          line_start: lineNumber,
          snippet: line.trim(),
          notes: 'AUTOLOAD dispatch cannot be statically resolved'
        });
      }
      continue;
    }

    const useMatch = line.match(/^\s*use\s+([A-Za-z_][\w:]*)(?:\s+(.+?))?\s*;/);
    if (useMatch) {
      const moduleName = useMatch[1]!;
      if (moduleName === 'parent' || moduleName === 'base') {
        const target = (useMatch[2] ?? '').split(/\s*,\s*/).map(unquote).find(Boolean);
        if (target) {
          dependencies.push({
            source_module: currentPackage,
            target_module: target,
            source_file: filePath,
            kind: moduleName,
            line_start: lineNumber
          });
        }
      } else {
        dependencies.push({
          source_module: currentPackage,
          target_module: moduleName,
          source_file: filePath,
          kind: 'use',
          line_start: lineNumber
        });
      }
      continue;
    }

    const requireMatch = line.match(/^\s*require\s+(.+?)\s*;/);
    if (requireMatch) {
      const target = dependencyTarget(line);
      if (target) {
        dependencies.push({
          source_module: currentPackage,
          target_module: target,
          source_file: filePath,
          kind: 'require',
          line_start: lineNumber
        });
      } else {
        unsupported_patterns.push({
          kind: 'dynamic_require',
          file_path: filePath,
          line_start: lineNumber,
          snippet: line.trim(),
          notes: 'Dynamic require target cannot be statically resolved'
        });
      }
      continue;
    }

    if (/\beval\s+\$/.test(line) || /\beval\s+["']/.test(line)) {
      unsupported_patterns.push({
        kind: 'eval_string',
        file_path: filePath,
        line_start: lineNumber,
        snippet: line.trim(),
        notes: 'String eval cannot be statically resolved'
      });
    }

    if (/\*\{/.test(line) || /^\s*\*\w+::/.test(line)) {
      unsupported_patterns.push({
        kind: 'glob_assignment',
        file_path: filePath,
        line_start: lineNumber,
        snippet: line.trim(),
        notes: 'Typeglob assignment may alter the symbol table'
      });
    }

    if (currentSub) {
      for (const match of line.matchAll(/([A-Za-z_][\w:]*(?:::[A-Za-z_]\w*)?)\s*\(/g)) {
        const expression = match[1]!;
        if (['if', 'for', 'foreach', 'while', 'return'].includes(expression)) continue;
        calls.push({ caller: currentSub, expression, file_path: filePath, line_start: lineNumber });
      }
      for (const match of line.matchAll(/((?:\$[A-Za-z_]\w*)|(?:[A-Za-z_][\w:]*))\s*->\s*([A-Za-z_]\w*)/g)) {
        calls.push({
          caller: currentSub,
          expression: `${match[1]!}->${match[2]!}`,
          file_path: filePath,
          line_start: lineNumber
        });
      }
    }
  }

  return { symbols, dependencies, calls, unsupported_patterns };
}
```

- [ ] **Step 4: Run extractor tests**

Run:

```bash
cd perlgraph
npm test -- tests/perl-extractor.test.ts
```

Expected: PASS.

- [ ] **Step 5: Run all checks**

Run:

```bash
cd perlgraph
npm run typecheck
npm test
```

Expected: both pass.

- [ ] **Step 6: Commit extractor**

Run:

```bash
cd perlgraph
git add src/extraction/perl-extractor.ts tests/perl-extractor.test.ts
git commit -m "feat: extract perl symbols and dependencies"
```

Expected: commit succeeds.

---

### Task 5: Module Resolution

**Files:**
- Create: `perlgraph/src/resolution/module-resolver.ts`
- Create: `perlgraph/tests/module-resolver.test.ts`

- [ ] **Step 1: Write failing module resolver tests**

Create `perlgraph/tests/module-resolver.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { resolveModuleDependency } from '../src/resolution/module-resolver.js';

const files = new Set([
  'lib/My/App.pm',
  'lib/My/Service.pm',
  't/lib/Test/Helper.pm',
  'script/legacy.pl'
]);

describe('module resolver', () => {
  it('resolves module names to repository files', () => {
    expect(resolveModuleDependency('My::Service', files)).toEqual({
      module: 'My::Service',
      file_path: 'lib/My/Service.pm',
      confidence: 'high'
    });
  });

  it('resolves quoted require paths', () => {
    expect(resolveModuleDependency('script/legacy.pl', files)).toEqual({
      module: 'script/legacy.pl',
      file_path: 'script/legacy.pl',
      confidence: 'high'
    });
  });

  it('records unresolved modules', () => {
    expect(resolveModuleDependency('Missing::Thing', files)).toEqual({
      module: 'Missing::Thing',
      confidence: 'low'
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd perlgraph
npm test -- tests/module-resolver.test.ts
```

Expected: FAIL because `src/resolution/module-resolver.ts` does not exist.

- [ ] **Step 3: Implement module resolver**

Create `perlgraph/src/resolution/module-resolver.ts`:

```ts
import type { Confidence } from '../types.js';

export interface ModuleResolution {
  module: string;
  file_path?: string;
  confidence: Confidence;
}

const ROOTS = ['', 'lib/', 't/lib/'];

export function moduleToPathCandidates(moduleName: string): string[] {
  if (moduleName.endsWith('.pl') || moduleName.endsWith('.pm')) {
    return [moduleName.replace(/^\.\//, '')];
  }
  const relative = `${moduleName.replaceAll('::', '/')}.pm`;
  return ROOTS.map((root) => `${root}${relative}`);
}

export function resolveModuleDependency(moduleName: string, files: Set<string>): ModuleResolution {
  for (const candidate of moduleToPathCandidates(moduleName)) {
    if (files.has(candidate)) {
      return { module: moduleName, file_path: candidate, confidence: 'high' };
    }
  }
  return { module: moduleName, confidence: 'low' };
}
```

- [ ] **Step 4: Run module resolver tests**

Run:

```bash
cd perlgraph
npm test -- tests/module-resolver.test.ts
```

Expected: PASS.

- [ ] **Step 5: Run all checks**

Run:

```bash
cd perlgraph
npm run typecheck
npm test
```

Expected: both pass.

- [ ] **Step 6: Commit module resolver**

Run:

```bash
cd perlgraph
git add src/resolution/module-resolver.ts tests/module-resolver.test.ts
git commit -m "feat: resolve perl module dependencies"
```

Expected: commit succeeds.

---

### Task 6: Call Resolution With Confidence

**Files:**
- Create: `perlgraph/src/resolution/call-resolver.ts`
- Create: `perlgraph/tests/call-resolver.test.ts`

- [ ] **Step 1: Write failing call resolver tests**

Create `perlgraph/tests/call-resolver.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { resolveCalls } from '../src/resolution/call-resolver.js';
import type { PerlSymbol } from '../src/types.js';

const symbols: PerlSymbol[] = [
  { qualified_name: 'My::App::run', name: 'run', kind: 'method', language: 'perl', file_path: 'lib/My/App.pm', line_start: 10, line_end: 20, provenance: ['tree-sitter'] },
  { qualified_name: 'My::App::helper', name: 'helper', kind: 'sub', language: 'perl', file_path: 'lib/My/App.pm', line_start: 22, line_end: 24, provenance: ['tree-sitter'] },
  { qualified_name: 'My::Service::execute', name: 'execute', kind: 'sub', language: 'perl', file_path: 'lib/My/Service.pm', line_start: 5, line_end: 8, provenance: ['tree-sitter'] },
  { qualified_name: 'My::Service::new', name: 'new', kind: 'method', language: 'perl', file_path: 'lib/My/Service.pm', line_start: 1, line_end: 4, provenance: ['tree-sitter'] }
];

describe('call resolver', () => {
  it('resolves local and package-qualified calls', () => {
    const relationships = resolveCalls(
      [
        { caller: 'My::App::run', expression: 'helper', file_path: 'lib/My/App.pm', line_start: 12 },
        { caller: 'My::App::run', expression: 'My::Service::execute', file_path: 'lib/My/App.pm', line_start: 13 },
        { caller: 'My::App::run', expression: 'My::Service->new', file_path: 'lib/My/App.pm', line_start: 14 }
      ],
      symbols
    );

    expect(relationships.map((relationship) => [relationship.target, relationship.confidence])).toEqual([
      ['My::App::helper', 'high'],
      ['My::Service::execute', 'high'],
      ['My::Service::new', 'high']
    ]);
  });

  it('keeps unresolved method calls as low confidence references', () => {
    const relationships = resolveCalls(
      [{ caller: 'My::App::run', expression: '$svc->execute', file_path: 'lib/My/App.pm', line_start: 15 }],
      symbols
    );

    expect(relationships).toEqual([
      {
        source: 'My::App::run',
        target: 'execute',
        kind: 'calls',
        file_path: 'lib/My/App.pm',
        line_start: 15,
        confidence: 'low',
        provenance: ['method-name-match'],
        notes: 'Receiver type for $svc->execute was not statically resolved'
      }
    ]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd perlgraph
npm test -- tests/call-resolver.test.ts
```

Expected: FAIL because `src/resolution/call-resolver.ts` does not exist.

- [ ] **Step 3: Implement call resolver**

Create `perlgraph/src/resolution/call-resolver.ts`:

```ts
import type { PerlRelationship, PerlSymbol } from '../types.js';
import type { ExtractedCall } from '../extraction/perl-extractor.js';

function packageOf(qualifiedName: string): string {
  return qualifiedName.split('::').slice(0, -1).join('::');
}

function methodExpressionParts(expression: string): { receiver: string; method: string } | undefined {
  const match = expression.match(/^(.+)->([A-Za-z_]\w*)$/);
  if (!match) return undefined;
  return { receiver: match[1]!, method: match[2]! };
}

export function resolveCalls(calls: ExtractedCall[], symbols: PerlSymbol[]): PerlRelationship[] {
  const byQualifiedName = new Map(symbols.map((symbol) => [symbol.qualified_name, symbol]));
  const relationships: PerlRelationship[] = [];

  for (const call of calls) {
    const callerPackage = packageOf(call.caller);
    const methodParts = methodExpressionParts(call.expression);

    if (methodParts) {
      const receiver = methodParts.receiver.replace(/^['"]|['"]$/g, '');
      if (!receiver.startsWith('$')) {
        const target = `${receiver}::${methodParts.method}`;
        if (byQualifiedName.has(target)) {
          relationships.push({
            source: call.caller,
            target,
            kind: 'calls',
            file_path: call.file_path,
            line_start: call.line_start,
            confidence: 'high',
            provenance: ['tree-sitter', 'package-method-resolution']
          });
          continue;
        }
      }
      relationships.push({
        source: call.caller,
        target: methodParts.method,
        kind: 'calls',
        file_path: call.file_path,
        line_start: call.line_start,
        confidence: 'low',
        provenance: ['method-name-match'],
        notes: `Receiver type for ${call.expression} was not statically resolved`
      });
      continue;
    }

    const qualifiedTarget = call.expression.includes('::')
      ? call.expression
      : `${callerPackage}::${call.expression}`;

    if (byQualifiedName.has(qualifiedTarget)) {
      relationships.push({
        source: call.caller,
        target: qualifiedTarget,
        kind: 'calls',
        file_path: call.file_path,
        line_start: call.line_start,
        confidence: 'high',
        provenance: ['tree-sitter', 'name-resolution']
      });
      continue;
    }

    relationships.push({
      source: call.caller,
      target: call.expression,
      kind: 'calls',
      file_path: call.file_path,
      line_start: call.line_start,
      confidence: 'low',
      provenance: ['unresolved-call'],
      notes: `Call expression ${call.expression} did not resolve to a known symbol`
    });
  }

  return relationships;
}
```

- [ ] **Step 4: Run call resolver tests**

Run:

```bash
cd perlgraph
npm test -- tests/call-resolver.test.ts
```

Expected: PASS.

- [ ] **Step 5: Run all checks**

Run:

```bash
cd perlgraph
npm run typecheck
npm test
```

Expected: both pass.

- [ ] **Step 6: Commit call resolver**

Run:

```bash
cd perlgraph
git add src/resolution/call-resolver.ts tests/call-resolver.test.ts
git commit -m "feat: resolve perl calls with confidence"
```

Expected: commit succeeds.

---

### Task 7: Analysis Orchestrator And CLI

**Files:**
- Create: `perlgraph/src/analysis/analyze.ts`
- Create: `perlgraph/src/cli/perlgraph.ts`
- Create: `perlgraph/tests/analyze.test.ts`
- Modify: `perlgraph/package.json`

- [ ] **Step 1: Write failing end-to-end analysis test**

Create `perlgraph/tests/analyze.test.ts`:

```ts
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { analyzeRepository } from '../src/analysis/analyze.js';

describe('analyzeRepository', () => {
  it('builds symbols, module graph, and call graph for a tiny Perl repo', async () => {
    const root = path.join(tmpdir(), `perlgraph-analyze-${Date.now()}`);
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      mkdirSync(path.join(root, 't'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/App.pm'), [
        'package My::App;',
        'use My::Service;',
        'sub run {',
        '  return My::Service::execute();',
        '}',
        '1;'
      ].join('\\n'));
      writeFileSync(path.join(root, 'lib/My/Service.pm'), [
        'package My::Service;',
        'sub execute { return 1; }',
        '1;'
      ].join('\\n'));
      writeFileSync(path.join(root, 't/app.t'), [
        'use Test::More;',
        'use My::App;',
        'ok(My::App::run());',
        'done_testing;'
      ].join('\\n'));

      const analysis = await analyzeRepository(root);

      expect(analysis.supported).toBe(true);
      expect(analysis.index_stats.index_state).toBe('ready');
      expect(analysis.symbols.some((symbol) => symbol.qualified_name === 'My::App::run')).toBe(true);
      expect(analysis.module_graph).toContainEqual({
        source_module: 'My::App',
        target_module: 'My::Service',
        source_file: 'lib/My/App.pm',
        target_file: 'lib/My/Service.pm',
        kind: 'use',
        confidence: 'high'
      });
      expect(analysis.call_graph).toContainEqual({
        source: 'My::App::run',
        target: 'My::Service::execute',
        confidence: 'high',
        provenance: ['tree-sitter', 'name-resolution']
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd perlgraph
npm test -- tests/analyze.test.ts
```

Expected: FAIL because `src/analysis/analyze.ts` does not exist.

- [ ] **Step 3: Implement analysis orchestrator**

Create `perlgraph/src/analysis/analyze.ts`:

```ts
import path from 'node:path';
import { discoverPerlFiles } from '../extraction/files.js';
import { extractPerlFile } from '../extraction/perl-extractor.js';
import { resolveCalls } from '../resolution/call-resolver.js';
import { resolveModuleDependency } from '../resolution/module-resolver.js';
import type { IndexState, ModuleGraphEntry, PerlGraphAnalysis, PerlRelationship } from '../types.js';

function indexState(totalFiles: number, failedFiles: number, dynamicCount: number): IndexState {
  if (totalFiles === 0) return 'empty';
  if (failedFiles > 0 || dynamicCount > 0) return 'degraded';
  return 'ready';
}

export async function analyzeRepository(
  repoPath: string,
  options: { include?: string[]; exclude?: string[] } = {}
): Promise<PerlGraphAnalysis> {
  const resolvedRepoPath = path.resolve(repoPath);
  const files = await discoverPerlFiles(resolvedRepoPath, options);
  const fileSet = new Set(files.map((file) => file.relativePath));
  const symbols = [];
  const relationships: PerlRelationship[] = [];
  const moduleGraph: ModuleGraphEntry[] = [];
  const extractedCalls = [];
  const unsupportedPatterns = [];

  for (const file of files) {
    const extracted = extractPerlFile(file.relativePath, file.content);
    symbols.push(...extracted.symbols);
    extractedCalls.push(...extracted.calls);
    unsupportedPatterns.push(...extracted.unsupported_patterns);

    for (const dependency of extracted.dependencies) {
      const resolution = resolveModuleDependency(dependency.target_module, fileSet);
      moduleGraph.push({
        source_module: dependency.source_module,
        target_module: dependency.target_module,
        source_file: dependency.source_file,
        target_file: resolution.file_path,
        kind: dependency.kind,
        confidence: resolution.confidence
      });
      relationships.push({
        source: dependency.source_module,
        target: dependency.target_module,
        kind: dependency.kind === 'parent' || dependency.kind === 'base' ? 'inherits' : dependency.kind === 'require' ? 'requires' : 'imports',
        file_path: dependency.source_file,
        line_start: dependency.line_start,
        confidence: resolution.confidence,
        provenance: ['tree-sitter', 'module-resolution'],
        notes: resolution.file_path ? undefined : `Module ${dependency.target_module} did not resolve to a repository file`
      });
    }
  }

  const callRelationships = resolveCalls(extractedCalls, symbols);
  relationships.push(...callRelationships);

  const state = indexState(files.length, 0, unsupportedPatterns.length);
  return {
    schema_version: 1,
    tool: 'perlgraph',
    generated_at: new Date().toISOString(),
    repo_path: resolvedRepoPath,
    supported: files.length > 0,
    language_coverage: {
      '.pl': 'supported',
      '.pm': 'supported',
      '.t': 'supported',
      '.psgi': 'supported'
    },
    symbols,
    relationships,
    call_graph: callRelationships.map((relationship) => ({
      source: relationship.source,
      target: relationship.target,
      confidence: relationship.confidence,
      provenance: relationship.provenance
    })),
    module_graph: moduleGraph,
    unsupported_patterns: unsupportedPatterns,
    index_stats: {
      total_files: files.length,
      parsed_files: files.length,
      failed_files: 0,
      symbol_count: symbols.length,
      relationship_count: relationships.length,
      dynamic_pattern_count: unsupportedPatterns.length,
      index_state: state
    }
  };
}
```

- [ ] **Step 4: Implement CLI**

Create `perlgraph/src/cli/perlgraph.ts`:

```ts
#!/usr/bin/env node
import { Command } from 'commander';
import { analyzeRepository } from '../analysis/analyze.js';
import { renderSummary, writeJsonAtomic } from '../output/writer.js';

const program = new Command();

program
  .name('perlgraph')
  .description('Static structural graph extraction for Perl repositories')
  .version('0.1.0');

program
  .command('analyze')
  .requiredOption('--repo-path <path>', 'repository path to analyze')
  .option('--output-path <path>', 'analysis JSON output path')
  .option('--summary-path <path>', 'summary JSON output path')
  .option('--include <glob...>', 'include glob patterns')
  .option('--exclude <glob...>', 'exclude glob patterns')
  .option('--json', 'print analysis JSON to stdout')
  .action(async (options) => {
    const analysis = await analyzeRepository(options.repoPath, {
      include: options.include,
      exclude: options.exclude
    });

    if (options.outputPath) {
      await writeJsonAtomic(options.outputPath, analysis);
    }

    if (options.summaryPath) {
      await writeJsonAtomic(options.summaryPath, renderSummary(analysis));
    }

    if (options.json || !options.outputPath) {
      process.stdout.write(`${JSON.stringify(analysis, null, 2)}\n`);
    }
  });

program.parseAsync(process.argv).catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`[perlgraph] ERROR: ${message}\n`);
  process.exitCode = 1;
});
```

Modify `perlgraph/package.json` scripts:

```json
{
  "scripts": {
    "build": "tsc && node -e \"require('fs').chmodSync('dist/cli/perlgraph.js', 0o755)\"",
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "tsc --noEmit",
    "lint": "tsc --noEmit"
  }
}
```

- [ ] **Step 5: Run analysis tests**

Run:

```bash
cd perlgraph
npm test -- tests/analyze.test.ts
```

Expected: PASS.

- [ ] **Step 6: Build and smoke-test CLI**

Run:

```bash
cd perlgraph
npm run build
node dist/cli/perlgraph.js analyze --repo-path tests --json
```

Expected: build passes, CLI prints valid JSON with `"tool": "perlgraph"`.

- [ ] **Step 7: Run all checks**

Run:

```bash
cd perlgraph
npm run typecheck
npm test
```

Expected: both pass.

- [ ] **Step 8: Commit analyzer and CLI**

Run:

```bash
cd perlgraph
git add package.json src/analysis/analyze.ts src/cli/perlgraph.ts tests/analyze.test.ts
git commit -m "feat: add perlgraph analyze cli"
```

Expected: commit succeeds.

---

### Task 8: Documentation And Upstream Notes

**Files:**
- Create: `perlgraph/docs/output-contract.md`
- Create: `perlgraph/docs/codegraph-upstream-notes.md`
- Create: `perlgraph/README.md`

- [ ] **Step 1: Create output contract docs**

Create `perlgraph/docs/output-contract.md`:

```markdown
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
- `index_stats`: counts and index state

## Confidence

- `high`: direct static target
- `medium`: likely target inferred from local context
- `low`: name or convention-based candidate
- `dynamic`: runtime behavior that cannot be safely resolved statically

Consumers must not treat low-confidence or dynamic edges as proof of behavior.
```

- [ ] **Step 2: Create CodeGraph upstream notes**

Create `perlgraph/docs/codegraph-upstream-notes.md`:

```markdown
# CodeGraph Upstream Notes

PerlGraph is intentionally shaped as an incubator for future CodeGraph Perl support.

## Mapping

- `.pl`, `.pm`, `.t`, `.psgi` map to language `perl`.
- `package Foo::Bar` maps to a namespace/module node.
- `sub name` maps to a function node unless method evidence is present.
- constructor-style and `$self` subs map to method nodes.
- `use` and `require` map to import/require edges.
- `use parent` and `use base` map to inheritance edges.
- direct calls and package-qualified calls map to calls edges.

## Contribution Strategy

Port the smallest high-confidence subset first:

1. grammar registration and extension mapping
2. package and sub extraction
3. use/require dependency extraction
4. direct and package-qualified calls
5. fixture snapshots

Method dispatch, Moose/Moo, AUTOLOAD, symbolic references, and string eval should remain diagnostic or low-confidence behavior until CodeGraph has an explicit confidence model for Perl edges.
```

- [ ] **Step 3: Create README**

Create `perlgraph/README.md`:

````markdown
# PerlGraph

PerlGraph is a static structural graph extractor for Perl repositories. It parses Perl files, extracts packages and subs, resolves module dependencies, and emits confidence-aware call graph artifacts.

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
````

- [ ] **Step 4: Run documentation-adjacent checks**

Run:

```bash
cd perlgraph
npm run typecheck
npm test
```

Expected: both pass.

- [ ] **Step 5: Commit docs**

Run:

```bash
cd perlgraph
git add README.md docs/output-contract.md docs/codegraph-upstream-notes.md
git commit -m "docs: document perlgraph output and upstream path"
```

Expected: commit succeeds.

---

### Task 9: Echelon Integration Plan Stub

**Files:**
- Modify: `echelon/docs/superpowers/specs/2026-06-17-perlgraph-standalone-design.md`
- Create: `echelon/docs/superpowers/plans/2026-06-17-perlgraph-echelon-integration.md` in a separate Echelon-specific planning turn

- [ ] **Step 1: Keep Echelon integration out of the standalone repo**

Do not add Echelon code in this implementation pass. The standalone tool must be useful without Echelon.

- [ ] **Step 2: Record integration prerequisites**

After Task 8 passes, open the design spec in Echelon and verify it still says Echelon consumes PerlGraph only through CLI artifacts:

```bash
cd echelon
rg -n "Echelon should consume `perlgraph` through its CLI only|perlgraph-analysis.json|perlgraph-summary.json" docs/superpowers/specs/2026-06-17-perlgraph-standalone-design.md
```

Expected: all three references are present.

- [ ] **Step 3: Defer Echelon implementation to a separate plan**

Create the Echelon integration plan only after the standalone `perlgraph analyze` command exists and its output contract is stable.

Expected future plan scope:

- detect Perl files in target repositories
- detect `perlgraph` binary
- run `perlgraph analyze`
- write `perlgraph-analysis.json`, `perlgraph-summary.json`, and `perlgraph-error.txt`
- teach RE/verify-spec agents to read PerlGraph summary first

- [ ] **Step 4: Commit any Echelon doc adjustment if needed**

If the design spec needed clarification, commit it separately:

```bash
cd echelon
git add docs/superpowers/specs/2026-06-17-perlgraph-standalone-design.md
git commit -m "docs: clarify perlgraph echelon integration boundary"
```

Expected: commit succeeds only if the design file changed. If no changes were needed, skip the commit.

---

## Verification Checklist

At the end of standalone implementation:

- [ ] `cd perlgraph && npm run typecheck` passes.
- [ ] `cd perlgraph && npm test` passes.
- [ ] `cd perlgraph && npm run build` passes.
- [ ] `node dist/cli/perlgraph.js analyze --repo-path <fixture> --json` prints valid JSON.
- [ ] `perlgraph-analysis.json` includes symbols, relationships, call graph, module graph, unsupported patterns, and index stats.
- [ ] Low-confidence and dynamic behavior are not emitted as high-confidence proof.
- [ ] `docs/codegraph-upstream-notes.md` explains the first upstreamable subset.
