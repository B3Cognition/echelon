"use strict";
/**
 * Sync Module
 *
 * Provides synchronization functionality for keeping the code graph
 * up-to-date with file system changes.
 *
 * Components:
 * - FileWatcher: Debounced fs.watch that auto-triggers sync on file changes
 * - Content hashing for change detection (in extraction module)
 * - Incremental reindexing (in extraction module)
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.FileWatcher = void 0;
var watcher_1 = require("./watcher");
Object.defineProperty(exports, "FileWatcher", { enumerable: true, get: function () { return watcher_1.FileWatcher; } });
//# sourceMappingURL=index.js.map