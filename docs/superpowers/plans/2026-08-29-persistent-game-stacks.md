# Persistent Game Stacks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four composable Echelon stack definitions that let projects select one persistent-game client archetype and shared Postgres persistence guidance.

**Architecture:** Add only declarative `stack.yml` and `context.md` files under `runtime/stacks/`; do not change stack parser or resolver behavior. The shared persistence capability applies to all three game client archetypes, while each archetype exposes a distinct `x.game.client_runtime` capability so mutually incompatible clients fail deterministic stack resolution.

**Tech Stack:** Echelon stack schema v1.0, YAML, Markdown, Python pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-persistent-game-stacks-design.md`

## Global Constraints

- Add `game-persistence-postgres`, `browser-3d-game`, `ios-ar-game`, and `browser-wasm-game`; no real-time multiplayer stack is part of this change.
- Every persistent game project selects `game-persistence-postgres` and one client archetype.
- Postgres is the durable source of truth; migrations are checked in; privileged mutations are server-side; persistence occurs at checkpoints or bounded snapshots, never every render/simulation tick.
- Browser 3D uses TypeScript, pnpm, Vite, React, Three.js, React Three Fiber, and Drei.
- iPhone AR uses Swift, SwiftUI, RealityKit, and ARKit.
- Browser WASM uses TypeScript, pnpm, Vite, React, and a Rust-to-WASM gameplay module.
- Use existing capability namespaces where available and `x.game.*` for game-specific semantics; do not modify the schema’s core namespace list.
- Do not select a database vendor, hosting provider, ORM, authentication provider, project scaffold, or App Store release workflow.
- Stack context is prompt guidance and preflight only; dependency allow/deny enforcement is deferred to a future validation-command contract.

---

## File Structure

- `runtime/stacks/game-persistence-postgres/stack.yml`: shared persistence capability declaration.
- `runtime/stacks/game-persistence-postgres/context.md`: durable-state, authorization, and write-frequency rules.
- `runtime/stacks/browser-3d-game/stack.yml`: browser 3D archetype declaration and package/tool evidence.
- `runtime/stacks/browser-3d-game/context.md`: Three.js/R3F client boundary guidance.
- `runtime/stacks/ios-ar-game/stack.yml`: iPhone AR archetype declaration and Apple host-tool requirements.
- `runtime/stacks/ios-ar-game/context.md`: SwiftUI/RealityKit/ARKit lifecycle guidance.
- `runtime/stacks/browser-wasm-game/stack.yml`: browser WASM archetype declaration and Rust/WASM tool requirements.
- `runtime/stacks/browser-wasm-game/context.md`: WASM/TypeScript boundary guidance.
- `tests/unit/test_stacks_integration.py`: catalog inventory and valid/invalid composition coverage.
- `runtime/echelon-config.yml`: examples for generic persistent-game stack selection.

### Task 1: Shared Postgres persistence capability

**Files:**
- Create: `runtime/stacks/game-persistence-postgres/stack.yml`
- Create: `runtime/stacks/game-persistence-postgres/context.md`
- Modify: `tests/unit/test_stacks_integration.py`

**Interfaces:**
- Consumes: `load_stack_definitions(extension_root)` and `resolve_stacks(selected_ids, definitions, target_archetypes)` from `harness.stacks`.
- Produces: stack ID `game-persistence-postgres`, applicable to `browser_3d_game`, `ios_ar_game`, and `browser_wasm_game`.

- [ ] **Step 1: Write the failing catalog test**

Add this expectation to `test_loads_bundled_statsperform_stacks`, renaming it to `test_loads_bundled_stack_catalog`:

```python
assert sorted(definitions) == [
    "game-persistence-postgres",
    "statsperform-msa-service",
    "statsperform-playbook",
    "statsperform-stark-webapp",
]
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `pytest tests/unit/test_stacks_integration.py::test_loads_bundled_stack_catalog -v`

Expected: FAIL because the four game stack directories do not yet exist.

- [ ] **Step 3: Add the persistence stack definition and context**

Create `runtime/stacks/game-persistence-postgres/stack.yml` with this capability contract:

```yaml
schema_version: "1.0"
stack:
  id: game-persistence-postgres
  name: Game Persistence with Postgres
  version: "1.0.0"
  kind: capability
  owner: echelon
  description: Durable Postgres persistence and authority boundaries for persistent games.
applies_to:
  archetypes: [browser_3d_game, ios_ar_game, browser_wasm_game]
provides:
  data.database: postgres
  data.migrations: checked-in
  data.durability: checkpoint-snapshots
  x.game.mutation_authority: server
  x.game.persistence_cadence: bounded
implies: []
requires: {}
context:
  files: [context.md]
conflicts: []
```

