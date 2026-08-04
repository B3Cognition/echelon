import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

async function loadAnalyzer(): Promise<typeof import('../src/analysis/analyze.js')> {
  return import('../src/analysis/analyze.js');
}

function repository(name: string): string {
  const root = path.join(tmpdir(), `perlgraph-${name}-${Date.now()}-${Math.random()}`);
  mkdirSync(root, { recursive: true });
  return root;
}

describe('analyzeRepository', () => {
  afterEach(() => {
    vi.doUnmock('../src/extraction/perl-extractor.js');
    vi.resetModules();
  });

  it('emits schema 2 exact symbols and relationships for a healthy Perl repository', async () => {
    const root = repository('ready');
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/App.pm'), 'package My::App;\nuse My::Service;\nsub run {\n  My::Service::execute();\n}\n1;\n');
      writeFileSync(path.join(root, 'lib/My/Service.pm'), 'package My::Service;\nsub execute { 1 }\n1;\n');
      const analysis = await (await loadAnalyzer()).analyzeRepository(root);

      expect(analysis).toMatchObject({ schema_version: 2, tool: 'perlgraph', tool_version: '0.1.0', provider_status: 'ready', complete: true });
      expect(analysis.counts.emitted_symbols).toBe(analysis.symbols.length);
      expect(analysis.symbols.every((symbol) => /^sha256:[0-9a-f]{64}$/.test(symbol.symbol_key))).toBe(true);
      expect(analysis.relationships).toEqual(expect.arrayContaining([
        expect.objectContaining({ kind: 'calls', source: 'My::App::run', target: 'My::Service::execute', source_key: expect.any(String), target_key: expect.any(String) })
      ]));
      expect(analysis.relationships.every((relationship) => analysis.symbols.some((symbol) => symbol.symbol_key === relationship.source_key) && analysis.symbols.some((symbol) => symbol.symbol_key === relationship.target_key))).toBe(true);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('reports no Perl files as a complete unsupported capability result', async () => {
    const root = repository('unsupported');
    try {
      const analysis = await (await loadAnalyzer()).analyzeRepository(root);
      expect(analysis).toMatchObject({ supported: false, provider_status: 'unsupported', complete: true });
      expect(analysis.counts).toMatchObject({ discovered_files: 0, emitted_symbols: 0 });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('reports Perl files with no symbols as complete but empty', async () => {
    vi.doMock('../src/extraction/perl-extractor.js', async (importOriginal) => {
      const actual = await importOriginal<typeof import('../src/extraction/perl-extractor.js')>();
      return { ...actual, extractPerlFile: () => ({ symbols: [], dependencies: [], role_applications: [], exports: [], calls: [], unsupported_patterns: [], parse_diagnostics: [] }) };
    });
    const root = repository('empty');
    try {
      writeFileSync(path.join(root, 'Empty.pm'), 'package Empty;\n1;\n');
      const analysis = await (await loadAnalyzer()).analyzeRepository(root);
      expect(analysis).toMatchObject({ supported: true, provider_status: 'empty', complete: true });
      expect(analysis.counts).toMatchObject({ discovered_files: 1, emitted_symbols: 0 });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('reports parse diagnostics as degraded without discarding extracted symbols', async () => {
    const root = repository('degraded');
    try {
      writeFileSync(path.join(root, 'Broken.pm'), 'package Broken;\nsub okay { 1 }\nsub broken { if (\n');
      const analysis = await (await loadAnalyzer()).analyzeRepository(root);
      expect(analysis.provider_status).toBe('degraded');
      expect(analysis.complete).toBe(true);
      expect(analysis.counts.parse_diagnostics).toBeGreaterThan(0);
      expect(analysis.symbols.length).toBeGreaterThan(0);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('reports complete extraction failures as degraded and only counts emitted files', async () => {
    vi.doMock('../src/extraction/perl-extractor.js', async (importOriginal) => {
      const actual = await importOriginal<typeof import('../src/extraction/perl-extractor.js')>();
      return { ...actual, extractPerlFile: () => { throw new Error('synthetic extraction failure'); } };
    });
    const root = repository('failed');
    try {
      writeFileSync(path.join(root, 'Failed.pm'), 'package Failed;\n1;\n');
      const analysis = await (await loadAnalyzer()).analyzeRepository(root);
      expect(analysis).toMatchObject({ provider_status: 'degraded', complete: true });
      expect(analysis.counts).toMatchObject({ discovered_files: 1, emitted_files: 0, emitted_symbols: 0, parse_failures: 1 });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('rejects duplicate canonical locators before relationship resolution', async () => {
    vi.doMock('../src/extraction/perl-extractor.js', async (importOriginal) => {
      const actual = await importOriginal<typeof import('../src/extraction/perl-extractor.js')>();
      const duplicate = { qualified_name: 'Duplicate::run', name: 'run', kind: 'sub' as const, language: 'perl' as const, file_path: 'Duplicate.pm', line_start: 2, line_end: 2, signature: 'sub run', provenance: ['test'] };
      return { ...actual, extractPerlFile: () => ({ symbols: [duplicate, duplicate], dependencies: [], role_applications: [], exports: [], calls: [], unsupported_patterns: [], parse_diagnostics: [] }) };
    });
    const root = repository('duplicate');
    try {
      writeFileSync(path.join(root, 'Duplicate.pm'), 'package Duplicate;\n1;\n');
      await expect((await loadAnalyzer()).analyzeRepository(root)).rejects.toThrow(/duplicate canonical locator/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('rejects a repository path that does not exist', async () => {
    await expect((await loadAnalyzer()).analyzeRepository(path.join(tmpdir(), `missing-perlgraph-${Date.now()}`))).rejects.toThrow(/Repository path does not exist/);
  });

  it('continues after a partial extraction failure and reports only successfully emitted files', async () => {
    vi.doMock('../src/extraction/perl-extractor.js', async (importOriginal) => {
      const actual = await importOriginal<typeof import('../src/extraction/perl-extractor.js')>();
      return { ...actual, extractPerlFile(filePath: string, content: string) {
        if (filePath === 'lib/My/Broken.pm') throw new Error('synthetic extraction failure');
        return actual.extractPerlFile(filePath, content);
      } };
    });
    const root = repository('partial-failure');
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/Ok.pm'), 'package My::Ok;\nsub ready { 1 }\n1;\n');
      writeFileSync(path.join(root, 'lib/My/Broken.pm'), 'package My::Broken;\nsub nope { 0 }\n1;\n');
      const analysis = await (await loadAnalyzer()).analyzeRepository(root);
      expect(analysis).toMatchObject({ provider_status: 'degraded', complete: true });
      expect(analysis.counts).toMatchObject({ discovered_files: 2, emitted_files: 1, parse_failures: 1 });
      expect(analysis.parse_failures).toEqual([{ file_path: 'lib/My/Broken.pm', error: 'synthetic extraction failure' }]);
      expect(analysis.symbols.some((entry) => entry.qualified_name === 'My::Ok::ready')).toBe(true);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('retains resolved module edges and moves unresolved module observations to diagnostics', async () => {
    const root = repository('module-diagnostics');
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/App.pm'), 'package My::App;\nuse My::Service;\nuse Missing::Thing;\n1;\n');
      writeFileSync(path.join(root, 'lib/My/Service.pm'), 'package My::Service;\n1;\n');
      const analysis = await (await loadAnalyzer()).analyzeRepository(root);
      const resolvedModule = analysis.module_graph.find((entry) => entry.target_module === 'My::Service');
      const unresolvedModule = analysis.module_graph.find((entry) => entry.target_module === 'Missing::Thing');
      expect(resolvedModule).toMatchObject({ target_file: 'lib/My/Service.pm', confidence: 'high' });
      expect(Object.hasOwn(unresolvedModule!, 'target_file')).toBe(false);
      expect(analysis.relationships).toEqual(expect.arrayContaining([expect.objectContaining({ kind: 'imports', source: 'My::App', target: 'My::Service', source_key: expect.any(String), target_key: expect.any(String) })]));
      expect(analysis.unresolved_relationships).toEqual(expect.arrayContaining([expect.objectContaining({ kind: 'imports', target: 'Missing::Thing', notes: 'Module Missing::Thing did not resolve to a repository file' })]));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('preserves local receiver inference, self methods, and dynamic call diagnostics', async () => {
    const root = repository('local-inference');
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/App.pm'), 'package My::App;\nsub run {\n my ($self) = @_;\n my $svc = My::Service->new();\n $self->helper();\n $svc->execute();\n $dbh->prepare();\n}\nsub helper { 1 }\n1;\n');
      writeFileSync(path.join(root, 'lib/My/Service.pm'), 'package My::Service;\nsub new { bless {}, shift }\nsub execute { 1 }\n1;\n');
      const analysis = await (await loadAnalyzer()).analyzeRepository(root);
      expect(analysis.relationships).toEqual(expect.arrayContaining([
        expect.objectContaining({ target: 'My::App::helper', provenance: ['tree-sitter', 'self-method-resolution'] }),
        expect.objectContaining({ target: 'My::Service::execute', provenance: ['tree-sitter', 'local-constructor-flow'] })
      ]));
      expect(analysis.unresolved_relationships).toEqual(expect.arrayContaining([expect.objectContaining({ target: 'DBI::db::prepare', provenance: ['tree-sitter', 'external-api-resolution'] })]));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('resolves static inheritance and transitive role composition with exact endpoints', async () => {
    const root = repository('inheritance-roles');
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/App.pm'), 'package My::App;\nuse Moo;\nextends "My::Child";\nwith "My::OuterRole";\nsub run {\n my ($self) = @_;\n $self->shared();\n $self->provided();\n}\n1;\n');
      writeFileSync(path.join(root, 'lib/My/Child.pm'), 'package My::Child;\nuse parent "My::Base";\n1;\n');
      writeFileSync(path.join(root, 'lib/My/Base.pm'), 'package My::Base;\nsub shared { 1 }\n1;\n');
      writeFileSync(path.join(root, 'lib/My/OuterRole.pm'), 'package My::OuterRole;\nuse Moo::Role;\nwith "My::InnerRole";\n1;\n');
      writeFileSync(path.join(root, 'lib/My/InnerRole.pm'), 'package My::InnerRole;\nuse Moo::Role;\nsub provided { 1 }\n1;\n');
      const analysis = await (await loadAnalyzer()).analyzeRepository(root);
      expect(analysis.relationships).toEqual(expect.arrayContaining([
        expect.objectContaining({ kind: 'inherits', source: 'My::App', target: 'My::Child', source_key: expect.any(String), target_key: expect.any(String) }),
        expect.objectContaining({ target: 'My::Base::shared', provenance: ['tree-sitter', 'inheritance-method-resolution'] }),
        expect.objectContaining({ target: 'My::InnerRole::provided', provenance: ['tree-sitter', 'role-method-resolution'] })
      ]));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('extracts Moose extends declarations and resolves inherited self calls exactly', async () => {
    const root = repository('moose-inheritance');
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/App.pm'), 'package My::App;\nuse Moose;\nextends "My::Base";\nsub run {\n my ($self) = @_;\n $self->shared();\n}\n1;\n');
      writeFileSync(path.join(root, 'lib/My/Base.pm'), 'package My::Base;\nsub shared { 1 }\n1;\n');
      const analysis = await (await loadAnalyzer()).analyzeRepository(root);
      expect(analysis.relationships).toEqual(expect.arrayContaining([
        expect.objectContaining({ kind: 'inherits', source: 'My::App', target: 'My::Base', source_key: expect.any(String), target_key: expect.any(String) }),
        expect.objectContaining({ kind: 'calls', source: 'My::App::run', target: 'My::Base::shared', provenance: ['tree-sitter', 'inheritance-method-resolution'], source_key: expect.any(String), target_key: expect.any(String) })
      ]));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('normalizes static require paths and constrained concatenation', async () => {
    const root = repository('requires');
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/App.pm'), 'package My::App;\nrequire "My/Service.pm";\nrequire "My" . "/Other.pm";\n1;\n');
      writeFileSync(path.join(root, 'lib/My/Service.pm'), 'package My::Service;\n1;\n');
      writeFileSync(path.join(root, 'lib/My/Other.pm'), 'package My::Other;\n1;\n');
      const analysis = await (await loadAnalyzer()).analyzeRepository(root);
      expect(analysis.module_graph).toEqual(expect.arrayContaining([
        expect.objectContaining({ target_module: 'My::Service', kind: 'require', target_file: 'lib/My/Service.pm' }),
        expect.objectContaining({ target_module: 'My::Other', kind: 'require', target_file: 'lib/My/Other.pm' })
      ]));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('resolves implicit exports from repository modules and records external explicit imports as diagnostics', async () => {
    const root = repository('exports');
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/App.pm'), 'package My::App;\nuse My::Log;\nuse JSON qw(decode_json);\nsub run {\n qlog();\n decode_json();\n}\n1;\n');
      writeFileSync(path.join(root, 'lib/My/Log.pm'), 'package My::Log;\nour @EXPORT = qw(qlog);\nsub qlog { 1 }\n1;\n');
      const analysis = await (await loadAnalyzer()).analyzeRepository(root);
      expect(analysis.relationships).toEqual(expect.arrayContaining([expect.objectContaining({ target: 'My::Log::qlog', provenance: ['tree-sitter', 'implicit-export-resolution'] })]));
      expect(analysis.unresolved_relationships).toEqual(expect.arrayContaining([expect.objectContaining({ target: 'JSON::decode_json', provenance: ['tree-sitter', 'explicit-import-resolution'] })]));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
