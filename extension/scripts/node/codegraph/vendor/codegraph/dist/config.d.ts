/**
 * Configuration Management
 *
 * Load, save, and validate CodeGraph configuration.
 */
import { CodeGraphConfig, NodeKind } from './types';
/**
 * Configuration filename
 */
export declare const CONFIG_FILENAME = "config.json";
/**
 * Get the config file path for a project
 */
export declare function getConfigPath(projectRoot: string): string;
/**
 * Validate a configuration object
 */
export declare function validateConfig(config: unknown): config is CodeGraphConfig;
/**
 * Load configuration from a project
 */
export declare function loadConfig(projectRoot: string): CodeGraphConfig;
/**
 * Save configuration to a project
 */
export declare function saveConfig(projectRoot: string, config: CodeGraphConfig): void;
/**
 * Create default configuration for a new project
 */
export declare function createDefaultConfig(projectRoot: string): CodeGraphConfig;
/**
 * Update specific configuration values
 */
export declare function updateConfig(projectRoot: string, updates: Partial<CodeGraphConfig>): CodeGraphConfig;
/**
 * Add patterns to include list
 */
export declare function addIncludePatterns(projectRoot: string, patterns: string[]): CodeGraphConfig;
/**
 * Add patterns to exclude list
 */
export declare function addExcludePatterns(projectRoot: string, patterns: string[]): CodeGraphConfig;
/**
 * Add a custom pattern
 */
export declare function addCustomPattern(projectRoot: string, name: string, pattern: string, kind: NodeKind): CodeGraphConfig;
/**
 * Check if a file path matches the include/exclude patterns
 */
export declare function shouldIncludeFile(filePath: string, config: CodeGraphConfig): boolean;
//# sourceMappingURL=config.d.ts.map