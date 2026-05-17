"use strict";
/**
 * Database Layer
 *
 * Handles SQLite database initialization and connection management.
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
exports.DATABASE_FILENAME = exports.DatabaseConnection = exports.getActiveBackend = void 0;
exports.getDatabasePath = getDatabasePath;
const sqlite_adapter_1 = require("./sqlite-adapter");
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const migrations_1 = require("./migrations");
var sqlite_adapter_2 = require("./sqlite-adapter");
Object.defineProperty(exports, "getActiveBackend", { enumerable: true, get: function () { return sqlite_adapter_2.getActiveBackend; } });
/**
 * Database connection wrapper with lifecycle management
 */
class DatabaseConnection {
    db;
    dbPath;
    constructor(db, dbPath) {
        this.db = db;
        this.dbPath = dbPath;
    }
    /**
     * Initialize a new database at the given path
     */
    static initialize(dbPath) {
        // Ensure parent directory exists
        const dir = path.dirname(dbPath);
        if (!fs.existsSync(dir)) {
            fs.mkdirSync(dir, { recursive: true });
        }
        // Create and configure database
        const db = (0, sqlite_adapter_1.createDatabase)(dbPath);
        // Enable foreign keys and WAL mode for better performance
        db.pragma('foreign_keys = ON');
        db.pragma('journal_mode = WAL');
        // Wait up to 2 minutes if database is locked by another process
        // (indexing operations can hold locks for extended periods)
        db.pragma('busy_timeout = 120000');
        // Performance tuning
        db.pragma('synchronous = NORMAL'); // Safe with WAL mode
        db.pragma('cache_size = -64000'); // 64 MB page cache
        db.pragma('temp_store = MEMORY'); // Temp tables in memory
        db.pragma('mmap_size = 268435456'); // 256 MB memory-mapped I/O
        // Run schema initialization
        const schemaPath = path.join(__dirname, 'schema.sql');
        const schema = fs.readFileSync(schemaPath, 'utf-8');
        db.exec(schema);
        // Record current schema version so migrations aren't re-applied on open
        const currentVersion = (0, migrations_1.getCurrentVersion)(db);
        if (currentVersion < migrations_1.CURRENT_SCHEMA_VERSION) {
            db.prepare('INSERT OR IGNORE INTO schema_versions (version, applied_at, description) VALUES (?, ?, ?)').run(migrations_1.CURRENT_SCHEMA_VERSION, Date.now(), 'Initial schema includes all migrations');
        }
        return new DatabaseConnection(db, dbPath);
    }
    /**
     * Open an existing database
     */
    static open(dbPath) {
        if (!fs.existsSync(dbPath)) {
            throw new Error(`Database not found: ${dbPath}`);
        }
        const db = (0, sqlite_adapter_1.createDatabase)(dbPath);
        // Enable foreign keys and WAL mode
        db.pragma('foreign_keys = ON');
        db.pragma('journal_mode = WAL');
        // Wait up to 2 minutes if database is locked by another process
        // (indexing operations can hold locks for extended periods)
        db.pragma('busy_timeout = 120000');
        // Performance tuning
        db.pragma('synchronous = NORMAL');
        db.pragma('cache_size = -64000');
        db.pragma('temp_store = MEMORY');
        db.pragma('mmap_size = 268435456');
        // Check and run migrations if needed
        const conn = new DatabaseConnection(db, dbPath);
        const currentVersion = (0, migrations_1.getCurrentVersion)(db);
        if (currentVersion < migrations_1.CURRENT_SCHEMA_VERSION) {
            (0, migrations_1.runMigrations)(db, currentVersion);
        }
        return conn;
    }
    /**
     * Get the underlying database instance
     */
    getDb() {
        return this.db;
    }
    /**
     * Get database file path
     */
    getPath() {
        return this.dbPath;
    }
    /**
     * Get current schema version
     */
    getSchemaVersion() {
        const row = this.db
            .prepare('SELECT version, applied_at, description FROM schema_versions ORDER BY version DESC LIMIT 1')
            .get();
        if (!row)
            return null;
        return {
            version: row.version,
            appliedAt: row.applied_at,
            description: row.description ?? undefined,
        };
    }
    /**
     * Execute a function within a transaction
     */
    transaction(fn) {
        return this.db.transaction(fn)();
    }
    /**
     * Get database file size in bytes
     */
    getSize() {
        const stats = fs.statSync(this.dbPath);
        return stats.size;
    }
    /**
     * Optimize database (vacuum and analyze)
     */
    optimize() {
        this.db.exec('VACUUM');
        this.db.exec('ANALYZE');
    }
    /**
     * Close the database connection
     */
    close() {
        this.db.close();
    }
    /**
     * Check if the database connection is open
     */
    isOpen() {
        return this.db.open;
    }
}
exports.DatabaseConnection = DatabaseConnection;
/**
 * Default database filename
 */
exports.DATABASE_FILENAME = 'codegraph.db';
/**
 * Get the default database path for a project
 */
function getDatabasePath(projectRoot) {
    return path.join(projectRoot, '.codegraph', exports.DATABASE_FILENAME);
}
//# sourceMappingURL=index.js.map