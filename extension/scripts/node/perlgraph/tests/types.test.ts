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
