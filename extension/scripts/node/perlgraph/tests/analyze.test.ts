import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

async function loadAnalyzer(): Promise<typeof import('../src/analysis/analyze.js')> {
  return import('../src/analysis/analyze.js');
}

describe('analyzeRepository', () => {
  afterEach(() => {
    vi.doUnmock('../src/extraction/perl-extractor.js');
    vi.resetModules();
  });

  it('builds symbols, module graph, and call graph for a tiny Perl repo', async () => {
    const { analyzeRepository } = await loadAnalyzer();
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
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/Service.pm'), [
        'package My::Service;',
        'sub execute { return 1; }',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 't/app.t'), [
        'use Test::More;',
        'use My::App;',
        'ok(My::App::run());',
        'done_testing;'
      ].join('\n'));

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
      expect(analysis.parse_failures).toEqual([]);
      expect(analysis.parse_diagnostics).toEqual([]);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('rejects when the repository path does not exist', async () => {
    const { analyzeRepository } = await loadAnalyzer();
    const missingRoot = path.join(tmpdir(), `perlgraph-missing-${Date.now()}`);

    await expect(analyzeRepository(missingRoot)).rejects.toThrow(/Repository path does not exist/);
  });

  it('continues after extraction failures and reports degraded index stats', async () => {
    vi.doMock('../src/extraction/perl-extractor.js', async (importOriginal) => {
      const actual = await importOriginal<typeof import('../src/extraction/perl-extractor.js')>();
      return {
        ...actual,
        extractPerlFile(filePath: string, content: string) {
          if (filePath === 'lib/My/Broken.pm') {
            throw new Error('synthetic extraction failure');
          }
          return actual.extractPerlFile(filePath, content);
        }
      };
    });
    const { analyzeRepository } = await loadAnalyzer();
    const root = path.join(tmpdir(), `perlgraph-failure-${Date.now()}`);
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/Ok.pm'), [
        'package My::Ok;',
        'sub ready { return 1; }',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/Broken.pm'), [
        'package My::Broken;',
        'sub nope { return 0; }',
        '1;'
      ].join('\n'));

      const analysis = await analyzeRepository(root);

      expect(analysis.index_stats.index_state).toBe('degraded');
      expect(analysis.index_stats.total_files).toBe(2);
      expect(analysis.index_stats.parsed_files).toBe(1);
      expect(analysis.index_stats.failed_files).toBe(1);
      expect(analysis.index_stats.parse_error_count).toBe(0);
      expect(analysis.parse_failures).toEqual([{
        file_path: 'lib/My/Broken.pm',
        error: 'synthetic extraction failure'
      }]);
      expect(analysis.symbols.some((symbol) => symbol.qualified_name === 'My::Ok::ready')).toBe(true);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('reports parse diagnostics without failing partial analysis', async () => {
    const { analyzeRepository } = await loadAnalyzer();
    const root = path.join(tmpdir(), `perlgraph-parse-diagnostic-${Date.now()}`);
    try {
      mkdirSync(path.join(root, 'lib'), { recursive: true });
      writeFileSync(path.join(root, 'lib/Broken.pm'), [
        'package Broken;',
        'sub ok { return 1; }',
        'sub broken { if ('
      ].join('\n'));

      const analysis = await analyzeRepository(root);

      expect(analysis.parse_failures).toEqual([]);
      expect(analysis.parse_diagnostics).toEqual([{
        file_path: 'lib/Broken.pm',
        error_count: expect.any(Number),
        notes: 'tree-sitter reported parse errors; extraction may be partial'
      }]);
      expect(analysis.parse_diagnostics[0]!.error_count).toBeGreaterThan(0);
      expect(analysis.index_stats.parse_error_count).toBe(analysis.parse_diagnostics[0]!.error_count);
      expect(analysis.index_stats.index_state).toBe('degraded');
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('omits undefined optional properties for module resolution output', async () => {
    const { analyzeRepository } = await loadAnalyzer();
    const root = path.join(tmpdir(), `perlgraph-unresolved-${Date.now()}`);
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/App.pm'), [
        'package My::App;',
        'use My::Service;',
        'use Missing::Thing;',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/Service.pm'), [
        'package My::Service;',
        '1;'
      ].join('\n'));

      const analysis = await analyzeRepository(root);
      const resolvedModule = analysis.module_graph.find((entry) => entry.target_module === 'My::Service');
      const unresolvedModule = analysis.module_graph.find((entry) => entry.target_module === 'Missing::Thing');
      const resolvedRelationship = analysis.relationships.find((relationship) => relationship.target === 'My::Service');
      const unresolvedRelationship = analysis.relationships.find((relationship) => relationship.target === 'Missing::Thing');

      expect(resolvedModule).toMatchObject({
        source_module: 'My::App',
        target_module: 'My::Service',
        target_file: 'lib/My/Service.pm',
        confidence: 'high'
      });
      expect(Object.hasOwn(resolvedRelationship!, 'notes')).toBe(false);
      expect(unresolvedModule).toMatchObject({
        source_module: 'My::App',
        target_module: 'Missing::Thing',
        confidence: 'low'
      });
      expect(Object.hasOwn(unresolvedModule!, 'target_file')).toBe(false);
      expect(JSON.stringify(unresolvedModule)).not.toContain('target_file');
      expect(unresolvedRelationship).toMatchObject({
        target: 'Missing::Thing',
        notes: 'Module Missing::Thing did not resolve to a repository file'
      });
      expect(Object.hasOwn(unresolvedRelationship!, 'notes')).toBe(true);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('resolves safe local method inference while preserving dynamic diagnostics', async () => {
    const { analyzeRepository } = await loadAnalyzer();
    const root = path.join(tmpdir(), `perlgraph-dynamic-roadmap-${Date.now()}`);
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/App.pm'), [
        'package My::App;',
        'use Moo;',
        'use My::Service;',
        'with "My::Role";',
        'has service => (is => "ro");',
        'sub run {',
        '  my ($self) = @_;',
        '  my $svc = My::Service->new();',
        '  $self->helper();',
        '  $self->service();',
        '  return $svc->execute();',
        '}',
        'sub helper { return 1; }',
        'eval $code;',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/Role.pm'), [
        'package My::Role;',
        'use Moo::Role;',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/Service.pm'), [
        'package My::Service;',
        'sub new { bless {}, shift }',
        'sub execute { return 1; }',
        '1;'
      ].join('\n'));

      const analysis = await analyzeRepository(root);

      expect(analysis.call_graph).toContainEqual({
        source: 'My::App::run',
        target: 'My::App::helper',
        confidence: 'medium',
        provenance: ['tree-sitter', 'self-method-resolution']
      });
      expect(analysis.call_graph).toContainEqual({
        source: 'My::App::run',
        target: 'My::App::service',
        confidence: 'medium',
        provenance: ['tree-sitter', 'self-method-resolution']
      });
      expect(analysis.call_graph).toContainEqual({
        source: 'My::App::run',
        target: 'My::Service::execute',
        confidence: 'medium',
        provenance: ['tree-sitter', 'local-constructor-flow']
      });
      expect(analysis.relationships).toContainEqual({
        source: 'My::App',
        target: 'My::Role',
        kind: 'uses_role',
        file_path: 'lib/My/App.pm',
        line_start: 4,
        confidence: 'high',
        provenance: ['moose-moo-role', 'module-resolution']
      });
      expect(analysis.unsupported_patterns).toContainEqual({
        kind: 'eval_string',
        file_path: 'lib/My/App.pm',
        line_start: 14,
        snippet: 'eval $code;',
        notes: 'String eval cannot be statically resolved'
      });
      expect(analysis.index_stats.index_state).toBe('degraded');
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('resolves self method calls through static parent inheritance', async () => {
    const { analyzeRepository } = await loadAnalyzer();
    const root = path.join(tmpdir(), `perlgraph-inherited-method-${Date.now()}`);
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/Child.pm'), [
        'package My::Child;',
        'use parent "My::Base";',
        'sub run {',
        '  my ($self) = @_;',
        '  return $self->shared();',
        '}',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/Base.pm'), [
        'package My::Base;',
        'sub shared { return 1; }',
        '1;'
      ].join('\n'));

      const analysis = await analyzeRepository(root);

      expect(analysis.call_graph).toContainEqual({
        source: 'My::Child::run',
        target: 'My::Base::shared',
        confidence: 'medium',
        provenance: ['tree-sitter', 'inheritance-method-resolution']
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('resolves self method calls supplied by static Moose and Moo roles', async () => {
    const { analyzeRepository } = await loadAnalyzer();
    const root = path.join(tmpdir(), `perlgraph-role-method-${Date.now()}`);
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/App.pm'), [
        'package My::App;',
        'use Moo;',
        'with "My::Role";',
        'sub run {',
        '  my ($self) = @_;',
        '  return $self->provided();',
        '}',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/Role.pm'), [
        'package My::Role;',
        'use Moo::Role;',
        'sub provided { return 1; }',
        '1;'
      ].join('\n'));

      const analysis = await analyzeRepository(root);

      expect(analysis.call_graph).toContainEqual({
        source: 'My::App::run',
        target: 'My::Role::provided',
        confidence: 'medium',
        provenance: ['tree-sitter', 'role-method-resolution']
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('resolves self method calls through transitive static role composition', async () => {
    const { analyzeRepository } = await loadAnalyzer();
    const root = path.join(tmpdir(), `perlgraph-transitive-role-${Date.now()}`);
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/App.pm'), [
        'package My::App;',
        'use Moo;',
        'with "My::OuterRole";',
        'sub run {',
        '  my ($self) = @_;',
        '  return $self->inner_method();',
        '}',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/OuterRole.pm'), [
        'package My::OuterRole;',
        'use Moo::Role;',
        'with "My::InnerRole";',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/InnerRole.pm'), [
        'package My::InnerRole;',
        'use Moo::Role;',
        'sub inner_method { return 1; }',
        '1;'
      ].join('\n'));

      const analysis = await analyzeRepository(root);

      expect(analysis.call_graph).toContainEqual({
        source: 'My::App::run',
        target: 'My::InnerRole::inner_method',
        confidence: 'medium',
        provenance: ['tree-sitter', 'role-method-resolution']
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('treats literal Moose and Moo extends declarations as inheritance', async () => {
    const { analyzeRepository } = await loadAnalyzer();
    const root = path.join(tmpdir(), `perlgraph-moose-extends-${Date.now()}`);
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/Child.pm'), [
        'package My::Child;',
        'use Moose;',
        'extends "My::Base";',
        'sub run {',
        '  my ($self) = @_;',
        '  return $self->shared();',
        '}',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/Base.pm'), [
        'package My::Base;',
        'sub shared { return 1; }',
        '1;'
      ].join('\n'));

      const analysis = await analyzeRepository(root);

      expect(analysis.relationships).toContainEqual({
        source: 'My::Child',
        target: 'My::Base',
        kind: 'inherits',
        file_path: 'lib/My/Child.pm',
        line_start: 3,
        confidence: 'high',
        provenance: ['tree-sitter', 'module-resolution']
      });
      expect(analysis.call_graph).toContainEqual({
        source: 'My::Child::run',
        target: 'My::Base::shared',
        confidence: 'medium',
        provenance: ['tree-sitter', 'inheritance-method-resolution']
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('normalizes static quoted require module paths', async () => {
    const { analyzeRepository } = await loadAnalyzer();
    const root = path.join(tmpdir(), `perlgraph-quoted-require-${Date.now()}`);
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/App.pm'), [
        'package My::App;',
        'require "My/Service.pm";',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/Service.pm'), [
        'package My::Service;',
        '1;'
      ].join('\n'));

      const analysis = await analyzeRepository(root);

      expect(analysis.module_graph).toContainEqual({
        source_module: 'My::App',
        target_module: 'My::Service',
        source_file: 'lib/My/App.pm',
        target_file: 'lib/My/Service.pm',
        kind: 'require',
        confidence: 'high'
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('resolves self method calls through transitive static inheritance', async () => {
    const { analyzeRepository } = await loadAnalyzer();
    const root = path.join(tmpdir(), `perlgraph-transitive-inheritance-${Date.now()}`);
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/Child.pm'), [
        'package My::Child;',
        'use parent "My::Middle";',
        'sub run {',
        '  my ($self) = @_;',
        '  return $self->shared();',
        '}',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/Middle.pm'), [
        'package My::Middle;',
        'use parent "My::Base";',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/Base.pm'), [
        'package My::Base;',
        'sub shared { return 1; }',
        '1;'
      ].join('\n'));

      const analysis = await analyzeRepository(root);

      expect(analysis.call_graph).toContainEqual({
        source: 'My::Child::run',
        target: 'My::Base::shared',
        confidence: 'medium',
        provenance: ['tree-sitter', 'inheritance-method-resolution']
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('resolves constrained static require concatenation', async () => {
    const { analyzeRepository } = await loadAnalyzer();
    const root = path.join(tmpdir(), `perlgraph-require-concat-${Date.now()}`);
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/App.pm'), [
        'package My::App;',
        'require "My/" . "Service.pm";',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/Service.pm'), [
        'package My::Service;',
        '1;'
      ].join('\n'));

      const analysis = await analyzeRepository(root);

      expect(analysis.module_graph).toContainEqual({
        source_module: 'My::App',
        target_module: 'My::Service',
        source_file: 'lib/My/App.pm',
        target_file: 'lib/My/Service.pm',
        kind: 'require',
        confidence: 'high'
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('resolves implicit exports from imported repository modules when unambiguous', async () => {
    const { analyzeRepository } = await loadAnalyzer();
    const root = path.join(tmpdir(), `perlgraph-implicit-export-${Date.now()}`);
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/Log.pm'), [
        'package My::Log;',
        'use Exporter "import";',
        'our @EXPORT = qw(qlog INFO);',
        'sub qlog { return 1; }',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/Other.pm'), [
        'package My::Other;',
        'use Exporter "import";',
        'our @EXPORT = qw(helper);',
        'sub helper { return 1; }',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/Ambiguous.pm'), [
        'package My::Ambiguous;',
        'use Exporter "import";',
        'our @EXPORT = qw(helper);',
        'sub helper { return 1; }',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/App.pm'), [
        'package My::App;',
        'use My::Log;',
        'use My::Other;',
        'use My::Ambiguous;',
        'sub run {',
        '  qlog(INFO, __PACKAGE__, "hello");',
        '  helper();',
        '}',
        '1;'
      ].join('\n'));

      const analysis = await analyzeRepository(root);

      expect(analysis.relationships).toContainEqual({
        source: 'My::App::run',
        target: 'My::Log::qlog',
        kind: 'calls',
        file_path: 'lib/My/App.pm',
        line_start: 6,
        confidence: 'medium',
        provenance: ['tree-sitter', 'implicit-export-resolution'],
        notes: 'Bare call qlog matched implicit export from My::Log'
      });
      expect(analysis.relationships).toContainEqual({
        source: 'My::App::run',
        target: 'helper',
        kind: 'calls',
        file_path: 'lib/My/App.pm',
        line_start: 7,
        confidence: 'low',
        provenance: ['unresolved-call'],
        notes: 'Call expression helper did not resolve to a known symbol'
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
