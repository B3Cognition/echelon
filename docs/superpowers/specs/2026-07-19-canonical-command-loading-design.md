# Canonical Echelon Command Loading

## Goal

Make Echelon's internal CLI execution load its command instructions from an
Echelon-owned, configurable content root, not from provider projections under
`.claude`, `.github`, or `.opencode`.

The change must be testable without starting an LLM process. Provider
projections remain available for interactive provider UX, but they are no
longer an internal runtime dependency.

## Current Problem

Seven commands (`bugfix`, `build`, `review`, `change`, `codegen`,
`verify-spec`, and `reopen`) resolve a provider-specific generated file before
dispatch. This makes Echelon CLI behavior depend on projection generation even
though the Phase A and RE runtimes already read agents, phase contracts, and
workflow definitions directly from an extension root supplied by their
callers.

## Considered Approaches

### 1. Continue loading provider projections

This preserves existing behavior but leaves command availability coupled to
spec-kit's provider generation and its provider-specific directory layout. It
does not meet the goal.

### 2. Load the canonical command and only rewrite textual paths

This is a small change, but it continues to ask the model to discover and load
phase contracts. Correctness would depend on model tool behavior and could not
be fully tested without an LLM.

### 3. Load and assemble canonical command dependencies in Python

This is the selected approach. Python resolves the configured content root,
loads the canonical command, strips frontmatter, substitutes arguments,
injects absolute extension path context, and deterministically includes the
referenced phase contracts. The resulting prompt can be inspected entirely in
unit tests.

## Design

### Echelon content-root resolution

Introduce one Echelon-owned resolver for the directory containing
`commands/`, `agents/`, `workflow/`, `templates/`, and `scripts/`. Callers may
also pass an explicit root directly, which keeps controllers and tests
independent of project layout.

Project-level resolution uses this precedence:

1. Explicit path supplied by the caller.
2. `ECHELON_EXTENSION_ROOT`, primarily for development, CI, and migration.
3. `runtime.extension_root` from Echelon's normal config cascade
   (`.echelon/config.yml`, then local overrides).
4. An Echelon-native deployment at `<project>/.echelon` when it contains the
   required extension markers and content directories.
5. The compatibility deployment at
   `<project>/.specify/extensions/echelon`.

Relative configured paths are resolved from the project root; absolute paths
are accepted. The resolver validates that the selected directory contains the
expected Echelon content surface. It reports every attempted source when none
is valid.

This makes `.specify/extensions/echelon` a migration fallback rather than an
architectural contract. A future installer can deploy `commands/`, `agents/`,
and the other runtime prose directly under `.echelon/` without changing the
command loader or controllers.

Resolve commands through the existing fixed `SKILL_MAP`; user input never
becomes a filesystem path. A missing extension or command produces a canonical
command-not-found error that identifies the expected installed path.

No fallback to `.claude`, `.github`, `.opencode`, or global provider files is
used for internal CLI execution. Provider projections are not content-root
candidates.

### Prompt rendering

The renderer performs these deterministic operations:

1. Read `commands/<skill-base>.md` from the resolved Echelon content root.
2. Remove YAML frontmatter from the command document.
3. Replace `$ARGUMENTS` with the CLI arguments, or append an Arguments section
   when the placeholder is absent.
4. Add the existing COMMANDER execution preamble.
5. Add an extension-path context containing absolute paths for the extension,
   agents, workflow, phase, template, and script directories.
6. Resolve command-owned `workflow/phases/*.md` references within the
   extension boundary and append each unique referenced phase contract in
   declaration order.

The renderer does not interpret agent frontmatter or provider metadata. Agent
and phase dispatch remain governed by the command and phase contracts.

### Provider execution

Claude, Codex, Copilot, and OpenAI-compatible providers receive the rendered
prompt through the existing execution code.

Opencode also receives the rendered prompt through the common AI coding CLI
provider rather than invoking a registered native command. This is necessary
to remove the projection dependency. Existing provider capability and tool
policy checks remain unchanged.

### Harness call sites

Harness prompt resolution will use the same canonical renderer. This removes
the mixed state where the harness loads some canonical phase files but begins
from a provider-generated command wrapper.

Provider scaffolding may remain for interactive provider commands and native
agent UX. It is outside the internal prompt-loading path.

## Safety and Errors

- Only fixed command names from the command map are accepted.
- Every appended phase path must resolve inside the resolved Echelon content
  root.
- Missing referenced phase contracts fail before provider invocation; silently
  sending an incomplete workflow is not allowed.
- Duplicate phase references are included once.
- Existing capability failures happen before prompt execution.

## Deterministic Testing

Unit tests construct temporary Echelon content roots and assert that:

- loading succeeds without any `.claude`, `.github`, or `.opencode` tree;
- explicit, environment, configured, native `.echelon`, and legacy `.specify`
  resolution follow the documented precedence;
- invalid configured roots fail clearly instead of silently selecting a
  provider projection;
- frontmatter is absent from the rendered prompt;
- arguments and absolute extension paths are present;
- referenced phase contracts are assembled in order and de-duplicated;
- missing canonical commands and missing referenced phases fail before any
  provider is instantiated;
- each provider route receives the canonical rendered prompt without starting
  a real LLM process;
- Opencode no longer invokes its native projected command path.

Focused CLI and harness unit suites provide regression coverage. The tests use
fake provider objects only at the external process boundary; prompt discovery
and rendering exercise real filesystem content.

## Compatibility Boundary

Interactive slash commands supplied by spec-kit are unchanged. Project-local
customizations made directly to provider projections will no longer affect
`echelon <command>` execution. Custom command behavior must live in the
installed extension source or a future explicit override mechanism.
