import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { symbolKey } from '../src/identity/symbol-key.js';
import { renderSummary, writeJsonAtomic } from '../src/output/writer.js';
import type { PerlGraphAnalysis, PerlSymbol } from '../src/types.js';

function symbol(value: Omit<PerlSymbol, 'symbol_key'>): PerlSymbol {
  return { ...value, symbol_key: symbolKey(value) };
}

function analysis(): PerlGraphAnalysis {
  const app = symbol({ qualified_name: 'My::App::run', name: 'run', kind: 'sub', language: 'perl', file_path: 'lib/My/App.pm', line_start: 3, line_end: 8, provenance: ['tree-sitter'] });
  const service = symbol({ qualified_name: 'My::Service::execute', name: 'execute', kind: 'sub', language: 'perl', file_path: 'lib/My/Service.pm', line_start: 3, line_end: 8, provenance: ['tree-sitter'] });
  return {
    schema_version: 2, tool: 'perlgraph', tool_version: '0.1.0', generated_at: '2026-06-17T00:00:00.000Z', repo_path: '/repo', supported: true,
    provider_status: 'degraded', complete: true,
    counts: { discovered_files: 2, emitted_files: 2, discovered_symbols: 2, emitted_symbols: 2, discovered_relationships: 2, emitted_relationships: 1, unresolved_relationships: 1, parse_failures: 0, parse_diagnostics: 0, dynamic_patterns: 1 },
    capabilities: { language: 'perl', supported_extensions: ['.pm'], exact_symbol_keys: true, exact_relationship_endpoints: true, unresolved_relationship_diagnostics: true },
    language_coverage: { '.pm': 'supported', '.pl': 'supported', '.t': 'supported', '.psgi': 'supported' }, symbols: [app, service],
    relationships: [{ source_key: app.symbol_key, target_key: service.symbol_key, source: app.qualified_name, target: service.qualified_name, kind: 'calls', file_path: app.file_path, line_start: 5, confidence: 'high', provenance: ['tree-sitter'] }],
    unresolved_relationships: [{ source_key: app.symbol_key, source: app.qualified_name, target: 'maybe', kind: 'calls', file_path: app.file_path, line_start: 6, confidence: 'low', provenance: ['unresolved-call'], notes: 'Call expression maybe did not resolve to a known symbol' }],
    call_graph: [{ source_key: app.symbol_key, target_key: service.symbol_key, source: app.qualified_name, target: service.qualified_name, confidence: 'high', provenance: ['tree-sitter'] }],
    module_graph: [], unsupported_patterns: [{ kind: 'eval_string', file_path: app.file_path, line_start: 7, snippet: 'eval $code', notes: 'String eval cannot be statically resolved' }], parse_failures: [], parse_diagnostics: [],
    index_stats: { total_files: 2, parsed_files: 2, failed_files: 0, parse_error_count: 0, symbol_count: 2, relationship_count: 1, dynamic_pattern_count: 1, index_state: 'degraded' }
  };
}

describe('output writer', () => {
  it('uses exact call keys for display summaries and includes unresolved confidence diagnostics', () => {
    const summary = renderSummary(analysis());
    expect(summary.schema_version).toBe(2);
    expect(summary.top_callers).toEqual([{ symbol: 'My::App::run', outgoing_calls: 1 }]);
    expect(summary.top_callees).toEqual([{ symbol: 'My::Service::execute', incoming_calls: 1 }]);
    expect(summary.confidence_audit.relationships).toEqual([{ confidence: 'high', count: 1 }, { confidence: 'low', count: 1 }]);
    expect(summary.confidence_audit.examples).toMatchObject([{ target: 'maybe', notes: expect.stringMatching(/did not resolve/) }]);
  });

  it('does not merge duplicate display names with different exact keys', () => {
    const payload = analysis();
    const duplicate = symbol({ qualified_name: 'My::App::run', name: 'run', kind: 'sub', language: 'perl', file_path: 'lib/My/Other.pm', line_start: 3, line_end: 8, provenance: ['tree-sitter'] });
    payload.call_graph = [
      ...payload.call_graph,
      { source_key: duplicate.symbol_key, target_key: payload.symbols[1]!.symbol_key, source: duplicate.qualified_name, target: payload.symbols[1]!.qualified_name, confidence: 'high', provenance: ['tree-sitter'] }
    ];

    const summary = renderSummary(payload);
    expect(summary.top_callers.filter((entry) => entry.symbol === 'My::App::run')).toEqual([
      { symbol: 'My::App::run', outgoing_calls: 1 },
      { symbol: 'My::App::run', outgoing_calls: 1 }
    ]);
  });

  it('writes stable pretty JSON', async () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'perlgraph-'));
    const out = path.join(dir, 'analysis.json');
    try {
      await writeJsonAtomic(out, { zed: true, alpha: { beta: 2 } });
      expect(readFileSync(out, 'utf8')).toBe('{\n  "zed": true,\n  "alpha": {\n    "beta": 2\n  }\n}\n');
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
