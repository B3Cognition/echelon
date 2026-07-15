import { stat } from 'node:fs/promises';
import path from 'node:path';
import { discoverPerlFiles } from '../extraction/files.js';
import { extractPerlFile, type ExtractedCall } from '../extraction/perl-extractor.js';
import { resolveCalls } from '../resolution/call-resolver.js';
import { resolveModuleDependency } from '../resolution/module-resolver.js';
import type {
  IndexState,
  ModuleGraphEntry,
  ParseDiagnostic,
  ParseFailure,
  PerlGraphAnalysis,
  PerlRelationship,
  PerlSymbol,
  UnsupportedPattern
} from '../types.js';

function indexState(totalFiles: number, failedFiles: number, dynamicCount: number, parseErrorCount: number): IndexState {
  if (totalFiles === 0) return 'empty';
  if (failedFiles > 0 || dynamicCount > 0 || parseErrorCount > 0) return 'degraded';
  return 'ready';
}

export async function analyzeRepository(
  repoPath: string,
  options: { include?: string[]; exclude?: string[] } = {}
): Promise<PerlGraphAnalysis> {
  const resolvedRepoPath = path.resolve(repoPath);
  let repoStats;
  try {
    repoStats = await stat(resolvedRepoPath);
  } catch (error) {
    const cause = error instanceof Error ? `: ${error.message}` : '';
    throw new Error(`Repository path does not exist: ${resolvedRepoPath}${cause}`);
  }
  if (!repoStats.isDirectory()) {
    throw new Error(`Repository path is not a directory: ${resolvedRepoPath}`);
  }

  const files = await discoverPerlFiles(resolvedRepoPath, options);
  const fileSet = new Set(files.map((file) => file.relativePath));
  const symbols: PerlSymbol[] = [];
  const relationships: PerlRelationship[] = [];
  const moduleGraph: ModuleGraphEntry[] = [];
  const extractedCalls: ExtractedCall[] = [];
  const unsupportedPatterns: UnsupportedPattern[] = [];
  const parseFailures: ParseFailure[] = [];
  const parseDiagnostics: ParseDiagnostic[] = [];
  const inheritance = new Map<string, string[]>();
  const roles = new Map<string, string[]>();
  const packageImports = new Map<string, string[]>();
  const moduleExports = new Map<string, string[]>();

  for (const file of files) {
    let extracted;
    try {
      extracted = extractPerlFile(file.relativePath, file.content);
    } catch (error) {
      parseFailures.push({
        file_path: file.relativePath,
        error: error instanceof Error ? error.message : String(error)
      });
      continue;
    }

    symbols.push(...extracted.symbols);
    extractedCalls.push(...extracted.calls);
    unsupportedPatterns.push(...extracted.unsupported_patterns);
    parseDiagnostics.push(...extracted.parse_diagnostics);

    for (const exported of extracted.exports) {
      const exports = moduleExports.get(exported.source_package) ?? [];
      exports.push(exported.name);
      moduleExports.set(exported.source_package, exports);
    }

    for (const dependency of extracted.dependencies) {
      const resolution = resolveModuleDependency(dependency.target_module, fileSet);
      if (dependency.kind === 'use') {
        const imports = packageImports.get(dependency.source_module) ?? [];
        imports.push(dependency.target_module);
        packageImports.set(dependency.source_module, imports);
      }
      if (dependency.kind === 'parent' || dependency.kind === 'base') {
        const parents = inheritance.get(dependency.source_module) ?? [];
        parents.push(dependency.target_module);
        inheritance.set(dependency.source_module, parents);
      }
      moduleGraph.push({
        source_module: dependency.source_module,
        target_module: dependency.target_module,
        source_file: dependency.source_file,
        kind: dependency.kind,
        confidence: resolution.confidence,
        ...(resolution.file_path ? { target_file: resolution.file_path } : {})
      });
      relationships.push({
        source: dependency.source_module,
        target: dependency.target_module,
        kind: dependency.kind === 'parent' || dependency.kind === 'base' ? 'inherits' : dependency.kind === 'require' ? 'requires' : 'imports',
        file_path: dependency.source_file,
        line_start: dependency.line_start,
        confidence: resolution.confidence,
        provenance: ['tree-sitter', 'module-resolution'],
        ...(resolution.file_path ? {} : { notes: `Module ${dependency.target_module} did not resolve to a repository file` })
      });
    }

    for (const roleApplication of extracted.role_applications) {
      const resolution = resolveModuleDependency(roleApplication.target_role, fileSet);
      const packageRoles = roles.get(roleApplication.source_package) ?? [];
      packageRoles.push(roleApplication.target_role);
      roles.set(roleApplication.source_package, packageRoles);
      relationships.push({
        source: roleApplication.source_package,
        target: roleApplication.target_role,
        kind: 'uses_role',
        file_path: roleApplication.file_path,
        line_start: roleApplication.line_start,
        confidence: resolution.confidence,
        provenance: ['moose-moo-role', 'module-resolution'],
        ...(resolution.file_path ? {} : { notes: `Role ${roleApplication.target_role} did not resolve to a repository file` })
      });
    }
  }

  const callRelationships = resolveCalls(extractedCalls, symbols, { inheritance, roles, packageImports, moduleExports });
  relationships.push(...callRelationships);

  const parseErrorCount = parseDiagnostics.reduce((sum, diagnostic) => sum + diagnostic.error_count, 0);
  const state = indexState(files.length, parseFailures.length, unsupportedPatterns.length, parseErrorCount);
  return {
    schema_version: 1,
    tool: 'perlgraph',
    generated_at: new Date().toISOString(),
    repo_path: resolvedRepoPath,
    supported: files.length > 0,
    language_coverage: {
      '.pl': 'supported',
      '.pm': 'supported',
      '.t': 'supported',
      '.psgi': 'supported'
    },
    symbols,
    relationships,
    call_graph: callRelationships.map((relationship) => ({
      source: relationship.source,
      target: relationship.target,
      confidence: relationship.confidence,
      provenance: relationship.provenance
    })),
    module_graph: moduleGraph,
    unsupported_patterns: unsupportedPatterns,
    parse_failures: parseFailures,
    parse_diagnostics: parseDiagnostics,
    index_stats: {
      total_files: files.length,
      parsed_files: files.length - parseFailures.length,
      failed_files: parseFailures.length,
      parse_error_count: parseErrorCount,
      symbol_count: symbols.length,
      relationship_count: relationships.length,
      dynamic_pattern_count: unsupportedPatterns.length,
      index_state: state
    }
  };
}