Write `context.md` with the global durable-state rules, including explicit server-side authorization/input validation and a prohibition on tick-by-tick writes or browser-only source-of-truth storage.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `pytest tests/unit/test_stacks_integration.py::test_loads_bundled_stack_catalog -v`

Expected: PASS.

- [ ] **Step 5: Commit the persistence capability**

```bash
git add runtime/stacks/game-persistence-postgres tests/unit/test_stacks_integration.py
git commit -m "feat: add game persistence stack"
```

### Task 2: Browser 3D archetype and valid composition

**Files:**
- Create: `runtime/stacks/browser-3d-game/stack.yml`
- Create: `runtime/stacks/browser-3d-game/context.md`
- Modify: `tests/unit/test_stacks_integration.py`

**Interfaces:**
- Consumes: `game-persistence-postgres` from Task 1.
- Produces: stack ID `browser-3d-game`, applicable to `browser_3d_game`, with `x.game.client_runtime: browser-3d`.

- [ ] **Step 1: Write the failing valid-composition test**

Extend `test_loads_bundled_stack_catalog` so its expected list includes
`"browser-3d-game"`, then add:

```python
def test_resolves_browser_3d_game_with_shared_persistence() -> None:
    resolved = resolve_stacks(
        ["game-persistence-postgres", "browser-3d-game"],
        _definitions(),
        target_archetypes={"browser_3d_game"},
    )

    assert resolved.resolved_ids == [
        "game-persistence-postgres",
        "browser-3d-game",
    ]
    assert resolved.capabilities["data.database"].value == "postgres"
    assert resolved.capabilities["web_app.rendering"].value == "react-three-fiber"
    assert resolved.capabilities["x.game.client_runtime"].value == "browser-3d"
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `pytest tests/unit/test_stacks_integration.py::test_resolves_browser_3d_game_with_shared_persistence -v`

Expected: FAIL with an unknown `browser-3d-game` stack error.

- [ ] **Step 3: Add the browser 3D stack definition and context**

Create a v1.0 archetype stack requiring `pnpm`; declare `web_app.framework: vite-react`, `web_app.rendering: react-three-fiber`, `web_app.workspace: pnpm`, `test.frontend: vitest-playwright`, `delivery.web_app: docker-web`, and `x.game.client_runtime: browser-3d`. Add positive detection evidence for `three`, `@react-three/fiber`, `@react-three/drei`, and `package.json`.

Write context requiring Three.js/R3F/Drei for rendering, browser memory for frame-rate state, and calls to the persistence/API boundary only at deliberate durable-state boundaries.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `pytest tests/unit/test_stacks_integration.py::test_resolves_browser_3d_game_with_shared_persistence -v`

Expected: PASS.

- [ ] **Step 5: Commit the browser 3D archetype**

```bash
git add runtime/stacks/browser-3d-game tests/unit/test_stacks_integration.py
git commit -m "feat: add browser 3d game stack"
```

### Task 3: iPhone AR and browser WASM archetypes

**Files:**
- Create: `runtime/stacks/ios-ar-game/stack.yml`
- Create: `runtime/stacks/ios-ar-game/context.md`
- Create: `runtime/stacks/browser-wasm-game/stack.yml`
- Create: `runtime/stacks/browser-wasm-game/context.md`
- Modify: `tests/unit/test_stacks_integration.py`

**Interfaces:**
- Consumes: `game-persistence-postgres` from Task 1 and existing resolver capability-conflict behavior.
- Produces: `ios-ar-game` with `x.game.client_runtime: ios-ar`, and `browser-wasm-game` with `x.game.client_runtime: browser-wasm`.

- [ ] **Step 1: Write failing composition and exclusivity tests**

Extend `test_loads_bundled_stack_catalog` so its expected list includes
`"browser-wasm-game"` and `"ios-ar-game"`, then add:

```python
@pytest.mark.parametrize(
    ("stack_id", "archetype", "runtime"),
    [
        ("ios-ar-game", "ios_ar_game", "ios-ar"),
        ("browser-wasm-game", "browser_wasm_game", "browser-wasm"),
    ],
)
def test_resolves_game_client_with_shared_persistence(
    stack_id: str, archetype: str, runtime: str
) -> None:
    resolved = resolve_stacks(
        ["game-persistence-postgres", stack_id],
        _definitions(),
        target_archetypes={archetype},
    )

    assert resolved.capabilities["data.database"].value == "postgres"
    assert resolved.capabilities["x.game.client_runtime"].value == runtime


