"use strict";
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
exports.ToolHandler = exports.tools = exports.StdioTransport = exports.MCPServer = void 0;
const path = __importStar(require("path"));
const index_1 = __importStar(require("../index"));
const transport_1 = require("./transport");
const tools_1 = require("./tools");
/**
 * Convert a file:// URI to a filesystem path.
 * Handles URL encoding and Windows drive letter paths.
 */
function fileUriToPath(uri) {
    try {
        const url = new URL(uri);
        let filePath = decodeURIComponent(url.pathname);
        // On Windows, file:///C:/path produces pathname /C:/path — strip leading /
        if (process.platform === 'win32' && /^\/[a-zA-Z]:/.test(filePath)) {
            filePath = filePath.slice(1);
        }
        return path.resolve(filePath);
    }
    catch {
        // Fallback for non-standard URIs
        return uri.replace(/^file:\/\/\/?/, '');
    }
}
/**
 * MCP Server Info
 */
const SERVER_INFO = {
    name: 'codegraph',
    version: '0.1.0',
};
/**
 * MCP Protocol Version
 */
const PROTOCOL_VERSION = '2024-11-05';
/**
 * MCP Server for CodeGraph
 *
 * Implements the Model Context Protocol to expose CodeGraph
 * functionality as tools that can be called by AI assistants.
 */
