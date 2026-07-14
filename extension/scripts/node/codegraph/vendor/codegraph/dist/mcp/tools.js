"use strict";
/**
 * MCP Tool Definitions
 *
 * Defines the tools exposed by the CodeGraph MCP server.
 */
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.ToolHandler = exports.tools = void 0;
exports.getExploreBudget = getExploreBudget;
const index_1 = __importStar(require("../index"));
const crypto_1 = require("crypto");
const fs_1 = require("fs");
const utils_1 = require("../utils");
const os_1 = require("os");
const path_1 = require("path");
/** Maximum output length to prevent context bloat (characters) */
const MAX_OUTPUT_LENGTH = 15000;
/**
 * Calculate the recommended number of codegraph_explore calls based on project size.
 * Larger codebases need more exploration calls to cover their surface area,
 * but smaller ones should use fewer to avoid unnecessary overhead.
 */
function getExploreBudget(fileCount) {
    if (fileCount < 500)
        return 1;
    if (fileCount < 5000)
        return 2;
    if (fileCount < 15000)
        return 3;
    if (fileCount < 25000)
        return 4;
    return 5;
}
/**
 * Mark a Claude session as having consulted MCP tools.
 * This enables Grep/Glob/Bash commands that would otherwise be blocked.
 */
function markSessionConsulted(sessionId) {
    try {
        const hash = (0, crypto_1.createHash)('md5').update(sessionId).digest('hex').slice(0, 16);
        const markerPath = (0, path_1.join)((0, os_1.tmpdir)(), `codegraph-consulted-${hash}`);
        (0, fs_1.writeFileSync)(markerPath, new Date().toISOString(), 'utf8');
    }
    catch {
        // Silently fail - don't break MCP on marker write failure
    }
}
/**
 * Common projectPath property for cross-project queries
 */
const projectPathProperty = {
    type: 'string',
    description: 'Path to a different project with .codegraph/ initialized. If omitted, uses current project. Use this to query other codebases.',
};
/**
 * All CodeGraph MCP tools
 *
 * Designed for minimal context usage - use codegraph_context as the primary tool,
 * and only use other tools for targeted follow-up queries.
 *
 * All tools support cross-project queries via the optional `projectPath` parameter.
 */
exports.tools = [
    {
        name: 'codegraph_search',
        description: 'Quick symbol search by name. Returns locations only (no code). Use codegraph_context instead for comprehensive task context.',
        inputSchema: {
            type: 'object',
            properties: {
                query: {
                    type: 'string',
                    description: 'Symbol name or partial name (e.g., "auth", "signIn", "UserService")',
                },
                kind: {
                    type: 'string',
                    description: 'Filter by node kind',
                    enum: ['function', 'method', 'class', 'interface', 'type', 'variable', 'route', 'component'],
                },
                limit: {
                    type: 'number',
                    description: 'Maximum results (default: 10)',
                    default: 10,
                },
                projectPath: projectPathProperty,
            },
            required: ['query'],
        },
    },
    {
        name: 'codegraph_context',
        description: 'PRIMARY TOOL: Build comprehensive context for a task. Returns entry points, related symbols, and key code - often enough to understand the codebase without additional tool calls. NOTE: This provides CODE context, not product requirements. For new features, still clarify UX/behavior questions with the user before implementing.',
        inputSchema: {
            type: 'object',
            properties: {
                task: {
                    type: 'string',
                    description: 'Description of the task, bug, or feature to build context for',
                },
                maxNodes: {
                    type: 'number',
                    description: 'Maximum symbols to include (default: 20)',
                    default: 20,
                },
                includeCode: {
                    type: 'boolean',
                    description: 'Include code snippets for key symbols (default: true)',
                    default: true,
                },
                projectPath: projectPathProperty,
            },
            required: ['task'],
        },
    },
    {
        name: 'codegraph_callers',
        description: 'Find all functions/methods that call a specific symbol. Useful for understanding usage patterns and impact of changes.',
        inputSchema: {
            type: 'object',
            properties: {
                symbol: {
                    type: 'string',
                    description: 'Name of the function, method, or class to find callers for',
                },
                limit: {
                    type: 'number',
                    description: 'Maximum number of callers to return (default: 20)',
                    default: 20,
                },
                projectPath: projectPathProperty,
            },
            required: ['symbol'],
        },
    },
    {
        name: 'codegraph_callees',
        description: 'Find all functions/methods that a specific symbol calls. Useful for understanding dependencies and code flow.',
        inputSchema: {
            type: 'object',
            properties: {
                symbol: {
                    type: 'string',
                    description: 'Name of the function, method, or class to find callees for',
                },
                limit: {
                    type: 'number',
                    description: 'Maximum number of callees to return (default: 20)',
                    default: 20,
                },
                projectPath: projectPathProperty,
            },
            required: ['symbol'],
        },
    },
    {
        name: 'codegraph_impact',
        description: 'Analyze the impact radius of changing a symbol. Shows what code could be affected by modifications.',
        inputSchema: {
            type: 'object',
            properties: {
                symbol: {
                    type: 'string',
                    description: 'Name of the symbol to analyze impact for',
                },
                depth: {
                    type: 'number',
                    description: 'How many levels of dependencies to traverse (default: 2)',
                    default: 2,
                },
                projectPath: projectPathProperty,
            },
            required: ['symbol'],
        },
    },
    {
        name: 'codegraph_node',
        description: 'Get detailed information about a specific code symbol. Use includeCode=true only when you need the full source code - otherwise just get location and signature to minimize context usage.',
        inputSchema: {
            type: 'object',
            properties: {
                symbol: {
                    type: 'string',
                    description: 'Name of the symbol to get details for',
                },
                includeCode: {
                    type: 'boolean',
                    description: 'Include full source code (default: false to minimize context)',
                    default: false,
                },
                projectPath: projectPathProperty,
            },
            required: ['symbol'],
        },
    },
    {
        name: 'codegraph_explore',
        description: 'Deep exploration tool — returns comprehensive context for a topic in a SINGLE call. Groups all relevant source code by file (contiguous sections, not snippets), includes a relationship map, and uses deeper graph traversal. Designed to replace multiple codegraph_node + file Read calls. Use this instead of codegraph_context when you need thorough understanding. IMPORTANT: Use specific symbol names, file names, or short code terms in your query — NOT natural language sentences. Before calling this, use codegraph_search to discover relevant symbol names, then include those names in your query. Bad: "how are agent prompts loaded and passed to the CLI". Good: "readAgentsFromDirectory createClaudeSession chat-manager agents.ts".',
        inputSchema: {
            type: 'object',
            properties: {
                query: {
                    type: 'string',
                    description: 'Symbol names, file names, or short code terms to explore (e.g., "AuthService loginUser session-manager", "GraphTraverser BFS impact traversal.ts"). Use codegraph_search first to find relevant names.',
                },
                maxFiles: {
                    type: 'number',
                    description: 'Maximum number of files to include source code from (default: 12)',
                    default: 12,
                },
                projectPath: projectPathProperty,
            },
            required: ['query'],
        },
    },
    {
        name: 'codegraph_status',
        description: 'Get the status of the CodeGraph index, including statistics about indexed files, nodes, and edges.',
        inputSchema: {
            type: 'object',
            properties: {
                projectPath: projectPathProperty,
            },
        },
    },
    {
        name: 'codegraph_files',
        description: 'REQUIRED for file/folder exploration. Get the project file structure from the CodeGraph index. Returns a tree view of all indexed files with metadata (language, symbol count). Much faster than Glob/filesystem scanning. Use this FIRST when exploring project structure, finding files, or understanding codebase organization.',
        inputSchema: {
            type: 'object',
            properties: {
                path: {
                    type: 'string',
                    description: 'Filter to files under this directory path (e.g., "src/components"). Returns all files if not specified.',
                },
                pattern: {
                    type: 'string',
                    description: 'Filter files matching this glob pattern (e.g., "*.tsx", "**/*.test.ts")',
                },
                format: {
                    type: 'string',
                    description: 'Output format: "tree" (hierarchical, default), "flat" (simple list), "grouped" (by language)',
                    enum: ['tree', 'flat', 'grouped'],
                    default: 'tree',
                },
                includeMetadata: {
                    type: 'boolean',
                    description: 'Include file metadata like language and symbol count (default: true)',
                    default: true,
                },
                maxDepth: {
                    type: 'number',
                    description: 'Maximum directory depth to show (default: unlimited)',
                },
                projectPath: projectPathProperty,
            },
        },
    },
];
/**
 * Tool handler that executes tools against a CodeGraph instance
 *
 * Supports cross-project queries via the projectPath parameter.
 * Other projects are opened on-demand and cached for performance.
 */
