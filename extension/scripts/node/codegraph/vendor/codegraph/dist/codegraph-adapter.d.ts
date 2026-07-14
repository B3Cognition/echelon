/**
 * CodeGraph Adapter
 *
 * Thin adapter layer that isolates the bridge from CodeGraph's API surface.
 * This is the ONLY file that imports from @colbymchenry/codegraph (or locally
 * from the main index for brownfield — same contract either way).
 * All bridge code MUST call through this adapter.
 *
 * ADR-003: Pre-1.0 API stability — all CodeGraph calls localized here.
 */
import { CodeGraph, IndexResult } from './index';
import type { OutputSymbol, Relationship, CallEdge, TypeEdge, ImpactEntry, IndexStats, ExtractionSummary } from './integration-types';
export interface IndexResult_Ext extends IndexResult {
    startTime?: number;
}
/**
 * 1. initializeGrammars
 *
 * Initialises the WASM grammar runtime, then loads grammars for the requested
 * languages. Catches per-language errors, logs a warning, and continues.
 *
 * @param languages  Optional list of language identifiers (e.g. ["typescript"]).
 *                   Defaults to all supported languages when omitted.
 */
export declare function initializeGrammars(languages?: string[]): Promise<void>;
/**
 * 2. buildIndex
 *
 * Creates a new CodeGraph instance, calls init() then indexAll().
 * Returns the IndexResult alongside the CodeGraph instance.
 *
 * @param repoPath    Absolute path to the repository.
 * @param onProgress  Optional progress callback.
 */
export declare function buildIndex(repoPath: string, onProgress?: (filesIndexed: number, filesTotal: number) => void): Promise<{
    cg: CodeGraph;
    result: IndexResult_Ext;
}>;
/**
 * 3. openIndex
 *
 * Opens an existing CodeGraph index (does NOT re-index).
 *
 * @param repoPath  Absolute path to the repository.
 */
export declare function openIndex(repoPath: string): Promise<CodeGraph>;
/**
 * 4. getSymbols
 *
 * Returns all symbols (nodes) from the index, projected to OutputSymbol.
 * Uses getNodesByKind for each kind to avoid the internal-only getAllNodes().
 */
export declare function getSymbols(cg: CodeGraph): Promise<OutputSymbol[]>;
/**
 * 5. getRelationships
 *
 * Returns all directed edges as Relationship objects.
 * Iterates nodes and collects outgoing edges, deduplicating by
 * source+target+kind identity.
 */
export declare function getRelationships(cg: CodeGraph): Promise<Relationship[]>;
/**
 * 6. getCallGraph
 *
 * Returns simplified caller→callee pairs from all "calls" edges.
 */
export declare function getCallGraph(cg: CodeGraph): Promise<CallEdge[]>;
/**
 * 7. getTypeHierarchy
 *
 * Returns type hierarchy edges (extends / implements only).
 */
export declare function getTypeHierarchy(cg: CodeGraph): Promise<TypeEdge[]>;
/**
 * 8. getImpactRadius
 *
 * Computes transitive impact radius for a set of symbol qualified names.
 * Enforces depth max 10.
 *
 * @param cg       CodeGraph instance.
 * @param symbols  Qualified names of the symbols to analyse.
 * @param depth    Traversal depth (1-10). Clamped to 10.
 */
export declare function getImpactRadius(cg: CodeGraph, symbols: string[], depth: number): Promise<ImpactEntry[]>;
/**
 * 9. getPublicSymbols
 *
 * Returns symbols visible outside their module (public or is_exported=true).
 */
export declare function getPublicSymbols(cg: CodeGraph): Promise<OutputSymbol[]>;
/**
 * 10. getIndexStats
 *
 * Computes IndexStats from an IndexResult_Ext.
 *
 * - extraction_success_rate = filesIndexed / (filesIndexed + filesErrored) * 100
 * - index_state = "degraded" when success rate < 50%, "ready" otherwise
 */
export declare function getIndexStats(result: IndexResult_Ext): IndexStats;
/**
 * 11. getExtractionSummary
 *
 * Aggregates per-language counts from IndexResult.
 */
export declare function getExtractionSummary(result: IndexResult_Ext): ExtractionSummary;
/**
 * 12. closeIndex
 *
 * Closes the CodeGraph instance, releasing the SQLite connection.
 */
export declare function closeIndex(cg: CodeGraph): Promise<void>;
//# sourceMappingURL=codegraph-adapter.d.ts.map