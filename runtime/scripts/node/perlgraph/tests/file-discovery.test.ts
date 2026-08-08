import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { discoverPerlFiles, isPerlFile } from '../src/extraction/files.js';

describe('Perl file discovery', () => {
  it('recognizes Perl extensions and shebang scripts', () => {
    expect(isPerlFile('lib/My/App.pm')).toBe(true);
    expect(isPerlFile('script/run.pl')).toBe(true);
    expect(isPerlFile('t/app.t')).toBe(true);
    expect(isPerlFile('app.psgi')).toBe(true);
    expect(isPerlFile('bin/tool', '#!/usr/bin/env perl\nprint 1;\n')).toBe(true);
    expect(isPerlFile('README.md')).toBe(false);
  });

  it('discovers supported files while ignoring common generated directories', async () => {
    const root = path.join(tmpdir(), `perlgraph-files-${Date.now()}`);
    try {
      mkdirSync(path.join(root, 'lib/My'), { recursive: true });
      mkdirSync(path.join(root, 't'), { recursive: true });
      mkdirSync(path.join(root, 'local/lib'), { recursive: true });
      mkdirSync(path.join(root, 'node_modules/x'), { recursive: true });
      mkdirSync(path.join(root, 'bin'), { recursive: true });
      writeFileSync(path.join(root, 'lib/My/App.pm'), 'package My::App;\n1;\n');
      writeFileSync(path.join(root, 't/app.t'), 'use Test::More;\n');
      writeFileSync(path.join(root, 'app.psgi'), 'sub { [200, [], []] };\n');
      writeFileSync(path.join(root, 'bin/tool'), '#!/usr/bin/env perl\nprint 1;\n');
      writeFileSync(path.join(root, 'local/lib/Generated.pm'), 'package Generated;\n1;\n');
      writeFileSync(path.join(root, 'node_modules/x/Bad.pm'), 'package Bad;\n1;\n');

      const files = await discoverPerlFiles(root);
      expect(files.map((file) => file.relativePath).sort()).toEqual([
        'app.psgi',
        'bin/tool',
        'lib/My/App.pm',
        't/app.t'
      ]);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('returns absolute paths when discovering from a relative repo path', async () => {
    const root = path.join(tmpdir(), `perlgraph-relative-files-${Date.now()}`);
    const relativeRoot = path.relative(process.cwd(), root);
    try {
      mkdirSync(path.join(root, 'lib'), { recursive: true });
      writeFileSync(path.join(root, 'lib/App.pm'), 'package App;\n1;\n');

      const [file] = await discoverPerlFiles(relativeRoot);
      expect(file?.relativePath).toBe('lib/App.pm');
      expect(path.isAbsolute(file?.absolutePath ?? '')).toBe(true);
      expect(file?.absolutePath).toBe(path.join(root, 'lib/App.pm'));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
