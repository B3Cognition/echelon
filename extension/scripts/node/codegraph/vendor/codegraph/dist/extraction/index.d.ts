/**
 * Extraction Orchestrator
 *
 * Coordinates file scanning, parsing, and database storage.
 */
import * as fs from 'fs';
import { ExtractionResult, ExtractionError, CodeGraphConfig } from '../types';
import { QueryBuilder } from '../db/queries';
/**
 * Progress callback for indexing operations
 */
export interface IndexProgress {
    phase: 'scanning' | 'parsing' | 'storing' | 'resolving';
    current: number;
    total: number;
    currentFile?: string;
}
/**
 * Result of an indexing operation
 */
export interface IndexResult {
    success: boolean;
    filesIndexed: number;
    filesSkipped: number;
    filesErrored: number;
    nodesCreated: number;
    edgesCreated: number;
    errors: ExtractionError[];
    durationMs: number;
}
/**
 * Result of a sync operation
 */
export interface SyncResult {
    filesChecked: number;
    filesAdded: number;
    filesModified: number;
    filesRemoved: number;
    nodesUpdated: number;
    durationMs: number;
    changedFilePaths?: string[];
}
/**
 * Calculate SHA256 hash of file contents
 */
export declare function hashContent(content: string): string;
/**
 * Check if a file should be included based on config
 */
export declare function shouldIncludeFile(filePath: string, config: CodeGraphConfig): boolean;
/**
 * Recursively scan directory for source files.
 *
 * In git repos, uses `git ls-files` to get the file list (inherently
 * respects .gitignore at all levels), then filters by config include patterns.
 * Falls back to filesystem walk for non-git projects.
 */
export declare function scanDirectory(rootDir: string, config: CodeGraphConfig, onProgress?: (current: number, file: string) => void): string[];
/**
 * Async variant of scanDirectory that yields to the event loop periodically,
 * allowing worker threads to receive and render progress messages.
 */
export declare function scanDirectoryAsync(rootDir: string, config: CodeGraphConfig, onProgress?: (current: number, file: string) => void): Promise<string[]>;
/**
 * Extraction orchestrator
 */
export declare class ExtractionOrchestrator {
    private rootDir;
    private config;
    private queries;
    constructor(rootDir: string, config: CodeGraphConfig, queries: QueryBuilder);
    /**
     * Index all files in the project
     */
    indexAll(onProgress?: (progress: IndexProgress) => void, signal?: AbortSignal, verbose?: boolean): Promise<IndexResult>;
    /**
     * Index specific files
     */
    indexFiles(filePaths: string[]): Promise<IndexResult>;
    /**
     * Index a single file
     */
    indexFile(relativePath: string): Promise<ExtractionResult>;
    /**
     * Index a single file with pre-read content and stats.
     * Used by the parallel batch reader to avoid redundant file I/O.
     */
    indexFileWithContent(relativePath: string, content: string, stats: fs.Stats): Promise<ExtractionResult>;
    /**
     * Store extraction result in database
     */
    private storeExtractionResult;
    /**
     * Sync with current file state.
     * Uses git status as a fast path when available, falling back to full scan.
     */
    sync(onProgress?: (progress: IndexProgress) => void): Promise<SyncResult>;
    /**
     * Get files that have changed since last index.
     * Uses git status as a fast path when available, falling back to full scan.
     */
    getChangedFiles(): {
        added: string[];
        modified: string[];
        removed: string[];
    };
}
export { extractFromSource } from './tree-sitter';
export { detectLanguage, isLanguageSupported, isGrammarLoaded, getSupportedLanguages, initGrammars, loadGrammarsForLanguages, loadAllGrammars } from './grammars';
//# sourceMappingURL=index.d.ts.map