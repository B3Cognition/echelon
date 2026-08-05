"use strict";
/**
 * CodeGraph Adapter
 *
 * Thin adapter layer that isolates the bridge from CodeGraph's API surface.
 * This is the ONLY file that imports from @colbymchenry/codegraph.
 * All bridge code MUST call through this adapter.
 *
 * ADR-003: API compatibility — all CodeGraph calls are localized here.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.initializeGrammars = initializeGrammars;
exports.buildIndex = buildIndex;
exports.openIndex = openIndex;
exports.getSymbols = getSymbols;
exports.getRelationships = getRelationships;
exports.getCallGraph = getCallGraph;
exports.getTypeHierarchy = getTypeHierarchy;
exports.getImpactRadius = getImpactRadius;
exports.getPublicSymbols = getPublicSymbols;
exports.getIndexStats = getIndexStats;
exports.getExtractionSummary = getExtractionSummary;
exports.closeIndex = closeIndex;
exports.normalizeSourcePath = normalizeSourcePath;
exports.symbolKey = symbolKey;
const index_1 = require("@colbymchenry/codegraph");
const crypto = require("crypto");
// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------
const NODE_KINDS = [
    'file', 'module', 'class', 'struct', 'interface', 'trait', 'protocol',
    'function', 'method', 'property', 'field', 'variable', 'constant',
    'enum', 'enum_member', 'type_alias', 'namespace', 'parameter',
    'import', 'export', 'route', 'component',
];
function normalizeSourcePath(filePath) {
    if (typeof filePath !== 'string' || filePath.length === 0) {
        throw new Error('[codegraph-adapter] contract error: symbol file path is required');
    }
    const normalized = filePath.replace(/\\/g, '/');
    if (normalized.startsWith('/') || /^[A-Za-z]:\//.test(normalized)) {
        throw new Error(`[codegraph-adapter] contract error: absolute symbol file path: ${filePath}`);
    }
    const segments = normalized.split('/');
    if (segments.some((segment) => segment === '..')) {
        throw new Error(`[codegraph-adapter] contract error: traversing symbol file path: ${filePath}`);
    }
    const sourceRelative = segments.filter((segment) => segment && segment !== '.').join('/');
    if (!sourceRelative) {
        throw new Error(`[codegraph-adapter] contract error: empty symbol file path: ${filePath}`);
    }
    return sourceRelative;
}
function symbolKey(node) {
    const locator = [
        normalizeSourcePath(node.filePath),
        String(node.qualifiedName),
        String(node.kind),
        node.signature == null ? '' : String(node.signature),
    ];
    return `sha256:${crypto.createHash('sha256')
        .update(JSON.stringify(locator), 'utf8').digest('hex')}`;
}
/** Map CodeGraph Node to integration OutputSymbol (camelCase → snake_case). */
function nodeToOutputSymbol(n) {
    // Build object with only defined optional fields so JSON.stringify omits nulls
    return {
        symbol_key: symbolKey(n),
        qualified_name: n.qualifiedName,
        name: n.name,
        kind: n.kind,
        file_path: normalizeSourcePath(n.filePath),
        line_start: n.startLine,
        line_end: n.endLine,
        // Optional fields: only include when non-null to avoid null values in JSON
        ...(n.visibility != null ? { visibility: n.visibility } : {}),
        ...(n.isExported != null ? { is_exported: n.isExported } : {}),
        ...(n.signature != null ? { signature: n.signature } : {}),
        ...(n.language != null ? { language: n.language } : {}),
    };
}
/** Map CodeGraph Edge to integration Relationship. */
function edgeToRelationship(edge, source, target) {
    return {
        kind: edge.kind,
        ...(source ? { source_key: source.symbol_key, source_name: source.qualified_name } : {}),
        ...(target ? { target_key: target.symbol_key, target_name: target.qualified_name } : {}),
        ...(edge.filePath != null ? { file_path: normalizeSourcePath(edge.filePath) } : {}),
    };
}
function collectNativeNodeData(cg) {
    const nodes = [];
    const seenNodeIds = new Set();
    const keyToNodeId = new Map();
    const symbolByNodeId = new Map();
    for (const kind of NODE_KINDS) {
        let nativeNodes;
        try {
            nativeNodes = cg.getNodesByKind(kind);
        }
        catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            throw new Error(`[codegraph-adapter] getNodesByKind failed for kind "${kind}": ${msg}`);
        }
        for (const node of nativeNodes) {
            if (seenNodeIds.has(node.id)) {
                continue;
            }
            seenNodeIds.add(node.id);
            const symbol = nodeToOutputSymbol(node);
            const existingNodeId = keyToNodeId.get(symbol.symbol_key);
            if (existingNodeId !== undefined && existingNodeId !== node.id) {
                throw new Error(`[codegraph-adapter] contract error: duplicate canonical locator for native nodes ${existingNodeId} and ${node.id}`);
            }
            keyToNodeId.set(symbol.symbol_key, node.id);
            symbolByNodeId.set(node.id, symbol);
            nodes.push(node);
        }
    }
    return { nodes, keyToNodeId, symbolByNodeId };
}
// ---------------------------------------------------------------------------
// Adapter public API
// ---------------------------------------------------------------------------
/**
 * 1. initializeGrammars
 *
 * Initialises the WASM grammar runtime, then loads grammars for the requested
 * languages. Catches per-language errors, logs a warning, and continues.
 *
 * @param languages  Optional list of language identifiers (e.g. ["typescript"]).
 *                   Defaults to all supported languages when omitted.
 */
