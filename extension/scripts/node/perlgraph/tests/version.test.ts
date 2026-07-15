import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { packageVersion } from '../src/version.js';

describe('packageVersion', () => {
  it('matches package.json', () => {
    const packageJson = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8')) as { version: string };

    expect(packageVersion()).toBe(packageJson.version);
  });
});
