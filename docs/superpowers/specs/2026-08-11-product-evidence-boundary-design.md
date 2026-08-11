# Product Evidence Boundary Design

**Date:** 2026-08-11
**Finding:** EGR-153
**Status:** approved through the ordered EGR-153 implementation request

## Goal

Give verify-spec a deterministic inventory of deliverable product files that
excludes Echelon's deployed control plane, so repository-wide requirements can
be judged without treating `.echelon/prosaic` or `.echelon/runtime` as product
content.

## Chosen Approach

Add a Python-owned `product-inventory.json` and `product-inventory.md` artifact
to the verify-spec run. Build the inventory from Git's tracked and non-ignored
untracked file set, then exclude the complete `.echelon/` control root, `.git/`,
and the root `.harness-build-status.json` control marker. Preserve all other
hidden files; Echelon must not equate hidden with non-product.

The verify-spec audit phase writes the inventory before IMPLEMENTATION MAPPER
runs. The mapper receives both forms, treats them as the authoritative bounded
file set for repository-wide existence and cardinality claims, and continues to
inspect cited source/tests for behavioral claims. The inventory is evidence,
not a requirement judge.

## Alternatives Rejected

### Prompt-only exclusions

Telling the mapper to ignore `.echelon` is inexpensive but does not produce
reproducible cardinality evidence. A later provider or prompt edit could silently
change the effective boundary.

### Do not deploy bundles to delivery worktrees

Direct Prosaic agents require the deployed prose and runtime companion files.
Removing them would reintroduce provider scaffolding and chicken-and-egg
failures already resolved by the migration.

## Artifact Contract

`product-inventory.json` contains:

- `schema_version: 1`;
- normalized project root;
- inventory source (`git-deliverable` or filesystem fallback);
- excluded control roots;
- sorted entries with relative path, kind, size, executable bit, and SHA-256
  for regular files;
- summary counts and basename counts.

`product-inventory.md` renders the same sorted entries for agent consumption.
The writer fails closed when the project root is missing or an inventory path
escapes the project root. A verify-spec state file must already exist; the CLI
stamps inventory readiness and file count only after both artifacts are written.

## Workflow Integration

- `verify-spec-3-audit` runs `python -m harness write-product-inventory`.
- `verify-spec-3-audit` declares both inventory files as outputs.
- `verify-spec-4-map` and IMPLEMENTATION MAPPER list both files as inputs.
- Repository-wide existence and cardinality evidence must cite the inventory.
- Behavioral fulfillment still requires direct source, test, or measured
  evidence; inventory membership alone is not behavioral proof.

## Testing

- Unit test Git-tracked and non-ignored untracked files are included.
- Unit test `.echelon/**`, `.git/**`, and ignored generated files are excluded.
- Unit test a different hidden product file remains included.
- CLI test writes both artifacts and stamps existing verify state.
- Prompt/workflow tests require the command, artifacts, and mapper boundary
  language.
- Focused fulfillment and prompt-reference suites must pass before rerunning the
  retained greenfield delivery.
