import { stat } from 'node:fs/promises';
import path from 'node:path';
import { discoverPerlFiles } from '../extraction/files.js';
import { extractPerlFile, type ExtractedCall, type ExtractedDependency, type ExtractedRoleApplication } from '../extraction/perl-extractor.js';
import { normalizeSourcePath, symbolKey } from '../identity/symbol-key.js';
import { resolveCalls } from '../resolution/call-resolver.js';
import { resolveModuleDependency } from '../resolution/module-resolver.js';
import { packageVersion } from '../version.js';
import type {
  IndexState,
  ModuleGraphEntry,
  ParseDiagnostic,
  ParseFailure,
  PerlGraphAnalysis,
  PerlRelationship,
  PerlSymbol,
  ProviderStatus,
  UnresolvedRelationship,
  UnsupportedPattern
} from '../types.js';

function indexState(totalFiles: number, failedFiles: number, dynamicCount: number, parseErrorCount: number): IndexState {
  if (totalFiles === 0) return 'empty';
  if (failedFiles > 0 || dynamicCount > 0 || parseErrorCount > 0) return 'degraded';
  return 'ready';
}

function providerStatus(totalFiles: number, symbols: PerlSymbol[], failures: ParseFailure[], diagnostics: ParseDiagnostic[], dynamicPatterns: UnsupportedPattern[]): ProviderStatus {
  if (totalFiles === 0) return 'unsupported';
  if (failures.length > 0 || diagnostics.length > 0 || dynamicPatterns.length > 0) return 'degraded';
  if (symbols.length === 0) return 'empty';
  return 'ready';
}

function uniqueSymbolByName(symbols: PerlSymbol[], qualifiedName: string, preferredFile?: string): PerlSymbol | undefined {
  const candidates = symbols.filter((symbol) => symbol.qualified_name === qualifiedName);
  const preferred = preferredFile ? candidates.filter((symbol) => symbol.file_path === preferredFile) : [];
  const selected = preferred.length === 1 ? preferred : candidates.length === 1 ? candidates : [];
  return selected[0];
}

