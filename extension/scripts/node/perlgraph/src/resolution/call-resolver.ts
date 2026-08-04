import type { PerlRelationship, PerlSymbol, UnresolvedRelationship } from '../types.js';
import type { ExtractedCall } from '../extraction/perl-extractor.js';

export interface CallResolutionContext {
  inheritance?: Map<string, string[]>;
  roles?: Map<string, string[]>;
  packageImports?: Map<string, string[]>;
  moduleExports?: Map<string, string[]>;
}

function packageOf(qualifiedName: string): string {
  return qualifiedName.split('::').slice(0, -1).join('::');
}

function methodExpressionParts(expression: string): { receiver: string; method: string } | undefined {
  const match = expression.match(/^(.+)->([A-Za-z_]\w*)$/);
  if (!match) return undefined;
  return { receiver: match[1]!, method: match[2]! };
}

function inheritanceCandidates(packageName: string, inheritance: Map<string, string[]> | undefined): string[] {
  if (!inheritance) return [];
  const candidates: string[] = [];
  const seen = new Set<string>();
  const visit = (current: string): void => {
    for (const parent of inheritance.get(current) ?? []) {
      if (seen.has(parent)) continue;
      seen.add(parent);
      candidates.push(parent);
      visit(parent);
    }
  };
  visit(packageName);
  return candidates;
}

function roleCandidates(packageName: string, roles: Map<string, string[]> | undefined): string[] {
  if (!roles) return [];
  const candidates: string[] = [];
  const seen = new Set<string>();
  const visit = (current: string): void => {
    for (const role of roles.get(current) ?? []) {
      if (seen.has(role)) continue;
      seen.add(role);
      candidates.push(role);
      visit(role);
    }
  };
  visit(packageName);
  return candidates;
}

const DBI_DATABASE_HANDLE_METHODS = new Set([
  'begin_work', 'commit', 'disconnect', 'do', 'err', 'errstr', 'last_insert_id', 'ping', 'prepare', 'quote',
  'rollback', 'selectall_arrayref', 'selectall_hashref', 'selectcol_arrayref', 'selectrow_array',
  'selectrow_arrayref', 'selectrow_hashref'
]);

const DBI_STATEMENT_HANDLE_METHODS = new Set([
  'bind_param', 'bind_param_array', 'bind_columns', 'execute', 'execute_array', 'fetch', 'fetchall_arrayref',
  'fetchall_hashref', 'fetchrow_array', 'fetchrow_arrayref', 'fetchrow_hashref', 'finish', 'rows'
]);

const OPTA_DATABASE_WRAPPER_METHODS = new Set([
  'connect', 'dbh', 'mysqlConnection', 'query', 'query_and_get'
]);

interface ExternalApiTarget {
  target: string;
  notes: string;
}

function externalApiTarget(receiver: string, method: string, receiverType?: string): ExternalApiTarget | undefined {
  if (receiverType === 'DBI::db' && DBI_DATABASE_HANDLE_METHODS.has(method)) {
    return {
      target: `DBI::db::${method}`,
      notes: 'Receiver type DBI::db matched common DBI database handle API'
    };
  }

  if (receiverType === 'DBI::st' && DBI_STATEMENT_HANDLE_METHODS.has(method)) {
    return {
      target: `DBI::st::${method}`,
      notes: 'Receiver type DBI::st matched common DBI statement handle API'
    };
  }

  if (receiverType === 'Opta::Database' && OPTA_DATABASE_WRAPPER_METHODS.has(method)) {
    return {
      target: `Opta::Database::${method}`,
      notes: 'Receiver type Opta::Database matched common Opta database wrapper API'
    };
  }

  if (!receiver.startsWith('$')) return undefined;
  const receiverName = receiver.slice(1).toLowerCase();

  if ((receiverName === 'dbh' || receiverName.includes('dbh')) && DBI_DATABASE_HANDLE_METHODS.has(method)) {
    return {
      target: `DBI::db::${method}`,
      notes: `Receiver ${receiver} matched common DBI database handle API`
    };
  }

  if (
    (receiverName === 'sth' || receiverName.includes('sth') || receiverName.includes('stmt') || receiverName.includes('statement'))
    && DBI_STATEMENT_HANDLE_METHODS.has(method)
  ) {
    return {
      target: `DBI::st::${method}`,
      notes: `Receiver ${receiver} matched common DBI statement handle API`
    };
  }

  if (
    (receiverName === 'mc' || receiverName === 'mysql' || receiverName.includes('mysqlconnection'))
    && OPTA_DATABASE_WRAPPER_METHODS.has(method)
  ) {
    return {
      target: `Opta::Database::${method}`,
      notes: `Receiver ${receiver} matched common Opta database wrapper API`
    };
  }

  return undefined;
}

function implicitExportTarget(
  callerPackage: string,
  expression: string,
  packageImports: Map<string, string[]> | undefined,
  moduleExports: Map<string, string[]> | undefined,
  byQualifiedName: Map<string, PerlSymbol>
): string | undefined {
  if (!packageImports || !moduleExports) return undefined;
  const candidates = (packageImports.get(callerPackage) ?? [])
    .filter((moduleName) => moduleExports.get(moduleName)?.includes(expression))
    .map((moduleName) => `${moduleName}::${expression}`)
    .filter((target) => byQualifiedName.has(target));
  return candidates.length === 1 ? candidates[0] : undefined;
}

export interface CallResolutionResult {
  relationships: PerlRelationship[];
  unresolved_relationships: UnresolvedRelationship[];
}

