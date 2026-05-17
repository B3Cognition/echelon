/**
 * Import Resolver
 *
 * Resolves import paths to actual files and symbols.
 */
import { Language } from '../types';
import { UnresolvedRef, ResolvedRef, ResolutionContext, ImportMapping } from './types';
/**
 * Resolve an import path to an actual file
 */
export declare function resolveImportPath(importPath: string, fromFile: string, language: Language, context: ResolutionContext): string | null;
/**
 * Extract import mappings from a file
 */
export declare function extractImportMappings(_filePath: string, content: string, language: Language): ImportMapping[];
/**
 * Clear the import mapping cache (call between indexing runs)
 */
export declare function clearImportMappingCache(): void;
/**
 * Resolve a reference using import mappings
 */
export declare function resolveViaImport(ref: UnresolvedRef, context: ResolutionContext): ResolvedRef | null;
//# sourceMappingURL=import-resolver.d.ts.map