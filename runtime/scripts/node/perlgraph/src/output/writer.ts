import { mkdir, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import type { PerlGraphAnalysis, PerlGraphSummary } from '../types.js';

export function renderSummary(analysis: PerlGraphAnalysis): PerlGraphSummary {
  return {
    schema_version: 2,
    tool: 'perlgraph',
    tool_version: analysis.tool_version,
    repo_path: analysis.repo_path,
    provider_status: analysis.provider_status,
    complete: analysis.complete,
    counts: analysis.counts,
    capabilities: analysis.capabilities,
    diagnostics: {
      unresolved_relationships: analysis.unresolved_relationships,
      parse_failures: analysis.parse_failures,
      parse_diagnostics: analysis.parse_diagnostics,
      unsupported_patterns: analysis.unsupported_patterns
    }
  };
}

export async function writeJsonAtomic(filePath: string, payload: unknown): Promise<void> {
  const dir = path.dirname(filePath);
  await mkdir(dir, { recursive: true });
  const tempPath = `${filePath}.tmp`;
  const json = `${JSON.stringify(payload, null, 2)}\n`;
  await writeFile(tempPath, json, 'utf8');
  await rename(tempPath, filePath);
}
