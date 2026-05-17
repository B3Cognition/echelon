/**
 * Config file writing for the CodeGraph installer
 * Writes to claude.json, settings.json, and CLAUDE.md
 */
export type InstallLocation = 'global' | 'local';
/**
 * Write the MCP server configuration to claude.json
 */
export declare function writeMcpConfig(location: InstallLocation): void;
/**
 * Write permissions to settings.json
 */
export declare function writePermissions(location: InstallLocation): void;
/**
 * Check if MCP config already exists for CodeGraph
 */
export declare function hasMcpConfig(location: InstallLocation): boolean;
/**
 * Check if permissions already exist for CodeGraph
 */
export declare function hasPermissions(location: InstallLocation): boolean;
/**
 * Check if CLAUDE.md has CodeGraph section
 */
export declare function hasClaudeMdSection(location: InstallLocation): boolean;
/**
 * Write or update CLAUDE.md with CodeGraph instructions
 *
 * If the file exists and has a CodeGraph section (marked or unmarked),
 * it will be replaced. Otherwise, the template is appended.
 */
export declare function writeClaudeMd(location: InstallLocation): {
    created: boolean;
    updated: boolean;
};
//# sourceMappingURL=config-writer.d.ts.map