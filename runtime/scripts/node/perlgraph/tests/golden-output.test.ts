import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { analyzeRepository } from '../src/analysis/analyze.js';
import { renderSummary } from '../src/output/writer.js';
import type { PerlGraphAnalysis } from '../src/types.js';

function normalizeAnalysis(analysis: PerlGraphAnalysis): PerlGraphAnalysis {
  return {
    ...analysis,
    generated_at: '<generated_at>',
    repo_path: '<repo_path>'
  };
}

describe('golden CodeGraph compatibility output', () => {
  it('emits stable analysis and summary shapes for a representative Perl repo', async () => {
    const root = path.join(tmpdir(), `perlgraph-golden-${Date.now()}`);
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
        '  return $self->service();',
        '}',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/Role.pm'), [
        'package My::Role;',
        'use Moo::Role;',
        'sub provided { return 1; }',
        '1;'
      ].join('\n'));
      writeFileSync(path.join(root, 'lib/My/Service.pm'), [
        'package My::Service;',
        'sub execute { return 1; }',
        '1;'
      ].join('\n'));

      const analysis = normalizeAnalysis(await analyzeRepository(root));
      const summary = renderSummary(analysis);

      expect(analysis).toMatchSnapshot();
      expect(summary).toMatchSnapshot();
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
