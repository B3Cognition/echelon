import Parser from 'tree-sitter';
import Perl from 'tree-sitter-perl';
import type { PerlSymbol, UnsupportedPattern } from '../types.js';

export interface ExtractedDependency {
  source_module: string;
  target_module: string;
  source_file: string;
  kind: 'use' | 'require' | 'parent' | 'base';
  line_start: number;
}

export interface ExtractedCall {
  caller: string;
  expression: string;
  file_path: string;
  line_start: number;
}

export interface ExtractedPerlFile {
  symbols: PerlSymbol[];
  dependencies: ExtractedDependency[];
  calls: ExtractedCall[];
  unsupported_patterns: UnsupportedPattern[];
}

const parser = new Parser();

interface TreeSitterLanguagePackage {
  language?: Parser.Language;
  nodeTypeInfo?: unknown;
}

function perlLanguage(): Parser.Language {
  const perlPackage = Perl as Parser.Language & TreeSitterLanguagePackage;
  return perlPackage;
}

parser.setLanguage(perlLanguage());

function parsePerl(content: string): Parser.Tree {
  return parser.parse(content);
}

function lineEnd(lines: string[], startIndex: number): number {
  for (let index = startIndex + 1; index < lines.length; index += 1) {
    if (/^\s*sub\s+\w+/.test(lines[index] ?? '') || /^\s*package\s+[\w:]+/.test(lines[index] ?? '')) {
      return index;
    }
  }
  return lines.length;
}

function classifySub(name: string, body: string): 'sub' | 'method' {
  if (name === 'new') return 'method';
  if (/\bmy\s*\(\s*\$(?:self|class)\s*\)/.test(body)) return 'method';
  if (/\$(?:self|class)\s*->/.test(body)) return 'method';
  return 'sub';
}

function unquote(value: string): string {
  return value.replace(/^[']|[']$/g, '').replace(/^["]|["]$/g, '');
}

function dependencyTarget(line: string): string | undefined {
  const quoted = line.match(/['"]([^'"]+)['"]/);
  if (quoted) return quoted[1];
  const bare = line.match(/\b(?:use|require)\s+([A-Za-z_][\w:]*)/);
  return bare?.[1];
}

export function extractPerlFile(filePath: string, content: string): ExtractedPerlFile {
  const tree = parsePerl(content);
  if (!tree.rootNode) {
    throw new Error(`Unable to parse Perl file: ${filePath}`);
  }

  const lines = content.split(/\r?\n/);
  const symbols: PerlSymbol[] = [{
    qualified_name: filePath,
    name: filePath,
    kind: 'file',
    language: 'perl',
    file_path: filePath,
    line_start: 1,
    line_end: lines.length,
    provenance: ['file-discovery']
  }];
  const dependencies: ExtractedDependency[] = [];
  const calls: ExtractedCall[] = [];
  const unsupported_patterns: UnsupportedPattern[] = [];
  let currentPackage = 'main';
  let currentSub: string | undefined;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? '';
    const lineNumber = index + 1;

    const packageMatch = line.match(/^\s*package\s+([A-Za-z_][\w:]*)\s*;/);
    if (packageMatch) {
      currentPackage = packageMatch[1]!;
      symbols.push({
        qualified_name: currentPackage,
        name: currentPackage,
        kind: 'package',
        language: 'perl',
        file_path: filePath,
        line_start: lineNumber,
        line_end: lineNumber,
        provenance: ['tree-sitter', 'line-scan']
      });
      currentSub = undefined;
      continue;
    }

    const subMatch = line.match(/^\s*sub\s+([A-Za-z_]\w*)/);
    if (subMatch) {
      const name = subMatch[1]!;
      const endLine = lineEnd(lines, index);
      const body = lines.slice(index, endLine).join('\n');
      const kind = classifySub(name, body);
      const qualifiedName = `${currentPackage}::${name}`;
      symbols.push({
        qualified_name: qualifiedName,
        name,
        kind,
        language: 'perl',
        file_path: filePath,
        line_start: lineNumber,
        line_end: endLine,
        signature: `sub ${name}`,
        provenance: ['tree-sitter', 'line-scan']
      });
      currentSub = qualifiedName;
      if (name === 'AUTOLOAD') {
        unsupported_patterns.push({
          kind: 'autoload',
          file_path: filePath,
          line_start: lineNumber,
          snippet: line.trim(),
          notes: 'AUTOLOAD dispatch cannot be statically resolved'
        });
      }
      continue;
    }

    const useMatch = line.match(/^\s*use\s+([A-Za-z_][\w:]*)(?:\s+(.+?))?\s*;/);
    if (useMatch) {
      const moduleName = useMatch[1]!;
      if (moduleName === 'parent' || moduleName === 'base') {
        const target = (useMatch[2] ?? '').split(/\s*,\s*/).map(unquote).find(Boolean);
        if (target) {
          dependencies.push({
            source_module: currentPackage,
            target_module: target,
            source_file: filePath,
            kind: moduleName,
            line_start: lineNumber
          });
        }
      } else {
        dependencies.push({
          source_module: currentPackage,
          target_module: moduleName,
          source_file: filePath,
          kind: 'use',
          line_start: lineNumber
        });
      }
      continue;
    }

    const requireMatch = line.match(/^\s*require\s+(.+?)\s*;/);
    if (requireMatch) {
      const target = dependencyTarget(line);
      if (target) {
        dependencies.push({
          source_module: currentPackage,
          target_module: target,
          source_file: filePath,
          kind: 'require',
          line_start: lineNumber
        });
      } else {
        unsupported_patterns.push({
          kind: 'dynamic_require',
          file_path: filePath,
          line_start: lineNumber,
          snippet: line.trim(),
          notes: 'Dynamic require target cannot be statically resolved'
        });
      }
      continue;
    }

    if (/\beval\s+\$/.test(line) || /\beval\s+["']/.test(line)) {
      unsupported_patterns.push({
        kind: 'eval_string',
        file_path: filePath,
        line_start: lineNumber,
        snippet: line.trim(),
        notes: 'String eval cannot be statically resolved'
      });
    }

    if (/\*\{/.test(line) || /^\s*\*\w+::/.test(line)) {
      unsupported_patterns.push({
        kind: 'glob_assignment',
        file_path: filePath,
        line_start: lineNumber,
        snippet: line.trim(),
        notes: 'Typeglob assignment may alter the symbol table'
      });
    }

    if (currentSub) {
      for (const match of line.matchAll(/([A-Za-z_][\w:]*(?:::[A-Za-z_]\w*)?)\s*\(/g)) {
        const expression = match[1]!;
        if (['if', 'for', 'foreach', 'while', 'return'].includes(expression)) continue;
        calls.push({ caller: currentSub, expression, file_path: filePath, line_start: lineNumber });
      }
      for (const match of line.matchAll(/((?:\$[A-Za-z_]\w*)|(?:[A-Za-z_][\w:]*))\s*->\s*([A-Za-z_]\w*)/g)) {
        calls.push({
          caller: currentSub,
          expression: `${match[1]!}->${match[2]!}`,
          file_path: filePath,
          line_start: lineNumber
        });
      }
    }
  }

  return { symbols, dependencies, calls, unsupported_patterns };
}
