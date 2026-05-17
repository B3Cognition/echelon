"use strict";
/**
 * Config file writing for the CodeGraph installer
 * Writes to claude.json, settings.json, and CLAUDE.md
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
exports.writeMcpConfig = writeMcpConfig;
exports.writePermissions = writePermissions;
exports.hasMcpConfig = hasMcpConfig;
exports.hasPermissions = hasPermissions;
exports.hasClaudeMdSection = hasClaudeMdSection;
exports.writeClaudeMd = writeClaudeMd;
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const os = __importStar(require("os"));
const claude_md_template_1 = require("./claude-md-template");
/**
 * Get the path to the Claude config directory
 */
function getClaudeConfigDir(location) {
    if (location === 'global') {
        return path.join(os.homedir(), '.claude');
    }
    return path.join(process.cwd(), '.claude');
}
/**
 * Get the path to the claude.json file
 * - Global: ~/.claude.json (root level)
 * - Local: ./.claude.json (project root)
 */
function getClaudeJsonPath(location) {
    if (location === 'global') {
        return path.join(os.homedir(), '.claude.json');
    }
    return path.join(process.cwd(), '.claude.json');
}
/**
 * Get the path to the settings.json file
 * - Global: ~/.claude/settings.json
 * - Local: ./.claude/settings.json
 */
function getSettingsJsonPath(location) {
    const configDir = getClaudeConfigDir(location);
    return path.join(configDir, 'settings.json');
}
/**
 * Read a JSON file, returning an empty object if it doesn't exist.
 * Distinguishes between missing files (returns {}) and corrupted
 * files (logs warning, returns {}).
 */
function readJsonFile(filePath) {
    if (!fs.existsSync(filePath)) {
        return {};
    }
    try {
        const content = fs.readFileSync(filePath, 'utf-8');
        return JSON.parse(content);
    }
    catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        console.warn(`  Warning: Could not parse ${path.basename(filePath)}: ${msg}`);
        console.warn(`  A backup will be created before overwriting.`);
        // Create a backup of the corrupted file
        try {
            const backupPath = filePath + '.backup';
            fs.copyFileSync(filePath, backupPath);
        }
        catch { /* ignore backup failure */ }
        return {};
    }
}
/**
 * Write a file atomically by writing to a temp file then renaming.
 * Prevents corruption if the process crashes mid-write.
 */
function atomicWriteFileSync(filePath, content) {
    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
    }
    const tmpPath = filePath + '.tmp.' + process.pid;
    try {
        fs.writeFileSync(tmpPath, content);
        fs.renameSync(tmpPath, filePath);
    }
    catch (err) {
        // Clean up temp file on failure
        try {
            fs.unlinkSync(tmpPath);
        }
        catch { /* ignore */ }
        throw err;
    }
}
/**
 * Write a JSON file, creating parent directories if needed
 */
function writeJsonFile(filePath, data) {
    atomicWriteFileSync(filePath, JSON.stringify(data, null, 2) + '\n');
}
/**
 * Get the MCP server configuration
 */
function getMcpServerConfig() {
    return {
        type: 'stdio',
        command: 'codegraph',
        args: ['serve', '--mcp'],
    };
}
/**
 * Write the MCP server configuration to claude.json
 */
function writeMcpConfig(location) {
    const claudeJsonPath = getClaudeJsonPath(location);
    const config = readJsonFile(claudeJsonPath);
    // Ensure mcpServers object exists
    if (!config.mcpServers) {
        config.mcpServers = {};
    }
    // Add or update codegraph server
    config.mcpServers.codegraph = getMcpServerConfig();
    writeJsonFile(claudeJsonPath, config);
}
/**
 * Get the list of permissions for CodeGraph tools
 */
function getCodeGraphPermissions() {
    return [
        'mcp__codegraph__codegraph_search',
        'mcp__codegraph__codegraph_context',
        'mcp__codegraph__codegraph_callers',
        'mcp__codegraph__codegraph_callees',
        'mcp__codegraph__codegraph_impact',
        'mcp__codegraph__codegraph_node',
        'mcp__codegraph__codegraph_status',
    ];
}
/**
 * Write permissions to settings.json
 */
function writePermissions(location) {
    const settingsPath = getSettingsJsonPath(location);
    const settings = readJsonFile(settingsPath);
    // Ensure permissions object exists
    if (!settings.permissions) {
        settings.permissions = {};
    }
    // Ensure allow array exists
    if (!Array.isArray(settings.permissions.allow)) {
        settings.permissions.allow = [];
    }
    // Add CodeGraph permissions (avoiding duplicates)
    const codegraphPermissions = getCodeGraphPermissions();
    for (const permission of codegraphPermissions) {
        if (!settings.permissions.allow.includes(permission)) {
            settings.permissions.allow.push(permission);
        }
    }
    writeJsonFile(settingsPath, settings);
}
/**
 * Check if MCP config already exists for CodeGraph
 */