function addNamedRelationship(
  relationships: PerlRelationship[],
  unresolved: UnresolvedRelationship[],
  symbols: PerlSymbol[],
  source: string,
  target: string,
  kind: PerlRelationship['kind'],
  filePath: string,
  lineStart: number,
  confidence: PerlRelationship['confidence'],
  provenance: string[],
  notes?: string
): void {
  const sourceSymbol = uniqueSymbolByName(symbols, source, filePath);
  const targetSymbol = uniqueSymbolByName(symbols, target);
  if (sourceSymbol && targetSymbol) {
    relationships.push({
      source_key: sourceSymbol.symbol_key,
      target_key: targetSymbol.symbol_key,
      source: sourceSymbol.qualified_name,
      target: targetSymbol.qualified_name,
      kind,
      file_path: filePath,
      line_start: lineStart,
      confidence,
      provenance,
      ...(notes ? { notes } : {})
    });
    return;
  }
  unresolved.push({
    ...(sourceSymbol ? { source_key: sourceSymbol.symbol_key } : {}),
    source,
    target,
    kind,
    file_path: filePath,
    line_start: lineStart,
    confidence,
    provenance,
    notes: notes ?? `Relationship ${source} -> ${target} did not resolve to two unique repository symbols`
  });
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
  if (!repoStats.isDirectory()) throw new Error(`Repository path is not a directory: ${resolvedRepoPath}`);

  const files = await discoverPerlFiles(resolvedRepoPath, options);
  const fileSet = new Set(files.map((file) => file.relativePath));
  const extractedSymbols: Array<Omit<PerlSymbol, 'symbol_key'>> = [];
  const extractedCalls: ExtractedCall[] = [];
  const dependencies: ExtractedDependency[] = [];
  const roleApplications: ExtractedRoleApplication[] = [];
  const moduleGraph: ModuleGraphEntry[] = [];
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
      parseFailures.push({ file_path: file.relativePath, error: error instanceof Error ? error.message : String(error) });
      continue;
    }
    extractedSymbols.push(...extracted.symbols);
    extractedCalls.push(...extracted.calls);
    dependencies.push(...extracted.dependencies);
    roleApplications.push(...extracted.role_applications);
    unsupportedPatterns.push(...extracted.unsupported_patterns);
    parseDiagnostics.push(...extracted.parse_diagnostics);
    for (const exported of extracted.exports) {
      const exports = moduleExports.get(exported.source_package) ?? [];
      exports.push(exported.name);
      moduleExports.set(exported.source_package, exports);
    }
    for (const dependency of extracted.dependencies) {
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
    }
    for (const roleApplication of extracted.role_applications) {
      const packageRoles = roles.get(roleApplication.source_package) ?? [];
      packageRoles.push(roleApplication.target_role);
      roles.set(roleApplication.source_package, packageRoles);
    }
  }

  const symbols = extractedSymbols.map((symbol) => ({
    ...symbol,
    file_path: normalizeSourcePath(symbol.file_path),
    symbol_key: symbolKey(symbol)
  }));
  const locators = new Set<string>();
  for (const symbol of symbols) {
    if (locators.has(symbol.symbol_key)) throw new Error(`PerlGraph contract error: duplicate canonical locator for ${symbol.qualified_name} in ${symbol.file_path}`);
    locators.add(symbol.symbol_key);
  }
  symbols.sort((left, right) => left.file_path.localeCompare(right.file_path)
    || left.line_start - right.line_start
    || left.kind.localeCompare(right.kind)
    || left.qualified_name.localeCompare(right.qualified_name)
    || left.symbol_key.localeCompare(right.symbol_key));

  const relationships: PerlRelationship[] = [];
  const unresolvedRelationships: UnresolvedRelationship[] = [];
  for (const dependency of dependencies) {
    const resolution = resolveModuleDependency(dependency.target_module, fileSet);
    moduleGraph.push({
      source_module: dependency.source_module,
      target_module: dependency.target_module,
      source_file: dependency.source_file,
      kind: dependency.kind,
      confidence: resolution.confidence,
      ...(resolution.file_path ? { target_file: resolution.file_path } : {})
    });
    const kind = dependency.kind === 'parent' || dependency.kind === 'base' ? 'inherits' : dependency.kind === 'require' ? 'requires' : 'imports';
    addNamedRelationship(
      relationships, unresolvedRelationships, symbols, dependency.source_module, dependency.target_module, kind,
      dependency.source_file, dependency.line_start, resolution.confidence, ['tree-sitter', 'module-resolution'],
      resolution.file_path ? undefined : `Module ${dependency.target_module} did not resolve to a repository file`
    );
  }
  for (const roleApplication of roleApplications) {
    const resolution = resolveModuleDependency(roleApplication.target_role, fileSet);
    addNamedRelationship(
      relationships, unresolvedRelationships, symbols, roleApplication.source_package, roleApplication.target_role, 'uses_role',
      roleApplication.file_path, roleApplication.line_start, resolution.confidence, ['moose-moo-role', 'module-resolution'],
      resolution.file_path ? undefined : `Role ${roleApplication.target_role} did not resolve to a repository file`
    );
  }
  const callResolution = resolveCalls(extractedCalls, symbols, { inheritance, roles, packageImports, moduleExports });
  relationships.push(...callResolution.relationships);
  unresolvedRelationships.push(...callResolution.unresolved_relationships);
  relationships.sort((left, right) => left.source_key.localeCompare(right.source_key) || left.target_key.localeCompare(right.target_key) || left.kind.localeCompare(right.kind) || left.file_path.localeCompare(right.file_path) || left.line_start - right.line_start);

  const parseErrorCount = parseDiagnostics.reduce((sum, diagnostic) => sum + diagnostic.error_count, 0);
  const state = indexState(files.length, parseFailures.length, unsupportedPatterns.length, parseErrorCount);
  const status = providerStatus(files.length, symbols, parseFailures, parseDiagnostics, unsupportedPatterns);
  return {
    schema_version: 2,
    tool: 'perlgraph',
    tool_version: packageVersion(),
    generated_at: new Date().toISOString(),
    repo_path: resolvedRepoPath,
    supported: files.length > 0,
    provider_status: status,
    complete: true,
    counts: {
      discovered_files: files.length,
      emitted_files: files.length - parseFailures.length,
      discovered_symbols: symbols.length,
      emitted_symbols: symbols.length,
      discovered_relationships: relationships.length + unresolvedRelationships.length,
      emitted_relationships: relationships.length,
      unresolved_relationships: unresolvedRelationships.length,
      parse_failures: parseFailures.length,
      parse_diagnostics: parseErrorCount,
      dynamic_patterns: unsupportedPatterns.length
    },
    capabilities: {
      language: 'perl',
      supported_extensions: ['.pl', '.pm', '.t', '.psgi'],
      exact_symbol_keys: true,
      exact_relationship_endpoints: true,
      unresolved_relationship_diagnostics: true
    },
    language_coverage: { '.pl': 'supported', '.pm': 'supported', '.t': 'supported', '.psgi': 'supported' },
    symbols,
    relationships,
    unresolved_relationships: unresolvedRelationships,
    call_graph: callResolution.relationships.map((relationship) => ({
      source_key: relationship.source_key,
      target_key: relationship.target_key,
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
