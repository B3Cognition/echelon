import { readFile } from 'node:fs/promises';
import path from 'node:path';
import fg from 'fast-glob';
import picomatch from 'picomatch';

export interface PerlFile {
  absolutePath: string;
  relativePath: string;
  content: string;
}

const PERL_EXTENSIONS = new Set(['.pl', '.pm', '.t', '.psgi']);
const DEFAULT_IGNORES = [
  '**/.git/**',
  '**/node_modules/**',
  '**/local/**',
  '**/vendor/**',
  '**/dist/**',
  '**/build/**',
  '**/blib/**',
  '**/_build/**',
  '**/.carton/**'
];

export function isPerlFile(filePath: string, content = ''): boolean {
  const ext = path.extname(filePath).toLowerCase();
  if (PERL_EXTENSIONS.has(ext)) return true;
  const firstLine = content.split(/\r?\n/, 1)[0] ?? '';
  return firstLine.startsWith('#!') && /\bperl\b/.test(firstLine);
}

export async function discoverPerlFiles(
  repoPath: string,
  options: { include?: string[]; exclude?: string[] } = {}
): Promise<PerlFile[]> {
  const absoluteRepoPath = path.resolve(repoPath);
  const entries = await fg('**/*', {
    cwd: absoluteRepoPath,
    dot: false,
    onlyFiles: true,
    ignore: [...DEFAULT_IGNORES, ...(options.exclude ?? [])],
    unique: true
  });

  const includeMatchers = (options.include ?? []).map((pattern) => picomatch(pattern));
  const files: PerlFile[] = [];

  for (const relativePath of entries.sort()) {
    if (includeMatchers.length > 0 && !includeMatchers.some((matches) => matches(relativePath))) {
      continue;
    }
    const absolutePath = path.join(absoluteRepoPath, relativePath);
    const content = await readFile(absolutePath, 'utf8');
    if (!isPerlFile(relativePath, content)) continue;
    files.push({ absolutePath, relativePath, content });
  }

  return files;
}