def test_rejects_two_game_client_archetypes() -> None:
    with pytest.raises(StackResolutionError, match="x.game.client_runtime"):
        resolve_stacks(
            ["browser-3d-game", "browser-wasm-game"],
            _definitions(),
            target_archetypes={"browser_3d_game", "browser_wasm_game"},
        )
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run: `pytest tests/unit/test_stacks_integration.py -k 'game_client_with_shared_persistence or two_game_client_archetypes' -v`

Expected: FAIL because both stack IDs are unknown.

- [ ] **Step 3: Add the iPhone AR stack definition and context**

Create a v1.0 archetype stack applying to `ios_ar_game`, requiring `swift` and `xcodebuild`, and declaring `web_app.framework: swiftui`, `web_app.rendering: realitykit`, `test.frontend: xctest`, `delivery.web_app: xcodebuild`, and `x.game.client_runtime: ios-ar`.

Write context requiring SwiftUI, RealityKit, and ARKit; treating AR session state as transient; and loading/saving durable player state through the persistence API rather than relying on an active AR session.

- [ ] **Step 4: Add the browser WASM stack definition and context**

Create a v1.0 archetype stack applying to `browser_wasm_game`, requiring `pnpm`, `cargo`, and `wasm-pack`, and declaring `web_app.framework: vite-react`, `web_app.workspace: pnpm`, `web_app.runtime: wasm-browser`, `test.frontend: vitest-playwright`, `delivery.web_app: docker-web`, and `x.game.client_runtime: browser-wasm`. Add positive detection evidence for `wasm-pack`, `cargo`, and `package.json`.

Write context requiring a Rust-to-WASM gameplay module for deterministic, performance-sensitive logic, while TypeScript owns UI, rendering integration, and durable/network boundaries; explicitly state that WASM does not bypass persistence or authority rules.

- [ ] **Step 5: Run the composition and conflict tests and verify they pass**

Run: `pytest tests/unit/test_stacks_integration.py -k 'game_client_with_shared_persistence or two_game_client_archetypes' -v`

Expected: PASS.

- [ ] **Step 6: Commit the two remaining archetypes**

```bash
git add runtime/stacks/ios-ar-game runtime/stacks/browser-wasm-game tests/unit/test_stacks_integration.py
git commit -m "feat: add ar and wasm game stacks"
```

### Task 4: Document selection and run regression coverage

**Files:**
- Modify: `runtime/echelon-config.yml`
- Test: `tests/unit/test_stacks_integration.py`

**Interfaces:**
- Consumes: all four stack IDs created in Tasks 1–3.
- Produces: discoverable configuration examples and a regression-checked stack catalog.

- [ ] **Step 1: Update the config-template comment**

Replace the Stats Perform-only example under `# STACKS — Opt-in technology profiles` with a concise generic example:

```yaml
# Add stack IDs only when a project should explicitly use known stack contracts,
# such as statsperform-playbook or a persistent game composition:
# game-persistence-postgres + browser-3d-game.
```

- [ ] **Step 2: Run focused stack regression tests**

Run: `pytest tests/unit/test_stacks_schema.py tests/unit/test_stacks_integration.py -v`

Expected: PASS.

- [ ] **Step 3: Run the complete unit suite**

Run: `pytest -m unit`

Expected: PASS.

- [ ] **Step 4: Commit docs and verification updates**

```bash
git add runtime/echelon-config.yml
git commit -m "docs: document persistent game stack selection"
```

## Plan self-review

- **Spec coverage:** Tasks 1–3 create all four requested stack definitions, shared persistence semantics, client-specific boundaries, host preflight requirements, source evidence, valid composition, and client exclusivity. Task 4 documents selection and runs parser/resolver regressions. The no-realtime, no-vendor, no-scaffold, and deferred deterministic dependency-policy boundaries are retained as global constraints.
- **Placeholder scan:** No implementation placeholders or deferred work items are present inside the executable tasks; the explicitly deferred validation-command contract is an out-of-scope product decision from the approved spec.
- **Type consistency:** Every test uses existing `resolve_stacks` and `StackResolutionError` interfaces. The four selected stack IDs, three target archetypes, and `x.game.client_runtime` values are consistent across tasks.
