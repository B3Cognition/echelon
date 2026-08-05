"use strict";
/**
 * CodeGraph Bridge
 *
 * Entry point for the bash pipeline. Parses CLI arguments, orchestrates
 * adapter calls, assembles codegraph-analysis.json, and writes atomically.
 *
 * ADR-001: Library import, single-invocation model.
 * ADR-002: Single bridge script, multi-command.
 * ADR-003: Adapter isolates all CodeGraph imports — do NOT import CodeGraph here.
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
exports.UsageError = exports.BRIDGE_TIMEOUT_MS = exports.MAX_DEPTH = exports.MIN_DEPTH = exports.DEFAULT_DEPTH = exports.DEFAULT_OUTPUT_RELATIVE = void 0;
exports.parseArgs = parseArgs;
exports.usageMessage = usageMessage;
exports.atomicWrite = atomicWrite;
exports.assembleAnalysisOutput = assembleAnalysisOutput;
exports.assembleSummary = assembleSummary;
exports.runBridge = runBridge;
const path = __importStar(require("path"));
const fs = __importStar(require("fs"));
const adapter = __importStar(require("./codegraph-adapter"));
const integrationTypes = require("./integration-types");
// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
exports.DEFAULT_OUTPUT_RELATIVE = '.specify/echelon/re/codegraph-analysis.json';
exports.DEFAULT_DEPTH = 3;
exports.MIN_DEPTH = 1;
exports.MAX_DEPTH = 10;
exports.BRIDGE_TIMEOUT_MS = 600_000; // 600 seconds
// ---------------------------------------------------------------------------
// Argument parsing (T006)
// ---------------------------------------------------------------------------
/**
 * Parses process.argv (or a supplied args array) into a structured ParsedArgs.
 *
 * Throws with a usage message (suitable for writing to stderr + exit 1) on
 * invalid input.
 *
 * Does NOT call process.exit() — that is the caller's responsibility so that
 * unit tests can capture the error without process termination.
 */
function parseArgs(argv) {
    // Skip node and script path — start from argv[2]
    const args = argv.slice(2);
    // First positional arg is the command (only "analyze" for MVP)
    const command = args[0] && !args[0].startsWith('--') ? args[0] : 'analyze';
    let repoPathRaw;
    let outputPathRaw;
    let summaryPathRaw;
    let languagesRaw;
    let depthRaw;
    for (let i = 0; i < args.length; i++) {
        const arg = args[i] ?? '';
        if (arg === '--repo-path' || arg.startsWith('--repo-path=')) {
            repoPathRaw = arg.includes('=') ? arg.split('=').slice(1).join('=') : args[++i];
        }
        else if (arg === '--output-path' || arg.startsWith('--output-path=')) {
            outputPathRaw = arg.includes('=') ? arg.split('=').slice(1).join('=') : args[++i];
        }
        else if (arg === '--summary-path' || arg.startsWith('--summary-path=')) {
            summaryPathRaw = arg.includes('=') ? arg.split('=').slice(1).join('=') : args[++i];
        }
        else if (arg === '--languages' || arg.startsWith('--languages=')) {
            languagesRaw = arg.includes('=') ? arg.split('=').slice(1).join('=') : args[++i];
        }
        else if (arg === '--depth' || arg.startsWith('--depth=')) {
            depthRaw = arg.includes('=') ? arg.split('=').slice(1).join('=') : args[++i];
        }
        // Unknown arguments are silently ignored for forward compatibility
    }
    // Validate --repo-path (required)
    if (!repoPathRaw) {
        throw new UsageError('Missing required argument: --repo-path\n' + usageMessage());
    }
    // Resolve to absolute path
    const resolvedPath = path.resolve(repoPathRaw);
    // Canonicalize with realpathSync (T028: security — resolves symlinks + traversal)
    let repoPath;
    try {
        repoPath = fs.realpathSync(resolvedPath);
    }
    catch {
        throw new UsageError(`--repo-path does not exist or is not accessible: ${resolvedPath}\n` +
            usageMessage());
    }
    // Validate --depth
    let depth = exports.DEFAULT_DEPTH;
    if (depthRaw !== undefined) {
        const parsed = parseInt(depthRaw, 10);
        if (isNaN(parsed) || parsed < exports.MIN_DEPTH || parsed > exports.MAX_DEPTH) {
            throw new UsageError(`--depth must be an integer between ${exports.MIN_DEPTH} and ${exports.MAX_DEPTH}, got: "${depthRaw}"\n` +
                usageMessage());
        }
        depth = parsed;
    }
    // Resolve output path
    const outputPath = outputPathRaw
        ? path.resolve(outputPathRaw)
        : path.join(repoPath, exports.DEFAULT_OUTPUT_RELATIVE);
    const summaryPath = summaryPathRaw ? path.resolve(summaryPathRaw) : undefined;
    // Parse --languages
    const languages = languagesRaw && languagesRaw.trim().length > 0
        ? languagesRaw.split(',').map(l => l.trim()).filter(l => l.length > 0)
        : undefined;
    return { command, repoPath, outputPath, summaryPath, languages, depth };
}
// ---------------------------------------------------------------------------
// UsageError — signals argument validation failure (exit 1)
// ---------------------------------------------------------------------------
class UsageError extends Error {
    constructor(message) {
        super(message);
        this.name = 'UsageError';
    }
}
exports.UsageError = UsageError;
// ---------------------------------------------------------------------------
// Usage message
// ---------------------------------------------------------------------------
function usageMessage() {
    return `Usage: codegraph-bridge analyze --repo-path <path> [options]

Options:
  --repo-path <path>       Required. Absolute or relative path to the repository.
  --output-path <path>     Output JSON path. Default: <repo-path>/${exports.DEFAULT_OUTPUT_RELATIVE}
  --summary-path <path>    Optional provider summary JSON path.
  --languages <list>       Comma-separated list of languages to extract (e.g. typescript,python).
  --depth <n>              Impact radius traversal depth (${exports.MIN_DEPTH}-${exports.MAX_DEPTH}). Default: ${exports.DEFAULT_DEPTH}.

Exit codes:
  0  Success (or partial extraction — check provider_status and complete)
  1  Invalid arguments or missing dependency
  2  System error (index build failure, write failure, timeout)
`;
}
// ---------------------------------------------------------------------------
// Atomic write helper (T008)
// ---------------------------------------------------------------------------
/**
 * Writes data to outputPath atomically via a .tmp file + rename.
 * Creates parent directories as needed.
 * Throws on failure after cleaning up the temp file.
 */