function hasMcpConfig(location) {
    const claudeJsonPath = getClaudeJsonPath(location);
    const config = readJsonFile(claudeJsonPath);
    return !!config.mcpServers?.codegraph;
}
/**
 * Check if permissions already exist for CodeGraph
 */
function hasPermissions(location) {
    const settingsPath = getSettingsJsonPath(location);
    const settings = readJsonFile(settingsPath);
    const permissions = settings.permissions?.allow;
    if (!Array.isArray(permissions)) {
        return false;
    }
    // Check if at least one CodeGraph permission exists
    return permissions.some((p) => p.startsWith('mcp__codegraph__'));
}
/**
 * Get the path to CLAUDE.md
 * - Global: ~/.claude/CLAUDE.md
 * - Local: ./.claude/CLAUDE.md
 */
function getClaudeMdPath(location) {
    const configDir = getClaudeConfigDir(location);
    return path.join(configDir, 'CLAUDE.md');
}
/**
 * Check if CLAUDE.md has CodeGraph section
 */
function hasClaudeMdSection(location) {
    const claudeMdPath = getClaudeMdPath(location);
    try {
        if (fs.existsSync(claudeMdPath)) {
            const content = fs.readFileSync(claudeMdPath, 'utf-8');
            return content.includes(claude_md_template_1.CODEGRAPH_SECTION_START) || content.includes('## CodeGraph');
        }
    }
    catch {
        // Ignore errors
    }
    return false;
}
/**
 * Write or update CLAUDE.md with CodeGraph instructions
 *
 * If the file exists and has a CodeGraph section (marked or unmarked),
 * it will be replaced. Otherwise, the template is appended.
 */
function writeClaudeMd(location) {
    const claudeMdPath = getClaudeMdPath(location);
    const configDir = getClaudeConfigDir(location);
    // Ensure directory exists
    if (!fs.existsSync(configDir)) {
        fs.mkdirSync(configDir, { recursive: true });
    }
    // Check if file exists
    if (!fs.existsSync(claudeMdPath)) {
        // Create new file with just the CodeGraph section
        atomicWriteFileSync(claudeMdPath, claude_md_template_1.CLAUDE_MD_TEMPLATE + '\n');
        return { created: true, updated: false };
    }
    // Read existing content
    let content = fs.readFileSync(claudeMdPath, 'utf-8');
    // Check for marked section (from previous installer)
    if (content.includes(claude_md_template_1.CODEGRAPH_SECTION_START)) {
        // Replace the marked section
        const startIdx = content.indexOf(claude_md_template_1.CODEGRAPH_SECTION_START);
        const endIdx = content.indexOf(claude_md_template_1.CODEGRAPH_SECTION_END);
        if (endIdx > startIdx) {
            // Replace existing marked section
            const before = content.substring(0, startIdx);
            const after = content.substring(endIdx + claude_md_template_1.CODEGRAPH_SECTION_END.length);
            content = before + claude_md_template_1.CLAUDE_MD_TEMPLATE + after;
            atomicWriteFileSync(claudeMdPath, content);
            return { created: false, updated: true };
        }
    }
    // Check for unmarked "## CodeGraph" section (from manual setup)
    const codegraphHeaderRegex = /\n## CodeGraph\n/;
    const match = content.match(codegraphHeaderRegex);
    if (match && match.index !== undefined) {
        // Find the end of the CodeGraph section (next h2 header or end of file)
        // Use negative lookahead (?!#) to match "## X" but not "### X"
        const sectionStart = match.index;
        const afterSection = content.substring(sectionStart + 1);
        const nextHeaderMatch = afterSection.match(/\n## (?!#)/);
        let sectionEnd;
        if (nextHeaderMatch && nextHeaderMatch.index !== undefined) {
            sectionEnd = sectionStart + 1 + nextHeaderMatch.index;
        }
        else {
            sectionEnd = content.length;
        }
        // Replace the section
        const before = content.substring(0, sectionStart);
        const after = content.substring(sectionEnd);
        content = before + '\n' + claude_md_template_1.CLAUDE_MD_TEMPLATE + after;
        atomicWriteFileSync(claudeMdPath, content);
        return { created: false, updated: true };
    }
    // No existing section, append to end
    content = content.trimEnd() + '\n\n' + claude_md_template_1.CLAUDE_MD_TEMPLATE + '\n';
    atomicWriteFileSync(claudeMdPath, content);
    return { created: false, updated: false };
}
//# sourceMappingURL=config-writer.js.map