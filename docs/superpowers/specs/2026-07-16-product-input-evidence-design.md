# Product Input Evidence Design

**Status:** Approved design
**Date:** 2026-07-16
**Related:** EGR-147 authoritative implementation targets

## Problem

`echelon spec run` currently receives product intent primarily through one free-form
description. Real feature work also starts from product-manager notes, recreated
reference-product specifications, API contracts, screenshots, exported designs,
and similar material. Operators can mention those paths in prose, but Echelon has
no deterministic contract that proves which resources were accepted, which agents
received them, which requirements were adopted, or whether those requirements
survived into target-owned delivery tasks.

The OptaSearch examples demonstrate two different input roles:

- `sources/PBS-E-45` is normative product intent that must be represented in the
  resulting specification and delivery tasks or explicitly rejected.
- `sources/provision` is a reconstructed reference product. It can inform the new
  solution, but its full feature set must not silently become PressBox scope.

The Provision folder also contains `provision.env`. Blind recursive prompt
concatenation would expose credentials. A safe input feature therefore needs role
semantics, immutable snapshots, secret containment, bounded prompt distribution,
and durable traceability.

## Goals

- Add one repeatable `--input <role>:<location>` option to `echelon spec run`.
- Support `requirement` and `reference` roles without conflating their authority.
- Resolve, validate, and snapshot all accepted inputs before the first LLM dispatch.
- Record every included and excluded resource with stable provenance.
- Make all accepted requirement units traceable through specification IDs to
  canonical tasks and declared implementation targets.
- Provide reference inputs to the phases that need them without copying a large
  corpus into every agent prompt.
- Publish input evidence with the canonical specification so it survives run cleanup.
- Support offline Figma evidence bundles and reduced-fidelity Figma exports.
- Optionally resolve credentialed Figma URLs into the same offline evidence bundle.

## Non-Goals

- Do not add a generic arbitrary-URL crawler.
- Do not make every reference-product feature part of the requested product.
- Do not let agents silently add new input paths after a run begins.
- Do not store credentials, environment values, or access tokens in snapshots,
  prompts, state, journals, or published evidence.
- Do not claim that a raw PNG, PDF, or SVG contains the complete editable Figma
  document model.
- Do not add post-hoc input mutation to an existing generated specification.

## CLI Contract

The canonical interface is repeatable and role-qualified:

```bash
echelon spec run "Add player connections to PressBox Search" \
  --target sources/pressbox-search \
  --target sources/pressbox-search-api \
  --input requirement:sources/PBS-E-45 \
  --input reference:sources/provision
```

`location` may be a workspace-relative path, an absolute path, or a supported
Figma URL. The parser splits only on the first colon, so URL schemes remain intact.
The initial role vocabulary is deliberately limited to:

- `requirement`: normative input. Every stable unit requires a final disposition.
- `reference`: informative input. It may influence discovery, architecture, or
  requirements, but cannot override a requirement input.

`--input` is valid only when a Phase A run is created or reset. `spec continue` and
`spec resume` reuse saved snapshots. Changing the original file does not alter the
active run. Adding, removing, or changing declared inputs requires a new spec run
because specification, architecture, estimates, plan, and tasks may all depend on
them.

## Architecture

### ProductInputResolver

Before squad initialization, a deterministic resolver:

1. Parses and normalizes role-qualified declarations.
2. Resolves local paths and Figma locations.
3. Recursively inventories directory inputs in stable lexical order.
4. Applies the inclusion, exclusion, and containment policy.
5. Snapshots accepted content under the run directory.
6. Computes SHA-256 hashes, media types, sizes, and source locators.
7. Unitizes accepted resources into stable evidence units.
8. Writes role-specific context bundles and the initial evidence ledger.

Any blocking preflight error occurs before configuration of an LLM provider or an
agent dispatch.

### Run-local layout

```text
runs/<run-id>/inputs/
  manifest.json
  catalog.json
  input-context.md
  requirement-context.md
  reference-context.md
  traceability.json
  traceability.md
  snapshots/
    <role>/<declaration-id>/...
```

Squad state stores immutable declaration metadata, manifest paths, manifest hash,
and traceability status. Environment variables are not a source of truth.

### Published layout

At Phase A publication, the complete safe evidence package is copied to:

```text
specs/<id>/inputs/
  manifest.json
  catalog.json
  traceability.json
  traceability.md
  snapshots/...
```

The artifact index names these files as product-input provenance. Published hashes
must match the run-local snapshot hashes.

## Inclusion and Safety Policy

Directory inputs are recursive. The resolver records every discovered entry as
accepted, excluded, or blocking.

Accepted initial formats:

- UTF-8 and detected text files, including Markdown and plain text.
- JSON, YAML, CSV, and other line-oriented structured text.
- PDF documents after safe page-addressable text extraction.
- PNG, JPEG, WebP, and SVG design evidence.
- A standardized Figma evidence bundle described below.

Automatically excluded without reading or copying contents:

