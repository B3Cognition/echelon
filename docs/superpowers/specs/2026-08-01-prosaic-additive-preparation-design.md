# Additive Prosaic Preparation Design

## Goal

Prepare Echelon to consume canonical, provider-neutral Prosaic Markdown without
changing existing Spec-Kit command execution until a project has an installed
`.echelon/prosaic/commands/` bundle.

## Scope

This preparation is additive. Echelon retains its installed Spec-Kit extension,
provider-native Markdown files, and current command dispatch as the fallback.
No configuration flag is added: the presence of the command bundle is the
explicit opt-in signal.

## Canonical Source Export

`echelon prosaic export` produces source under:

```
.echelon/prosaic/
  commands/
  subagents/
```

The exporter reads the legacy extension only as migration input. It removes
legacy Markdown frontmatter and writes neutral frontmatter derived from the
registered artifact metadata. It normalizes:

- `capability: fast|balanced|strong` to `model_tier` with the same value.
- `execution: isolated` to `execution: command`.
- `$ARGUMENTS` to `{{args}}` in command bodies.

It preserves the neutral values `effort`, `tools`, `color`, and `invocation`.
The generated source never retains legacy provider-specific `model` values or
the old `capability` key.

The export command remains a migration tool. The eventual installer will ship
and copy a versioned canonical bundle; runtime never reads `extension.yml`.

## Runtime Selection

When `.echelon/prosaic/commands/` exists, Echelon loads the requested command
with `prosaic inspect --source .echelon/prosaic`. It renders the inspected body
and dispatches it through the existing host-side provider path. When that
directory is absent, Echelon keeps the existing provider-native Spec-Kit lookup
and dispatch behavior unchanged.

An invalid installed Prosaic bundle is an explicit command error. It does not
silently fall back, because a partially installed or malformed canonical bundle
must not execute a different prompt than the user selected.

## Provider Metadata Preparation

The loader returns both rendered prompt text and neutral frontmatter. Only for
a Prosaic-loaded command, Echelon prepares provider request metadata:

- `model_tier` is resolved by an Echelon-owned provider mapping to a concrete
  model. The mapping is not part of Prosaic.
- `effort` becomes the provider reasoning-effort request when supported.
- `tools`, `color`, and `invocation` are preserved as Echelon policy metadata;
  this slice does not change provider tool permissions or command visibility.

An absent model-tier mapping leaves the provider's existing configured model in
place. Existing non-Prosaic commands receive no new metadata and retain their
current behavior.

## Delivery Order

1. Complete and test canonical export normalization, including migration of
   every legacy capability value and removal of `capability`.
2. Evolve the Prosaic loader/dispatch boundary to carry frontmatter alongside
   prompt text, without changing the legacy path.
3. Add provider-specific model-tier resolution and metadata propagation behind
   the Prosaic-loaded-command boundary, starting with OpenAI-compatible and
   Claude, then Codex, Copilot, and OpenCode.
4. Add installer-owned canonical bundle distribution only after the source and
   provider adapter contracts are proven.

## Tests

- Export tests assert legacy frontmatter removal, capability-to-model-tier
  migration, and preservation of the remaining neutral metadata.
- Command dispatch tests prove no Prosaic directory retains the legacy path;
  a Prosaic command directory uses inspected source instead.
- Provider tests verify the concrete model and effort payload for each
  supported adapter and verify unmapped tiers preserve current defaults.
