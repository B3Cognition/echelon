# TypeScript Code Review Rules

## Strict Mode

- `strict: true` MUST be enabled in `tsconfig.json`. No exceptions.
- `noImplicitAny: true` — every variable, parameter, and return type must have an explicit type or be inferrable.
- `strictNullChecks: true` — null and undefined must be handled explicitly.

## Type Safety

- **No `any` type.** Do not use `any`, `as any`, or `<any>`. Use `unknown` when the type is truly unknown, then narrow with type guards.
- **No non-null assertions (`!`).** Use optional chaining (`?.`), nullish coalescing (`??`), or explicit type narrowing instead.
- **No `as` type assertions** unless justified with a comment explaining why the assertion is safe. Prefer type guards or discriminated unions.
- **Prefer `unknown` over `any`** for values from external sources (API responses, JSON parsing, user input).
- **Use `readonly` for immutable data.** Arrays that should not be mutated use `readonly T[]` or `ReadonlyArray<T>`.

## Error Handling

- **Every `async` function must have error handling** or propagate errors explicitly. No unhandled promise rejections.
- **Use typed error classes** or discriminated union results (`Result<T, E>`) instead of throwing raw strings.
- **No bare `catch` blocks.** Always type the error parameter: `catch (error: unknown)` and narrow before using.
- **Error boundaries at system edges.** API handlers, event listeners, and integration points must catch and handle errors.
- **No `try/catch` around synchronous code** unless it interacts with APIs that throw (e.g., JSON.parse).

## Null Safety

- **Prefer optional chaining (`?.`)** over manual null checks for property access chains.
- **Use nullish coalescing (`??`)** instead of logical OR (`||`) for default values — `||` coerces falsy values (0, "", false).
- **Explicit return types on functions** that may return `null` or `undefined`: `function find(): T | null`.
- **No implicit undefined returns.** If a function can return nothing, declare `void` or `undefined` explicitly.

## Imports and Modules

- **No `import *` (barrel imports)** unless explicitly allowed by project ADR. Use named imports.
- **No circular dependencies.** If detected, refactor to break the cycle.
- **Use path aliases** configured in `tsconfig.json` instead of deep relative paths (`../../../`).

## Generics

- **Do not over-generalize.** A generic type parameter must be used in at least 2 positions (input and output, or constrained).
- **Name generic parameters descriptively** for complex generics: `TInput`, `TOutput` rather than `T`, `U`.
- **Constrain generics** with `extends` when the function depends on specific properties.

## Enums and Constants

- **Prefer `const` enums or string literal unions** over regular enums for serialization safety.
- **No magic numbers or strings.** Extract to named constants with descriptive names.

## Async Patterns

- **Use `async/await`** over raw `.then()` chains for readability.
- **No floating promises.** Every promise must be `await`ed, returned, or explicitly voided with `void promise`.
- **Use `Promise.all`** for independent concurrent operations, not sequential `await` in a loop.
