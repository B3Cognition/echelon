# Browser WASM Game

Use TypeScript, pnpm, Vite, and React for the browser shell, with a
Rust-to-WASM module for deterministic or performance-sensitive gameplay logic.
Keep UI, rendering integration, input bindings, and durable/network boundaries
in TypeScript unless a measured performance requirement calls for WASM.

Keep the WASM module focused on gameplay computation and expose a small,
explicit interface to the browser. WASM does not bypass the persistence or
authority model: client code may request durable mutations, while the server
validates, authorizes, and persists the result.

Use Cargo and wasm-pack to build the gameplay module, and run browser tests
through the Vite/React toolchain. Do not use browser storage as the durable
source of player progression.
