"use strict";
/**
 * Configuration Management
 *
 * Load, save, and validate CodeGraph configuration.
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
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.CONFIG_FILENAME = void 0;
exports.getConfigPath = getConfigPath;
exports.validateConfig = validateConfig;
exports.loadConfig = loadConfig;
exports.saveConfig = saveConfig;
exports.createDefaultConfig = createDefaultConfig;
exports.updateConfig = updateConfig;
exports.addIncludePatterns = addIncludePatterns;
exports.addExcludePatterns = addExcludePatterns;
exports.addCustomPattern = addCustomPattern;
exports.shouldIncludeFile = shouldIncludeFile;
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const picomatch_1 = __importDefault(require("picomatch"));
const types_1 = require("./types");
const utils_1 = require("./utils");
/**
 * Configuration filename
 */
exports.CONFIG_FILENAME = 'config.json';
/**
 * Get the config file path for a project
 */
function getConfigPath(projectRoot) {
    return path.join(projectRoot, '.codegraph', exports.CONFIG_FILENAME);
}
/**
 * Check if a regex pattern is safe from ReDoS attacks.
 *
 * Rejects patterns with nested quantifiers (e.g., (a+)+, (a*)*) which
 * are the primary source of catastrophic backtracking. Also rejects
 * excessively long patterns and validates compilability.
 */
function isSafeRegex(pattern) {
    // Reject excessively long patterns
    if (pattern.length > 500)
        return false;
    // Reject nested quantifiers: (...)+ followed by +, *, or {
    // These are the primary cause of catastrophic backtracking
    if (/([+*}])\s*[+*{]/.test(pattern))
        return false;
    if (/\([^)]*[+*][^)]*\)[+*{]/.test(pattern))
        return false;
    // Verify the pattern is a valid regex
    try {
        new RegExp(pattern);
        return true;
    }
    catch {
        return false;
    }
}
/**
 * Validate a configuration object
 */
function validateConfig(config) {
    if (typeof config !== 'object' || config === null) {
        return false;
    }
    const c = config;
    // Required fields
    if (typeof c.version !== 'number')
        return false;
    if (typeof c.rootDir !== 'string')
        return false;
    if (!Array.isArray(c.include))
        return false;
    if (!Array.isArray(c.exclude))
        return false;
    if (!Array.isArray(c.languages))
        return false;
    if (!Array.isArray(c.frameworks))
        return false;
    if (typeof c.maxFileSize !== 'number')
        return false;
    if (typeof c.extractDocstrings !== 'boolean')
        return false;
    if (typeof c.trackCallSites !== 'boolean')
        return false;
    // Validate include/exclude are string arrays
    if (!c.include.every((p) => typeof p === 'string'))
        return false;
    if (!c.exclude.every((p) => typeof p === 'string'))
        return false;
    // Validate languages
    const validLanguages = [
        'typescript',
        'javascript',
        'python',
        'go',
        'rust',
        'java',
        'svelte',
        'unknown',
    ];
    if (!c.languages.every((l) => validLanguages.includes(l)))
        return false;
    // Validate frameworks
    for (const fw of c.frameworks) {
        if (typeof fw !== 'object' || fw === null)
            return false;
        const framework = fw;
        if (typeof framework.name !== 'string')
            return false;
    }
    // Validate custom patterns if present
    if (c.customPatterns !== undefined) {
        if (!Array.isArray(c.customPatterns))
            return false;
        for (const pattern of c.customPatterns) {
            if (typeof pattern !== 'object' || pattern === null)
                return false;
            const p = pattern;
            if (typeof p.name !== 'string')
                return false;
            if (typeof p.pattern !== 'string')
                return false;
            if (typeof p.kind !== 'string')
                return false;
            // Validate regex is compilable and reject patterns with known ReDoS risks
            if (!isSafeRegex(p.pattern))
                return false;
        }
    }
    return true;
}
/**
 * Merge configuration with defaults
 */
function mergeConfig(defaults, overrides) {
    return {
        version: overrides.version ?? defaults.version,
        rootDir: overrides.rootDir ?? defaults.rootDir,
        include: overrides.include ?? defaults.include,
        exclude: overrides.exclude ?? defaults.exclude,
        languages: overrides.languages ?? defaults.languages,
        frameworks: overrides.frameworks ?? defaults.frameworks,
        maxFileSize: overrides.maxFileSize ?? defaults.maxFileSize,
        extractDocstrings: overrides.extractDocstrings ?? defaults.extractDocstrings,
        trackCallSites: overrides.trackCallSites ?? defaults.trackCallSites,
        customPatterns: overrides.customPatterns ?? defaults.customPatterns,
    };
}
/**
 * Load configuration from a project
 */
