import { describe, expect, it } from 'vitest';
import type { PerlGraphAnalysis } from '../src/types.js';

describe('PerlGraphAnalysis type contract', () => {
  it('accepts the minimum valid analysis payload', () => {
    const payload: PerlGraphAnalysis = {
      schema_version: 2,
      tool: 'perlgraph',
      tool_version: '0.1.0',
      generated_at: '2026-06-17T00:00:00.000Z',
      repo_path: '/repo',
      supported: false,
      provider_status: 'unsupported',
      complete: true,
      counts: {
        discovered_files: 0, emitted_files: 0, discovered_symbols: 0, emitted_symbols: 0,
        discovered_relationships: 0, emitted_relationships: 0, unresolved_relationships: 0,
        parse_failures: 0, parse_diagnostics: 0, dynamic_patterns: 0
      },
      capabilities: {
        language: 'perl', supported_extensions: ['.pl', '.pm', '.t', '.psgi'],
        exact_symbol_keys: true, exact_relationship_endpoints: true, unresolved_relationship_diagnostics: true
      },
      language_coverage: {
        '.pl': 'supported',
        '.pm': 'supported',
        '.t': 'supported',
        '.psgi': 'supported'
      },
      symbols: [],
      relationships: [],
      unresolved_relationships: [],
      call_graph: [],
      module_graph: [],
      unsupported_patterns: [],
      parse_failures: [],
      parse_diagnostics: [],
      index_stats: {
        total_files: 0,
        parsed_files: 0,
        failed_files: 0,
        parse_error_count: 0,
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
