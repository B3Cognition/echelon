import type { Confidence } from '../types.js';

export interface ModuleResolution {
  module: string;
  file_path?: string;
  confidence: Confidence;
}

const ROOTS = ['', 'lib/', 't/lib/'];

export function moduleToPathCandidates(moduleName: string): string[] {
  if (moduleName.endsWith('.pl') || moduleName.endsWith('.pm')) {
    return [moduleName.replace(/^\.\//, '')];
  }
  const relative = `${moduleName.replaceAll('::', '/')}.pm`;
  return ROOTS.map((root) => `${root}${relative}`);
}

export function resolveModuleDependency(moduleName: string, files: Set<string>): ModuleResolution {
  for (const candidate of moduleToPathCandidates(moduleName)) {
    if (files.has(candidate)) {
      return { module: moduleName, file_path: candidate, confidence: 'high' };
    }
  }
  return { module: moduleName, confidence: 'low' };
}