async function initializeGrammars(languages) {
    await (0, index_1.initGrammars)();
    if (languages && languages.length > 0) {
        const failures = [];
        for (const lang of languages) {
            try {
                await (0, index_1.loadGrammarsForLanguages)([lang]);
            }
            catch (err) {
                const msg = err instanceof Error ? err.message : String(err);
                console.warn(`[codegraph-adapter] WARN: grammar load failed for "${lang}": ${msg}`);
                failures.push(lang);
            }
        }
        if (failures.length === languages.length) {
            throw new Error(`All grammar loads failed (${failures.join(', ')}). Cannot proceed.`);
        }
    }
    else {
        // load all — any single grammar failure is not fatal
        try {
            await (0, index_1.loadAllGrammars)();
        }
        catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            console.warn(`[codegraph-adapter] WARN: loadAllGrammars failed, proceeding without pre-load: ${msg}`);
        }
    }
}
/**
 * 2. buildIndex
 *
 * Creates a new CodeGraph instance, calls init() then indexAll().
 * Returns the IndexResult alongside the CodeGraph instance.
 *
 * @param repoPath    Absolute path to the repository.
 * @param onProgress  Optional progress callback.
 */
async function buildIndex(repoPath, onProgress) {
    const startTime = Date.now();
    let cg;
    try {
        cg = await index_1.CodeGraph.init(repoPath, {
            onProgress: onProgress
                ? (p) => {
                    onProgress(p.current ?? 0, p.total ?? 0);
                }
                : undefined,
        });
    }
    catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        throw new Error(`[codegraph-adapter] buildIndex: init failed: ${msg}`);
    }
    let result;
    try {
        result = await cg.indexAll({
            onProgress: onProgress
                ? (p) => {
                    onProgress(p.current ?? 0, p.total ?? 0);
                }
                : undefined,
        });
    }
    catch (err) {
        await closeIndex(cg).catch(() => undefined);
        const msg = err instanceof Error ? err.message : String(err);
        throw new Error(`[codegraph-adapter] buildIndex: indexAll failed: ${msg}`);
    }
    const ext = { ...result, startTime };
    return { cg, result: ext };
}
/**
 * 3. openIndex
 *
 * Opens an existing CodeGraph index (does NOT re-index).
 *
 * @param repoPath  Absolute path to the repository.
 */
async function openIndex(repoPath) {
    try {
        return await index_1.CodeGraph.open(repoPath);
    }
    catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        throw new Error(`[codegraph-adapter] openIndex failed: ${msg}`);
    }
}
/**
 * 4. getSymbols
 *
 * Returns all symbols (nodes) from the index, projected to OutputSymbol.
 * Uses getNodesByKind for each kind to avoid the internal-only getAllNodes().
 */
async function getSymbols(cg) {
    return [...collectNativeNodeData(cg).symbolByNodeId.values()];
}
/**
 * 5. getRelationships
 *
 * Returns all directed edges as Relationship objects.
 * Iterates nodes and collects outgoing edges, deduplicating by
 * source+target+kind identity.
 */
async function getRelationships(cg) {
    const { nodes, symbolByNodeId } = collectNativeNodeData(cg);
    const seen = new Set();
    const relationships = [];
    for (const node of nodes) {
        let edges;
        try {
            edges = cg.getOutgoingEdges(node.id);
        }
        catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            throw new Error(`[codegraph-adapter] getOutgoingEdges failed for node ${node.id} (${node.qualifiedName}): ${msg}`);
        }
        for (const edge of edges) {
            const dedupeKey = `${edge.source}|${edge.target}|${edge.kind}`;
            if (seen.has(dedupeKey))
                continue;
            seen.add(dedupeKey);
            relationships.push(edgeToRelationship(edge, symbolByNodeId.get(edge.source), symbolByNodeId.get(edge.target)));
        }
    }
    return relationships;
}
/**
 * 6. getCallGraph
 *
 * Returns simplified caller→callee pairs from all "calls" edges.
 */
async function getCallGraph(cg) {
    const relationships = await getRelationships(cg);
    return relationships
        .filter((r) => r.kind === 'calls' && r.source_key && r.target_key)
        .map((r) => ({
        caller_key: r.source_key,
        callee_key: r.target_key,
        ...(r.source_name ? { caller_name: r.source_name } : {}),
        ...(r.target_name ? { callee_name: r.target_name } : {}),
    }));
}
/**
 * 7. getTypeHierarchy
 *
 * Returns type hierarchy edges (extends / implements only).
 */
