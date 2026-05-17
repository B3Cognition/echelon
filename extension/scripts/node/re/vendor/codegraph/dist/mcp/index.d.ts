/**
 * CodeGraph MCP Server
 *
 * Model Context Protocol server that exposes CodeGraph functionality
 * as tools for AI assistants like Claude.
 *
 * @module mcp
 *
 * @example
 * ```typescript
 * import { MCPServer } from 'codegraph';
 *
 * const server = new MCPServer('/path/to/project');
 * await server.start();
 * ```
 */
/**
 * MCP Server for CodeGraph
 *
 * Implements the Model Context Protocol to expose CodeGraph
 * functionality as tools that can be called by AI assistants.
 */
export declare class MCPServer {
    private transport;
    private cg;
    private toolHandler;
    private projectPath;
    constructor(projectPath?: string);
    /**
     * Start the MCP server
     *
     * Note: CodeGraph initialization is deferred until the initialize request
     * is received, which includes the rootUri from the client.
     */
    start(): Promise<void>;
    /**
     * Try to initialize CodeGraph for the default project.
     *
     * Walks up parent directories to find the nearest .codegraph/ folder,
     * similar to how git finds .git/ directories.
     *
     * If initialization fails, the error is recorded but the server continues
     * to work — cross-project queries and retries on subsequent tool calls
     * are still possible.
     */
    private tryInitializeDefault;
    /**
     * Retry initialization of the default project if it previously failed.
     * Called lazily on tool calls that need the default project.
     * Re-walks parent directories each time so it picks up projects
     * initialized after the MCP server started.
     */
    private retryInitIfNeeded;
    /**
     * Start file watching on the active CodeGraph instance.
     * Logs sync activity to stderr for diagnostics.
     */
    private startWatching;
    /**
     * Stop the server
     */
    stop(): void;
    /**
     * Handle incoming JSON-RPC messages
     */
    private handleMessage;
    /**
     * Handle initialize request
     */
    private handleInitialize;
    /**
     * Handle tools/list request
     */
    private handleToolsList;
    /**
     * Handle tools/call request
     */
    private handleToolsCall;
}
export { StdioTransport } from './transport';
export { tools, ToolHandler } from './tools';
//# sourceMappingURL=index.d.ts.map