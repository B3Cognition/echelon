import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { describe, expect, it } from 'vitest';

describe('PPI cross-check harness', () => {
  it('runs or skips cleanly without becoming a runtime dependency', () => {
    const root = mkdtempSync(path.join(tmpdir(), 'perlgraph-ppi-'));
    const filePath = path.join(root, 'Sample.pm');
    try {
      writeFileSync(filePath, [
        'package Sample;',
        'sub run { return 1; }',
        '1;'
      ].join('\n'));

      const result = spawnSync(process.execPath, ['scripts/ppi-cross-check.cjs', filePath], {
        cwd: process.cwd(),
        encoding: 'utf8'
      });

      expect(result.status).toBe(0);
      expect(result.stdout.trim()).toMatch(/^(SKIP: Perl PPI module is not available|\{"packages":\[.*\],"subs":\[.*\]\})$/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
