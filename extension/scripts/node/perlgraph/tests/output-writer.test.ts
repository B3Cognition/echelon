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
    parse_failures: [],
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
      await writeJsonAtomic(out, { zed: true, alpha: { beta: 2 } });
      const text = readFileSync(out, 'utf8');
      expect(text).toBe('{\n  "zed": true,\n  "alpha": {\n    "beta": 2\n  }\n}\n');
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