async function atomicWrite(outputPath, data) {
    const tmpPath = `${outputPath}.tmp`;
    // Create parent directories
    const dir = path.dirname(outputPath);
    fs.mkdirSync(dir, { recursive: true });
    try {
        fs.writeFileSync(tmpPath, data, 'utf-8');
    }
    catch (err) {
        // Clean up temp file if it was created
        try {
            fs.unlinkSync(tmpPath);
        }
        catch { /* ignore */ }
        throw err;
    }
    // Atomic rename
    try {
        fs.renameSync(tmpPath, outputPath);
    }
    catch (err) {
        try {
            fs.unlinkSync(tmpPath);
        }
        catch { /* ignore */ }
        throw err;
    }
}
// ---------------------------------------------------------------------------
// JSON assembly helper (T007)
// ---------------------------------------------------------------------------
/**
 * Assembles a complete AnalysisOutput from adapter results.
 * Exported for unit testing.
 */
function assembleAnalysisOutput(params) {
    const { repoPath, symbols, relationships, callGraph, typeHierarchy, impactRadius, publicSymbols, indexStats, extractionSummary, } = params;
    // CodeGraph follows git-tracked source by default, which can include
    // repository metadata such as .github/skills. Keep that data outside the
    // RE artifact boundary even when the upstream indexer includes it.
    const inScopeSymbols = symbols.filter((symbol) => !isHiddenDirectoryPath(symbol.file_path));
    const visibleSymbols = inScopeSymbols.filter((symbol) => hasSymbolKey(symbol.symbol_key));
    const discoveredSymbolKeys = new Set(symbols.filter((symbol) => hasSymbolKey(symbol.symbol_key)).map((symbol) => symbol.symbol_key));
    const visibleSymbolKeys = new Set(visibleSymbols.map((symbol) => symbol.symbol_key));
    const visibleRelationships = relationships.filter((relationship) => hasVisibleRelationshipEndpoints(relationship, visibleSymbolKeys));
    const visibleCallGraph = callGraph.filter((edge) => hasVisibleCallEndpoints(edge, visibleSymbolKeys));
    const visibleTypeHierarchy = typeHierarchy.filter((edge) => hasVisibleTypeEndpoints(edge, visibleSymbolKeys));
    const visibleImpactRadius = impactRadius
        .filter((entry) => hasSymbolKey(entry.symbol_key) && visibleSymbolKeys.has(entry.symbol_key))
        .map((entry) => filterVisibleImpactEntry(entry, visibleSymbolKeys));
    const visiblePublicSymbols = publicSymbols.filter((symbol) => hasSymbolKey(symbol.symbol_key) && visibleSymbolKeys.has(symbol.symbol_key));
    const unresolvedRelationships = relationships
        .filter((relationship) => !hasKnownRelationshipEndpoints(relationship, discoveredSymbolKeys))
        .map(unresolvedRelationshipObservation);
    // Build language_coverage map from extraction summary
    const languageCoverage = {};
    for (const lang of extractionSummary.languages) {
        // Use typical file extensions for known languages
        const ext = languageToExtension(lang.language);
        if (ext) {
            languageCoverage[ext] = lang.status;
        }
    }
    for (const unsup of extractionSummary.unsupported_languages) {
        const ext = languageToExtension(unsup);
        if (ext && !languageCoverage[ext]) {
            languageCoverage[ext] = 'unsupported';
        }
    }
    const extractionComplete = (indexStats.failed_files ?? 0) === 0 &&
        (extractionSummary.total_skipped_error ?? 0) === 0;
    const complete = extractionComplete &&
        visibleSymbols.length === inScopeSymbols.length &&
        visibleRelationships.every((relationship) => hasVisibleRelationshipEndpoints(relationship, visibleSymbolKeys));
    const output = {
        schema_version: integrationTypes.CODEGRAPH_SCHEMA_VERSION,
        version: '2.0.0',
        tool: integrationTypes.CODEGRAPH_TOOL,
        tool_version: integrationTypes.CODEGRAPH_TOOL_VERSION,
        provider_status: complete ? 'complete' : 'partial',
        complete,
        counts: {
            discovered_symbols: symbols.length,
            emitted_symbols: visibleSymbols.length,
            excluded_symbols: symbols.length - visibleSymbols.length,
            discovered_relationships: relationships.length,
            emitted_relationships: visibleRelationships.length,
            excluded_relationships: relationships.length - visibleRelationships.length,
        },
        diagnostics: {
            unresolved_relationships: unresolvedRelationships,
        },
        generated_at: new Date().toISOString(),
        repo_path: repoPath,
        supported: extractionSummary.total_extracted > 0,
        language_coverage: languageCoverage,
        symbols: visibleSymbols,
        relationships: visibleRelationships,
        call_graph: visibleCallGraph,
        type_hierarchy: visibleTypeHierarchy,
        impact_radius: visibleImpactRadius,
        coverage: {
            total_symbols: visiblePublicSymbols.length,
            documented_symbols: 0, // post-MVP (T026)
            coverage_percent: 0.0, // post-MVP
        },
        index_stats: indexStats,
        extraction_summary: extractionSummary,
    };
    return output;
}
/** Build the provider-owned receipt without copying the full graph artifact. */
function assembleSummary(output) {
    return {
        schema_version: output.schema_version,
        tool: output.tool,
        tool_version: output.tool_version,
        provider_status: output.provider_status,
        complete: output.complete,
        counts: output.counts,
        diagnostics: output.diagnostics,
    };
}