- Hidden OS metadata such as `.DS_Store`.
- `.env` and recognized secret/credential/key file names.
- Files detected as credentials by the existing secret-name/content guard.
- Executables, archives, object files, and unrelated arbitrary binaries.

Exclusion records contain the original path, classification, and reason, but never
secret content or a value-derived preview. Unsupported non-secret files block
preflight with a conversion or explicit-removal instruction rather than being
silently ignored.

Symlinks are resolved before classification. The manifest records both the declared
path and resolved path. A symlink that escapes its declared input root is blocking
unless the escaped target was separately declared as an input. Duplicate content is
stored once by hash while retaining every source locator.

## Stable Input Units

Stable unit IDs derive from role, declaration-relative path, locator, and snapshot
hash. Ordering never depends on filesystem traversal order.

- Markdown: heading sections, paragraphs, and list items with line ranges.
- Plain text: paragraphs and list items with line ranges.
- JSON/YAML/CSV: bounded structural records plus source path locators.
- PDF: page and extracted-text range.
- SVG: XML element/layer IDs when available, plus the rendered-file hash.
- Raster image: file hash and analyst-described region locator.
- Figma JSON: file, page, frame, component, or node ID.

Image descriptions produced by an LLM are interpretations and cannot replace the
immutable image hash or Figma node locator as provenance.

## Authority and Dispositions

Product evidence uses this authority order:

```text
explicit owner decision
  > requirement input
  > reference input
  > reverse-engineered current behavior
  > agent inference
```

Every requirement unit ends Phase A with exactly one disposition:

- `included`: mapped to one or more FR/NFR/AC/SC identifiers.
- `excluded`: omitted because the input itself marks it out of scope or because an
  explicit owner decision supplies the product rationale. An agent cannot silently
  exclude normative input on preference alone.
- `duplicate`: points to an equivalent unit and its mapped spec identifiers.
- `open_question`: temporary; must be resolved before publication.
- `conflict`: temporary; records competing evidence and resolution.

Reference resources use consumption states:

- `used`: includes exact adopted citations and resulting spec/architecture IDs.
- `reviewed_unused`: records why the reference did not affect the solution.
- `excluded`: records the deterministic safety or format exclusion reason.

A reference does not require feature-by-feature adoption. It does require evidence
that every accepted reference resource was delivered to a designated analysis phase
and received a final consumption state.

## Prompt and Phase Distribution

Every Phase A dispatch receives a bounded standard block:

```text
## Product Input Contract
PRODUCT_INPUT_MANIFEST=<immutable manifest>
PRODUCT_INPUT_CATALOG=<stable unit catalog>
PRODUCT_INPUT_TRACEABILITY=<current ledger>
REQUIREMENT_INPUTS are normative.
REFERENCE_INPUTS are informative and cannot override requirements.
Use immutable snapshot paths and cite input unit IDs.
Do not discover or add undeclared input paths.
```

Full content is distributed only where needed:

- TRACKER and CARTOGRAPHER receive all requirement units.
- SCOUT, CARTOGRAPHER, and ARCHITECT receive accepted reference resources.
- SAGE receives requirement units and the current traceability ledger.
- SENTINEL receives requirement-to-acceptance mappings.
- ORCHESTRATOR receives final requirement mappings and must connect every included
  implementation requirement to canonical target-owned tasks.
- Consensus and publication phases receive the ledger and validation reports.

The resolver creates deterministic role bundles with explicit file/unit boundaries.
The same large reference bundle is not appended to every prompt. State records which
phase received each accepted resource. A model attestation alone is not proof of
semantic adoption; adoption is proven by exact citations and traceability mappings.

## Traceability Model

For each requirement unit, `traceability.json` records:

```text
input unit ID
→ original and snapshot source locator
→ disposition and rationale
→ specification requirement and acceptance IDs
→ canonical task IDs
→ declared implementation targets
```

Illustrative PBS-E-45 chain:

```text
IN-PBS-E45-004
  source: sources/PBS-E-45/PBS-E-45:8
  statement: table rows are keyed by passer→receiver
  disposition: included
  spec_ids: [FR-209, AC-209.1]
  tasks:
    - T-006 target=sources/pressbox-search-api
    - T-014 target=sources/pressbox-search
```

The Markdown rendering is for operators. JSON is canonical and schema-validated.
Agents update mappings through their normal structured result contract; the Python
controller is the sole writer of the canonical ledger.

## Deterministic Gates

Publication is blocked unless:

1. Every accepted requirement unit has one valid final disposition.
2. Every included unit maps to existing spec identifiers.
3. Every mapped spec identifier exists in the canonical specification.
4. Every included implementation requirement maps to at least one canonical task.
5. Every mapped task has one explicit `target=` contained in `targets.yml`.
6. No `open_question` or `conflict` remains unresolved.
7. Every accepted reference resource has a final consumption state.
8. Every used reference citation resolves inside its immutable snapshot.
9. Manifest, catalog, traceability, and snapshot hashes agree.
10. Published input evidence matches the validated run-local evidence.

