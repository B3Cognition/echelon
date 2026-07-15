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