async function getTypeHierarchy(cg) {
    const relationships = await getRelationships(cg);
    return relationships
        .filter((r) => (r.kind === 'extends' || r.kind === 'implements') && r.source_key && r.target_key)
        .map((r) => ({
        child_key: r.source_key,
        parent_key: r.target_key,
        ...(r.source_name ? { child_name: r.source_name } : {}),
        ...(r.target_name ? { parent_name: r.target_name } : {}),
        kind: r.kind,
    }));
}
/**
 * 8. getImpactRadius
 *
 * Computes transitive impact radius for a set of exact symbol keys.
 * Enforces depth max 10.
 *
 * @param cg       CodeGraph instance.
 * @param symbols  Exact symbol keys of the symbols to analyse.
 * @param depth    Traversal depth (1-10). Clamped to 10.
 */
async function getImpactRadius(cg, symbols, depth) {
    const clampedDepth = Math.min(Math.max(1, depth), 10);
    const { keyToNodeId, symbolByNodeId } = collectNativeNodeData(cg);
    const results = [];
    for (const requestedSymbolKey of symbols) {
        const nodeId = keyToNodeId.get(requestedSymbolKey);
        if (nodeId === undefined) {
            results.push({ symbol_key: requestedSymbolKey, affected_keys: [], depth: clampedDepth });
            continue;
        }
        let subgraph;
        try {
            subgraph = cg.getImpactRadius(nodeId, clampedDepth);
        }
        catch {
            results.push({ symbol_key: requestedSymbolKey, affected_keys: [], depth: clampedDepth });
            continue;
        }
        // Subgraph.nodes is Map<string, Node>
        const affectedKeys = [];
        const affectedNames = [];
        for (const [id] of subgraph.nodes) {
            if (id !== nodeId) {
                const affected = symbolByNodeId.get(id);
                if (affected) {
                    affectedKeys.push(affected.symbol_key);
                    affectedNames.push(affected.qualified_name);
                }
            }
        }
        const source = symbolByNodeId.get(nodeId);
        results.push({
            symbol_key: requestedSymbolKey,
            ...(source ? { symbol_name: source.qualified_name } : {}),
            affected_keys: affectedKeys,
            affected_names: affectedNames,
            depth: clampedDepth,
        });
    }
    return results;
}
/**
 * 9. getPublicSymbols
 *
 * Returns symbols visible outside their module (public or is_exported=true).
 */
async function getPublicSymbols(cg) {
    const symbols = await getSymbols(cg);
    return symbols.filter((s) => s.visibility === 'public' || s.is_exported === true);
}
/**
 * 10. getIndexStats
 *
 * Computes IndexStats from an IndexResult_Ext.
 *
 * - extraction_success_rate = filesIndexed / (filesIndexed + filesErrored) * 100
 * - index_state = "degraded" when success rate < 50%, "ready" otherwise
 */
function getIndexStats(result) {
    const { filesIndexed = 0, filesErrored = 0, filesSkipped = 0 } = result;
    const total = filesIndexed + filesErrored + filesSkipped;
    const supported = filesIndexed + filesErrored; // filesSkipped = unsupported
    const rate = supported > 0 ? (filesIndexed / supported) * 100 : 100;
    return {
        total_files: total,
        supported_files: supported,
        unsupported_files: filesSkipped,
        failed_files: filesErrored,
        total_nodes: result.nodesCreated ?? 0,
        total_edges: result.edgesCreated ?? 0,
        build_time_ms: result.durationMs ?? 0,
        extraction_success_rate: Math.round(rate * 100) / 100,
        index_state: rate >= 50 ? 'ready' : 'degraded',
    };
}
/**
 * 11. getExtractionSummary
 *
 * Aggregates per-language counts from IndexResult.
 */
function getExtractionSummary(result) {
    // IndexResult doesn't expose per-language breakdowns; build a summary
    // from what we have. Full per-language stats are post-MVP (T026).
    const extracted = result.filesIndexed ?? 0;
    const errored = result.filesErrored ?? 0;
    const skipped = result.filesSkipped ?? 0;
    const languages = extracted > 0
        ? [{ language: 'unknown', file_count: extracted, status: 'supported' }]
        : [];
    const unsupported = skipped > 0 ? ['unsupported'] : [];
    return {
        languages,
        total_extracted: extracted,
        total_skipped_unsupported: skipped,
        total_skipped_error: errored,
        unsupported_languages: unsupported,
    };
}
/**
 * 12. closeIndex
 *
 * Closes the CodeGraph instance, releasing the SQLite connection.
 */
async function closeIndex(cg) {
    try {
        cg.close();
    }
    catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        console.warn(`[codegraph-adapter] WARN: closeIndex failed: ${msg}`);
    }
}
//# sourceMappingURL=codegraph-adapter.js.map
