import { describe, expect, it } from 'vitest';
import { symbolKey } from '../src/identity/symbol-key.js';
import { resolveCalls } from '../src/resolution/call-resolver.js';
import type { PerlSymbol } from '../src/types.js';

function symbol(value: Omit<PerlSymbol, 'symbol_key'>): PerlSymbol {
  return { ...value, symbol_key: symbolKey(value) };
}

const symbols: PerlSymbol[] = [
  symbol({ qualified_name: 'My::App::run', name: 'run', kind: 'method', language: 'perl', file_path: 'lib/My/App.pm', line_start: 10, line_end: 20, provenance: ['tree-sitter'] }),
  symbol({ qualified_name: 'My::App::helper', name: 'helper', kind: 'sub', language: 'perl', file_path: 'lib/My/App.pm', line_start: 22, line_end: 24, provenance: ['tree-sitter'] }),
  symbol({ qualified_name: 'My::Service::execute', name: 'execute', kind: 'sub', language: 'perl', file_path: 'lib/My/Service.pm', line_start: 5, line_end: 8, provenance: ['tree-sitter'] })
];

describe('call resolver', () => {
  it('emits only exact-key traversable relationships', () => {
    const result = resolveCalls([
      { caller: 'My::App::run', expression: 'helper', file_path: 'lib/My/App.pm', line_start: 12 },
      { caller: 'My::App::run', expression: 'My::Service::execute', file_path: 'lib/My/App.pm', line_start: 13 }
    ], symbols);

    expect(result.unresolved_relationships).toEqual([]);
    expect(result.relationships).toMatchObject([
      { source: 'My::App::run', target: 'My::App::helper', source_key: symbols[0]!.symbol_key, target_key: symbols[1]!.symbol_key, confidence: 'high' },
      { source: 'My::App::run', target: 'My::Service::execute', source_key: symbols[0]!.symbol_key, target_key: symbols[2]!.symbol_key, confidence: 'high' }
    ]);
  });

  it('keeps dynamic and external targets in diagnostics instead of fabricated graph edges', () => {
    const result = resolveCalls([
      { caller: 'My::App::run', expression: '$svc->execute', file_path: 'lib/My/App.pm', line_start: 15 },
      { caller: 'My::App::run', expression: 'decode_json', imported_from: 'JSON', file_path: 'lib/My/App.pm', line_start: 16 }
    ], symbols);

    expect(result.relationships).toEqual([]);
    expect(result.unresolved_relationships).toMatchObject([
      { source_key: symbols[0]!.symbol_key, target: 'execute', confidence: 'low', provenance: ['method-name-match'] },
      { source_key: symbols[0]!.symbol_key, target: 'JSON::decode_json', confidence: 'medium', provenance: ['tree-sitter', 'explicit-import-resolution'] }
    ]);
  });

  it('does not resolve ambiguous qualified names to an arbitrary symbol key', () => {
    const duplicate = symbol({ ...symbols[2]!, file_path: 'lib/Other.pm' });
    const result = resolveCalls([
      { caller: 'My::App::run', expression: 'My::Service::execute', file_path: 'lib/My/App.pm', line_start: 17 }
    ], [...symbols, duplicate]);

    expect(result.relationships).toEqual([]);
    expect(result.unresolved_relationships).toHaveLength(1);
  });
});
