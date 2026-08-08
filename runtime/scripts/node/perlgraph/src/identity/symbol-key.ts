import { createHash } from 'node:crypto';

export interface SymbolLocator {
  file_path: string;
  qualified_name: string;
  kind: string;
  signature?: string;
}

/** Return the canonical source-relative locator shared by topology providers. */
export function normalizeSourcePath(filePath: string): string {
  if (typeof filePath !== 'string' || filePath.length === 0) {
    throw new Error('PerlGraph contract error: symbol file path is required');
  }
  const normalized = filePath.replace(/\\/g, '/');
  if (normalized.startsWith('/') || /^[A-Za-z]:\//.test(normalized)) {
    throw new Error(`PerlGraph contract error: absolute symbol file path: ${filePath}`);
  }
  const segments = normalized.split('/');
  if (segments.some((segment) => segment === '..')) {
    throw new Error(`PerlGraph contract error: traversing symbol file path: ${filePath}`);
  }
  const sourceRelative = segments.filter((segment) => segment && segment !== '.').join('/');
  if (!sourceRelative) {
    throw new Error(`PerlGraph contract error: empty symbol file path: ${filePath}`);
  }
  return sourceRelative;
}

export function symbolKey(locator: SymbolLocator): string {
  const canonical = [
    normalizeSourcePath(locator.file_path),
    String(locator.qualified_name),
    String(locator.kind),
    locator.signature == null ? '' : String(locator.signature)
  ];
  return `sha256:${createHash('sha256').update(JSON.stringify(canonical), 'utf8').digest('hex')}`;
}
