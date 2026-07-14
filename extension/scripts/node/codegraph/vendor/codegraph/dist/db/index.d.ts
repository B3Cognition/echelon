/**
 * Database Layer
 *
 * Handles SQLite database initialization and connection management.
 */
import { SqliteDatabase } from './sqlite-adapter';
import { SchemaVersion } from '../types';
export { SqliteDatabase, getActiveBackend } from './sqlite-adapter';
/**
 * Database connection wrapper with lifecycle management
 */
export declare class DatabaseConnection {
    private db;
    private dbPath;
    private constructor();
    /**
     * Initialize a new database at the given path
     */
    static initialize(dbPath: string): DatabaseConnection;
    /**
     * Open an existing database
     */
    static open(dbPath: string): DatabaseConnection;
    /**
     * Get the underlying database instance
     */
    getDb(): SqliteDatabase;
    /**
     * Get database file path
     */
    getPath(): string;
    /**
     * Get current schema version
     */
    getSchemaVersion(): SchemaVersion | null;
    /**
     * Execute a function within a transaction
     */
    transaction<T>(fn: () => T): T;
    /**
     * Get database file size in bytes
     */
    getSize(): number;
    /**
     * Optimize database (vacuum and analyze)
     */
    optimize(): void;
    /**
     * Close the database connection
     */
    close(): void;
    /**
     * Check if the database connection is open
     */
    isOpen(): boolean;
}
/**
 * Default database filename
 */
export declare const DATABASE_FILENAME = "codegraph.db";
/**
 * Get the default database path for a project
 */
export declare function getDatabasePath(projectRoot: string): string;
//# sourceMappingURL=index.d.ts.map