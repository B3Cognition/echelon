# Persistent Game Stacks Design

**Status:** Proposed

## Purpose

Add reusable Echelon stack definitions for persistent games. The initial
catalog supports browser-first 3D games, iPhone-first augmented-reality games,
and browser-first WASM games. All three share a composable Postgres persistence
capability.

This work deliberately excludes real-time multiplayer. A future, separately
selected capability will cover authoritative rooms, WebSockets, matchmaking,
snapshots, reconciliation, and anti-cheat rules.

## Stack catalog

```text
game-persistence-postgres        capability: saves and durable game data
browser-3d-game                  archetype: browser 3D client
ios-ar-game                      archetype: native iPhone AR client
browser-wasm-game                archetype: browser client with a WASM module
```

Each project selects `game-persistence-postgres` and exactly one client
archetype. The persistence capability does not imply an application framework,
hosting vendor, real-time transport, or ORM. It establishes Postgres as the
durable source of truth and requires migrations, server-side validation of
privileged mutations, and authenticated access boundaries.

## Composition

Example selections:

```yaml
# Browser 3D game
stacks:
  target_archetypes: [browser_3d_game]
  selected: [game-persistence-postgres, browser-3d-game]

# iPhone AR game
stacks:
  target_archetypes: [ios_ar_game]
  selected: [game-persistence-postgres, ios-ar-game]

# Browser WASM game
stacks:
  target_archetypes: [browser_wasm_game]
  selected: [game-persistence-postgres, browser-wasm-game]
```

The persistence stack applies to all three target archetypes so the existing
resolver accepts each composition. Archetypes do not imply persistence: a
prototype can intentionally remain non-persistent, and a persistence decision
is visible in project configuration.

## Client archetypes

### `browser-3d-game`

Use TypeScript, pnpm, Vite, React, Three.js, React Three Fiber, and Drei.
Browser memory owns rendering, input, animation, and other frame-rate state.
Persist progress only at deliberate game boundaries; browser storage may cache
or support offline play but is not the durable source of truth.

### `ios-ar-game`

Use Swift, SwiftUI, RealityKit, and ARKit. The app owns AR session and render
state locally. Durable player data uses the shared persistence API and must not
depend on AR session state remaining available across launches.

### `browser-wasm-game`

Use TypeScript, pnpm, Vite, React, and a Rust-to-WASM gameplay module. The
WASM module contains deterministic, performance-sensitive gameplay logic;
browser TypeScript owns UI, rendering integration, and network boundaries.
WASM does not change the persistence or authority model.

## Shared persistence rules

- Store accounts, player profiles, inventories, progress, save snapshots, and
  durable leaderboards in Postgres.
- Make schema changes through checked-in migrations and test migrations in the
  verification path.
- Treat rewards, inventory changes, and leaderboard submissions as privileged
  server-side mutations. A client may request an action but does not author the
  durable outcome.
- Validate inputs at the API boundary and authorize every data mutation.
- Do not write database state every render or simulation tick. Persist at
  checkpoints, explicit save events, session end, and bounded periodic
  snapshots when needed.
- Do not select a second durable database, direct unauthenticated database
  access, or client-only storage as the source of truth without an explicit
  architecture amendment.

## Representation

Each stack receives a `runtime/stacks/<stack-id>/stack.yml` and `context.md`.
The YAML declares its archetypes, capabilities, required host commands, source
tree detection evidence, and agent-readable context. The context files express
the operational rules above in the resolved stack contract injected into both
Phase A and Phase B prompts.

The existing schema has no native `game.*` namespace, so game-specific facts
will use the supported `x.game.*` extension namespace. Existing `data.*`,
`web_app.*`, `test.*`, `delivery.*`, and `docs.*` namespaces carry generic
capabilities.

## Guardrails and verification

Stack context steers authoring and delivery agents, while the existing
preflight system checks required host commands. The initial delivery adds
declarative stack files and tests that the stack loader and resolver accept
valid intended combinations and reject mismatched archetypes.

It does not yet make forbidden package selection a deterministic CI failure.
A follow-up should add a stack validation-command contract and a
`validate-game-stack` script that checks dependency allow/deny lists,
migrations, and privileged API boundaries.

## Out of scope

- Authoritative real-time multiplayer, matchmaking, or anti-cheat runtime.
- A database vendor, managed hosting provider, ORM, or authentication provider.
- Project scaffolding or an example game.
- App Store signing, device provisioning, or release automation.