class ToolHandler {
    cg;
    // Cache of opened CodeGraph instances for cross-project queries
    projectCache = new Map();
    constructor(cg) {
        this.cg = cg;
    }
    /**
     * Update the default CodeGraph instance (e.g. after lazy initialization)
     */
    setDefaultCodeGraph(cg) {
        this.cg = cg;
    }
    /**
     * Whether a default CodeGraph instance is available
     */
    hasDefaultCodeGraph() {
        return this.cg !== null;
    }
    /**
     * Get tool definitions with dynamic descriptions based on project size.
     * The codegraph_explore tool description includes a budget recommendation
     * scaled to the number of indexed files.
     */
    getTools() {
        if (!this.cg)
            return exports.tools;
        try {
            const stats = this.cg.getStats();
            const budget = getExploreBudget(stats.fileCount);
            return exports.tools.map(tool => {
                if (tool.name === 'codegraph_explore') {
                    return {
                        ...tool,
                        description: `${tool.description} Budget: make at most ${budget} calls for this project (${stats.fileCount.toLocaleString()} files indexed).`,
                    };
                }
                return tool;
            });
        }
        catch {
            return exports.tools;
        }
    }
    /**
     * Get CodeGraph instance for a project
     *
     * If projectPath is provided, opens that project's CodeGraph (cached).
     * Otherwise returns the default CodeGraph instance.
     *
     * Walks up parent directories to find the nearest .codegraph/ folder,
     * similar to how git finds .git/ directories.
     */
    getCodeGraph(projectPath) {
        if (!projectPath) {
            if (!this.cg) {
                throw new Error('CodeGraph not initialized for this project. Run \'codegraph init\' first.');
            }
            return this.cg;
        }
        // Check cache first (using original path as key)
        if (this.projectCache.has(projectPath)) {
            return this.projectCache.get(projectPath);
        }
        // Walk up parent directories to find nearest .codegraph/
        const resolvedRoot = (0, index_1.findNearestCodeGraphRoot)(projectPath);
        if (!resolvedRoot) {
            throw new Error(`CodeGraph not initialized in ${projectPath}. Run 'codegraph init' in that project first.`);
        }
        // Check if we already have this resolved root cached (different path, same project)
        if (this.projectCache.has(resolvedRoot)) {
            const cg = this.projectCache.get(resolvedRoot);
            // Cache under original path too for faster future lookups
            this.projectCache.set(projectPath, cg);
            return cg;
        }
        // Open and cache under both paths
        const cg = index_1.default.openSync(resolvedRoot);
        this.projectCache.set(resolvedRoot, cg);
        if (projectPath !== resolvedRoot) {
            this.projectCache.set(projectPath, cg);
        }
        return cg;
    }
    /**
     * Close all cached project connections
     */
    closeAll() {
        for (const cg of this.projectCache.values()) {
            cg.close();
        }
        this.projectCache.clear();
    }
    /**
     * Validate that a value is a non-empty string
     */
    validateString(value, name) {
        if (typeof value !== 'string' || value.length === 0) {
            return this.errorResult(`${name} must be a non-empty string`);
        }
        return value;
    }
    /**
     * Execute a tool by name
     */
    async execute(toolName, args) {
        try {
            switch (toolName) {
                case 'codegraph_search':
                    return await this.handleSearch(args);
                case 'codegraph_context':
                    return await this.handleContext(args);
                case 'codegraph_callers':
                    return await this.handleCallers(args);
                case 'codegraph_callees':
                    return await this.handleCallees(args);
                case 'codegraph_impact':
                    return await this.handleImpact(args);
                case 'codegraph_explore':
                    return await this.handleExplore(args);
                case 'codegraph_node':
                    return await this.handleNode(args);
                case 'codegraph_status':
                    return await this.handleStatus(args);
                case 'codegraph_files':
                    return await this.handleFiles(args);
                default:
                    return this.errorResult(`Unknown tool: ${toolName}`);
            }
        }
        catch (err) {
            return this.errorResult(`Tool execution failed: ${err instanceof Error ? err.message : String(err)}`);
        }
    }
    /**
     * Handle codegraph_search
     */
    async handleSearch(args) {
        const query = this.validateString(args.query, 'query');
        if (typeof query !== 'string')
            return query;
        const cg = this.getCodeGraph(args.projectPath);
        const kind = args.kind;
        const rawLimit = Number(args.limit) || 10;
        const limit = (0, utils_1.clamp)(rawLimit, 1, 100);
        const results = cg.searchNodes(query, {
            limit,
            kinds: kind ? [kind] : undefined,
        });
        if (results.length === 0) {
            return this.textResult(`No results found for "${query}"`);
        }
        const formatted = this.formatSearchResults(results);
        return this.textResult(this.truncateOutput(formatted));
    }
    /**
     * Handle codegraph_context
     */
    async handleContext(args) {
        const task = this.validateString(args.task, 'task');
        if (typeof task !== 'string')
            return task;
        // Mark session as consulted (enables Grep/Glob/Bash)
        const sessionId = process.env.CLAUDE_SESSION_ID;
        if (sessionId) {
            markSessionConsulted(sessionId);
        }
        const cg = this.getCodeGraph(args.projectPath);
        const maxNodes = args.maxNodes || 20;
        const includeCode = args.includeCode !== false;
        const context = await cg.buildContext(task, {
            maxNodes,
            includeCode,
            format: 'markdown',
        });
        // Detect if this looks like a feature request (vs bug fix or exploration)
        const isFeatureQuery = this.looksLikeFeatureRequest(task);
        const reminder = isFeatureQuery
            ? '\n\n⚠️ **Ask user:** UX preferences, edge cases, acceptance criteria'
            : '';
        // buildContext returns string when format is 'markdown'
        if (typeof context === 'string') {
            return this.textResult(context + reminder);
        }
        // If it returns TaskContext, format it
        return this.textResult(this.formatTaskContext(context) + reminder);
    }
    /**
     * Heuristic to detect if a query looks like a feature request
     */
    looksLikeFeatureRequest(task) {
        const featureKeywords = [
            'add', 'create', 'implement', 'build', 'enable', 'allow',
            'new feature', 'support for', 'ability to', 'want to',
            'should be able', 'need to add', 'swap', 'edit', 'modify'
        ];
        const bugKeywords = [
            'fix', 'bug', 'error', 'broken', 'crash', 'issue', 'problem',
            'not working', 'fails', 'undefined', 'null'
        ];
        const explorationKeywords = [
            'how does', 'where is', 'what is', 'find', 'show me',
            'explain', 'understand', 'explore'
        ];
        const lowerTask = task.toLowerCase();
        // If it's clearly a bug or exploration, not a feature
        if (bugKeywords.some(k => lowerTask.includes(k)))
            return false;
        if (explorationKeywords.some(k => lowerTask.includes(k)))
            return false;
        // If it matches feature keywords, it's likely a feature request
        return featureKeywords.some(k => lowerTask.includes(k));
    }
    /**
     * Handle codegraph_callers
     */
    async handleCallers(args) {
        const symbol = this.validateString(args.symbol, 'symbol');
        if (typeof symbol !== 'string')
            return symbol;
        const cg = this.getCodeGraph(args.projectPath);
        const limit = (0, utils_1.clamp)(args.limit || 20, 1, 100);
        const allMatches = this.findAllSymbols(cg, symbol);
        if (allMatches.nodes.length === 0) {
            return this.textResult(`Symbol "${symbol}" not found in the codebase`);
        }
        // Aggregate callers across all matching symbols
        const seen = new Set();
        const allCallers = [];
        for (const node of allMatches.nodes) {
            for (const c of cg.getCallers(node.id)) {
                if (!seen.has(c.node.id)) {
                    seen.add(c.node.id);
                    allCallers.push(c.node);
                }
            }
        }
        if (allCallers.length === 0) {
            return this.textResult(`No callers found for "${symbol}"${allMatches.note}`);
        }
        const formatted = this.formatNodeList(allCallers.slice(0, limit), `Callers of ${symbol}`) + allMatches.note;
        return this.textResult(this.truncateOutput(formatted));
    }
    /**
     * Handle codegraph_callees
     */
    async handleCallees(args) {
        const symbol = this.validateString(args.symbol, 'symbol');
        if (typeof symbol !== 'string')
            return symbol;
        const cg = this.getCodeGraph(args.projectPath);
        const limit = (0, utils_1.clamp)(args.limit || 20, 1, 100);
        const allMatches = this.findAllSymbols(cg, symbol);
        if (allMatches.nodes.length === 0) {
            return this.textResult(`Symbol "${symbol}" not found in the codebase`);
        }
        // Aggregate callees across all matching symbols
        const seen = new Set();
        const allCallees = [];
        for (const node of allMatches.nodes) {
            for (const c of cg.getCallees(node.id)) {
                if (!seen.has(c.node.id)) {
                    seen.add(c.node.id);
                    allCallees.push(c.node);
                }
            }
        }
        if (allCallees.length === 0) {
            return this.textResult(`No callees found for "${symbol}"${allMatches.note}`);
        }
        const formatted = this.formatNodeList(allCallees.slice(0, limit), `Callees of ${symbol}`) + allMatches.note;
        return this.textResult(this.truncateOutput(formatted));
    }
    /**
     * Handle codegraph_impact
     */
    async handleImpact(args) {
        const symbol = this.validateString(args.symbol, 'symbol');
        if (typeof symbol !== 'string')
            return symbol;
        const cg = this.getCodeGraph(args.projectPath);
        const depth = (0, utils_1.clamp)(args.depth || 2, 1, 10);
        const allMatches = this.findAllSymbols(cg, symbol);
        if (allMatches.nodes.length === 0) {
            return this.textResult(`Symbol "${symbol}" not found in the codebase`);
        }
        // Aggregate impact across all matching symbols
        const mergedNodes = new Map();
        const mergedEdges = [];
        const seenEdges = new Set();
        for (const node of allMatches.nodes) {
            const impact = cg.getImpactRadius(node.id, depth);
            for (const [id, n] of impact.nodes) {
                mergedNodes.set(id, n);
            }
            for (const e of impact.edges) {
                const key = `${e.source}->${e.target}:${e.kind}`;
                if (!seenEdges.has(key)) {
                    seenEdges.add(key);
                    mergedEdges.push(e);
                }
            }
        }
        const mergedImpact = {
            nodes: mergedNodes,
            edges: mergedEdges,
            roots: allMatches.nodes.map(n => n.id),
        };
        const formatted = this.formatImpact(symbol, mergedImpact) + allMatches.note;
        return this.textResult(this.truncateOutput(formatted));
    }
    /** Maximum output for explore tool — sized to stay under MCP client token limits (~10k tokens) */
    static EXPLORE_MAX_OUTPUT = 35000;
    /**
     * Handle codegraph_explore — deep exploration in a single call
     *
     * Strategy: find relevant symbols via graph traversal, group by file,
     * then read contiguous file sections covering all symbols per file.
     * This replaces multiple codegraph_node + Read calls.
     */
    async handleExplore(args) {
        const query = this.validateString(args.query, 'query');
        if (typeof query !== 'string')
            return query;
        const cg = this.getCodeGraph(args.projectPath);
        const maxFiles = (0, utils_1.clamp)(args.maxFiles || 12, 1, 20);
        const projectRoot = cg.getProjectRoot();
        // Step 1: Find relevant context with generous parameters.
        // Use a large maxNodes budget — explore has its own 35k char output limit
        // that prevents context bloat, so more nodes just means better coverage
        // across entry points (especially for large files like Svelte components).
        const subgraph = await cg.findRelevantContext(query, {
            searchLimit: 8,
            traversalDepth: 3,
            maxNodes: 200,
            minScore: 0.2,
        });
        if (subgraph.nodes.size === 0) {
            return this.textResult(`No relevant code found for "${query}"`);
        }
        // Step 2: Group nodes by file, score by relevance
        const fileGroups = new Map();
        const entryNodeIds = new Set(subgraph.roots);
        // Build a set of nodes directly connected to entry points (depth 1)
        const connectedToEntry = new Set();
        for (const edge of subgraph.edges) {
            if (entryNodeIds.has(edge.source))
                connectedToEntry.add(edge.target);
            if (entryNodeIds.has(edge.target))
                connectedToEntry.add(edge.source);
        }
        for (const node of subgraph.nodes.values()) {
            // Skip import/export nodes — they add noise without information
            if (node.kind === 'import' || node.kind === 'export')
                continue;
            const group = fileGroups.get(node.filePath) || { nodes: [], score: 0 };
            group.nodes.push(node);
            // Score: entry point nodes worth 10, directly connected worth 3, others worth 1
            if (entryNodeIds.has(node.id)) {
                group.score += 10;
            }
            else if (connectedToEntry.has(node.id)) {
                group.score += 3;
            }
            else {
                group.score += 1;
            }
            fileGroups.set(node.filePath, group);
        }
        // Only include files that have entry points or nodes directly connected to entry points
        const relevantFiles = [...fileGroups.entries()].filter(([, group]) => group.score >= 3);
        // Extract query terms for relevance checking
        const queryTerms = query.toLowerCase().split(/\s+/).filter(t => t.length >= 3);
        // Sort files: highest relevance first, deprioritize low-value files
        const sortedFiles = relevantFiles.sort((a, b) => {
            const aPath = a[0].toLowerCase();
            const bPath = b[0].toLowerCase();
            // Check if any node name or file path relates to query terms
            const hasQueryRelevance = (filePath, nodes) => {
                const fp = filePath.toLowerCase();
                if (queryTerms.some(t => fp.includes(t)))
                    return true;
                return nodes.some(n => queryTerms.some(t => n.name.toLowerCase().includes(t)));
            };
            const aRelevant = hasQueryRelevance(aPath, a[1].nodes);
            const bRelevant = hasQueryRelevance(bPath, b[1].nodes);
            if (aRelevant !== bRelevant)
                return aRelevant ? -1 : 1;
            // Deprioritize test files, icon files, and i18n files
            const isLowValue = (p) => /\/(tests?|__tests?__|spec)\//i.test(p) ||
                /\bicons?\b/i.test(p) ||
                /\bi18n\b/i.test(p);
            const aLow = isLowValue(aPath);
            const bLow = isLowValue(bPath);
            if (aLow !== bLow)
                return aLow ? 1 : -1;
            if (a[1].score !== b[1].score)
                return b[1].score - a[1].score;
            return b[1].nodes.length - a[1].nodes.length;
        });
        // Step 3: Build relationship map
        const lines = [
            `## Exploration: ${query}`,
            '',
            `Found ${subgraph.nodes.size} symbols across ${fileGroups.size} files.`,
            '',
        ];
        // Relationship map — show how symbols connect
        const significantEdges = subgraph.edges.filter(e => e.kind !== 'contains' // skip contains — it's implied by file grouping
        );
        if (significantEdges.length > 0) {
            lines.push('### Relationships');
            lines.push('');
            // Group edges by kind for readability
            const byKind = new Map();
            for (const edge of significantEdges) {
                const sourceNode = subgraph.nodes.get(edge.source);
                const targetNode = subgraph.nodes.get(edge.target);
                if (!sourceNode || !targetNode)
                    continue;
                const group = byKind.get(edge.kind) || [];
                group.push({ source: sourceNode.name, target: targetNode.name });
                byKind.set(edge.kind, group);
            }
            for (const [kind, edges] of byKind) {
                // Show up to 15 relationships per kind
                const shown = edges.slice(0, 15);
                lines.push(`**${kind}:**`);
                for (const e of shown) {
                    lines.push(`- ${e.source} → ${e.target}`);
                }
                if (edges.length > 15) {
                    lines.push(`- ... and ${edges.length - 15} more`);
                }
                lines.push('');
            }
        }
        // Step 4: Read contiguous file sections
        lines.push('### Source Code');
        lines.push('');
        let totalChars = lines.join('\n').length;
        let filesIncluded = 0;
        for (const [filePath, group] of sortedFiles) {
            if (filesIncluded >= maxFiles)
                break;
            if (totalChars > ToolHandler.EXPLORE_MAX_OUTPUT * 0.9)
                break;
            const absPath = (0, utils_1.validatePathWithinRoot)(projectRoot, filePath);
            if (!absPath || !(0, fs_1.existsSync)(absPath))
                continue;
            let fileContent;
            try {
                fileContent = (0, fs_1.readFileSync)(absPath, 'utf-8');
            }
            catch {
                continue;
            }
            const fileLines = fileContent.split('\n');
            const lang = group.nodes[0]?.language || '';
            // Cluster nearby symbols to avoid reading huge gaps between distant symbols.
            // Sort by start line, then merge overlapping/adjacent ranges (within 15 lines).
            // Include both node ranges AND edge source locations so template sections
            // with component usages/calls are covered (not just script block symbols).
            const ranges = group.nodes
                .filter(n => n.startLine > 0 && n.endLine > 0)
                // Skip file/component nodes that span the entire file — they'd create one giant cluster
                .filter(n => !(n.kind === 'component' && n.startLine === 1 && n.endLine >= fileLines.length - 1))
                .map(n => ({ start: n.startLine, end: n.endLine, name: n.name, kind: n.kind }));
            // Add edge source locations in this file — captures template references
            // (component usages, event handlers) that aren't nodes themselves.
            // Query edges directly from the DB (not just the subgraph) because BFS
            // traversal may have pruned template reference targets due to node budget.
            const edgeLines = new Set(); // dedup by "line:name"
            for (const node of group.nodes) {
                const outgoing = cg.getOutgoingEdges(node.id);
                for (const edge of outgoing) {
                    if (!edge.line || edge.line <= 0 || edge.kind === 'contains')
                        continue;
                    const key = `${edge.line}:${edge.target}`;
                    if (edgeLines.has(key))
                        continue;
                    edgeLines.add(key);
                    // Look up target name from subgraph first, fall back to edge kind
                    const targetNode = subgraph.nodes.get(edge.target);
                    const targetName = targetNode?.name ?? edge.kind;
                    ranges.push({ start: edge.line, end: edge.line, name: targetName, kind: edge.kind });
                }
            }
            ranges.sort((a, b) => a.start - b.start);
            if (ranges.length === 0)
                continue;
            const GAP_THRESHOLD = 15; // merge sections within 15 lines of each other
            const clusters = [];
            let current = { start: ranges[0].start, end: ranges[0].end, symbols: [`${ranges[0].name}(${ranges[0].kind})`] };
            for (let i = 1; i < ranges.length; i++) {
                const r = ranges[i];
                if (r.start <= current.end + GAP_THRESHOLD) {
                    current.end = Math.max(current.end, r.end);
                    current.symbols.push(`${r.name}(${r.kind})`);
                }
                else {
                    clusters.push(current);
                    current = { start: r.start, end: r.end, symbols: [`${r.name}(${r.kind})`] };
                }
            }
            clusters.push(current);
            // Build file section output from clusters
            const contextPadding = 3;
            let fileSection = '';
            const allSymbols = [];
            for (const cluster of clusters) {
                const startIdx = Math.max(0, cluster.start - 1 - contextPadding);
                const endIdx = Math.min(fileLines.length, cluster.end + contextPadding);
                const section = fileLines.slice(startIdx, endIdx).join('\n');
                if (fileSection.length > 0) {
                    fileSection += '\n\n// ... (gap) ...\n\n';
                }
                fileSection += section;
                allSymbols.push(...cluster.symbols);
            }
            // Skip if this section would blow the output limit
            if (totalChars + fileSection.length + 200 > ToolHandler.EXPLORE_MAX_OUTPUT) {
                const budget = ToolHandler.EXPLORE_MAX_OUTPUT - totalChars - 200;
                if (budget < 500)
                    break;
                const trimmed = fileSection.slice(0, budget) + '\n// ... trimmed ...';
                lines.push(`#### ${filePath} — ${allSymbols.join(', ')}`);
                lines.push('');
                lines.push('```' + lang);
                lines.push(trimmed);
                lines.push('```');
                lines.push('');
                totalChars += trimmed.length + 200;
                filesIncluded++;
                break;
            }
            lines.push(`#### ${filePath} — ${allSymbols.join(', ')}`);
            lines.push('');
            lines.push('```' + lang);
            lines.push(fileSection);
            lines.push('```');
            lines.push('');
            totalChars += fileSection.length + 200;
            filesIncluded++;
        }
        // Add remaining files as references (from both relevant and peripheral files)
        const remainingRelevant = sortedFiles.slice(filesIncluded);
        const peripheralFiles = [...fileGroups.entries()]
            .filter(([, group]) => group.score < 3)
            .sort((a, b) => b[1].score - a[1].score);
        const remainingFiles = [...remainingRelevant, ...peripheralFiles];
        if (remainingFiles.length > 0) {
            lines.push('### Additional relevant files (not shown)');
            lines.push('');
            for (const [filePath, group] of remainingFiles.slice(0, 10)) {
                const symbols = group.nodes.map(n => `${n.name}:${n.startLine}`).join(', ');
                lines.push(`- ${filePath}: ${symbols}`);
            }
            if (remainingFiles.length > 10) {
                lines.push(`- ... and ${remainingFiles.length - 10} more files`);
            }
        }
        // Add completeness signal so agents know they don't need to re-read these files
        lines.push('');
        lines.push('---');
        lines.push(`> **Complete source code is included above for ${filesIncluded} files.** You do NOT need to re-read these files — the relevant sections are already shown in full. Only use Read/Grep for files listed under "Additional relevant files" if you need more detail.`);
        // Add explore budget note based on project size
        try {
            const stats = cg.getStats();
            const budget = getExploreBudget(stats.fileCount);
            lines.push('');
            lines.push(`> **Explore budget: ${budget} calls max for this project (${stats.fileCount.toLocaleString()} files indexed).** Stop exploring and synthesize your answer once you've used ${budget} calls — do NOT make additional explore calls beyond this budget.`);
        }
        catch {
            // Stats unavailable — skip budget note
        }
        return this.textResult(lines.join('\n'));
    }
    /**
     * Handle codegraph_node
     */
    async handleNode(args) {
        const symbol = this.validateString(args.symbol, 'symbol');
        if (typeof symbol !== 'string')
            return symbol;
        const cg = this.getCodeGraph(args.projectPath);
        // Default to false to minimize context usage
        const includeCode = args.includeCode === true;
        const match = this.findSymbol(cg, symbol);
        if (!match) {
            return this.textResult(`Symbol "${symbol}" not found in the codebase`);
        }
        let code = null;
        if (includeCode) {
            code = await cg.getCode(match.node.id);
        }
        const formatted = this.formatNodeDetails(match.node, code) + match.note;
        return this.textResult(this.truncateOutput(formatted));
    }
    /**
     * Handle codegraph_status
     */
    async handleStatus(args) {
        const cg = this.getCodeGraph(args.projectPath);
        const stats = cg.getStats();
        const lines = [
            '## CodeGraph Status',
            '',
            `**Files indexed:** ${stats.fileCount}`,
            `**Total nodes:** ${stats.nodeCount}`,
            `**Total edges:** ${stats.edgeCount}`,
            `**Database size:** ${(stats.dbSizeBytes / 1024 / 1024).toFixed(2)} MB`,
            '',
            '### Nodes by Kind:',
        ];
        for (const [kind, count] of Object.entries(stats.nodesByKind)) {
            if (count > 0) {
                lines.push(`- ${kind}: ${count}`);
            }
        }
        lines.push('', '### Languages:');
        for (const [lang, count] of Object.entries(stats.filesByLanguage)) {
            if (count > 0) {
                lines.push(`- ${lang}: ${count}`);
            }
        }
        return this.textResult(lines.join('\n'));
    }
    /**
     * Handle codegraph_files - get project file structure from the index
     */
    async handleFiles(args) {
        const cg = this.getCodeGraph(args.projectPath);
        const pathFilter = args.path;
        const pattern = args.pattern;
        const format = args.format || 'tree';
        const includeMetadata = args.includeMetadata !== false;
        const maxDepth = args.maxDepth != null ? (0, utils_1.clamp)(args.maxDepth, 1, 20) : undefined;
        // Get all files from the index
        const allFiles = cg.getFiles();
        if (allFiles.length === 0) {
            return this.textResult('No files indexed. Run `codegraph index` first.');
        }
        // Filter by path prefix
        let files = pathFilter
            ? allFiles.filter(f => f.path.startsWith(pathFilter) || f.path.startsWith('./' + pathFilter))
            : allFiles;
        // Filter by glob pattern
        if (pattern) {
            const regex = this.globToRegex(pattern);
            files = files.filter(f => regex.test(f.path));
        }
        if (files.length === 0) {
            return this.textResult(`No files found matching the criteria.`);
        }
        // Format output
        let output;
        switch (format) {
            case 'flat':
                output = this.formatFilesFlat(files, includeMetadata);
                break;
            case 'grouped':
                output = this.formatFilesGrouped(files, includeMetadata);
                break;
            case 'tree':
            default:
                output = this.formatFilesTree(files, includeMetadata, maxDepth);
                break;
        }
        return this.textResult(this.truncateOutput(output));
    }
    /**
     * Convert glob pattern to regex
     */
    globToRegex(pattern) {
        const escaped = pattern
            .replace(/[.+^${}()|[\]\\]/g, '\\$&') // Escape special regex chars except * and ?
            .replace(/\*\*/g, '{{GLOBSTAR}}') // Temp placeholder for **
            .replace(/\*/g, '[^/]*') // * matches anything except /
            .replace(/\?/g, '[^/]') // ? matches single char except /
            .replace(/\{\{GLOBSTAR\}\}/g, '.*'); // ** matches anything including /
        return new RegExp(escaped);
    }
    /**
     * Format files as a flat list
     */
    formatFilesFlat(files, includeMetadata) {
        const lines = [`## Files (${files.length})`, ''];
        for (const file of files.sort((a, b) => a.path.localeCompare(b.path))) {
            if (includeMetadata) {
                lines.push(`- ${file.path} (${file.language}, ${file.nodeCount} symbols)`);
            }
            else {
                lines.push(`- ${file.path}`);
            }
        }
        return lines.join('\n');
    }
    /**
     * Format files grouped by language
     */
    formatFilesGrouped(files, includeMetadata) {
        const byLang = new Map();
        for (const file of files) {
            const existing = byLang.get(file.language) || [];
            existing.push(file);
            byLang.set(file.language, existing);
        }
        const lines = [`## Files by Language (${files.length} total)`, ''];
        // Sort languages by file count (descending)
        const sortedLangs = [...byLang.entries()].sort((a, b) => b[1].length - a[1].length);
        for (const [lang, langFiles] of sortedLangs) {
            lines.push(`### ${lang} (${langFiles.length})`);
            for (const file of langFiles.sort((a, b) => a.path.localeCompare(b.path))) {
                if (includeMetadata) {
                    lines.push(`- ${file.path} (${file.nodeCount} symbols)`);
                }
                else {
                    lines.push(`- ${file.path}`);
                }
            }
            lines.push('');
        }
        return lines.join('\n');
    }
    /**
     * Format files as a tree structure
     */
    formatFilesTree(files, includeMetadata, maxDepth) {
        const root = { name: '', children: new Map() };
        for (const file of files) {
            const parts = file.path.split('/');
            let current = root;
            for (let i = 0; i < parts.length; i++) {
                const part = parts[i];
                if (!part)
                    continue;
                if (!current.children.has(part)) {
                    current.children.set(part, { name: part, children: new Map() });
                }
                current = current.children.get(part);
                // If this is the last part, it's a file
                if (i === parts.length - 1) {
                    current.file = { language: file.language, nodeCount: file.nodeCount };
                }
            }
        }
        // Render tree
        const lines = [`## Project Structure (${files.length} files)`, ''];
        const renderNode = (node, prefix, isLast, depth) => {
            if (maxDepth !== undefined && depth > maxDepth)
                return;
            const connector = isLast ? '└── ' : '├── ';
            const childPrefix = isLast ? '    ' : '│   ';
            if (node.name) {
                let line = prefix + connector + node.name;
                if (node.file && includeMetadata) {
                    line += ` (${node.file.language}, ${node.file.nodeCount} symbols)`;
                }
                lines.push(line);
            }
            const children = [...node.children.values()];
            // Sort: directories first, then files, both alphabetically
            children.sort((a, b) => {
                const aIsDir = a.children.size > 0 && !a.file;
                const bIsDir = b.children.size > 0 && !b.file;
                if (aIsDir !== bIsDir)
                    return aIsDir ? -1 : 1;
                return a.name.localeCompare(b.name);
            });
            for (let i = 0; i < children.length; i++) {
                const child = children[i];
                const nextPrefix = node.name ? prefix + childPrefix : prefix;
                renderNode(child, nextPrefix, i === children.length - 1, depth + 1);
            }
        };
        renderNode(root, '', true, 0);
        return lines.join('\n');
    }
    // =========================================================================
    // Symbol resolution helpers
    // =========================================================================
    /**
     * Find a symbol by name, handling disambiguation when multiple matches exist.
     * Returns the best match and a note about alternatives if any.
     */
    /**
     * Check if a node matches a symbol query, supporting both simple names and
     * qualified "Parent.child" notation (e.g., "Session.request" matches a method
     * named "request" inside a class named "Session").
     */
    matchesSymbol(node, symbol) {
        // Simple name match
        if (node.name === symbol)
            return true;
        // File basename match (e.g., "product-card" matches "product-card.liquid")
        if (node.kind === 'file' && node.name.replace(/\.[^.]+$/, '') === symbol)
            return true;
        // Qualified name match: "Parent.child" → look for "::Parent::child" in qualified_name
        if (symbol.includes('.')) {
            const parts = symbol.split('.');
            const qualifiedSuffix = parts.join('::');
            if (node.qualifiedName.includes(qualifiedSuffix))
                return true;
        }
        return false;
    }
    findSymbol(cg, symbol) {
        // Use higher limit for qualified lookups (e.g., "Session.request") since the
        // target may rank lower in FTS when there are many partial matches
        const limit = symbol.includes('.') ? 50 : 10;
        const results = cg.searchNodes(symbol, { limit });
        if (results.length === 0 || !results[0]) {
            return null;
        }
        const exactMatches = results.filter(r => this.matchesSymbol(r.node, symbol));
        if (exactMatches.length === 1) {
            return { node: exactMatches[0].node, note: '' };
        }
        if (exactMatches.length > 1) {
            // Multiple exact matches - pick first, note the others
            const picked = exactMatches[0].node;
            const others = exactMatches.slice(1).map(r => `${r.node.name} (${r.node.kind}) at ${r.node.filePath}:${r.node.startLine}`);
            const note = `\n\n> **Note:** ${exactMatches.length} symbols named "${symbol}". Showing results for \`${picked.filePath}:${picked.startLine}\`. Others: ${others.join(', ')}`;
            return { node: picked, note };
        }
        // No exact match, use best fuzzy match
        return { node: results[0].node, note: '' };
    }
    /**
     * Find ALL symbols matching a name. Used by callers/callees/impact to aggregate
     * results across all matching symbols (e.g., multiple classes with an `execute` method).
     */
    findAllSymbols(cg, symbol) {
        const results = cg.searchNodes(symbol, { limit: 50 });
        if (results.length === 0) {
            return { nodes: [], note: '' };
        }
        const exactMatches = results.filter(r => this.matchesSymbol(r.node, symbol));
        if (exactMatches.length <= 1) {
            const node = exactMatches[0]?.node ?? results[0].node;
            return { nodes: [node], note: '' };
        }
        const locations = exactMatches.map(r => `${r.node.kind} at ${r.node.filePath}:${r.node.startLine}`);
        const note = `\n\n> **Note:** Aggregated results across ${exactMatches.length} symbols named "${symbol}": ${locations.join(', ')}`;
        return { nodes: exactMatches.map(r => r.node), note };
    }
    /**
     * Truncate output if it exceeds the maximum length
     */
    truncateOutput(text) {
        if (text.length <= MAX_OUTPUT_LENGTH)
            return text;
        const truncated = text.slice(0, MAX_OUTPUT_LENGTH);
        const lastNewline = truncated.lastIndexOf('\n');
        const cutPoint = lastNewline > MAX_OUTPUT_LENGTH * 0.8 ? lastNewline : MAX_OUTPUT_LENGTH;
        return truncated.slice(0, cutPoint) + '\n\n... (output truncated)';
    }
    // =========================================================================
    // Formatting helpers (compact by default to reduce context usage)
    // =========================================================================
    formatSearchResults(results) {
        const lines = [`## Search Results (${results.length} found)`, ''];
        for (const result of results) {
            const { node } = result;
            const location = node.startLine ? `:${node.startLine}` : '';
            // Compact format: one line per result with key info
            lines.push(`### ${node.name} (${node.kind})`);
            lines.push(`${node.filePath}${location}`);
            if (node.signature)
                lines.push(`\`${node.signature}\``);
            lines.push('');
        }
        return lines.join('\n');
    }
    formatNodeList(nodes, title) {
        const lines = [`## ${title} (${nodes.length} found)`, ''];
        for (const node of nodes) {
            const location = node.startLine ? `:${node.startLine}` : '';
            // Compact: just name, kind, location
            lines.push(`- ${node.name} (${node.kind}) - ${node.filePath}${location}`);
        }
        return lines.join('\n');
    }
    formatImpact(symbol, impact) {
        const nodeCount = impact.nodes.size;
        // Compact format: just list affected symbols grouped by file
        const lines = [
            `## Impact: "${symbol}" affects ${nodeCount} symbols`,
            '',
        ];
        // Group by file
        const byFile = new Map();
        for (const node of impact.nodes.values()) {
            const existing = byFile.get(node.filePath) || [];
            existing.push(node);
            byFile.set(node.filePath, existing);
        }
        for (const [file, nodes] of byFile) {
            lines.push(`**${file}:**`);
            // Compact: inline list
            const nodeList = nodes.map(n => `${n.name}:${n.startLine}`).join(', ');
            lines.push(nodeList);
            lines.push('');
        }
        return lines.join('\n');
    }
    formatNodeDetails(node, code) {
        const location = node.startLine ? `:${node.startLine}` : '';
        const lines = [
            `## ${node.name} (${node.kind})`,
            '',
            `**Location:** ${node.filePath}${location}`,
        ];
        if (node.signature) {
            lines.push(`**Signature:** \`${node.signature}\``);
        }
        // Only include docstring if it's short and useful
        if (node.docstring && node.docstring.length < 200) {
            lines.push('', node.docstring);
        }
        if (code) {
            lines.push('', '```' + node.language, code, '```');
        }
        return lines.join('\n');
    }
    formatTaskContext(context) {
        return context.summary || 'No context found';
    }
    textResult(text) {
        return {
            content: [{ type: 'text', text }],
        };
    }
    errorResult(message) {
        return {
            content: [{ type: 'text', text: `Error: ${message}` }],
            isError: true,
        };
    }
}
exports.ToolHandler = ToolHandler;
//# sourceMappingURL=tools.js.map