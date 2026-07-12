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
const index_1 = require("@colbymchenry/codegraph");
// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------
/** Map CodeGraph Node to integration OutputSymbol (camelCase → snake_case). */
function nodeToOutputSymbol(n) {
    // Build object with only defined optional fields so JSON.stringify omits nulls
    return {
        qualified_name: n.qualifiedName,
        name: n.name,
        kind: n.kind,
        file_path: n.filePath,
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
function edgeToRelationship(edge, sourceQualifiedName, targetQualifiedName) {
    return {
        source: sourceQualifiedName,
        target: targetQualifiedName,
        kind: edge.kind,
        file_path: undefined,
    };
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
    const allKinds = [
        'file', 'module', 'class', 'struct', 'interface', 'trait', 'protocol',
        'function', 'method', 'property', 'field', 'variable', 'constant',
        'enum', 'enum_member', 'type_alias', 'namespace', 'parameter',
        'import', 'export', 'route', 'component',
    ];
    const seen = new Set();
    const symbols = [];
    for (const kind of allKinds) {
        let nodes;
        try {
            nodes = cg.getNodesByKind(kind);
        }
        catch {
            nodes = [];
        }
        for (const n of nodes) {
            if (!seen.has(n.id)) {
                seen.add(n.id);
                symbols.push(nodeToOutputSymbol(n));
            }
        }
    }
    return symbols;
}
/**
 * 5. getRelationships
 *
 * Returns all directed edges as Relationship objects.
 * Iterates nodes and collects outgoing edges, deduplicating by
 * source+target+kind identity.
 */
async function getRelationships(cg) {
    const symbols = await getSymbols(cg);
    // Build a qualified-name lookup from node ids — we'll need it to resolve
    // source/target qualified names from edge source/target ids.
    const idToQualifiedName = new Map();
    for (const kind of [
        'file', 'module', 'class', 'struct', 'interface', 'trait', 'protocol',
        'function', 'method', 'property', 'field', 'variable', 'constant',
        'enum', 'enum_member', 'type_alias', 'namespace', 'parameter',
        'import', 'export', 'route', 'component',
    ]) {
        try {
            const nodes = cg.getNodesByKind(kind);
            for (const n of nodes) {
                idToQualifiedName.set(n.id, n.qualifiedName);
            }
        }
        catch {
            // ignore missing kinds
        }
    }
    const seen = new Set();
    const relationships = [];
    for (const sym of symbols) {
        // Find the node id corresponding to this qualified name
        let nodeId;
        for (const [id, qn] of idToQualifiedName) {
            if (qn === sym.qualified_name) {
                nodeId = id;
                break;
            }
        }
        if (!nodeId)
            continue;
        let edges;
        try {
            edges = cg.getOutgoingEdges(nodeId);
        }
        catch {
            continue;
        }
        for (const edge of edges) {
            const targetQN = idToQualifiedName.get(edge.target);
            if (!targetQN)
                continue;
            const dedupeKey = `${edge.source}|${edge.target}|${edge.kind}`;
            if (seen.has(dedupeKey))
                continue;
            seen.add(dedupeKey);
            relationships.push(edgeToRelationship(edge, sym.qualified_name, targetQN));
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
        .filter((r) => r.kind === 'calls')
        .map((r) => ({ caller: r.source, callee: r.target }));
}
/**
 * 7. getTypeHierarchy
 *
 * Returns type hierarchy edges (extends / implements only).
 */
async function getTypeHierarchy(cg) {
    const relationships = await getRelationships(cg);
    return relationships
        .filter((r) => r.kind === 'extends' || r.kind === 'implements')
        .map((r) => ({
        child: r.source,
        parent: r.target,
        kind: r.kind,
    }));
}
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
async function getImpactRadius(cg, symbols, depth) {
    const clampedDepth = Math.min(Math.max(1, depth), 10);
    // Build id→qualifiedName and qualifiedName→id maps
    const allKinds = [
        'file', 'module', 'class', 'struct', 'interface', 'trait', 'protocol',
        'function', 'method', 'property', 'field', 'variable', 'constant',
        'enum', 'enum_member', 'type_alias', 'namespace', 'parameter',
        'import', 'export', 'route', 'component',
    ];
    const qnToId = new Map();
    const idToQn = new Map();
    for (const kind of allKinds) {
        try {
            const nodes = cg.getNodesByKind(kind);
            for (const n of nodes) {
                qnToId.set(n.qualifiedName, n.id);
                idToQn.set(n.id, n.qualifiedName);
            }
        }
        catch {
            // ignore
        }
    }
    const results = [];
    for (const symbolQN of symbols) {
        const nodeId = qnToId.get(symbolQN);
        if (!nodeId) {
            results.push({ symbol: symbolQN, affected: [], depth: clampedDepth });
            continue;
        }
        let subgraph;
        try {
            subgraph = cg.getImpactRadius(nodeId, clampedDepth);
        }
        catch {
            results.push({ symbol: symbolQN, affected: [], depth: clampedDepth });
            continue;
        }
        // Subgraph.nodes is Map<string, Node>
        const affected = [];
        for (const [id, n] of subgraph.nodes) {
            if (id !== nodeId) {
                affected.push(n.qualifiedName);
            }
        }
        results.push({ symbol: symbolQN, affected, depth: clampedDepth });
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