class MCPServer {
    transport;
    cg = null;
    toolHandler;
    projectPath;
    constructor(projectPath) {
        this.projectPath = projectPath || null;
        this.transport = new transport_1.StdioTransport();
        // Create ToolHandler eagerly — cross-project queries work even without a default project
        this.toolHandler = new tools_1.ToolHandler(null);
    }
    /**
     * Start the MCP server
     *
     * Note: CodeGraph initialization is deferred until the initialize request
     * is received, which includes the rootUri from the client.
     */
    async start() {
        // Start listening for messages immediately - don't check initialization yet
        // We'll get the project path from the initialize request's rootUri
        this.transport.start(this.handleMessage.bind(this));
        // Keep the process running
        process.on('SIGINT', () => this.stop());
        process.on('SIGTERM', () => this.stop());
        // When the parent process (Claude Code) exits, stdin closes.
        // Detect this and shut down gracefully to prevent orphaned processes.
        process.stdin.on('end', () => this.stop());
        process.stdin.on('close', () => this.stop());
    }
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
    async tryInitializeDefault(projectPath) {
        // Walk up parent directories to find nearest .codegraph/
        const resolvedRoot = (0, index_1.findNearestCodeGraphRoot)(projectPath);
        if (!resolvedRoot) {
            this.projectPath = projectPath;
            return;
        }
        this.projectPath = resolvedRoot;
        try {
            this.cg = await index_1.default.open(resolvedRoot);
            this.toolHandler.setDefaultCodeGraph(this.cg);
            this.startWatching();
        }
        catch (err) {
            // Log the error so transient failures are diagnosable (see issue #47)
            const msg = err instanceof Error ? err.message : String(err);
            process.stderr.write(`[CodeGraph MCP] Failed to open project at ${resolvedRoot}: ${msg}\n`);
        }
    }
    /**
     * Retry initialization of the default project if it previously failed.
     * Called lazily on tool calls that need the default project.
     * Re-walks parent directories each time so it picks up projects
     * initialized after the MCP server started.
     */
    retryInitIfNeeded() {
        // Already initialized successfully
        if (this.toolHandler.hasDefaultCodeGraph())
            return;
        // No project path to retry with
        if (!this.projectPath)
            return;
        const resolvedRoot = (0, index_1.findNearestCodeGraphRoot)(this.projectPath);
        if (!resolvedRoot)
            return;
        try {
            // Close any previously failed instance to avoid leaking resources
            if (this.cg) {
                try {
                    this.cg.close();
                }
                catch { /* ignore */ }
                this.cg = null;
            }
            this.cg = index_1.default.openSync(resolvedRoot);
            this.projectPath = resolvedRoot;
            this.toolHandler.setDefaultCodeGraph(this.cg);
            this.startWatching();
        }
        catch {
            // Still failing — will retry on next tool call
        }
    }
    /**
     * Start file watching on the active CodeGraph instance.
     * Logs sync activity to stderr for diagnostics.
     */
    startWatching() {
        if (!this.cg)
            return;
        const started = this.cg.watch({
            onSyncComplete: (result) => {
                if (result.filesChanged > 0) {
                    process.stderr.write(`[CodeGraph MCP] Auto-synced ${result.filesChanged} file(s) in ${result.durationMs}ms\n`);
                }
            },
            onSyncError: (err) => {
                process.stderr.write(`[CodeGraph MCP] Auto-sync error: ${err.message}\n`);
            },
        });
        if (started) {
            process.stderr.write('[CodeGraph MCP] File watcher active — graph will auto-sync on changes\n');
        }
    }
    /**
     * Stop the server
     */
    stop() {
        // Close all cached cross-project connections first
        this.toolHandler.closeAll();
        // Close the main CodeGraph instance
        if (this.cg) {
            this.cg.close();
            this.cg = null;
        }
        this.transport.stop();
        process.exit(0);
    }
    /**
     * Handle incoming JSON-RPC messages
     */
    async handleMessage(message) {
        // Check if it's a request (has id) or notification (no id)
        const isRequest = 'id' in message;
        switch (message.method) {
            case 'initialize':
                if (isRequest) {
                    await this.handleInitialize(message);
                }
                break;
            case 'initialized':
                // Notification that client has finished initialization
                // No action needed - the client is ready
                break;
            case 'tools/list':
                if (isRequest) {
                    await this.handleToolsList(message);
                }
                break;
            case 'tools/call':
                if (isRequest) {
                    await this.handleToolsCall(message);
                }
                break;
            case 'ping':
                if (isRequest) {
                    this.transport.sendResult(message.id, {});
                }
                break;
            default:
                if (isRequest) {
                    this.transport.sendError(message.id, transport_1.ErrorCodes.MethodNotFound, `Method not found: ${message.method}`);
                }
        }
    }
    /**
     * Handle initialize request
     */
    async handleInitialize(request) {
        const params = request.params;
        // Extract project path from rootUri or workspaceFolders
        let projectPath = this.projectPath;
        if (params?.rootUri) {
            projectPath = fileUriToPath(params.rootUri);
        }
        else if (params?.workspaceFolders?.[0]?.uri) {
            projectPath = fileUriToPath(params.workspaceFolders[0].uri);
        }
        // Fall back to current working directory if no path provided
        if (!projectPath) {
            projectPath = process.cwd();
        }
        // Try to initialize the default project (non-fatal if it fails)
        await this.tryInitializeDefault(projectPath);
        // We accept the client's protocol version but respond with our supported version
        this.transport.sendResult(request.id, {
            protocolVersion: PROTOCOL_VERSION,
            capabilities: {
                tools: {},
            },
            serverInfo: SERVER_INFO,
        });
    }
    /**
     * Handle tools/list request
     */
    async handleToolsList(request) {
        this.retryInitIfNeeded();
        this.transport.sendResult(request.id, {
            tools: this.toolHandler.getTools(),
        });
    }
    /**
     * Handle tools/call request
     */
    async handleToolsCall(request) {
        const params = request.params;
        if (!params || !params.name) {
            this.transport.sendError(request.id, transport_1.ErrorCodes.InvalidParams, 'Missing tool name');
            return;
        }
        const toolName = params.name;
        const toolArgs = params.arguments || {};
        // Validate tool exists
        const tool = tools_1.tools.find(t => t.name === toolName);
        if (!tool) {
            this.transport.sendError(request.id, transport_1.ErrorCodes.InvalidParams, `Unknown tool: ${toolName}`);
            return;
        }
        // If the default project isn't initialized yet, retry in case it was
        // initialized after the MCP server started (e.g. user ran codegraph init)
        this.retryInitIfNeeded();
        const result = await this.toolHandler.execute(toolName, toolArgs);
        this.transport.sendResult(request.id, result);
    }
}
exports.MCPServer = MCPServer;
// Export for use in CLI
var transport_2 = require("./transport");
Object.defineProperty(exports, "StdioTransport", { enumerable: true, get: function () { return transport_2.StdioTransport; } });
var tools_2 = require("./tools");
Object.defineProperty(exports, "tools", { enumerable: true, get: function () { return tools_2.tools; } });
Object.defineProperty(exports, "ToolHandler", { enumerable: true, get: function () { return tools_2.ToolHandler; } });
//# sourceMappingURL=index.js.map