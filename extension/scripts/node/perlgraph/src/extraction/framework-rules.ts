export type FrameworkName = 'Moose' | 'Moo';

export interface FrameworkDeclaration {
  kind: 'role' | 'extends' | 'attribute' | 'requires' | 'modifier';
  values: string[];
}

export function frameworkForModule(moduleName: string): FrameworkName | undefined {
  if (/^Moose(?:::Role)?$/.test(moduleName)) return 'Moose';
  if (/^Moo(?:::Role)?$/.test(moduleName)) return 'Moo';
  return undefined;
}

export function staticListValues(value: string): string[] {
  const targets: string[] = [];
  const withoutOptions = value.replace(/\s*-\w+\s*,?/g, ' ');

  for (const match of withoutOptions.matchAll(/\bqw\s*[(/{[]\s*([^)/}\]]+)\s*[)/}\]]/g)) {
    targets.push(...match[1]!.split(/\s+/).filter(Boolean));
  }
  for (const match of withoutOptions.matchAll(/\bqw\s*\|\s*([^|]+)\s*\|/g)) {
    targets.push(...match[1]!.split(/\s+/).filter(Boolean));
  }

  const withoutQw = withoutOptions
    .replace(/\bqw\s*[(/{[]\s*[^)/}\]]+\s*[)/}\]]/g, ' ')
    .replace(/\bqw\s*\|\s*[^|]+\s*\|/g, ' ');
  targets.push(...[...withoutQw.matchAll(/['"]([^'"]+)['"]/g)].map((match) => match[1]!).filter(Boolean));

  for (const part of withoutQw.split(/\s*,\s*/)) {
    const bare = part.trim().match(/^([A-Za-z_][\w:]*)$/);
    if (bare) targets.push(bare[1]!);
  }

  return [...new Set(targets)];
}

export function attributeNames(value: string): string[] {
  const trimmed = value.trim();
  const quoted = trimmed.match(/^['"]([^'"]+)['"]$/);
  if (quoted) return [quoted[1]!];
  const qwList = trimmed.match(/^\[\s*qw\s*[(/{[]\s*([^)/}\]]+)\s*[)/}\]]\s*\]$/);
  if (qwList) return qwList[1]!.split(/\s+/).filter(Boolean);
  const bare = trimmed.match(/^([A-Za-z_]\w*)$/);
  if (bare) return [bare[1]!];
  return [];
}

export function frameworkDeclaration(line: string): FrameworkDeclaration | undefined {
  const roleMatch = line.match(/^\s*with\s+(.+?)\s*;/);
  if (roleMatch) return { kind: 'role', values: staticListValues(roleMatch[1]!) };

  const extendsMatch = line.match(/^\s*extends\s+(.+?)\s*;/);
  if (extendsMatch) return { kind: 'extends', values: staticListValues(extendsMatch[1]!) };

  const attributeMatch = line.match(/^\s*has\s+(.+?)\s*=>/);
  if (attributeMatch) return { kind: 'attribute', values: attributeNames(attributeMatch[1]!) };

  const requiresMatch = line.match(/^\s*requires\s+(.+?)\s*;/);
  if (requiresMatch) return { kind: 'requires', values: staticListValues(requiresMatch[1]!) };

  const modifierMatch = line.match(/^\s*(before|after|around)\s+(.+?)\s*=>/);
  if (modifierMatch) return { kind: 'modifier', values: staticListValues(modifierMatch[2]!) };

  return undefined;
}
