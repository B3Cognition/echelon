/**
 * CodeGraph Bridge
 *
 * Entry point for the bash pipeline. Parses CLI arguments, orchestrates
 * adapter calls, assembles codegraph-analysis.json, and writes atomically.
 *
 * ADR-001: Library import, single-invocation model.
 * ADR-002: Single bridge script, multi-command.
 * ADR-003: Adapter isolates all CodeGraph imports — do NOT import CodeGraph here.
 */
import type { AnalysisOutput } from './integration-types';
import * as adapter from './codegraph-adapter';
export declare const DEFAULT_OUTPUT_RELATIVE = ".specify/echelon/re/codegraph-analysis.json";
export declare const DEFAULT_DEPTH = 3;
export declare const DEFAULT_MAX_SYMBOLS = 10000;
export declare const MIN_DEPTH = 1;
export declare const MAX_DEPTH = 10;
export declare const BRIDGE_TIMEOUT_MS = 600000;
export interface ParsedArgs {
    command: string;
    repoPath: string;
    outputPath: string;
    languages: string[] | undefined;
    depth: number;
    maxSymbols: number;
}
/**
 * Parses process.argv (or a supplied args array) into a structured ParsedArgs.
 *
 * Throws with a usage message (suitable for writing to stderr + exit 1) on
 * invalid input.
 *
 * Does NOT call process.exit() — that is the caller's responsibility so that
 * unit tests can capture the error without process termination.
 */
export declare function parseArgs(argv: string[]): ParsedArgs;
export declare class UsageError extends Error {
    constructor(message: string);
}
export declare function usageMessage(): string;
/**
 * Writes data to outputPath atomically via a .tmp file + rename.
 * Creates parent directories as needed.
 * Throws on failure after cleaning up the temp file.
 */
export declare function atomicWrite(outputPath: string, data: string): Promise<void>;
/**
 * Assembles a complete AnalysisOutput from adapter results.
 * Exported for unit testing.
 */
export declare function assembleAnalysisOutput(params: {
    repoPath: string;
    symbols: Awaited<ReturnType<typeof adapter.getSymbols>>;
    relationships: Awaited<ReturnType<typeof adapter.getRelationships>>;
    callGraph: Awaited<ReturnType<typeof adapter.getCallGraph>>;
    typeHierarchy: Awaited<ReturnType<typeof adapter.getTypeHierarchy>>;
    impactRadius: Awaited<ReturnType<typeof adapter.getImpactRadius>>;
    publicSymbols: Awaited<ReturnType<typeof adapter.getPublicSymbols>>;
    indexStats: ReturnType<typeof adapter.getIndexStats>;
    extractionSummary: ReturnType<typeof adapter.getExtractionSummary>;
}): AnalysisOutput;
/**
 * Truncates symbols to maxSymbols by incoming call count (T009).
 * Symbols with more incoming calls are retained first.
 */
export declare function truncateSymbols(symbols: Awaited<ReturnType<typeof adapter.getSymbols>>, callGraph: Awaited<ReturnType<typeof adapter.getCallGraph>>, maxSymbols: number): Awaited<ReturnType<typeof adapter.getSymbols>>;
/**
 * Full bridge orchestration pipeline.
 * Exported for integration testing.
 */
export declare function runBridge(repoPath: string, outputPath: string, languages: string[] | undefined, depth: number, maxSymbols: number): Promise<void>;
//# sourceMappingURL=codegraph-bridge.d.ts.map