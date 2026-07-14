/**
 * Integration Types: CodeGraph Bridge
 *
 * TypeScript interfaces for codegraph-analysis.json output schema v1.0.0.
 * These types represent the JSON output of the bridge consumed by echelon's
 * re-* LLM command templates. Each field maps field-for-field to contracts/analysis-schema.json.
 */
/**
 * Symbol kind — maps to NodeKind enum in CodeGraph's internal type system.
 */
export type SymbolKind = 'file' | 'module' | 'class' | 'struct' | 'interface' | 'trait' | 'protocol' | 'function' | 'method' | 'property' | 'field' | 'variable' | 'constant' | 'enum' | 'enum_member' | 'type_alias' | 'namespace' | 'parameter' | 'import' | 'export' | 'route' | 'component';
/**
 * Visibility modifier for a symbol.
 */
export type VisibilityKind = 'public' | 'private' | 'protected' | 'internal';
/**
 * A code symbol extracted from a source file.
 * Projected from CodeGraph's internal Node type with fields relevant to LLM consumption.
 */
export interface OutputSymbol {
    /** Fully-qualified symbol identifier (e.g., src/utils.ts::MathHelper.calculateTotal) */
    readonly qualified_name: string;
    /** Simple name (e.g., calculateTotal) */
    readonly name: string;
    /** Symbol kind */
    readonly kind: SymbolKind;
    /** Source file path relative to repo_path */
    readonly file_path: string;
    /** Starting line number (1-indexed) */
    readonly line_start: number;
    /** Ending line number (1-indexed) */
    readonly line_end: number;
    /** Access modifier */
    readonly visibility?: VisibilityKind;
    /** Whether symbol is exported from its module */
    readonly is_exported?: boolean;
    /** Function/method signature */
    readonly signature?: string;
    /** Programming language */
    readonly language?: string;
}
/**
 * Relationship kind — subset of EdgeKind from CodeGraph's internal type system.
 */
export type RelationshipKind = 'calls' | 'imports' | 'exports' | 'extends' | 'implements' | 'contains' | 'references' | 'overrides';
/**
 * A directed relationship (edge) between two symbols.
 */
export interface Relationship {
    /** Source symbol qualified name */
    readonly source: string;
    /** Target symbol qualified name */
    readonly target: string;
    /** Relationship type */
    readonly kind: RelationshipKind;
    /** File where relationship was detected (relative to repo_path) */
    readonly file_path?: string;
}
/**
 * Simplified caller-callee pair for call graph representation.
 */
export interface CallEdge {
    /** Calling symbol qualified name */
    readonly caller: string;
    /** Called symbol qualified name */
    readonly callee: string;
}
/**
 * Type hierarchy kind (inheritance or implementation).
 */
export type TypeEdgeKind = 'extends' | 'implements';
/**
 * Type hierarchy relationship (inheritance or implementation).
 */
export interface TypeEdge {
    /** Subclass or implementor qualified name */
    readonly child: string;
    /** Superclass or interface qualified name */
    readonly parent: string;
    /** Hierarchy type */
    readonly kind: TypeEdgeKind;
}
/**
 * Impact radius for a symbol — the set of symbols transitively dependent on it.
 */
export interface ImpactEntry {
    /** Source symbol qualified name */
    readonly symbol: string;
    /** Transitively dependent symbol qualified names */
    readonly affected: readonly string[];
    /** Traversal depth used (1-10) */
    readonly depth: number;
}
/**
 * Symbol-level coverage metrics.
 */
export interface CoverageReport {
    /** Count of all public symbols */
    readonly total_symbols: number;
    /** Count of symbols referenced in specifications */
    readonly documented_symbols: number;
    /** Coverage percentage (0.0–100.0) */
    readonly coverage_percent: number;
}
/**
 * Index state after build.
 */
export type IndexState = 'ready' | 'degraded';
/**
 * Build performance and completeness metrics.
 */
export interface IndexStats {
    /** Total files scanned */
    readonly total_files: number;
    /** Files in supported languages */
    readonly supported_files: number;
    /** Files in unsupported languages */
    readonly unsupported_files: number;
    /** Files that failed extraction */
    readonly failed_files: number;
    /** Total symbols extracted */
    readonly total_nodes: number;
    /** Total relationships extracted */
    readonly total_edges: number;
    /** Time to build index in milliseconds */
    readonly build_time_ms: number;
    /** Percentage of files successfully extracted (0.0–100.0) */
    readonly extraction_success_rate: number;
    /** "degraded" when success rate < 50% */
    readonly index_state: IndexState;
}
/**
 * Per-language file count entry.
 */
export interface LanguageEntry {
    /** Language name */
    readonly language: string;
    /** Number of files in this language */
    readonly file_count: number;
    /** Whether extraction was attempted */
    readonly status: 'supported' | 'unsupported';
}
/**
 * Per-language breakdown of extraction results.
 */
export interface ExtractionSummary {
    /** Per-language counts */
    readonly languages: readonly LanguageEntry[];
    /** Files successfully extracted */
    readonly total_extracted: number;
    /** Files skipped (unsupported language) */
    readonly total_skipped_unsupported: number;
    /** Files skipped (parse error) */
    readonly total_skipped_error: number;
    /** List of unsupported language names encountered */
    readonly unsupported_languages: readonly string[];
}
/**
 * Language coverage status for a file extension.
 */
export type LanguageSupportStatus = 'supported' | 'unsupported';
/**
 * Map of file extension to support status.
 */
export type LanguageCoverageMap = Record<string, LanguageSupportStatus>;
/**
 * The primary integration artifact: codegraph-analysis.json.
 * Produced by the bridge during re-analyze, consumed by echelon re-* LLM command templates.
 */
export interface AnalysisOutput {
    /** Schema version (semver, e.g., "1.0.0") */
    readonly version: string;
    /** ISO-8601 timestamp of when analysis was produced */
    readonly generated_at: string;
    /** Absolute path to the analyzed repository */
    readonly repo_path: string;
    /** Whether any supported-language source files were found */
    readonly supported: boolean;
    /** Map of file extension to support status */
    readonly language_coverage: LanguageCoverageMap;
    /** Extracted code symbols (max 10,000) */
    readonly symbols: readonly OutputSymbol[];
    /** Directed edges between symbols */
    readonly relationships: readonly Relationship[];
    /** Simplified caller-callee pairs */
    readonly call_graph: readonly CallEdge[];
    /** Inheritance and implementation relationships */
    readonly type_hierarchy: readonly TypeEdge[];
    /** Per-symbol transitive dependency sets */
    readonly impact_radius: readonly ImpactEntry[];
    /** Symbol coverage metrics */
    readonly coverage: CoverageReport;
    /** Build performance and completeness metrics */
    readonly index_stats: IndexStats;
    /** Per-language extraction breakdown */
    readonly extraction_summary: ExtractionSummary;
}
//# sourceMappingURL=integration-types.d.ts.map