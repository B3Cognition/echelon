"use strict";
/**
 * Framework Resolver Registry
 *
 * Manages framework-specific resolvers.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.vaporResolver = exports.uikitResolver = exports.swiftUIResolver = exports.aspnetResolver = exports.rustResolver = exports.goResolver = exports.springResolver = exports.railsResolver = exports.fastapiResolver = exports.flaskResolver = exports.djangoResolver = exports.svelteResolver = exports.reactResolver = exports.expressResolver = exports.FACADE_MAPPINGS = exports.laravelResolver = void 0;
exports.getAllFrameworkResolvers = getAllFrameworkResolvers;
exports.getFrameworkResolver = getFrameworkResolver;
exports.detectFrameworks = detectFrameworks;
exports.registerFrameworkResolver = registerFrameworkResolver;
const laravel_1 = require("./laravel");
const express_1 = require("./express");
const react_1 = require("./react");
const svelte_1 = require("./svelte");
const python_1 = require("./python");
const ruby_1 = require("./ruby");
const java_1 = require("./java");
const go_1 = require("./go");
const rust_1 = require("./rust");
const csharp_1 = require("./csharp");
const swift_1 = require("./swift");
/**
 * All registered framework resolvers
 */
const FRAMEWORK_RESOLVERS = [
    // PHP
    laravel_1.laravelResolver,
    // JavaScript/TypeScript
    express_1.expressResolver,
    react_1.reactResolver,
    svelte_1.svelteResolver,
    // Python
    python_1.djangoResolver,
    python_1.flaskResolver,
    python_1.fastapiResolver,
    // Ruby
    ruby_1.railsResolver,
    // Java
    java_1.springResolver,
    // Go
    go_1.goResolver,
    // Rust
    rust_1.rustResolver,
    // C#
    csharp_1.aspnetResolver,
    // Swift
    swift_1.swiftUIResolver,
    swift_1.uikitResolver,
    swift_1.vaporResolver,
];
/**
 * Get all framework resolvers
 */
function getAllFrameworkResolvers() {
    return FRAMEWORK_RESOLVERS;
}
/**
 * Get a resolver by name
 */
function getFrameworkResolver(name) {
    return FRAMEWORK_RESOLVERS.find((r) => r.name === name);
}
/**
 * Detect which frameworks are used in a project
 */
function detectFrameworks(context) {
    return FRAMEWORK_RESOLVERS.filter((resolver) => {
        try {
            return resolver.detect(context);
        }
        catch {
            return false;
        }
    });
}
/**
 * Register a custom framework resolver
 */
function registerFrameworkResolver(resolver) {
    // Remove existing resolver with same name
    const index = FRAMEWORK_RESOLVERS.findIndex((r) => r.name === resolver.name);
    if (index !== -1) {
        FRAMEWORK_RESOLVERS.splice(index, 1);
    }
    FRAMEWORK_RESOLVERS.push(resolver);
}
// Re-export framework resolvers
var laravel_2 = require("./laravel");
Object.defineProperty(exports, "laravelResolver", { enumerable: true, get: function () { return laravel_2.laravelResolver; } });
Object.defineProperty(exports, "FACADE_MAPPINGS", { enumerable: true, get: function () { return laravel_2.FACADE_MAPPINGS; } });
var express_2 = require("./express");
Object.defineProperty(exports, "expressResolver", { enumerable: true, get: function () { return express_2.expressResolver; } });
var react_2 = require("./react");
Object.defineProperty(exports, "reactResolver", { enumerable: true, get: function () { return react_2.reactResolver; } });
var svelte_2 = require("./svelte");
Object.defineProperty(exports, "svelteResolver", { enumerable: true, get: function () { return svelte_2.svelteResolver; } });
var python_2 = require("./python");
Object.defineProperty(exports, "djangoResolver", { enumerable: true, get: function () { return python_2.djangoResolver; } });
Object.defineProperty(exports, "flaskResolver", { enumerable: true, get: function () { return python_2.flaskResolver; } });
Object.defineProperty(exports, "fastapiResolver", { enumerable: true, get: function () { return python_2.fastapiResolver; } });
var ruby_2 = require("./ruby");
Object.defineProperty(exports, "railsResolver", { enumerable: true, get: function () { return ruby_2.railsResolver; } });
var java_2 = require("./java");
Object.defineProperty(exports, "springResolver", { enumerable: true, get: function () { return java_2.springResolver; } });
var go_2 = require("./go");
Object.defineProperty(exports, "goResolver", { enumerable: true, get: function () { return go_2.goResolver; } });
var rust_2 = require("./rust");
Object.defineProperty(exports, "rustResolver", { enumerable: true, get: function () { return rust_2.rustResolver; } });
var csharp_2 = require("./csharp");
Object.defineProperty(exports, "aspnetResolver", { enumerable: true, get: function () { return csharp_2.aspnetResolver; } });
var swift_2 = require("./swift");
Object.defineProperty(exports, "swiftUIResolver", { enumerable: true, get: function () { return swift_2.swiftUIResolver; } });
Object.defineProperty(exports, "uikitResolver", { enumerable: true, get: function () { return swift_2.uikitResolver; } });
Object.defineProperty(exports, "vaporResolver", { enumerable: true, get: function () { return swift_2.vaporResolver; } });
//# sourceMappingURL=index.js.map