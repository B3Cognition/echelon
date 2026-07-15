import type { PerlRelationship, PerlSymbol } from '../types.js';
import type { ExtractedCall } from '../extraction/perl-extractor.js';

function packageOf(qualifiedName: string): string {
  return qualifiedName.split('::').slice(0, -1).join('::');
}

function methodExpressionParts(expression: string): { receiver: string; method: string } | undefined {
  const match = expression.match(/^(.+)->([A-Za-z_]\w*)$/);
  if (!match) return undefined;
  return { receiver: match[1]!, method: match[2]! };
}

export function resolveCalls(calls: ExtractedCall[], symbols: PerlSymbol[]): PerlRelationship[] {
  const byQualifiedName = new Map(symbols.map((symbol) => [symbol.qualified_name, symbol]));
  const relationships: PerlRelationship[] = [];

  for (const call of calls) {
    const callerPackage = packageOf(call.caller);
    const methodParts = methodExpressionParts(call.expression);

    if (methodParts) {
      const receiver = methodParts.receiver.replace(/^[']|[']$/g, '').replace(/^["]|["]$/g, '');
      if (!receiver.startsWith('$')) {
        const target = `${receiver}::${methodParts.method}`;
        if (byQualifiedName.has(target)) {
          relationships.push({
            source: call.caller,
            target,
            kind: 'calls',
            file_path: call.file_path,
            line_start: call.line_start,
            confidence: 'high',
            provenance: ['tree-sitter', 'package-method-resolution']
          });
          continue;
        }
      }
      relationships.push({
        source: call.caller,
        target: methodParts.method,
        kind: 'calls',
        file_path: call.file_path,
        line_start: call.line_start,
        confidence: 'low',
        provenance: ['method-name-match'],
        notes: `Receiver type for ${call.expression} was not statically resolved`
      });
      continue;
    }

    const qualifiedTarget = call.expression.includes('::')
      ? call.expression
      : `${callerPackage}::${call.expression}`;

    if (byQualifiedName.has(qualifiedTarget)) {
      relationships.push({
        source: call.caller,
        target: qualifiedTarget,
        kind: 'calls',
        file_path: call.file_path,
        line_start: call.line_start,
        confidence: 'high',
        provenance: ['tree-sitter', 'name-resolution']
      });
      continue;
    }

    relationships.push({
      source: call.caller,
      target: call.expression,
      kind: 'calls',
      file_path: call.file_path,
      line_start: call.line_start,
      confidence: 'low',
      provenance: ['unresolved-call'],
      notes: `Call expression ${call.expression} did not resolve to a known symbol`
    });
  }

  return relationships;
}
