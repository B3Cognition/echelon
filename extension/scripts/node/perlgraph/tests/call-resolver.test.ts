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

  it('keeps self calls with multiple inherited implementations out of the traversable graph', () => {
    const parentOne = symbol({ qualified_name: 'My::ParentOne::shared', name: 'shared', kind: 'method', language: 'perl', file_path: 'lib/My/ParentOne.pm', line_start: 2, line_end: 4, provenance: ['tree-sitter'] });
    const parentTwo = symbol({ qualified_name: 'My::ParentTwo::shared', name: 'shared', kind: 'method', language: 'perl', file_path: 'lib/My/ParentTwo.pm', line_start: 2, line_end: 4, provenance: ['tree-sitter'] });
    const result = resolveCalls(
      [{ caller: 'My::App::run', expression: '$self->shared', file_path: 'lib/My/App.pm', line_start: 18 }],
      [...symbols, parentOne, parentTwo],
      { inheritance: new Map([['My::App', ['My::ParentOne', 'My::ParentTwo']]]) }
    );

    expect(result.relationships).toEqual([]);
    expect(result.unresolved_relationships).toMatchObject([{
      source_key: symbols[0]!.symbol_key,
      target: 'shared',
      provenance: ['tree-sitter', 'ambiguous-self-method-resolution']
    }]);
  });

  it('keeps self calls with multiple role implementations out of the traversable graph', () => {
    const roleOne = symbol({ qualified_name: 'My::RoleOne::shared', name: 'shared', kind: 'method', language: 'perl', file_path: 'lib/My/RoleOne.pm', line_start: 2, line_end: 4, provenance: ['tree-sitter'] });
    const roleTwo = symbol({ qualified_name: 'My::RoleTwo::shared', name: 'shared', kind: 'method', language: 'perl', file_path: 'lib/My/RoleTwo.pm', line_start: 2, line_end: 4, provenance: ['tree-sitter'] });
    const result = resolveCalls(
      [{ caller: 'My::App::run', expression: '$self->shared', file_path: 'lib/My/App.pm', line_start: 19 }],
      [...symbols, roleOne, roleTwo],
      { roles: new Map([['My::App', ['My::RoleOne', 'My::RoleTwo']]]) }
    );

    expect(result.relationships).toEqual([]);
    expect(result.unresolved_relationships).toMatchObject([{
      source_key: symbols[0]!.symbol_key,
      target: 'shared',
      provenance: ['tree-sitter', 'ambiguous-self-method-resolution']
    }]);
  });

  it('does not prefer one inherited implementation over one role implementation', () => {
    const parent = symbol({ qualified_name: 'My::Parent::shared', name: 'shared', kind: 'method', language: 'perl', file_path: 'lib/My/Parent.pm', line_start: 2, line_end: 4, provenance: ['tree-sitter'] });
    const role = symbol({ qualified_name: 'My::Role::shared', name: 'shared', kind: 'method', language: 'perl', file_path: 'lib/My/Role.pm', line_start: 2, line_end: 4, provenance: ['tree-sitter'] });
    const result = resolveCalls(
      [{ caller: 'My::App::run', expression: '$self->shared', file_path: 'lib/My/App.pm', line_start: 20 }],
      [...symbols, parent, role],
      { inheritance: new Map([['My::App', ['My::Parent']]]), roles: new Map([['My::App', ['My::Role']]]) }
    );

    expect(result.relationships).toEqual([]);
    expect(result.unresolved_relationships).toMatchObject([{
      source_key: symbols[0]!.symbol_key,
      target: 'shared',
      provenance: ['tree-sitter', 'ambiguous-self-method-resolution'],
      notes: 'Self call $self->shared matched multiple methods: My::Parent::shared, My::Role::shared'
    }]);
  });

  it('resolves local self/class and inferred receiver calls to exact keys', () => {
    const build = symbol({ qualified_name: 'My::App::build', name: 'build', kind: 'method', language: 'perl', file_path: 'lib/My/App.pm', line_start: 25, line_end: 28, provenance: ['tree-sitter'] });
    const result = resolveCalls([
      { caller: 'My::App::run', expression: '$self->helper', file_path: 'lib/My/App.pm', line_start: 20 },
      { caller: 'My::App::run', expression: '$class->build', file_path: 'lib/My/App.pm', line_start: 21 },
      { caller: 'My::App::run', expression: '$svc->execute', receiver_type: 'My::Service', file_path: 'lib/My/App.pm', line_start: 22 }
    ], [...symbols, build]);

    expect(result.relationships).toMatchObject([
      { target: 'My::App::helper', confidence: 'medium', provenance: ['tree-sitter', 'self-method-resolution'] },
      { target: 'My::App::build', confidence: 'medium', provenance: ['tree-sitter', 'self-method-resolution'] },
      { target: 'My::Service::execute', confidence: 'medium', provenance: ['tree-sitter', 'local-constructor-flow'] }
    ]);
  });

  it('resolves transitive inheritance and role composition only when their endpoint is unique', () => {
    const base = symbol({ qualified_name: 'My::Base::shared', name: 'shared', kind: 'method', language: 'perl', file_path: 'lib/My/Base.pm', line_start: 2, line_end: 4, provenance: ['tree-sitter'] });
    const role = symbol({ qualified_name: 'My::InnerRole::provided', name: 'provided', kind: 'method', language: 'perl', file_path: 'lib/My/InnerRole.pm', line_start: 2, line_end: 4, provenance: ['tree-sitter'] });
    const result = resolveCalls([
      { caller: 'My::App::run', expression: '$self->shared', file_path: 'lib/My/App.pm', line_start: 23 },
      { caller: 'My::App::run', expression: '$self->provided', file_path: 'lib/My/App.pm', line_start: 24 }
    ], [...symbols, base, role], {
      inheritance: new Map([['My::App', ['My::Child']], ['My::Child', ['My::Base']]]),
      roles: new Map([['My::App', ['My::OuterRole']], ['My::OuterRole', ['My::InnerRole']]])
    });

    expect(result.relationships).toMatchObject([
      { target: 'My::Base::shared', target_key: base.symbol_key, provenance: ['tree-sitter', 'inheritance-method-resolution'] },
      { target: 'My::InnerRole::provided', target_key: role.symbol_key, provenance: ['tree-sitter', 'role-method-resolution'] }
    ]);
  });

  it('records explicit imports and external APIs as diagnostics unless a repository symbol exists', () => {
    const result = resolveCalls([
      { caller: 'My::App::run', expression: 'decode_json', imported_from: 'JSON', file_path: 'lib/My/App.pm', line_start: 25 },
      { caller: 'My::App::run', expression: '$dbh->prepare', file_path: 'lib/My/App.pm', line_start: 26 },
      { caller: 'My::App::run', expression: '$cursor->fetchrow_hashref', receiver_type: 'DBI::st', file_path: 'lib/My/App.pm', line_start: 27 },
      { caller: 'My::App::run', expression: '$mc->query', file_path: 'lib/My/App.pm', line_start: 28 }
    ], symbols);

    expect(result.relationships).toEqual([]);
    expect(result.unresolved_relationships).toMatchObject([
      { target: 'JSON::decode_json', provenance: ['tree-sitter', 'explicit-import-resolution'] },
      { target: 'DBI::db::prepare', provenance: ['tree-sitter', 'external-api-resolution'] },
      { target: 'DBI::st::fetchrow_hashref', provenance: ['tree-sitter', 'external-api-resolution'] },
      { target: 'Opta::Database::query', provenance: ['tree-sitter', 'external-api-resolution'] }
    ]);
  });
});
