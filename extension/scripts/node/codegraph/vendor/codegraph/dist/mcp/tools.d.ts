/**
 * MCP Tool Definitions
 *
 * Defines the tools exposed by the CodeGraph MCP server.
 */
import CodeGraph from '../index';
/**
 * Calculate the recommended number of codegraph_explore calls based on project size.
 * Larger codebases need more exploration calls to cover their surface area,
 * but smaller ones should use fewer to avoid unnecessary overhead.
 */
export declare function getExploreBudget(fileCount: number): number;
/**
 * MCP Tool definition
 */
export interface ToolDefinition {
    name: string;
    description: string;
    inputSchema: {
        type: 'object';
        properties: Record<string, PropertySchema>;
        required?: string[];
    };
}
interface PropertySchema {
    type: string;
    description: string;
    enum?: string[];
    default?: unknown;
}
/**
 * Tool execution result
 */
export interface ToolResult {
    content: Array<{
        type: 'text';
        text: string;
    }>;
    isError?: boolean;
}
/**
 * All CodeGraph MCP tools
 *
 * Designed for minimal context usage - use codegraph_context as the primary tool,
 * and only use other tools for targeted follow-up queries.
 *
 * All tools support cross-project queries via the optional `projectPath` parameter.
 */
export declare const tools: ToolDefinition[];
/**
 * Tool handler that executes tools against a CodeGraph instance
 *
 * Supports cross-project queries via the projectPath parameter.
 * Other projects are opened on-demand and cached for performance.
 */
export declare class ToolHandler {
    private cg;
    private projectCache;
    constructor(cg: CodeGraph | null);
    /**
     * Update the default CodeGraph instance (e.g. after lazy initialization)
     */
    setDefaultCodeGraph(cg: CodeGraph): void;
    /**
     * Whether a default CodeGraph instance is available
     */
    hasDefaultCodeGraph(): boolean;
    /**
     * Get tool definitions with dynamic descriptions based on project size.
     * The codegraph_explore tool description includes a budget recommendation
     * scaled to the number of indexed files.
     */
    getTools(): ToolDefinition[];
    /**
     * Get CodeGraph instance for a project
     *
     * If projectPath is provided, opens that project's CodeGraph (cached).
     * Otherwise returns the default CodeGraph instance.
     *
     * Walks up parent directories to find the nearest .codegraph/ folder,
     * similar to how git finds .git/ directories.
     */
    private getCodeGraph;
    /**
     * Close all cached project connections
     */
    closeAll(): void;
    /**
     * Validate that a value is a non-empty string
     */
    private validateString;
    /**
     * Execute a tool by name
     */
    execute(toolName: string, args: Record<string, unknown>): Promise<ToolResult>;
    /**
     * Handle codegraph_search
     */
    private handleSearch;
    /**
     * Handle codegraph_context
     */
    private handleContext;
    /**
     * Heuristic to detect if a query looks like a feature request
     */
    private looksLikeFeatureRequest;
    /**
     * Handle codegraph_callers
     */
    private handleCallers;
    /**
     * Handle codegraph_callees
     */
    private handleCallees;
    /**
     * Handle codegraph_impact
     */
    private handleImpact;
    /** Maximum output for explore tool — sized to stay under MCP client token limits (~10k tokens) */
    private static readonly EXPLORE_MAX_OUTPUT;
    /**
     * Handle codegraph_explore — deep exploration in a single call
     *
     * Strategy: find relevant symbols via graph traversal, group by file,
     * then read contiguous file sections covering all symbols per file.
     * This replaces multiple codegraph_node + Read calls.
     */
    private handleExplore;
    /**
     * Handle codegraph_node
     */
    private handleNode;
    /**
     * Handle codegraph_status
     */
    private handleStatus;
    /**
     * Handle codegraph_files - get project file structure from the index
     */
    private handleFiles;
    /**
     * Convert glob pattern to regex
     */
    private globToRegex;
    /**
     * Format files as a flat list
     */
    private formatFilesFlat;
    /**
     * Format files grouped by language
     */
    private formatFilesGrouped;
    /**
     * Format files as a tree structure
     */
    private formatFilesTree;
    /**
     * Find a symbol by name, handling disambiguation when multiple matches exist.
     * Returns the best match and a note about alternatives if any.
     */
    /**
     * Check if a node matches a symbol query, supporting both simple names and
     * qualified "Parent.child" notation (e.g., "Session.request" matches a method
     * named "request" inside a class named "Session").
     */
    private matchesSymbol;
    private findSymbol;
    /**
     * Find ALL symbols matching a name. Used by callers/callees/impact to aggregate
     * results across all matching symbols (e.g., multiple classes with an `execute` method).
     */
    private findAllSymbols;
    /**
     * Truncate output if it exceeds the maximum length
     */
    private truncateOutput;
    private formatSearchResults;
    private formatNodeList;
    private formatImpact;
    private formatNodeDetails;
    private formatTaskContext;
    private textResult;
    private errorResult;
}
export {};
//# sourceMappingURL=tools.d.ts.map