# Provider Product-Plane Boundary Design

**Date:** 2026-08-12
**Status:** approved for implementation

## Goal

Prevent an AI provider dispatched by Echelon from discovering or interpreting
Echelon's control-plane prose as product evidence. Providers receive the one
selected command or subagent, its resolved companion content, and the requested
workspace task. They do not discover their instructions by searching the
workspace.

## Storage Boundary

Keep the canonical deployed bundles at `.echelon/prosaic` and
`.echelon/runtime`. These are Echelon control-plane resources and may be needed
by the host orchestrator while a run is active. Their location is not the bug;
allowing a provider to treat the entire workspace as instruction search space
is the bug.

`.echelon/packages` is temporary installation staging and is removed after a
successful or failed deployment attempt. Delivery worktrees continue to receive
`.echelon/prosaic` and `.echelon/runtime`, but Echelon no longer asks Prosaic to
also generate `.claude/commands`, `.claude/agents`, or `.claude/skills` there.

## Prompt Boundary

Echelon resolves all selected package resources before provider invocation.
This includes Prosaic Markdown companions and referenced runtime templates or
schemas in Markdown, YAML, or JSON. The assembled prompt replaces filesystem
references with neutral embedded section references, uses headings that do not
expose package paths, and fails when a referenced resource cannot be resolved.
The provider therefore has no reason to grep for agent, command, workflow,
template, schema, or validator prose.

Every `AICodingCliProvider` invocation prepends a product-plane contract. It
states that selected instructions are already embedded, forbids searching
control-plane directories, and forbids repository-wide searches intended to
discover Echelon instructions.

## Mechanical Enforcement

Echelon adds absolute control-plane roots beneath the invocation working
directory to `prompt_metadata.tool_forbidden_roots`, preserving any narrower
read and write scopes already supplied by a caller. The forbidden set includes
Echelon and provider directories plus root/provider instruction files such as
`CLAUDE.md`, `AGENTS.md`, Copilot instructions, `.mcp.json`, and OpenCode
configuration.

- Claude on macOS applies the existing `sandbox-exec` filesystem boundary.
- Explicitly named helpers under `.echelon/runtime/scripts` are executable.
  Claude receives read-only access to that scripts tree, literal read access to
  `.echelon/config.yml` and `.echelon/local.yml`, and metadata-only access to
  the `.echelon` directory for helper root detection. Directory listing and all
  other control-plane reads remain denied.
- The OpenAI-compatible tool registry rejects direct and recursive access to
  forbidden roots and returns an explicit tool error.
- Codex, Copilot, and OpenCode receive the same prompt and metadata contract.
  Echelon does not claim hard filesystem containment where their current CLI
  integrations do not expose a suitable mechanism.

Hard enforcement is best-effort for ordinary dispatches so a platform without
`sandbox-exec` does not make Echelon unusable. Existing workflows that explicitly
require a hard boundary retain their fail-closed behavior.

## Testing

- Package installation removes `.echelon/packages` while preserving deployed
  `.echelon/prosaic` and `.echelon/runtime` output.
- Delivery synchronization never invokes provider-native Prosaic deployment.
- Companion assembly recursively embeds content, removes package paths, and
  fails on unresolved references.
- ORCHESTRATOR embeds all six planning templates and exposes none of their
  `.echelon/runtime/templates` paths to the provider.
- Both prompt and agent provider entry points receive the product-plane contract
  and merged forbidden-root metadata.
- OpenAI-compatible filesystem tools reject direct reads and exclude forbidden
  trees from broad listing and grep operations.
- Claude applies the boundary when available and keeps prompt-only enforcement
  for ordinary dispatch when the host boundary is unavailable.
- The macOS profile executes the config helper while continuing to reject
  `.echelon` listing, runtime-template reads, and Prosaic-prompt reads.
