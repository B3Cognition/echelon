# Typed RE Artifact Catalog

## Goal

Make every durable reverse-engineering artifact explicitly typed at publication time. Context selection, MemPalace mining, and graph construction must consume one canonical descriptor model instead of independently inferring artifact meaning from filenames.

## Canonical Ownership

`re/index.json` remains the publication trust root. It is not self-described.

The index owns one typed descriptor for `re/workspace/manifest.json` and one for every `re/sources/<source-id>/manifest.json`. Each manifest owns typed descriptors for the child artifacts in its scope, excluding itself. Consequently, every published artifact other than the trust-root index has exactly one canonical descriptor and no artifact must contain its own hash.

Existing named path fields remain during the compatibility period. Typed descriptors are authoritative when present; legacy fields and path classification are fallback behavior for older publication generations only.

## Descriptor Contract

Every descriptor has this shape:

```json
{
  "kind": "re-architecture",
  "path": "re/sources/pressbox-search/architecture.md",
  "sha256": "sha256:<lowercase-hex>",
  "scope": "source",
  "source_id": "pressbox-search"
}
```

Required fields:

- `kind`: a supported stable RE artifact kind.
- `path`: normalized workspace-relative path below `re/`.
- `sha256`: hash of the published bytes using the existing `sha256:<hex>` representation.
- `scope`: either `source` or `workspace`.

`source_id` is required for source scope and forbidden for workspace scope. Unknown fields are tolerated for forward compatibility, but unknown kinds are rejected at publication and ignored by legacy consumers.

Descriptor arrays are sorted by path. Duplicate paths, paths escaping `re/`, scope/path mismatches, source ownership mismatches, missing files, and hash mismatches fail publication validation.

## Artifact Kinds

The initial stable taxonomy covers all current durable outputs:

| Kind | Typical artifact |
|---|---|
| `re-source-manifest` | source manifest registered by the index |
| `re-workspace-manifest` | workspace manifest registered by the index |
| `re-overview` | source or workspace overview |
| `re-architecture` | source architecture |
| `re-contracts` | source or workspace contracts |
| `re-components` | source component catalog |
| `re-decision` | source or workspace ADR |
| `re-codegraph-summary` | compact source or workspace CodeGraph summary |
| `re-codegraph-analysis` | full source CodeGraph analysis |
| `re-analysis` | source analysis |
| `re-structure` | source structure inventory |
| `re-configs` | source configuration inventory |
| `re-dependencies` | source dependency inventory |
| `re-domain-manifest` | source domain manifest |
| `re-generated-spec` | generated source-domain specification |
| `re-generated-checklist` | generated source-domain checklist |
| `re-supporting-artifacts` | legacy source supporting-artifact document |
| `re-architecture-map` | workspace architecture map |
| `re-relationships` | workspace relationship synthesis |
| `re-domain` | workspace domain document |
| `re-strategy` | workspace strategy document other than an ADR |
| `re-workspace-checklist` | workspace RE checklist |
| `re-quality-report` | published RE quality evidence |

Kinds describe semantics, not whether an artifact is suitable for prompt injection or memory mining. Consumer policy remains separate so large evidence such as `re-codegraph-analysis` can be registered without being injected or mined wholesale.

## Publication Shape

Each source entry in `re/index.json` gains `manifest_artifact`, while retaining the existing `manifest` string:

```json
{
  "manifest": "re/sources/pressbox-search/manifest.json",
  "manifest_artifact": {
    "kind": "re-source-manifest",
    "path": "re/sources/pressbox-search/manifest.json",
    "sha256": "sha256:<hex>",
    "scope": "source",
    "source_id": "pressbox-search"
  }
}
```

The workspace index entry gains the equivalent `manifest_artifact` with workspace scope. Source and workspace manifests gain a sorted `artifacts` array containing their owned children.

Publication materialization generates descriptors from the validated publication plan and published bytes. LLM output does not choose artifact kinds or hashes.

## Consumer Migration

The RE registry exposes one normalized artifact-descriptor API:

1. Load and validate typed catalogs when present.
2. Fall back to the current named fields and deterministic path classifier for legacy generations.
3. Return descriptors to context attachment, MemPalace, and graph consumers.

Context attachment applies the existing selection policy over descriptors:

- workspace briefing artifacts remain broadly available according to current policy;
- source artifacts are selected from implementation targets and explicit `--re-source` values;
- large evidence kinds remain registered but excluded from rendered briefings unless a future explicit policy enables them.

MemPalace derives artifact kind and room from descriptors. Graph construction derives source topology and decision nodes from descriptors. Path classification remains only as legacy compatibility and defensive fallback.

Canonical `re-context.json` rows remain path/hash snapshots for immutable spec lineage. During graph construction, their paths are joined with the publication descriptor catalog to recover types. This avoids changing the context snapshot schema while making type interpretation canonical.

## OptaSearch Migration

After implementation, republish the existing validated OptaSearch RE run using the new catalog schema. Do not hand-edit publication files. Then:

1. Validate the typed index and all manifests.
2. Refresh RE MemPalace memory.
3. Audit drawer identity, kind, room, and hashes.
4. Refresh current spec and workspace graphs without retroactively attaching RE to specs that lack `re-context.json`.
5. Verify representative source and workspace descriptors, including all workspace ADRs.

## Compatibility And Failure Handling

- Existing schema-version-1 publications without typed catalogs continue to load.
- Existing named fields remain emitted in the first typed-catalog release.
- A partially present typed catalog is invalid; consumers do not silently mix typed and inferred descriptors within one owning manifest.
- A malformed descriptor blocks publication and produces an explicit registry error when reading an already published generation.
- Optional artifacts absent from a run produce no descriptor.
- Unknown future kinds fail current publication validation rather than receiving accidental consumer behavior.

## Tests

1. Materialization emits deterministic descriptors for every published source and workspace child artifact.
2. Index manifest descriptors have correct kinds, ownership, and hashes.
3. Publication validation rejects duplicate paths, traversal, wrong scope/source, missing files, unsupported kinds, and hash mismatches.
4. Registry loading prefers typed descriptors and preserves legacy fallback.
5. Context selection produces the same bounded briefing set from typed publications and excludes large registered evidence.
6. MemPalace uses descriptor kinds and rooms without path reclassification.
7. Spec graphs create source and decision topology from descriptors joined to attached context rows.
8. OptaSearch republishing registers architecture, contracts, components, ADRs, CodeGraph artifacts, generated specs/checklists, and remaining durable outputs.
9. The full Echelon suite remains green.

## Out Of Scope

- Changing which source is automatically selected for a spec run.
- Injecting every registered artifact into prompts.
- Expanding raw CodeGraph entities into graph nodes.
- Retroactively attaching current RE publications to historical specs.
- Removing legacy named manifest fields in this release.