export function resolveCalls(
  calls: ExtractedCall[],
  symbols: PerlSymbol[],
  context: CallResolutionContext = {}
): CallResolutionResult {
  const candidatesByQualifiedName = new Map<string, PerlSymbol[]>();
  for (const symbol of symbols) {
    const candidates = candidatesByQualifiedName.get(symbol.qualified_name) ?? [];
    candidates.push(symbol);
    candidatesByQualifiedName.set(symbol.qualified_name, candidates);
  }
  const byQualifiedName = new Map<string, PerlSymbol>();
  for (const [qualifiedName, candidates] of candidatesByQualifiedName) {
    if (candidates.length === 1) byQualifiedName.set(qualifiedName, candidates[0]!);
  }
  const relationships: PerlRelationship[] = [];
  const unresolvedRelationships: UnresolvedRelationship[] = [];

  const sourceFor = (call: ExtractedCall): PerlSymbol | undefined => {
    const candidates = candidatesByQualifiedName.get(call.caller) ?? [];
    const inFile = candidates.filter((candidate) => candidate.file_path === call.file_path);
    return inFile.length === 1 ? inFile[0] : candidates.length === 1 ? candidates[0] : undefined;
  };
  const resolved = (
    call: ExtractedCall,
    target: string,
    confidence: PerlRelationship['confidence'],
    provenance: string[],
    notes?: string
  ): boolean => {
    const source = sourceFor(call);
    const targetSymbol = byQualifiedName.get(target);
    if (!source || !targetSymbol) return false;
    relationships.push({
      source_key: source.symbol_key,
      target_key: targetSymbol.symbol_key,
      source: source.qualified_name,
      target: targetSymbol.qualified_name,
      kind: 'calls',
      file_path: call.file_path,
      line_start: call.line_start,
      confidence,
      provenance,
      ...(notes ? { notes } : {})
    });
    return true;
  };
  const unresolved = (
    call: ExtractedCall,
    target: string,
    confidence: UnresolvedRelationship['confidence'],
    provenance: string[],
    notes: string
  ): void => {
    const source = sourceFor(call);
    unresolvedRelationships.push({
      ...(source ? { source_key: source.symbol_key } : {}),
      source: call.caller,
      target,
      kind: 'calls',
      file_path: call.file_path,
      line_start: call.line_start,
      confidence,
      provenance,
      notes
    });
  };

  for (const call of calls) {
    const callerPackage = packageOf(call.caller);
    const methodParts = methodExpressionParts(call.expression);

    if (methodParts) {
      const receiver = methodParts.receiver.replace(/^[']|[']$/g, '').replace(/^["]|["]$/g, '');
      if (!receiver.startsWith('$')) {
        const target = `${receiver}::${methodParts.method}`;
        if (resolved(call, target, 'high', ['tree-sitter', 'package-method-resolution'])) {
          continue;
        }
      }
      if (receiver === '$self' || receiver === '$class') {
        const target = `${callerPackage}::${methodParts.method}`;
        if (resolved(call, target, 'medium', ['tree-sitter', 'self-method-resolution'])) {
          continue;
        }
        const inheritedTarget = inheritanceCandidates(callerPackage, context.inheritance)
          .map((parent) => `${parent}::${methodParts.method}`)
          .find((candidate) => byQualifiedName.has(candidate));
        if (inheritedTarget && resolved(call, inheritedTarget, 'medium', ['tree-sitter', 'inheritance-method-resolution'])) {
          continue;
        }
        const roleTarget = roleCandidates(callerPackage, context.roles)
          .map((role) => `${role}::${methodParts.method}`)
          .find((candidate) => byQualifiedName.has(candidate));
        if (roleTarget && resolved(call, roleTarget, 'medium', ['tree-sitter', 'role-method-resolution'])) {
          continue;
        }
      }
      if (call.receiver_type) {
        const target = `${call.receiver_type}::${methodParts.method}`;
        if (resolved(call, target, 'medium', ['tree-sitter', 'local-constructor-flow'])) {
          continue;
        }
      }
      const externalTarget = externalApiTarget(receiver, methodParts.method, call.receiver_type);
      if (externalTarget) {
        unresolved(call, externalTarget.target, 'medium', ['tree-sitter', 'external-api-resolution'], externalTarget.notes);
        continue;
      }
      unresolved(call, methodParts.method, 'low', ['method-name-match'], `Receiver type for ${call.expression} was not statically resolved`);
      continue;
    }

    const qualifiedTarget = call.expression.includes('::')
      ? call.expression
      : `${callerPackage}::${call.expression}`;

    if (resolved(call, qualifiedTarget, 'high', ['tree-sitter', 'name-resolution'])) {
      continue;
    }

    if (call.imported_from) {
      const target = `${call.imported_from}::${call.expression}`;
      const notes = `Bare call ${call.expression} matched explicit import from ${call.imported_from}`;
      if (resolved(call, target, 'medium', ['tree-sitter', 'explicit-import-resolution'], notes)) continue;
      unresolved(call, target, 'medium', ['tree-sitter', 'explicit-import-resolution'], notes);
      continue;
    }

    const implicitTarget = implicitExportTarget(callerPackage, call.expression, context.packageImports, context.moduleExports, byQualifiedName);
    if (implicitTarget && resolved(call, implicitTarget, 'medium', ['tree-sitter', 'implicit-export-resolution'], `Bare call ${call.expression} matched implicit export from ${packageOf(implicitTarget)}`)) {
      continue;
    }

    unresolved(call, call.expression, 'low', ['unresolved-call'], `Call expression ${call.expression} did not resolve to a known symbol`);
  }

  return { relationships, unresolved_relationships: unresolvedRelationships };
}
