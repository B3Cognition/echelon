import { mkdir, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import type {
  PerlGraphAnalysis,
  PerlGraphSummary,
  RelationshipKind,
  SymbolKind,
  UnsupportedPattern
} from '../types.js';

function countBy<T extends string>(values: T[]): Array<{ key: T; count: number }> {
  const counts = new Map<T, number>();
  for (const value of values) {
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([key, count]) => ({ key, count }))
    .sort((a, b) => b.count - a.count || a.key.localeCompare(b.key));
}

export function renderSummary(analysis: PerlGraphAnalysis): PerlGraphSummary {
  const symbolKinds = countBy(analysis.symbols.map((symbol) => symbol.kind));
  const relationshipKinds = countBy(analysis.relationships.map((relationship) => relationship.kind));
  const callers = countBy(analysis.call_graph.map((edge) => edge.source));
  const callees = countBy(analysis.call_graph.map((edge) => edge.target));
  const modules = countBy(analysis.module_graph.map((edge) => edge.source_module));
  const dynamicPatterns = countBy(analysis.unsupported_patterns.map((pattern) => pattern.kind));

  return {
    schema_version: 1,
    tool: 'perlgraph',
    generated_at: analysis.generated_at,
    repo_path: analysis.repo_path,
    index_state: analysis.index_stats.index_state,
    index_stats: analysis.index_stats,
    symbol_kinds: symbolKinds.map(({ key, count }) => ({ kind: key as SymbolKind, count })),
    relationship_kinds: relationshipKinds.map(({ key, count }) => ({ kind: key as RelationshipKind, count })),
    top_callers: callers.slice(0, 25).map(({ key, count }) => ({ symbol: key, outgoing_calls: count })),
    top_callees: callees.slice(0, 25).map(({ key, count }) => ({ symbol: key, incoming_calls: count })),
    top_modules: modules.slice(0, 25).map(({ key, count }) => ({ module: key, outgoing_dependencies: count })),
    dynamic_risk: {
      count: analysis.unsupported_patterns.length,
      patterns: dynamicPatterns.map(({ key, count }) => ({ kind: key as UnsupportedPattern['kind'], count }))
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