function hasSymbolKey(value) {
    return typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value);
}
function hasVisibleRelationshipEndpoints(relationship, visibleSymbolKeys) {
    return hasSymbolKey(relationship.source_key) && hasSymbolKey(relationship.target_key) &&
        visibleSymbolKeys.has(relationship.source_key) && visibleSymbolKeys.has(relationship.target_key);
}
function hasKnownRelationshipEndpoints(relationship, discoveredSymbolKeys) {
    return hasSymbolKey(relationship.source_key) && hasSymbolKey(relationship.target_key) &&
        discoveredSymbolKeys.has(relationship.source_key) && discoveredSymbolKeys.has(relationship.target_key);
}
function hasVisibleCallEndpoints(edge, visibleSymbolKeys) {
    return hasSymbolKey(edge.caller_key) && hasSymbolKey(edge.callee_key) &&
        visibleSymbolKeys.has(edge.caller_key) && visibleSymbolKeys.has(edge.callee_key);
}
function hasVisibleTypeEndpoints(edge, visibleSymbolKeys) {
    return hasSymbolKey(edge.child_key) && hasSymbolKey(edge.parent_key) &&
        visibleSymbolKeys.has(edge.child_key) && visibleSymbolKeys.has(edge.parent_key);
}
function filterVisibleImpactEntry(entry, visibleSymbolKeys) {
    const affectedKeys = Array.isArray(entry.affected_keys) ? entry.affected_keys : [];
    const affectedNames = Array.isArray(entry.affected_names) ? entry.affected_names : [];
    const retainedIndexes = affectedKeys.reduce((indexes, key, index) => {
        if (hasSymbolKey(key) && visibleSymbolKeys.has(key)) {
            indexes.push(index);
        }
        return indexes;
    }, []);
    return {
        ...entry,
        affected_keys: retainedIndexes.map((index) => affectedKeys[index]),
        ...(affectedNames.length ? { affected_names: retainedIndexes.map((index) => affectedNames[index]) } : {}),
    };
}
function unresolvedRelationshipObservation(relationship) {
    return {
        kind: relationship.kind,
        ...(relationship.source_key ? { source_key: relationship.source_key } : {}),
        ...(relationship.target_key ? { target_key: relationship.target_key } : {}),
        ...(relationship.source_name ? { source_name: relationship.source_name } : {}),
        ...(relationship.target_name ? { target_name: relationship.target_name } : {}),
    };
}

