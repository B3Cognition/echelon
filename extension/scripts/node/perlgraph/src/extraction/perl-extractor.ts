import Parser from 'tree-sitter';
import Perl from 'tree-sitter-perl';
import type { ParseDiagnostic, PerlSymbol, UnsupportedPattern } from '../types.js';
import { frameworkDeclaration, frameworkForModule, staticListValues } from './framework-rules.js';

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
  receiver_type?: string;
  imported_from?: string;
  file_path: string;
  line_start: number;
}

export interface ExtractedRoleApplication {
  source_package: string;
  target_role: string;
  file_path: string;
  line_start: number;
}

export interface ExtractedExport {
  source_package: string;
  name: string;
}

export interface ExtractedPerlFile {
  symbols: PerlSymbol[];
  dependencies: ExtractedDependency[];
  role_applications: ExtractedRoleApplication[];
  exports: ExtractedExport[];
  calls: ExtractedCall[];
  unsupported_patterns: UnsupportedPattern[];
  parse_diagnostics: ParseDiagnostic[];
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

const NON_CALL_KEYWORDS = new Set([
  'BEGIN', 'CHECK', 'END', 'INIT', 'UNITCHECK',
  'catch', 'continue', 'default', 'do', 'else', 'elsif', 'eval', 'finally', 'for', 'foreach', 'given', 'goto',
  'if', 'last', 'local', 'my', 'next', 'no', 'our', 'package', 'redo', 'require', 'return', 'state', 'sub',
  'try', 'unless', 'until', 'use', 'when', 'while'
]);

const NON_CALL_BUILTINS = new Set([
  'abs', 'accept', 'alarm', 'atan2', 'bind', 'binmode', 'bless', 'caller', 'chdir', 'chmod', 'chomp', 'chop',
  'chown', 'chr', 'chroot', 'close', 'closedir', 'connect', 'cos', 'crypt', 'dbmclose', 'dbmopen', 'defined',
  'delete', 'die', 'dump', 'each', 'endgrent', 'endhostent', 'endnetent', 'endprotoent', 'endpwent',
  'endservent', 'eof', 'exec', 'exists', 'exit', 'exp', 'fcntl', 'fileno', 'flock', 'fork', 'formline',
  'getc', 'getgrent', 'getgrgid', 'getgrnam', 'gethostbyaddr', 'gethostbyname', 'gethostent', 'getlogin',
  'getnetbyaddr', 'getnetbyname', 'getnetent', 'getpeername', 'getpgrp', 'getppid', 'getpriority',
  'getprotobyname', 'getprotobynumber', 'getprotoent', 'getpwent', 'getpwnam', 'getpwuid', 'getservbyname',
  'getservbyport', 'getservent', 'getsockname', 'getsockopt', 'glob', 'gmtime', 'grep', 'hex', 'import',
  'index', 'int', 'ioctl', 'join', 'keys', 'kill', 'lc', 'lcfirst', 'length', 'link', 'listen', 'localtime',
  'log', 'lstat', 'map', 'mkdir', 'msgctl', 'msgget', 'msgrcv', 'msgsnd', 'oct', 'open', 'opendir', 'ord',
  'pack', 'pipe', 'pop', 'pos', 'print', 'printf', 'prototype', 'push', 'quotemeta', 'rand', 'read',
  'readdir', 'readline', 'readlink', 'readpipe', 'recv', 'ref', 'rename', 'reset', 'reverse', 'rewinddir',
  'rindex', 'rmdir', 'say', 'scalar', 'seek', 'seekdir', 'select', 'semctl', 'semget', 'semop', 'send',
  'setgrent', 'sethostent', 'setnetent', 'setpgrp', 'setpriority', 'setprotoent', 'setpwent', 'setservent',
  'setsockopt', 'shift', 'shmctl', 'shmget', 'shmread', 'shmwrite', 'shutdown', 'sin', 'sleep', 'socket',
  'socketpair', 'sort', 'splice', 'split', 'sprintf', 'sqrt', 'srand', 'stat', 'study', 'substr', 'symlink',
  'syscall', 'sysopen', 'sysread', 'sysseek', 'system', 'syswrite', 'tell', 'telldir', 'tie', 'tied', 'time',
  'times', 'truncate', 'uc', 'ucfirst', 'umask', 'undef', 'unlink', 'unpack', 'unshift', 'untie', 'utime',
  'values', 'vec', 'wait', 'waitpid', 'wantarray', 'warn', 'write'
]);

const NON_CALL_QUOTE_OPERATORS = new Set(['m', 'q', 'qq', 'qr', 'qw', 'qx', 's', 'tr', 'y']);

const NON_CALL_SQL_TOKENS = new Set([
  'ABS', 'AND', 'AS', 'ASC', 'AVG', 'BETWEEN', 'BY', 'CASE', 'CAST', 'COALESCE', 'CONCAT', 'COUNT', 'DATE',
  'DATEDIFF', 'DATE_FORMAT', 'DELETE', 'DESC', 'DISTINCT', 'ELSE', 'END', 'EXISTS', 'FROM', 'GROUP', 'HAVING',
  'IF', 'IFNULL', 'IN', 'INNER', 'INSERT', 'IS', 'JOIN', 'LEFT', 'LIKE', 'LIMIT', 'MAX', 'MIN', 'NOT', 'NOW',
  'NULL', 'ON', 'OR', 'ORDER', 'OUTER', 'RIGHT', 'SELECT', 'SET', 'SUM', 'THEN', 'UNION', 'UPDATE', 'VALUES',
  'WHEN', 'WHERE'
]);

interface LogicalLine {
  text: string;
  lineNumber: number;
}

interface MaskedLine {
  text: string;
  openQuoteClose?: string;
}

function parsePerl(content: string): Parser.Tree {
  return parser.parse(content);
}

function parseErrorCount(rootNode: Parser.SyntaxNode): number {
  if (!rootNode.hasError) return 0;
  return rootNode.descendantsOfType('ERROR').length || 1;
}

function logicalLines(content: string): LogicalLine[] {
  const rawLines = content.split(/\r?\n/);
  const result: LogicalLine[] = [];
  let buffer: string[] = [];
  let startLine = 1;

  for (let index = 0; index < rawLines.length; index += 1) {
    const line = rawLines[index] ?? '';
    const trimmed = line.trim();
    if (buffer.length === 0 && /^(?:use|require|with|extends|has)\b/.test(trimmed) && !trimmed.endsWith(';')) {
      buffer = [trimmed];
      startLine = index + 1;
      continue;
    }
    if (buffer.length > 0) {
      buffer.push(trimmed);
      if (trimmed.endsWith(';')) {
        result.push({ text: buffer.join(' '), lineNumber: startLine });
        buffer = [];
      }
      continue;
    }
    result.push({ text: line, lineNumber: index + 1 });
  }

  if (buffer.length > 0) {
    result.push({ text: buffer.join(' '), lineNumber: startLine });
  }

  return result;
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

function packageOf(qualifiedName: string): string {
  return qualifiedName.split('::').slice(0, -1).join('::');
}

function unquote(value: string): string {
  return value.replace(/^[']|[']$/g, '').replace(/^["]|["]$/g, '');
}

function dependencyTarget(line: string): string | undefined {
  const staticRequire = line.match(/^\s*require\s+(.+?)\s*;/);
  if (staticRequire) {
    const target = staticStringExpression(staticRequire[1]!);
    if (target) return normalizeRequireTarget(target);
  }
  const bare = line.match(/\b(?:use|require)\s+([A-Za-z_][\w:]*)/);
  return bare?.[1];
}

function isVersionRequire(line: string): boolean {
  return /^\s*require\s+v?\d+(?:[._]\d+)*\s*;/.test(line);
}

function isEvalStringRequire(line: string): boolean {
  return /\beval\s+["']\s*require\s+(?:\$|\$\{)/.test(line);
}

function isEvalStringUse(line: string): boolean {
  return /\beval\s+["']\s*use\s+[A-Za-z_][\w:]*/.test(line);
}

function globAssignmentTargets(line: string): string[] {
  const targets = new Set<string>();
  for (const match of line.matchAll(/\*\{\s*["'][^"']*::([A-Za-z_]\w*)["']\s*\}/g)) {
    targets.add(match[1]!);
  }
  return [...targets];
}

function staticStringExpression(value: string): string | undefined {
  const strings = [...value.matchAll(/['"]([^'"]*)['"]/g)].map((match) => match[1]!);
  if (strings.length === 0) return undefined;
  const remainder = value.replace(/['"][^'"]*['"]/g, '').trim();
  if (!/^(?:\s*\.\s*)*$/.test(remainder)) return undefined;
  return strings.join('');
}

function normalizeRequireTarget(target: string): string {
  const normalized = target.replace(/^\.\//, '');
  if (/^[A-Za-z_]\w*(?:\/[A-Za-z_]\w*)+\.pm$/.test(normalized)) {
    return normalized.replace(/\.pm$/, '').replaceAll('/', '::');
  }
  return normalized;
}

function isNonCallBareExpression(expression: string): boolean {
  return NON_CALL_KEYWORDS.has(expression)
    || NON_CALL_BUILTINS.has(expression)
    || NON_CALL_QUOTE_OPERATORS.has(expression)
    || (/^[A-Z_]+$/.test(expression) && NON_CALL_SQL_TOKENS.has(expression));
}

function heredocTerminator(line: string): string | undefined {
  const match = line.match(/<<\s*['"]?([A-Za-z_]\w*)['"]?/);
  return match?.[1];
}

function importedFunctionNames(importList: string | undefined): string[] {
  if (!importList) return [];
  return staticListValues(importList).filter((name) => /^[A-Za-z_]\w*$/.test(name));
}

function boundedSelfDispatchMethods(line: string, staticMethodArrays = new Map<string, string[]>()): string[] {
  const methods: string[] = [];
  for (const match of line.matchAll(/\bmap\s*\{[^}]*\$self\s*->\s*\$_[^}]*\}\s*(.+?)(?:;|$)/g)) {
    const source = match[1]!.trim();
    const arrayMatch = source.match(/^(@[A-Za-z_]\w*)$/);
    if (arrayMatch) {
      methods.push(...(staticMethodArrays.get(arrayMatch[1]!) ?? []));
    } else {
      methods.push(...staticListValues(source).filter((name) => /^[A-Za-z_]\w*$/.test(name)));
    }
  }
  return [...new Set(methods)];
}

function unresolvedArraySelfDispatch(line: string, staticMethodArrays: Map<string, string[]>): boolean {
  for (const match of line.matchAll(/\bmap\s*\{[^}]*\$self\s*->\s*\$_[^}]*\}\s*(.+?)(?:;|$)/g)) {
    const arrayMatch = match[1]!.trim().match(/^(@[A-Za-z_]\w*)$/);
    if (arrayMatch && !staticMethodArrays.has(arrayMatch[1]!)) return true;
  }
  return false;
}

function staticLoopMethodBinding(line: string, staticHashKeys = new Map<string, string[]>()): { variable: string; methods: string[]; indent: number } | undefined {
  const match = line.match(/\b(?:for|foreach)\s+my\s+(\$[A-Za-z_]\w*)\s*\(\s*(.+?)\s*\)\s*\{/);
  if (!match) return undefined;
  const source = match[2]!;
  const hashKeys = source.match(/^(?:sort\s+)?keys\s+(%[A-Za-z_]\w*)$/)?.[1];
  const methods = (hashKeys ? staticHashKeys.get(hashKeys) ?? [] : staticListValues(source))
    .filter((name) => /^[A-Za-z_]\w*$/.test(name));
  return methods.length > 0 ? { variable: match[1]!, methods, indent: line.match(/^\s*/)?.[0].length ?? 0 } : undefined;
}

function staticConditionalMethodBinding(line: string): { variable: string; methods: string[] } | undefined {
  const match = line.match(/\b(?:my|our|state)?\s*(\$[A-Za-z_]\w*)\s*=.+\?\s*['"]([A-Za-z_]\w*)['"]\s*:\s*['"]([A-Za-z_]\w*)['"]/);
  if (!match) return undefined;
  return { variable: match[1]!, methods: [...new Set([match[2]!, match[3]!])] };
}

function staticImplicitLoopMethods(line: string): string[] {
  const match = line.match(/\b(?:for|foreach)\s*\(\s*(.+?)\s*\)\s*\{/);
  if (!match) return [];
  return staticListValues(match[1]!).filter((name) => /^[A-Za-z_]\w*$/.test(name));
}

function staticArrayMethodBinding(line: string): { variable: string; methods: string[] } | undefined {
  const match = line.match(/\b(?:my|our|state)?\s*(@[A-Za-z_]\w*)\s*=\s*(.+?)\s*;/);
  if (!match) return undefined;
  const methods = staticListValues(match[2]!).filter((name) => /^[A-Za-z_]\w*$/.test(name));
  return methods.length > 0 ? { variable: match[1]!, methods } : undefined;
}

function staticMethodNamesFromListSource(line: string): string[] {
  return staticListValues(line.replace(/;\s*$/, '')).filter((name) => /^[A-Za-z_]\w*$/.test(name));
}

function canGuardedImplicitDispatchReceivers(line: string): string[] {
  const receivers = new Set<string>();
  for (const match of line.matchAll(/(\$[A-Za-z_]\w*)\s*->\s*\$_/g)) {
    const receiver = match[1]!;
    const escaped = receiver.replace(/\$/g, '\\$');
    if (new RegExp(`${escaped}\\s*->\\s*can\\s*\\(\\s*\\$_\\s*\\)`).test(line)) {
      receivers.add(receiver);
    }
  }
  return [...receivers];
}

function modifierCallerName(packageName: string, line: string, targets: string[], lineNumber: number): string {
  const modifierKind = line.match(/^\s*(before|after|around)\b/)?.[1] ?? 'modifier';
  const targetPart = targets.length > 0 ? targets.join('_') : `line_${lineNumber}`;
  const safeTarget = targetPart.replace(/[^A-Za-z0-9_]+/g, '_').replace(/^_+|_+$/g, '') || `line_${lineNumber}`;
  return `${packageName}::__modifier_${modifierKind}_${safeTarget}`;
}

function modifierKind(line: string): string {
  return line.match(/^\s*(before|after|around)\b/)?.[1] ?? 'modifier';
}

function hashFieldKey(line: string): string | undefined {
  const quoted = line.match(/^\s*['"]([A-Za-z_]\w*)['"]\s*=>/);
  if (quoted) return quoted[1];
  const bare = line.match(/^\s*([A-Za-z_]\w*)\s*=>/);
  return bare?.[1];
}

function pairedDelimiterClose(open: string): string | undefined {
  return {
    '(': ')',
    '[': ']',
    '{': '}',
    '<': '>'
  }[open];
}

function maskRange(chars: string[], start: number, end: number): void {
  for (let index = start; index < end; index += 1) {
    chars[index] = ' ';
  }
}

function maskNonCodeSegments(line: string): MaskedLine {
  const chars = line.split('');
  let index = 0;

  while (index < chars.length) {
    const char = line[index]!;

    if (char === '#') {
      maskRange(chars, index, chars.length);
      break;
    }

    if (char === '"' || char === "'") {
      const quote = char;
      let end = index + 1;
      while (end < chars.length) {
        if (line[end] === '\\') {
          end += 2;
          continue;
        }
        if (line[end] === quote) {
          end += 1;
          break;
        }
        end += 1;
      }
      maskRange(chars, index, Math.min(end, chars.length));
      index = end;
      continue;
    }

    const quoteMatch = line.slice(index).match(/^(?:q|qq|qr|qw|qx)\s*([\[({<])/);
    const previous = index > 0 ? line[index - 1] : '';
    if (quoteMatch && !/[A-Za-z0-9_:]/.test(previous ?? '')) {
      const close = pairedDelimiterClose(quoteMatch[1]!);
      if (close) {
        const start = index;
        const bodyStart = index + quoteMatch[0].length;
        const closeIndex = line.indexOf(close, bodyStart);
        if (closeIndex >= 0) {
          maskRange(chars, start, closeIndex + 1);
          index = closeIndex + 1;
          continue;
        }
        maskRange(chars, start, chars.length);
        return { text: chars.join(''), openQuoteClose: close };
      }
    }

    index += 1;
  }

  return { text: chars.join('') };
}

export function extractPerlFile(filePath: string, content: string): ExtractedPerlFile {
  const tree = parsePerl(content);
  if (!tree.rootNode) {
    throw new Error(`Unable to parse Perl file: ${filePath}`);
  }
  const errorCount = parseErrorCount(tree.rootNode);

  const rawLines = content.split(/\r?\n/);
  const lineEntries = logicalLines(content);
  const lines = lineEntries.map((entry) => entry.text);
  const symbols: PerlSymbol[] = [{
    qualified_name: filePath,
    name: filePath,
    kind: 'file',
    language: 'perl',
    file_path: filePath,
    line_start: 1,
    line_end: rawLines.length,
    provenance: ['file-discovery']
  }];
  const dependencies: ExtractedDependency[] = [];
  const role_applications: ExtractedRoleApplication[] = [];
  const exports: ExtractedExport[] = [];
  const calls: ExtractedCall[] = [];
  const unsupported_patterns: UnsupportedPattern[] = [];
  const parse_diagnostics: ParseDiagnostic[] = errorCount > 0
    ? [{
      file_path: filePath,
      error_count: errorCount,
      notes: 'tree-sitter reported parse errors; extraction may be partial'
    }]
    : [];
  let currentPackage = 'main';
  let currentSub: string | undefined;
  let localReceiverTypes = new Map<string, string>();
  let factoryReturnTypes = new Map<string, string>();
  let importedFunctions = new Map<string, string>();
  let dynamicSelfMethodNames = new Map<string, string[]>();
  let staticMethodArrays = new Map<string, string[]>();
  let activeDynamicLoopVariables = new Map<string, number>();
  let activeImplicitLoopMethods: string[] = [];
  let activeModifierScope: string | undefined;
  let activeModifierKind: string | undefined;
  let activeModifierTargets: string[] = [];
  let pendingMultilineSelfMap: { line_start?: number; snippet?: string; awaitingList: boolean } | undefined;
  let autoloadAccessorFields = new Map<string, number>();
  let collectingFieldsHash = false;
  let staticHashKeys = new Map<string, string[]>();
  let collectingStaticHash: string | undefined;
  let currentPackageUsesMooseOrMoo = false;
  let activeHeredocTerminator: string | undefined;
  let activeQuoteClose: string | undefined;

  for (let index = 0; index < lineEntries.length; index += 1) {
    const line = lineEntries[index]?.text ?? '';
    const lineNumber = lineEntries[index]?.lineNumber ?? index + 1;

    if (activeHeredocTerminator) {
      if (line.trim() === activeHeredocTerminator) {
        activeHeredocTerminator = undefined;
      }
      continue;
    }

    if (activeQuoteClose) {
      if (line.includes(activeQuoteClose)) {
        activeQuoteClose = undefined;
      }
      continue;
    }

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
      localReceiverTypes = new Map<string, string>();
      factoryReturnTypes = new Map<string, string>();
      importedFunctions = new Map<string, string>();
      staticMethodArrays = new Map<string, string[]>();
      activeImplicitLoopMethods = [];
      activeModifierScope = undefined;
      activeModifierKind = undefined;
      activeModifierTargets = [];
      pendingMultilineSelfMap = undefined;
      autoloadAccessorFields = new Map<string, number>();
      collectingFieldsHash = false;
      staticHashKeys = new Map<string, string[]>();
      collectingStaticHash = undefined;
      currentPackageUsesMooseOrMoo = false;
      continue;
    }

    if (/^\s*(?:my|our)\s+%fields\s*=\s*\(/.test(line)) {
      collectingFieldsHash = true;
      const key = hashFieldKey(line);
      if (key) autoloadAccessorFields.set(key, lineNumber);
      if (/^\s*\);/.test(line) || /\)\s*;/.test(line)) collectingFieldsHash = false;
      continue;
    }

    if (collectingFieldsHash) {
      const key = hashFieldKey(line);
      if (key) autoloadAccessorFields.set(key, lineNumber);
      if (/^\s*\);/.test(line)) collectingFieldsHash = false;
      continue;
    }

    const staticHashMatch = line.match(/^\s*(?:my|our|state)\s+(%[A-Za-z_]\w*)\s*=\s*\(/);
    if (staticHashMatch && !/AUTOLOAD/.test(staticHashMatch[1]!)) {
      const hashName = staticHashMatch[1]!;
      staticHashKeys.set(hashName, []);
      collectingStaticHash = hashName;
      const key = hashFieldKey(line);
      if (key) staticHashKeys.set(hashName, [...(staticHashKeys.get(hashName) ?? []), key]);
      if (/^\s*\);/.test(line) || /\)\s*;/.test(line)) collectingStaticHash = undefined;
      continue;
    }

    if (collectingStaticHash) {
      const key = hashFieldKey(line);
      if (key) staticHashKeys.set(collectingStaticHash, [...(staticHashKeys.get(collectingStaticHash) ?? []), key]);
      if (/^\s*\);/.test(line)) collectingStaticHash = undefined;
      continue;
    }

    const exportMatch = line.match(/^\s*(?:our\s+)?@EXPORT(?:_OK)?\s*=\s*(.+?)\s*;/);
    if (exportMatch) {
      for (const name of staticListValues(exportMatch[1]!).filter((value) => /^[A-Za-z_]\w*$/.test(value))) {
        exports.push({ source_package: currentPackage, name });
      }
      continue;
    }

    const subMatch = line.match(/^\s*sub\s+([A-Za-z_]\w*)/);
    if (subMatch) {
      const name = subMatch[1]!;
      const endLine = lineEnd(lines, index);
      const body = lines.slice(index, endLine).join('\n');
      const kind = classifySub(name, body);
      const qualifiedName = `${currentPackage}::${name}`;
      const factoryReturn = body.match(/\breturn\s+([A-Za-z_][\w:]*)\s*->\s*new\b/);
      if (factoryReturn) {
        factoryReturnTypes.set(qualifiedName, factoryReturn[1]!);
      }
      if (name === 'AUTOLOAD' && /\{_permitted\}/.test(body)) {
        for (const [fieldName, fieldLine] of autoloadAccessorFields) {
          symbols.push({
            qualified_name: `${currentPackage}::${fieldName}`,
            name: fieldName,
            kind: 'method',
            language: 'perl',
            file_path: filePath,
            line_start: fieldLine,
            line_end: fieldLine,
            signature: `AUTOLOAD accessor ${fieldName}`,
            provenance: ['autoload-accessor', 'line-scan']
          });
        }
      }
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
      localReceiverTypes = new Map<string, string>();
      dynamicSelfMethodNames = new Map<string, string[]>();
      staticMethodArrays = new Map<string, string[]>();
      activeDynamicLoopVariables = new Map<string, number>();
      activeImplicitLoopMethods = [];
      activeModifierScope = undefined;
      activeModifierKind = undefined;
      activeModifierTargets = [];
      pendingMultilineSelfMap = undefined;
      if (name === 'AUTOLOAD') {
        const autoloadTargets = /\{_permitted\}/.test(body) ? [...autoloadAccessorFields.keys()] : [];
        unsupported_patterns.push({
          kind: 'autoload',
          file_path: filePath,
          line_start: lineNumber,
          snippet: line.trim(),
          notes: autoloadTargets.length > 0
            ? `AUTOLOAD dispatch cannot be statically resolved; static accessor evidence for: ${autoloadTargets.join(', ')}`
            : 'AUTOLOAD dispatch cannot be statically resolved',
          ...(autoloadTargets.length > 0 ? { targets: autoloadTargets } : {})
        });
      }
      continue;
    }

    if (/%AUTOLOAD_[A-Z_]*MAP\b|\bAUTOLOAD_[A-Z_]*MAP\b/.test(line)) {
      unsupported_patterns.push({
        kind: 'autoload_dispatch_map',
        file_path: filePath,
        line_start: lineNumber,
        snippet: line.trim(),
        notes: 'Static AUTOLOAD dispatch map is evidence but AUTOLOAD remains dynamic'
      });
    }

    const useMatch = line.match(/^\s*use\s+([A-Za-z_][\w:]*)(?:\s+(.+?))?\s*;/);
    if (useMatch) {
      const moduleName = useMatch[1]!;
      if (frameworkForModule(moduleName)) {
        currentPackageUsesMooseOrMoo = true;
      }
      if (moduleName === 'parent' || moduleName === 'base') {
        for (const target of staticListValues(useMatch[2] ?? '')) {
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
        for (const importedName of importedFunctionNames(useMatch[2])) {
          importedFunctions.set(importedName, moduleName);
        }
      }
      continue;
    }

    if (currentPackageUsesMooseOrMoo) {
      const declaration = frameworkDeclaration(line);
      if (declaration?.kind === 'role') {
        for (const role of declaration.values) {
          role_applications.push({
            source_package: currentPackage,
            target_role: role,
            file_path: filePath,
            line_start: lineNumber
          });
        }
        continue;
      }

      if (declaration?.kind === 'extends') {
        for (const target of declaration.values) {
          dependencies.push({
            source_module: currentPackage,
            target_module: target,
            source_file: filePath,
            kind: 'parent',
            line_start: lineNumber
          });
        }
        continue;
      }

      if (declaration?.kind === 'attribute') {
        for (const name of declaration.values) {
          symbols.push({
            qualified_name: `${currentPackage}::${name}`,
            name,
            kind: 'method',
            language: 'perl',
            file_path: filePath,
            line_start: lineNumber,
            line_end: lineNumber,
            signature: `has ${name}`,
            provenance: ['moose-moo-attribute', 'line-scan']
          });
        }
        continue;
      }

      if (declaration?.kind === 'requires') {
        for (const name of declaration.values) {
          symbols.push({
            qualified_name: `${currentPackage}::${name}`,
            name,
            kind: 'method',
            language: 'perl',
            file_path: filePath,
            line_start: lineNumber,
            line_end: lineNumber,
            signature: `requires ${name}`,
            provenance: ['moose-moo-requires', 'line-scan']
          });
        }
        continue;
      }

      if (declaration?.kind === 'modifier') {
        const targets = declaration.values;
        const kind = modifierKind(line);
        const modifierCaller = modifierCallerName(currentPackage, line, targets, lineNumber);
        unsupported_patterns.push({
          kind: 'moose_modifier',
          file_path: filePath,
          line_start: lineNumber,
          snippet: line.trim(),
          notes: targets.length > 0
            ? `Moose/Moo method modifier changes dispatch semantics for: ${targets.join(', ')}`
            : 'Moose/Moo method modifier changes dispatch semantics',
          ...(targets.length > 0 ? { targets } : {})
        });
        if (/\bsub\s*\{/.test(line) && !/\}\s*;/.test(line)) {
          currentSub = modifierCaller;
          activeModifierScope = modifierCaller;
          activeModifierKind = kind;
          activeModifierTargets = targets;
          localReceiverTypes = new Map<string, string>();
          dynamicSelfMethodNames = new Map<string, string[]>();
          staticMethodArrays = new Map<string, string[]>();
          activeDynamicLoopVariables = new Map<string, number>();
          activeImplicitLoopMethods = [];
          pendingMultilineSelfMap = undefined;
        }
        continue;
      }
    }

    const requireMatch = line.match(/^\s*require\s+(.+?)\s*;/);
    if (requireMatch) {
      if (isVersionRequire(line)) continue;
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

    if (isEvalStringRequire(line)) {
      unsupported_patterns.push({
        kind: 'dynamic_require',
        file_path: filePath,
        line_start: lineNumber,
        snippet: line.trim(),
        notes: 'String eval performs a dynamic require target that cannot be statically resolved'
      });
    } else if (isEvalStringUse(line)) {
      unsupported_patterns.push({
        kind: 'dynamic_use',
        file_path: filePath,
        line_start: lineNumber,
        snippet: line.trim(),
        notes: 'String eval performs a dynamic use statement that cannot be statically resolved'
      });
    } else if (/\beval\s+\$/.test(line) || /\beval\s+["']/.test(line)) {
      unsupported_patterns.push({
        kind: 'eval_string',
        file_path: filePath,
        line_start: lineNumber,
        snippet: line.trim(),
        notes: 'String eval cannot be statically resolved'
      });
    }

    if (/\*\{/.test(line) || /^\s*\*\w+::/.test(line)) {
      const targets = globAssignmentTargets(line);
      unsupported_patterns.push({
        kind: 'glob_assignment',
        file_path: filePath,
        line_start: lineNumber,
        snippet: line.trim(),
        notes:
          targets.length > 0
            ? `Typeglob assignment may alter the symbol table; static target evidence for: ${targets.join(', ')}`
            : 'Typeglob assignment may alter the symbol table',
        ...(targets.length > 0 ? { targets } : {})
      });
    }

    if (/\$\{\s*\$[A-Za-z_]\w*\s*\}/.test(line)) {
      unsupported_patterns.push({
        kind: 'symbolic_ref',
        file_path: filePath,
        line_start: lineNumber,
        snippet: line.trim(),
        notes: 'Symbolic reference target cannot be statically resolved'
      });
    }

    const dynamicPatternLine = maskNonCodeSegments(line).text;
    if (!currentSub && /(?:\$[A-Za-z_]\w*)\s*->\s*\$[A-Za-z_]\w*/.test(dynamicPatternLine) && boundedSelfDispatchMethods(line).length === 0) {
      unsupported_patterns.push({
        kind: 'dynamic_method',
        file_path: filePath,
        line_start: lineNumber,
        snippet: line.trim(),
        notes: 'Dynamic method name cannot be statically resolved'
      });
    }

    if (/[$@%&]\{\s*\$[A-Za-z_]\w*\s*\}\s*->/.test(dynamicPatternLine)) {
      unsupported_patterns.push({
        kind: 'symbolic_method_receiver',
        file_path: filePath,
        line_start: lineNumber,
        snippet: line.trim(),
        notes: 'Symbolic method receiver cannot be statically resolved'
      });
    }

    if (currentSub) {
      activeHeredocTerminator = heredocTerminator(line);
      const maskedLine = maskNonCodeSegments(line);
      activeQuoteClose = maskedLine.openQuoteClose;
      if (pendingMultilineSelfMap?.awaitingList) {
        const methods = staticMethodNamesFromListSource(line);
        if (methods.length > 0 && pendingMultilineSelfMap.line_start) {
          for (const methodName of methods) {
            calls.push({
              caller: currentSub,
              expression: `$self->${methodName}`,
              file_path: filePath,
              line_start: pendingMultilineSelfMap.line_start
            });
          }
          pendingMultilineSelfMap = undefined;
        } else if (line.trim() && !/^\s*}\s*$/.test(line)) {
          unsupported_patterns.push({
            kind: 'dynamic_method',
            file_path: filePath,
            line_start: pendingMultilineSelfMap.line_start ?? lineNumber,
            snippet: pendingMultilineSelfMap.snippet ?? line.trim(),
            notes: 'Dynamic method name cannot be statically resolved'
          });
          pendingMultilineSelfMap = undefined;
        }
      }
      if (/\bmap\s*\{/.test(line) && !line.includes('}')) {
        pendingMultilineSelfMap = { awaitingList: false };
      }
      if (pendingMultilineSelfMap && /\$self\s*->\s*\$_/.test(line)) {
        pendingMultilineSelfMap.line_start = lineNumber;
        pendingMultilineSelfMap.snippet = line.trim();
      }
      const arrayBinding = staticArrayMethodBinding(line);
      const assignedArray = line.match(/\b(?:my|our|state)?\s*(@[A-Za-z_]\w*)\s*=/);
      if (arrayBinding) {
        staticMethodArrays.set(arrayBinding.variable, arrayBinding.methods);
      } else if (assignedArray) {
        staticMethodArrays.delete(assignedArray[1]!);
      }
      const expandedSelfDispatchMethods = boundedSelfDispatchMethods(line, staticMethodArrays);
      const hasUnresolvedArraySelfDispatch = unresolvedArraySelfDispatch(line, staticMethodArrays);
      const loopBinding = staticLoopMethodBinding(line, staticHashKeys);
      const implicitLoopMethods = staticImplicitLoopMethods(line);
      if (implicitLoopMethods.length > 0) {
        activeImplicitLoopMethods = implicitLoopMethods;
      }
      if (loopBinding) {
        dynamicSelfMethodNames.set(loopBinding.variable, loopBinding.methods);
        activeDynamicLoopVariables.set(loopBinding.variable, loopBinding.indent);
      }
      const conditionalBinding = staticConditionalMethodBinding(line);
      if (conditionalBinding) {
        dynamicSelfMethodNames.set(conditionalBinding.variable, conditionalBinding.methods);
      }

      const classAlias = line.match(/\b(?:my|our|state)?\s*(\$[A-Za-z_]\w*)\s*=\s*['"]([A-Za-z_][\w:]*)['"]/);
      if (classAlias) {
        localReceiverTypes.set(classAlias[1]!, classAlias[2]!);
        if (!classAlias[2]!.includes('::')) {
          dynamicSelfMethodNames.set(classAlias[1]!, [classAlias[2]!]);
        }
      }

      const constructorAssignment = line.match(/\b(?:my|our|state)?\s*(\$[A-Za-z_]\w*)\s*=\s*((?:\$[A-Za-z_]\w*)|(?:[A-Za-z_][\w:]*))\s*->\s*new\b/);
      if (constructorAssignment) {
        const receiver = constructorAssignment[2]!;
        const receiverType = receiver.startsWith('$') ? localReceiverTypes.get(receiver) : receiver;
        if (receiverType) {
          localReceiverTypes.set(constructorAssignment[1]!, receiverType);
        }
      }

      const factoryAssignment = line.match(/\b(?:my|our|state)?\s*(\$[A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*\(/);
      if (factoryAssignment) {
        const factoryType = factoryReturnTypes.get(`${packageOf(currentSub)}::${factoryAssignment[2]!}`);
        if (factoryType) {
          localReceiverTypes.set(factoryAssignment[1]!, factoryType);
        }
      }

      const methodAssignment = line.match(/\b(?:my|our|state)?\s*(\$[A-Za-z_]\w*)\s*=\s*((?:\$[A-Za-z_]\w*)|(?:[A-Za-z_][\w:]*))\s*->\s*([A-Za-z_]\w*)\b/);
      if (methodAssignment) {
        const assigned = methodAssignment[1]!;
        const receiver = methodAssignment[2]!;
        const method = methodAssignment[3]!;
        const receiverType = localReceiverTypes.get(receiver);
        if (method === 'dbh' || method === 'mysqlConnection') {
          localReceiverTypes.set(assigned, 'DBI::db');
        } else if (method === 'prepare' && (receiverType === 'DBI::db' || receiver.toLowerCase().includes('dbh'))) {
          localReceiverTypes.set(assigned, 'DBI::st');
        } else if (method === 'query' && (receiverType === 'Opta::Database' || receiver === '$mc' || receiver.toLowerCase().includes('mysql'))) {
          localReceiverTypes.set(assigned, 'DBI::st');
        }
      }

      for (const match of maskedLine.text.matchAll(/([A-Za-z_][\w:]*(?:::[A-Za-z_]\w*)?)\s*\(/g)) {
        const expression = match[1]!;
        if (isNonCallBareExpression(expression)) continue;
        const previous = maskedLine.text.slice(Math.max(0, match.index - 2), match.index);
        if (previous === '->' || previous === '::') continue;
        const previousChar = maskedLine.text[Math.max(0, match.index - 1)];
        if (previousChar && /[$@%&]/.test(previousChar)) continue;
        const receiverType = factoryReturnTypes.get(`${packageOf(currentSub)}::${expression}`);
        calls.push({
          caller: currentSub,
          expression,
          ...(receiverType ? { receiver_type: receiverType } : {}),
          ...(importedFunctions.has(expression) ? { imported_from: importedFunctions.get(expression)! } : {}),
          file_path: filePath,
          line_start: lineNumber
        });
      }
      for (const methodName of expandedSelfDispatchMethods) {
        calls.push({
          caller: currentSub,
          expression: `$self->${methodName}`,
          file_path: filePath,
          line_start: lineNumber
        });
      }
      const expandedImplicitLoopMethods = /\$self\s*->\s*\$_/.test(maskedLine.text) ? activeImplicitLoopMethods : [];
      for (const methodName of expandedImplicitLoopMethods) {
        calls.push({
          caller: currentSub,
          expression: `$self->${methodName}`,
          file_path: filePath,
          line_start: lineNumber
        });
      }
      const canGuardedReceivers = activeImplicitLoopMethods.length > 0
        ? canGuardedImplicitDispatchReceivers(maskedLine.text)
        : [];
      for (const receiver of canGuardedReceivers.filter((receiver) => receiver !== '$self')) {
        for (const methodName of activeImplicitLoopMethods) {
          calls.push({
            caller: currentSub,
            expression: `${receiver}->${methodName}`,
            file_path: filePath,
            line_start: lineNumber
          });
        }
      }
      const dynamicSelfMatch = maskedLine.text.match(/\$self\s*->\s*(\$[A-Za-z_]\w*)/);
      if (dynamicSelfMatch) {
        const variable = dynamicSelfMatch[1]!;
        const methods = dynamicSelfMethodNames.get(variable);
        const pendingMultilineSelfDispatch = variable === '$_' && pendingMultilineSelfMap?.line_start === lineNumber;
        const aroundOrigDispatch = activeModifierKind === 'around' && variable === '$orig';
        if (methods) {
          for (const methodName of methods) {
            calls.push({
              caller: currentSub,
              expression: `$self->${methodName}`,
              file_path: filePath,
              line_start: lineNumber
            });
          }
        } else if (aroundOrigDispatch) {
          unsupported_patterns.push({
            kind: 'moose_around_orig',
            file_path: filePath,
            line_start: lineNumber,
            snippet: line.trim(),
            notes: 'Moose around modifier continuation cannot be resolved as a normal static method',
            ...(activeModifierTargets.length > 0 ? { targets: activeModifierTargets } : {})
          });
        } else if (!(variable === '$_' && (expandedSelfDispatchMethods.length > 0 || expandedImplicitLoopMethods.length > 0 || hasUnresolvedArraySelfDispatch || pendingMultilineSelfDispatch))) {
          unsupported_patterns.push({
            kind: 'dynamic_method',
            file_path: filePath,
            line_start: lineNumber,
            snippet: line.trim(),
            notes: 'Dynamic method name cannot be statically resolved'
          });
        }
      }
      if (hasUnresolvedArraySelfDispatch) {
        unsupported_patterns.push({
          kind: 'dynamic_method',
          file_path: filePath,
          line_start: lineNumber,
          snippet: line.trim(),
          notes: 'Dynamic method name cannot be statically resolved'
        });
      }
      if (!dynamicSelfMatch && /(?:\$[A-Za-z_]\w*)\s*->\s*\$[A-Za-z_]\w*/.test(maskedLine.text) && canGuardedReceivers.length === 0) {
        unsupported_patterns.push({
          kind: 'dynamic_method',
          file_path: filePath,
          line_start: lineNumber,
          snippet: line.trim(),
          notes: 'Dynamic method name cannot be statically resolved'
        });
      }
      for (const match of maskedLine.text.matchAll(/((?:\$[A-Za-z_]\w*)|(?:[A-Za-z_][\w:]*))\s*->\s*([A-Za-z_]\w*)/g)) {
        const receiver = match[1]!;
        const receiverType = localReceiverTypes.get(receiver);
        calls.push({
          caller: currentSub,
          expression: `${receiver}->${match[2]!}`,
          ...(receiverType ? { receiver_type: receiverType } : {}),
          file_path: filePath,
          line_start: lineNumber
        });
      }
      if (/^\s*\}/.test(line)) {
        const closeIndent = line.match(/^\s*/)?.[0].length ?? 0;
        for (const [variable, loopIndent] of activeDynamicLoopVariables) {
          if (closeIndent <= loopIndent) {
            dynamicSelfMethodNames.delete(variable);
            activeDynamicLoopVariables.delete(variable);
          }
        }
        activeImplicitLoopMethods = [];
        if (pendingMultilineSelfMap?.line_start) {
          pendingMultilineSelfMap.awaitingList = true;
        }
        if (activeModifierScope && /^\s*}\s*;?\s*$/.test(line)) {
          currentSub = undefined;
          activeModifierScope = undefined;
          activeModifierKind = undefined;
          activeModifierTargets = [];
          localReceiverTypes = new Map<string, string>();
          dynamicSelfMethodNames = new Map<string, string[]>();
          staticMethodArrays = new Map<string, string[]>();
          pendingMultilineSelfMap = undefined;
        }
      }
    }
  }

  return { symbols, dependencies, role_applications, exports, calls, unsupported_patterns, parse_diagnostics };
}
