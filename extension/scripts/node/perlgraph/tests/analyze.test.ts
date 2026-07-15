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
      expect(analysis.parse_failures).toEqual([{
        file_path: 'lib/My/Broken.pm',
        error: 'synthetic extraction failure'
      }]);
      expect(analysis.symbols.some((symbol) => symbol.qualified_name === 'My::Ok::ready')).toBe(true);
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
});