function isHiddenDirectoryPath(filePath) {
    if (typeof filePath !== 'string')
        return false;
    const parts = filePath.replace(/\\/g, '/').split('/');
    return parts.slice(0, -1).some((part) => part.startsWith('.'));
}
/**
 * Maps a language identifier to a canonical file extension.
 */
function languageToExtension(language) {
    const map = {
        typescript: '.ts',
        javascript: '.js',
        tsx: '.tsx',
        jsx: '.jsx',
        python: '.py',
        go: '.go',
        rust: '.rs',
        java: '.java',
        c: '.c',
        cpp: '.cpp',
        csharp: '.cs',
        php: '.php',
        ruby: '.rb',
        swift: '.swift',
        kotlin: '.kt',
        dart: '.dart',
        svelte: '.svelte',
        liquid: '.liquid',
        pascal: '.pas',
    };
    return map[language.toLowerCase()];
}
// ---------------------------------------------------------------------------
// Bridge main entry point (T007)
// ---------------------------------------------------------------------------
/**
 * Main bridge entry point. Invoked when the file is run directly.
 * Not exported — use the module functions for testing.
 */
async function main() {
    // Node.js version check (T012)
    const nodeMajor = parseInt((process.version.replace('v', '').split('.')[0] ?? '0'), 10);
    if (nodeMajor < 18) {
        process.stderr.write(`[codegraph-bridge] ERROR: prerequisites: Node.js >= 18 required, got ${process.version}\n`);
        process.exit(1);
    }
    // Parse arguments
    let parsed;
    try {
        parsed = parseArgs(process.argv);
    }
    catch (err) {
        if (err instanceof UsageError) {
            process.stderr.write(`[codegraph-bridge] ERROR: ${err.message}\n`);
            process.exit(1);
        }
        throw err;
    }
    const { repoPath, outputPath, summaryPath, languages, depth } = parsed;
    // Timeout guard (T015)
    let timeoutId;
    const timeoutPromise = new Promise((_, reject) => {
        timeoutId = setTimeout(() => {
            reject(new Error(`Index build exceeded ${exports.BRIDGE_TIMEOUT_MS / 1000} seconds. ` +
                `Consider reducing scope with --languages flag.`));
        }, exports.BRIDGE_TIMEOUT_MS);
    });
    try {
        await Promise.race([
            runBridge(repoPath, outputPath, languages, depth, summaryPath),
            timeoutPromise,
        ]);
        clearTimeout(timeoutId);
        process.exit(0);
    }
    catch (err) {
        clearTimeout(timeoutId);
        const msg = err instanceof Error ? err.message : String(err);
        process.stderr.write(`[codegraph-bridge] ERROR: system: ${msg}\n`);
        process.exit(2);
    }
}
/**
 * Full bridge orchestration pipeline.
 * Exported for integration testing.
 */
