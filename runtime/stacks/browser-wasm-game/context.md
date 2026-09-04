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

## User-runnability contract

This stack requires a fresh Linux-container user journey. Put candidate-specific
commands and observations in `.echelon/runnability.yml`, not in global stack
configuration. Declare install/build steps for both pnpm and Rust/WASM, the real
start/readiness path, a primary journey with a harness-observed `browser_dom`
result, and teardown commands. Test success or a project command that merely
exits zero is not user-runnability evidence.

After a passing run, `echelon delivery status <spec_id>` prints the exact local
commands and evidence path. An owner may explicitly record follow-up scope with
`echelon spec defer-runnability <spec_id> --reason "<reason>"`; otherwise a
missing, failed, or stale contract remains current-spec repair work.
