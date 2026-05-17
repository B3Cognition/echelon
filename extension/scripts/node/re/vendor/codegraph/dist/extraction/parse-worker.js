"use strict";
/**
 * Parse Worker
 *
 * Runs tree-sitter parsing in a separate thread so the main thread
 * stays unblocked and the UI animation renders smoothly.
 */
Object.defineProperty(exports, "__esModule", { value: true });
const worker_threads_1 = require("worker_threads");
const tree_sitter_1 = require("./tree-sitter");
const grammars_1 = require("./grammars");
const PARSER_RESET_INTERVAL = 5000;
const parseCounts = new Map();
worker_threads_1.parentPort.on('message', async (msg) => {
    if (msg.type === 'load-grammars') {
        await (0, grammars_1.loadGrammarsForLanguages)(msg.languages);
        worker_threads_1.parentPort.postMessage({ type: 'grammars-loaded' });
    }
    else if (msg.type === 'parse') {
        const { id, filePath, content } = msg;
        try {
            const language = (0, grammars_1.detectLanguage)(filePath, content);
            const result = (0, tree_sitter_1.extractFromSource)(filePath, content, language);
            // Periodic parser reset to reclaim WASM heap memory
            const count = (parseCounts.get(language) ?? 0) + 1;
            parseCounts.set(language, count);
            if (count % PARSER_RESET_INTERVAL === 0) {
                (0, grammars_1.resetParser)(language);
            }
            worker_threads_1.parentPort.postMessage({ type: 'parse-result', id, result });
        }
        catch (err) {
            const message = err instanceof Error ? err.message : String(err);
            // WASM memory errors leave the module in a corrupted state — all
            // subsequent parses would also fail (cascading failures). Crash the
            // worker so the main thread spawns a fresh one with a clean heap.
            if (message.includes('memory access out of bounds') || message.includes('out of memory')) {
                process.exit(1);
            }
            worker_threads_1.parentPort.postMessage({
                type: 'parse-result',
                id,
                result: {
                    nodes: [],
                    edges: [],
                    unresolvedReferences: [],
                    errors: [{ message: `Parse worker error: ${message}`, filePath: filePath, severity: 'error', code: 'parse_error' }],
                    durationMs: 0,
                },
            });
        }
    }
    else if (msg.type === 'shutdown') {
        worker_threads_1.parentPort.postMessage({ type: 'shutdown-ack' });
    }
});
//# sourceMappingURL=parse-worker.js.map