The task mapping uses the existing canonical `req=` field and explicit `target=`
contract. File paths may validate task ownership but never infer it.

## Figma Support

### Offline Figma evidence bundle

The primary Figma contract is a local safe bundle:

```text
figma-export/
  manifest.json
  design.json
  frames/
    player-connections.png
    player-connections.svg
```

`design.json` uses Figma's REST-shaped node representation (`JSON_REST_V1`) for the
selected file or node scope. The manifest records the Figma file/version, selected
node IDs, export time, exporter version, and hashes. Rendered PNG/SVG files provide
visual evidence. A companion Figma plugin may create this bundle from the user's
authenticated Figma session, so Echelon does not need to retain Figma credentials.

### Reduced-fidelity exports

Raw SVG, PNG, JPEG, or PDF exports are accepted. They are marked
`reduced_fidelity` because they do not preserve the complete Figma component,
variant, constraint, annotation, and prototype model. SVG is XML and may expose
layer IDs, but it remains rendered design evidence rather than a full Figma file.

### Optional URL resolver

A Figma design URL may be used as the input location when a Figma connector is
configured:

```bash
--input requirement:https://www.figma.com/design/<file>?node-id=<node>
```

The resolver accesses only the explicitly named file/node scope, uses OAuth or an
approved token/connector outside prompts, and requires read-only file-content
access. It immediately materializes the same offline evidence bundle. Credentials
and temporary image URLs never enter state or the manifest. Missing authentication,
insufficient access, extraction gaps, or a scope exceeding configured size limits
block preflight and point to the offline export path.

## Drift and Recovery

Resume and continuation always use immutable snapshots. Before each continuation,
the controller may re-hash reachable originals and report drift, but drift does not
alter the active inputs. The operator can continue with the existing snapshot or
start a new run; Echelon never merges changed product input into target-dependent
artifacts automatically.

A run interrupted during input resolution is not resumable as a valid Phase A run
until the manifest and all snapshots pass atomic-completion validation. Snapshot and
ledger writes use temporary files plus atomic replacement.

## Failure Behavior

Preflight blocks before LLM dispatch for:

- Invalid role syntax or an unsupported role.
- Missing or unreadable declared locations.
- Unsupported non-secret resources.
- Unsafe symlink escape.
- Figma authentication, authorization, or extraction failure.
- Per-file or total-size limit violations.
- Manifest or snapshot hash inconsistency.

Later Phase A gates block for incomplete disposition, unresolved conflicts, invalid
citations, missing spec IDs, or missing task/target coverage. Errors name exact input
unit IDs and corrective actions without printing sensitive contents.

## Testing Strategy

### Unit tests

- Role-qualified CLI parsing, including URLs containing colons.
- Stable recursive ordering, hashing, deduplication, and unit IDs.
- Text, Markdown, structured text, PDF, SVG, raster, and Figma-bundle handlers.
- Secret-name/content exclusion and redacted exclusion records.
- Symlink containment and duplicate resolved paths.
- Traceability schema and every deterministic gate.
- Original-input drift detection and immutable resume behavior.

### Prompt and workflow tests

- Standard product-input contract appears in every Phase A prompt.
- Full role bundles appear only in designated phases.
- Requirement and reference authority language is consistent.
- Controller-owned ledger writes cannot be replaced by agent-authored files.
- ORCHESTRATOR receives input-to-spec mappings and emits target-owned tasks.

### Integration tests

- PBS-E-45-style plain text produces paragraph/list units and complete traceability.
- A Provision-sized reference corpus is snapshotted once and not duplicated in every
  dispatch prompt.
- A folder containing `.env`, `.DS_Store`, and safe Markdown excludes unsafe files
  without leaking values.
- Offline Figma bundle, reduced-fidelity SVG, and optional URL resolution converge on
  the same normalized evidence schema.
- Resume remains bound to original snapshots after source files change.
- Publication fails on any missing input→spec→task→target link.

## Compatibility and Migration

Runs without `--input` are unchanged. Existing specs do not acquire synthetic input
evidence. Mentioning a path only in the free-form description remains ordinary prose
and does not create a product-input contract; the CLI and docs direct operators to
use `--input` when provenance and capture verification are required.

The feature extends EGR-147's immutable Phase A intent model: implementation targets
and product inputs are both resolved before agents work, persisted in squad state,
and consumed by delivery without inference or post-hoc mutation.

## Figma References

- [Figma export formats and settings](https://help.figma.com/hc/en-us/articles/13402894554519-Export-formats-and-settings)
- [Figma Plugin API `exportAsync`](https://developers.figma.com/docs/plugins/api/properties/nodes-exportasync/)
- [Figma Plugin API export settings](https://developers.figma.com/docs/plugins/api/ExportSettings/)
- [Figma REST file endpoints](https://developers.figma.com/docs/rest-api/file-endpoints/)
- [Figma REST authentication](https://developers.figma.com/docs/rest-api/authentication/)
