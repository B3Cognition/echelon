import { readFileSync } from 'node:fs';

export function packageVersion(): string {
  const packageJson = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8')) as { version: string };
  return packageJson.version;
}