async function runBridge(repoPath, outputPath, languages, depth, summaryPath) {
    // Step 1: Grammar init
    process.stderr.write('[codegraph-bridge] INFO: grammar init: starting\n');
    try {
        await adapter.initializeGrammars(languages);
    }
    catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        throw new Error(`grammar init total failure: ${msg}`);
    }
    process.stderr.write('[codegraph-bridge] INFO: grammar init: complete\n');
    // Step 2: Build index
    process.stderr.write(`[codegraph-bridge] INFO: index build: starting for ${repoPath}\n`);
    let cg;
    let indexResult;
    try {
        ({ cg, result: indexResult } = await adapter.buildIndex(repoPath, (current, total) => {
            process.stderr.write(`[codegraph-bridge] INFO: index progress: ${current}/${total}\n`);
        }));
    }
    catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        throw new Error(`index build failure: ${msg}`);
    }
    process.stderr.write('[codegraph-bridge] INFO: index build: complete\n');
    // Steps 3-9: Query
    process.stderr.write('[codegraph-bridge] INFO: query execution: starting\n');
    const [symbols, relationships] = await Promise.all([
        adapter.getSymbols(cg),
        adapter.getRelationships(cg),
    ]);
    const callGraph = relationships
        .filter((relationship) => relationship.kind === 'calls' && relationship.source_key && relationship.target_key)
        .map((relationship) => ({
        caller_key: relationship.source_key,
        callee_key: relationship.target_key,
        ...(relationship.source_name ? { caller_name: relationship.source_name } : {}),
        ...(relationship.target_name ? { callee_name: relationship.target_name } : {}),
    }));
    const typeHierarchy = relationships
        .filter((relationship) => (relationship.kind === 'extends' || relationship.kind === 'implements') && relationship.source_key && relationship.target_key)
        .map((relationship) => ({
        child_key: relationship.source_key,
        parent_key: relationship.target_key,
        ...(relationship.source_name ? { child_name: relationship.source_name } : {}),
        ...(relationship.target_name ? { parent_name: relationship.target_name } : {}),
        kind: relationship.kind,
    }));
    const publicSymbols = symbols.filter((symbol) => symbol.visibility === 'public' || symbol.is_exported === true);
    // Step 8: Impact radius for top 50 symbols by outgoing edge count
    const topSymbols = selectTopSymbols(symbols, callGraph, 50);
    const impactRadius = await adapter.getImpactRadius(cg, topSymbols, depth);
    process.stderr.write('[codegraph-bridge] INFO: query execution: complete\n');
    // Step 10-11: Stats
    const indexStats = adapter.getIndexStats(indexResult);
    const extractionSummary = adapter.getExtractionSummary(indexResult);
    // Step 12: Assemble output
    const output = assembleAnalysisOutput({
        repoPath,
        symbols,
        relationships,
        callGraph,
        typeHierarchy,
        impactRadius,
        publicSymbols,
        indexStats,
        extractionSummary,
    });
    // Step 13: Serialize
    const json = JSON.stringify(output, null, 2);
    // Check file size
    const sizeBytes = Buffer.byteLength(json, 'utf-8');
    const sizeMB = sizeBytes / (1024 * 1024);
    if (sizeMB > 50) {
        process.stderr.write(`[codegraph-bridge] WARN: output size ${sizeMB.toFixed(1)}MB exceeds 50MB threshold\n`);
    }
    // Step 14: Close index
    await adapter.closeIndex(cg);
    // Step 15: Atomic writes
    process.stderr.write(`[codegraph-bridge] INFO: writing output: ${outputPath}\n`);
    try {
        await atomicWrite(outputPath, json);
        if (summaryPath) {
            await atomicWrite(summaryPath, JSON.stringify(assembleSummary(output), null, 2));
        }
    }
    catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        throw new Error(`output write failure: ${msg}`);
    }
    process.stderr.write('[codegraph-bridge] INFO: bridge complete\n');
}
/**
 * Selects the top N symbols by outgoing call count.
 * Used for impact radius computation.
 */
function selectTopSymbols(symbols, callGraph, n) {
    const outgoing = new Map();
    for (const edge of callGraph) {
        outgoing.set(edge.caller_key, (outgoing.get(edge.caller_key) ?? 0) + 1);
    }
    return [...symbols]
        .sort((a, b) => (outgoing.get(b.symbol_key) ?? 0) - (outgoing.get(a.symbol_key) ?? 0))
        .slice(0, n)
        .map(s => s.symbol_key);
}
// Run when invoked directly
if (require.main === module || process.argv[1]?.endsWith('codegraph-bridge.ts') ||
    process.argv[1]?.endsWith('codegraph-bridge.js')) {
    main().catch(err => {
        process.stderr.write(`[codegraph-bridge] FATAL: ${err?.message ?? err}\n`);
        process.exit(2);
    });
}
//# sourceMappingURL=codegraph-bridge.js.map
