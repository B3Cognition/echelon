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
});
