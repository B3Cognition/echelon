"use strict";
/**
 * MCP Stdio Transport
 *
 * Handles JSON-RPC 2.0 communication over stdin/stdout for MCP protocol.
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
exports.StdioTransport = exports.ErrorCodes = void 0;
const readline = __importStar(require("readline"));
// Standard JSON-RPC error codes
exports.ErrorCodes = {
    ParseError: -32700,
    InvalidRequest: -32600,
    MethodNotFound: -32601,
    InvalidParams: -32602,
    InternalError: -32603,
};
/**
 * Stdio Transport for MCP
 *
 * Reads JSON-RPC messages from stdin and writes responses to stdout.
 */
class StdioTransport {
    rl = null;
    messageHandler = null;
    /**
     * Start listening for messages on stdin
     */
    start(handler) {
        this.messageHandler = handler;
        this.rl = readline.createInterface({
            input: process.stdin,
            output: process.stdout,
            terminal: false,
        });
        this.rl.on('line', async (line) => {
            await this.handleLine(line);
        });
        this.rl.on('close', () => {
            process.exit(0);
        });
    }
    /**
     * Stop listening
     */
    stop() {
        if (this.rl) {
            this.rl.close();
            this.rl = null;
        }
    }
    /**
     * Send a response
     */
    send(response) {
        const json = JSON.stringify(response);
        process.stdout.write(json + '\n');
    }
    /**
     * Send a notification (no id)
     */
    notify(method, params) {
        const notification = {
            jsonrpc: '2.0',
            method,
            params,
        };
        process.stdout.write(JSON.stringify(notification) + '\n');
    }
    /**
     * Send a success response
     */
    sendResult(id, result) {
        this.send({
            jsonrpc: '2.0',
            id,
            result,
        });
    }
    /**
     * Send an error response
     */
    sendError(id, code, message, data) {
        this.send({
            jsonrpc: '2.0',
            id,
            error: { code, message, data },
        });
    }
    /**
     * Handle an incoming line of JSON
     */
    async handleLine(line) {
        const trimmed = line.trim();
        if (!trimmed)
            return;
        let parsed;
        try {
            parsed = JSON.parse(trimmed);
        }
        catch {
            this.sendError(null, exports.ErrorCodes.ParseError, 'Parse error: invalid JSON');
            return;
        }
        // Validate basic JSON-RPC structure
        if (!this.isValidMessage(parsed)) {
            this.sendError(null, exports.ErrorCodes.InvalidRequest, 'Invalid Request: not a valid JSON-RPC 2.0 message');
            return;
        }
        if (this.messageHandler) {
            try {
                await this.messageHandler(parsed);
            }
            catch (err) {
                const message = parsed;
                if ('id' in message) {
                    this.sendError(message.id, exports.ErrorCodes.InternalError, `Internal error: ${err instanceof Error ? err.message : String(err)}`);
                }
            }
        }
    }
    /**
     * Check if message is a valid JSON-RPC 2.0 message
     */
    isValidMessage(msg) {
        if (typeof msg !== 'object' || msg === null)
            return false;
        const obj = msg;
        if (obj.jsonrpc !== '2.0')
            return false;
        if (typeof obj.method !== 'string')
            return false;
        return true;
    }
}
exports.StdioTransport = StdioTransport;
//# sourceMappingURL=transport.js.map