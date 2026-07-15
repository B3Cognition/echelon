import { describe, expect, it } from 'vitest';
import { resolveCalls } from '../src/resolution/call-resolver.js';
import type { PerlSymbol } from '../src/types.js';

const symbols: PerlSymbol[] = [
  { qualified_name: 'My::App::run', name: 'run', kind: 'method', language: 'perl', file_path: 'lib/My/App.pm', line_start: 10, line_end: 20, provenance: ['tree-sitter'] },
  { qualified_name: 'My::App::helper', name: 'helper', kind: 'sub', language: 'perl', file_path: 'lib/My/App.pm', line_start: 22, line_end: 24, provenance: ['tree-sitter'] },
  { qualified_name: 'My::App::build', name: 'build', kind: 'method', language: 'perl', file_path: 'lib/My/App.pm', line_start: 26, line_end: 28, provenance: ['tree-sitter'] },
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

  it('resolves current package methods called on self or class receivers', () => {
    const relationships = resolveCalls(
      [
        { caller: 'My::App::run', expression: '$self->helper', file_path: 'lib/My/App.pm', line_start: 16 },
        { caller: 'My::App::run', expression: '$class->build', file_path: 'lib/My/App.pm', line_start: 17 }
      ],
      symbols
    );

    expect(relationships).toEqual([
      {
        source: 'My::App::run',
        target: 'My::App::helper',
        kind: 'calls',
        file_path: 'lib/My/App.pm',
        line_start: 16,
        confidence: 'medium',
        provenance: ['tree-sitter', 'self-method-resolution']
      },
      {
        source: 'My::App::run',
        target: 'My::App::build',
        kind: 'calls',
        file_path: 'lib/My/App.pm',
        line_start: 17,
        confidence: 'medium',
        provenance: ['tree-sitter', 'self-method-resolution']
      }
    ]);
  });

  it('resolves method calls with receiver types inferred from local constructor assignment', () => {
    const relationships = resolveCalls(
      [{ caller: 'My::App::run', expression: '$svc->execute', receiver_type: 'My::Service', file_path: 'lib/My/App.pm', line_start: 18 }],
      symbols
    );

    expect(relationships).toEqual([
      {
        source: 'My::App::run',
        target: 'My::Service::execute',
        kind: 'calls',
        file_path: 'lib/My/App.pm',
        line_start: 18,
        confidence: 'medium',
        provenance: ['tree-sitter', 'local-constructor-flow']
      }
    ]);
  });

  it('resolves explicit imported bare calls as medium-confidence external calls', () => {
    const relationships = resolveCalls(
      [
        { caller: 'My::App::run', expression: 'decode_json', imported_from: 'JSON', file_path: 'lib/My/App.pm', line_start: 19 },
        { caller: 'My::App::run', expression: 'helper', imported_from: 'Other::Helpers', file_path: 'lib/My/App.pm', line_start: 20 }
      ],
      symbols
    );

    expect(relationships).toEqual([
      {
        source: 'My::App::run',
        target: 'JSON::decode_json',
        kind: 'calls',
        file_path: 'lib/My/App.pm',
        line_start: 19,
        confidence: 'medium',
        provenance: ['tree-sitter', 'explicit-import-resolution'],
        notes: 'Bare call decode_json matched explicit import from JSON'
      },
      {
        source: 'My::App::run',
        target: 'My::App::helper',
        kind: 'calls',
        file_path: 'lib/My/App.pm',
        line_start: 20,
        confidence: 'high',
        provenance: ['tree-sitter', 'name-resolution']
      }
    ]);
  });

  it('classifies common DBI and project database wrapper method calls', () => {
    const relationships = resolveCalls(
      [
        { caller: 'My::App::run', expression: '$dbh->prepare', file_path: 'lib/My/App.pm', line_start: 21 },
        { caller: 'My::App::run', expression: '$sth->fetchrow_hashref', file_path: 'lib/My/App.pm', line_start: 22 },
        { caller: 'My::App::run', expression: '$mc->query', file_path: 'lib/My/App.pm', line_start: 23 },
        { caller: 'My::App::run', expression: '$rows->get', file_path: 'lib/My/App.pm', line_start: 24 }
      ],
      symbols
    );

    expect(relationships).toEqual([
      {
        source: 'My::App::run',
        target: 'DBI::db::prepare',
        kind: 'calls',
        file_path: 'lib/My/App.pm',
        line_start: 21,
        confidence: 'medium',
        provenance: ['tree-sitter', 'external-api-resolution'],
        notes: 'Receiver $dbh matched common DBI database handle API'
      },
      {
        source: 'My::App::run',
        target: 'DBI::st::fetchrow_hashref',
        kind: 'calls',
        file_path: 'lib/My/App.pm',
        line_start: 22,
        confidence: 'medium',
        provenance: ['tree-sitter', 'external-api-resolution'],
        notes: 'Receiver $sth matched common DBI statement handle API'
      },
      {
        source: 'My::App::run',
        target: 'Opta::Database::query',
        kind: 'calls',
        file_path: 'lib/My/App.pm',
        line_start: 23,
        confidence: 'medium',
        provenance: ['tree-sitter', 'external-api-resolution'],
        notes: 'Receiver $mc matched common Opta database wrapper API'
      },
      {
        source: 'My::App::run',
        target: 'get',
        kind: 'calls',
        file_path: 'lib/My/App.pm',
        line_start: 24,
        confidence: 'low',
        provenance: ['method-name-match'],
        notes: 'Receiver type for $rows->get was not statically resolved'
      }
    ]);
  });

  it('classifies external APIs from inferred receiver types when variable names are generic', () => {
    const relationships = resolveCalls(
      [
        { caller: 'My::App::run', expression: '$cursor->fetchrow_hashref', receiver_type: 'DBI::st', file_path: 'lib/My/App.pm', line_start: 25 },
        { caller: 'My::App::run', expression: '$handle->quote', receiver_type: 'DBI::db', file_path: 'lib/My/App.pm', line_start: 26 }
      ],
      symbols
    );

    expect(relationships).toEqual([
      {
        source: 'My::App::run',
        target: 'DBI::st::fetchrow_hashref',
        kind: 'calls',
        file_path: 'lib/My/App.pm',
        line_start: 25,
        confidence: 'medium',
        provenance: ['tree-sitter', 'external-api-resolution'],
        notes: 'Receiver type DBI::st matched common DBI statement handle API'
      },
      {
        source: 'My::App::run',
        target: 'DBI::db::quote',
        kind: 'calls',
        file_path: 'lib/My/App.pm',
        line_start: 26,
        confidence: 'medium',
        provenance: ['tree-sitter', 'external-api-resolution'],
        notes: 'Receiver type DBI::db matched common DBI database handle API'
      }
    ]);
  });
});
