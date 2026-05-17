/**
 * Framework Resolver Registry
 *
 * Manages framework-specific resolvers.
 */
import { FrameworkResolver, ResolutionContext } from '../types';
/**
 * Get all framework resolvers
 */
export declare function getAllFrameworkResolvers(): FrameworkResolver[];
/**
 * Get a resolver by name
 */
export declare function getFrameworkResolver(name: string): FrameworkResolver | undefined;
/**
 * Detect which frameworks are used in a project
 */
export declare function detectFrameworks(context: ResolutionContext): FrameworkResolver[];
/**
 * Register a custom framework resolver
 */
export declare function registerFrameworkResolver(resolver: FrameworkResolver): void;
export { laravelResolver, FACADE_MAPPINGS } from './laravel';
export { expressResolver } from './express';
export { reactResolver } from './react';
export { svelteResolver } from './svelte';
export { djangoResolver, flaskResolver, fastapiResolver } from './python';
export { railsResolver } from './ruby';
export { springResolver } from './java';
export { goResolver } from './go';
export { rustResolver } from './rust';
export { aspnetResolver } from './csharp';
export { swiftUIResolver, uikitResolver, vaporResolver } from './swift';
//# sourceMappingURL=index.d.ts.map