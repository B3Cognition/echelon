import { describe, expect, it } from 'vitest';
import { resolveModuleDependency } from '../src/resolution/module-resolver.js';

const files = new Set([
  'lib/My/App.pm',
  'lib/My/Service.pm',
  't/lib/Test/Helper.pm',
  'script/legacy.pl'
]);

describe('module resolver', () => {
  it('resolves module names to repository files', () => {
    expect(resolveModuleDependency('My::Service', files)).toEqual({
      module: 'My::Service',
      file_path: 'lib/My/Service.pm',
      confidence: 'high'
    });
  });

  it('resolves quoted require paths', () => {
    expect(resolveModuleDependency('script/legacy.pl', files)).toEqual({
      module: 'script/legacy.pl',
      file_path: 'script/legacy.pl',
      confidence: 'high'
    });
  });

  it('normalizes leading dot slash in quoted require paths', () => {
    expect(resolveModuleDependency('./script/legacy.pl', files)).toEqual({
      module: './script/legacy.pl',
      file_path: 'script/legacy.pl',
      confidence: 'high'
    });
  });

  it('records unresolved modules', () => {
    expect(resolveModuleDependency('Missing::Thing', files)).toEqual({
      module: 'Missing::Thing',
      confidence: 'low'
    });
  });
});
