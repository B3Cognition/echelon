import { describe, expect, it } from 'vitest';
import { normalizeSourcePath, symbolKey } from '../src/identity/symbol-key.js';

describe('PerlGraph symbol identity', () => {
  it('normalizes source-relative paths and hashes the canonical locator deterministically', () => {
    const locator = { file_path: './lib\\A.pm', qualified_name: 'A::run', kind: 'sub', signature: '' };
    expect(normalizeSourcePath(locator.file_path)).toBe('lib/A.pm');
    expect(symbolKey(locator)).toBe(symbolKey({ ...locator, file_path: 'lib/A.pm' }));
    expect(symbolKey(locator)).toMatch(/^sha256:[0-9a-f]{64}$/);
  });

  it('rejects absolute and traversing locators', () => {
    expect(() => normalizeSourcePath('/tmp/A.pm')).toThrow(/absolute/);
    expect(() => normalizeSourcePath('lib/../A.pm')).toThrow(/traversing/);
  });

  it('distinguishes the same qualified name in different files', () => {
    expect(symbolKey({ file_path: 'lib/A.pm', qualified_name: 'A::run', kind: 'sub' }))
      .not.toBe(symbolKey({ file_path: 'lib/B.pm', qualified_name: 'A::run', kind: 'sub' }));
  });
});
