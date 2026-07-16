# Product Input Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `echelon spec run --input <role>:<location>` create an immutable, safe evidence package and block Phase A publication until normative inputs are traceable to target-owned tasks.

**Architecture:** A new deterministic product-input module resolves local files/directories before any LLM dispatch, snapshots safe content under the run directory, and writes a manifest, catalog, bounded role context, and an initial traceability ledger. The squad persists only those immutable paths and hashes, injects their contract into every phase prompt, publishes the package with the spec, and validates the final requirement→spec→task→target chain.

**Tech Stack:** Python 3.11+, `pathlib`, `hashlib`, JSON/YAML already used by Echelon, pytest, Typer.

## Global Constraints

- Preserve the existing dirty EGR-147 changes; do not reset, checkout, or reformat unrelated files.
- `--input` accepts only `requirement` and `reference`; split on the first colon so URL schemes remain intact.
- Exclude hidden metadata and secret-like files without reading/copying content; unsupported non-secret files fail preflight.
- Use snapshots as the only agent-readable source; do not append arbitrary source directories into prompts.
- A requirement input cannot publish with `open_question`/`conflict`/unmapped status; included requirements must reach `target=` canonical tasks.
- URL resolution is an adapter boundary. This increment supports offline Figma bundles and provides actionable rejection for a URL without a configured adapter; it never stores credentials.

---

## File Structure

- Create `src/echelon/product_inputs.py`: declarations, safe local resolver, manifests/catalogs/context bundles, traceability schema, and publication/readiness validation.
- Modify `src/echelon/cli_app.py` and `src/echelon/cli.py`: accept and parse repeatable `--input`, resolve it before provider construction, and pass immutable metadata to the squad.
- Modify `src/harness/squad_state.py` and `src/harness/squad.py`: persist input metadata, include it in run context, copy evidence into the published spec, and enforce the evidence gate.
- Modify `src/harness/squad_executors.py`: prepend the bounded product-input contract to all Phase A agent prompts.
- Modify `src/echelon/artifact_index.py`: list the published input evidence package.
- Modify `extension/workflow/phases/phase1-what.md`, `phase1-why2.md`, `phase3-plan.md`, `phase3-sentinel.md`, and `phase3-consensus.md`: require the appropriate agents to cite unit IDs and complete the traceability ledger.
- Create `tests/unit/test_product_inputs.py`: resolver, safety, Figma bundle, traceability, and publication gate tests.
- Modify `tests/unit/test_cli_typer_app.py`, `tests/unit/test_cli_mode_args.py`, and `tests/unit/test_squad_re_context.py`: CLI forwarding, preflight, persisted state, and prompt contract coverage.

### Task 1: Safe immutable product-input resolver

**Files:**
- Create: `src/echelon/product_inputs.py`
- Test: `tests/unit/test_product_inputs.py`

**Interfaces:**
- `parse_input_declaration(value: str) -> ProductInputDeclaration`
- `resolve_product_inputs(project_root: Path, run_dir: Path, declarations: Sequence[ProductInputDeclaration]) -> ProductInputResolution`
- `validate_product_input_traceability(spec_dir: Path, declared_targets: Sequence[str]) -> list[str]`

- [ ] **Step 1: Write failing resolver tests** for a `requirement` text folder, a `reference` folder containing `provision.env` and `.DS_Store`, an unsupported binary, an escaping symlink, and a duplicate declaration. Assert stable hashes/order, snapshots only for accepted files, and exclusion records with no secret content.

- [ ] **Step 2: Run the focused tests**

Run: `pytest tests/unit/test_product_inputs.py -q`

Expected: FAIL because `echelon.product_inputs` does not exist.

- [ ] **Step 3: Implement the minimum resolver** using lexical `Path.rglob`, SHA-256 content hashes, explicit suffix/name classification, root-containment checks, and atomic JSON writes. Create `manifest.json`, `catalog.json`, `requirement-context.md`, `reference-context.md`, `input-context.md`, and an initial `traceability.json`/`.md` under `run_dir/inputs`.

- [ ] **Step 4: Add Figma offline bundle tests and implementation**. Accept a directory with `manifest.json` plus `design.json`/frame assets as a Figma bundle; accept SVG/PNG/PDF as reduced-fidelity evidence; reject `https://figma.com/...` without an injected resolver with an instruction to export an offline bundle or configure a connector.

- [ ] **Step 5: Run resolver tests**

Run: `pytest tests/unit/test_product_inputs.py -q`

