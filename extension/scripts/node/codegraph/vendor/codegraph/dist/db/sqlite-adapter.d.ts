/**
 * SQLite Adapter
 *
 * Provides a unified interface over better-sqlite3 (native) and
 * node-sqlite3-wasm (WASM fallback) for universal cross-platform support.
 */
export interface SqliteStatement {
    run(...params: any[]): {
        changes: number;
        lastInsertRowid: number | bigint;
    };
    get(...params: any[]): any;
    all(...params: any[]): any[];
}
export interface SqliteDatabase {
    prepare(sql: string): SqliteStatement;
    exec(sql: string): void;
    pragma(str: string): any;
    transaction<T>(fn: (...args: any[]) => T): (...args: any[]) => T;
    close(): void;
    readonly open: boolean;
}
export type SqliteBackend = 'native' | 'wasm';
/**
 * Get the currently active SQLite backend.
 */
export declare function getActiveBackend(): SqliteBackend | null;
/**
 * Create a database connection. Tries native better-sqlite3 first,
 * falls back to node-sqlite3-wasm.
 */
export declare function createDatabase(dbPath: string): SqliteDatabase;
//# sourceMappingURL=sqlite-adapter.d.ts.map