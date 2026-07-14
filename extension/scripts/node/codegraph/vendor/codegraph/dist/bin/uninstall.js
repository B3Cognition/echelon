#!/usr/bin/env node
"use strict";
/**
 * CodeGraph preuninstall cleanup script
 *
 * Runs automatically when `npm uninstall -g @colbymchenry/codegraph` is called.
 * Removes all CodeGraph configuration from Claude Code:
 *   - MCP server entry from ~/.claude.json
 *   - Permissions from ~/.claude/settings.json
 *   - CodeGraph section from ~/.claude/CLAUDE.md
 *
 * This script must never throw — a failed cleanup must not block uninstall.
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
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const os = __importStar(require("os"));
const CODEGRAPH_SECTION_START = '<!-- CODEGRAPH_START -->';
const CODEGRAPH_SECTION_END = '<!-- CODEGRAPH_END -->';
function readJson(filePath) {
    try {
        if (!fs.existsSync(filePath))
            return null;
        return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
    }
    catch {
        return null;
    }
}
function writeJson(filePath, data) {
    fs.writeFileSync(filePath, JSON.stringify(data, null, 2) + '\n');
}
/**
 * Remove CodeGraph MCP server from ~/.claude.json
 */
function removeMcpConfig() {
    const filePath = path.join(os.homedir(), '.claude.json');
    const config = readJson(filePath);
    if (!config?.mcpServers?.codegraph)
        return;
    delete config.mcpServers.codegraph;
    // Clean up empty mcpServers object
    if (Object.keys(config.mcpServers).length === 0) {
        delete config.mcpServers;
    }
    writeJson(filePath, config);
}
/**
 * Remove CodeGraph permissions from ~/.claude/settings.json
 */
function removeSettings() {
    const filePath = path.join(os.homedir(), '.claude', 'settings.json');
    const settings = readJson(filePath);
    if (!settings)
        return;
    // Remove codegraph permissions
    if (Array.isArray(settings.permissions?.allow)) {
        const before = settings.permissions.allow.length;
        settings.permissions.allow = settings.permissions.allow.filter((p) => !p.startsWith('mcp__codegraph__'));
        if (settings.permissions.allow.length === before)
            return;
        // Clean up empty allow array
        if (settings.permissions.allow.length === 0) {
            delete settings.permissions.allow;
        }
        // Clean up empty permissions object
        if (Object.keys(settings.permissions).length === 0) {
            delete settings.permissions;
        }
        writeJson(filePath, settings);
    }
}
/**
 * Remove CodeGraph section from ~/.claude/CLAUDE.md
 */
function removeClaudeMd() {
    const filePath = path.join(os.homedir(), '.claude', 'CLAUDE.md');
    try {
        if (!fs.existsSync(filePath))
            return;
        let content = fs.readFileSync(filePath, 'utf-8');
        // Remove marked section
        const startIdx = content.indexOf(CODEGRAPH_SECTION_START);
        const endIdx = content.indexOf(CODEGRAPH_SECTION_END);
        if (startIdx !== -1 && endIdx > startIdx) {
            const before = content.substring(0, startIdx).trimEnd();
            const after = content.substring(endIdx + CODEGRAPH_SECTION_END.length).trimStart();
            content = before + (before && after ? '\n\n' : '') + after;
            if (content.trim() === '') {
                // File is empty after removing section — delete it
                fs.unlinkSync(filePath);
            }
            else {
                fs.writeFileSync(filePath, content.trim() + '\n');
            }
        }
    }
    catch {
        // Never fail
    }
}
// Run cleanup — never throw
try {
    removeMcpConfig();
}
catch { /* ignore */ }
try {
    removeSettings();
}
catch { /* ignore */ }
try {
    removeClaudeMd();
}
catch { /* ignore */ }
//# sourceMappingURL=uninstall.js.map