Expected: PASS.

### Task 2: CLI preflight and immutable run state

**Files:**
- Modify: `src/echelon/cli_app.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/harness/squad_state.py`
- Modify: `src/harness/squad.py`
- Test: `tests/unit/test_cli_typer_app.py`
- Test: `tests/unit/test_cli_mode_args.py`

**Interfaces:**
- `SquadController(..., product_inputs: ProductInputResolution | None = None)`
- state key `product_inputs` containing declaration, manifest, catalog, context, and traceability paths/hashes.

- [ ] **Step 1: Write failing CLI tests** that `echelon spec run --input requirement:sources/PBS-E-45 --input reference:sources/provision` forwards both values in order; missing role/path and unsupported content exit before the provider is created; an existing resumable run refuses changed inputs.

- [ ] **Step 2: Run the focused CLI tests**

Run: `pytest tests/unit/test_cli_typer_app.py tests/unit/test_cli_mode_args.py -q`

Expected: FAIL because `--input` is not recognized/forwarded.

- [ ] **Step 3: Add repeatable Typer forwarding and legacy parsing**, resolve declarations after target validation but before `SquadCliProvider` construction, and pass the result to `SquadController`.

- [ ] **Step 4: Persist immutable metadata at initialization**. On resume, compare declared input manifest hashes/locations to state and raise an actionable new-run/reset error on mutation; never reread original product files.

- [ ] **Step 5: Run the focused CLI tests**

Run: `pytest tests/unit/test_cli_typer_app.py tests/unit/test_cli_mode_args.py -q`

Expected: PASS.

### Task 3: Prompt contract, traceability gate, and published evidence

**Files:**
- Modify: `src/harness/squad_executors.py`
- Modify: `src/harness/squad.py`
- Modify: `src/echelon/artifact_index.py`
- Modify: `extension/workflow/phases/phase1-what.md`
- Modify: `extension/workflow/phases/phase1-why2.md`
- Modify: `extension/workflow/phases/phase3-plan.md`
- Modify: `extension/workflow/phases/phase3-sentinel.md`
- Modify: `extension/workflow/phases/phase3-consensus.md`
- Test: `tests/unit/test_squad_re_context.py`
- Test: `tests/unit/test_product_inputs.py`

**Interfaces:**
- `_render_product_input_context(state: dict) -> str`
- `validate_product_input_traceability(spec_dir, declared_targets) -> list[str]`, where `[]` means publication may proceed.

- [ ] **Step 1: Write failing tests** asserting every assembled standard prompt contains manifest/catalog/traceability paths, authority semantics, and snapshot-only instruction; asserting publication copies `inputs/`; and asserting blockers for a requirement unit lacking final disposition/spec citation/task `req=` mapping/declared `target=`.

- [ ] **Step 2: Run the focused tests**

Run: `pytest tests/unit/test_squad_re_context.py tests/unit/test_product_inputs.py -q`

Expected: FAIL because no product-input preamble or readiness gate exists.

- [ ] **Step 3: Add the prompt preamble and role-specific phase requirements**. CARTOGRAPHER records unit→spec citations and dispositions; SAGE/SENTINEL review them; ORCHESTRATOR maps included units to canonical `req=` and declared `target=` tasks; consensus resolves all temporary states. The controller remains the canonical publisher/validator of the ledger.

- [ ] **Step 4: Add publication and gate wiring**. Copy only the safe run `inputs/` package into `specs/<id>/inputs`, refresh `traceability.md` from canonical JSON, validate before Phase A readiness, and add manifest/catalog/traceability entries to the artifact index.

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/unit/test_squad_re_context.py tests/unit/test_product_inputs.py -q`

Expected: PASS.

### Task 4: Regression verification and documentation

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Test: affected unit suites

- [ ] **Step 1: Document the command and evidence lifecycle** with the approved PBS-E-45/Provision example, offline Figma bundle inputs, and the explicit rule that direct URLs need a configured credentialed connector.

- [ ] **Step 2: Add a changelog entry** describing `--input`, safe snapshots, published provenance, and the publication gate.

- [ ] **Step 3: Run regression suites**

Run: `pytest tests/unit/test_product_inputs.py tests/unit/test_cli_typer_app.py tests/unit/test_cli_mode_args.py tests/unit/test_squad_re_context.py -q`

Expected: PASS.

- [ ] **Step 4: Run the complete suite**

Run: `pytest -q`

Expected: all product-input tests pass; report any pre-existing failures separately.