function loadConfig(projectRoot) {
    const configPath = getConfigPath(projectRoot);
    if (!fs.existsSync(configPath)) {
        // Return default config with adjusted rootDir
        return {
            ...types_1.DEFAULT_CONFIG,
            rootDir: projectRoot,
        };
    }
    try {
        const content = fs.readFileSync(configPath, 'utf-8');
        const parsed = JSON.parse(content);
        // Merge with defaults to ensure all fields are present
        const merged = mergeConfig(types_1.DEFAULT_CONFIG, parsed);
        merged.rootDir = projectRoot; // Always use actual project root
        if (!validateConfig(merged)) {
            throw new Error('Invalid configuration format');
        }
        return merged;
    }
    catch (error) {
        if (error instanceof SyntaxError) {
            throw new Error(`Invalid JSON in config file: ${configPath}`);
        }
        throw error;
    }
}
/**
 * Save configuration to a project
 */
function saveConfig(projectRoot, config) {
    const configPath = getConfigPath(projectRoot);
    const dir = path.dirname(configPath);
    // Ensure directory exists
    if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
    }
    // Create a copy without rootDir (it's always derived from project path)
    const toSave = { ...config };
    delete toSave.rootDir;
    const content = JSON.stringify(toSave, null, 2);
    // Atomic write: write to temp file then rename to prevent partial/corrupt configs
    const tmpPath = configPath + '.tmp';
    fs.writeFileSync(tmpPath, content, 'utf-8');
    fs.renameSync(tmpPath, configPath);
}
/**
 * Create default configuration for a new project
 */
function createDefaultConfig(projectRoot) {
    return {
        ...types_1.DEFAULT_CONFIG,
        rootDir: projectRoot,
    };
}
/**
 * Update specific configuration values
 */
function updateConfig(projectRoot, updates) {
    const current = loadConfig(projectRoot);
    const updated = mergeConfig(current, updates);
    updated.rootDir = projectRoot;
    saveConfig(projectRoot, updated);
    return updated;
}
/**
 * Add patterns to include list
 */
function addIncludePatterns(projectRoot, patterns) {
    const config = loadConfig(projectRoot);
    const newPatterns = patterns.filter((p) => !config.include.includes(p));
    config.include = [...config.include, ...newPatterns];
    saveConfig(projectRoot, config);
    return config;
}
/**
 * Add patterns to exclude list
 */
function addExcludePatterns(projectRoot, patterns) {
    const config = loadConfig(projectRoot);
    const newPatterns = patterns.filter((p) => !config.exclude.includes(p));
    config.exclude = [...config.exclude, ...newPatterns];
    saveConfig(projectRoot, config);
    return config;
}
/**
 * Add a custom pattern
 */
function addCustomPattern(projectRoot, name, pattern, kind) {
    const config = loadConfig(projectRoot);
    if (!config.customPatterns) {
        config.customPatterns = [];
    }
    // Check for duplicate name
    const existing = config.customPatterns.find((p) => p.name === name);
    if (existing) {
        existing.pattern = pattern;
        existing.kind = kind;
    }
    else {
        config.customPatterns.push({ name, pattern, kind });
    }
    saveConfig(projectRoot, config);
    return config;
}
/**
 * Check if a file path matches the include/exclude patterns
 */
function shouldIncludeFile(filePath, config) {
    // Normalize to forward slashes so Windows backslash paths match glob patterns
    filePath = (0, utils_1.normalizePath)(filePath);
    // Simple glob matching (for now, just check if any pattern matches)
    // A full implementation would use a proper glob library
    const matchesPattern = (pattern, filePath) => {
        return picomatch_1.default.isMatch(filePath, pattern, { dot: true });
    };
    // Check exclude patterns first
    for (const pattern of config.exclude) {
        if (matchesPattern(pattern, filePath)) {
            return false;
        }
    }
    // Check include patterns
    for (const pattern of config.include) {
        if (matchesPattern(pattern, filePath)) {
            return true;
        }
    }
    // Default to not including if no pattern matches
    return false;
}
//# sourceMappingURL=config.js.map