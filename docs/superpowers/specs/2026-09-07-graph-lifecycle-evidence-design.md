# Graph Lifecycle Evidence Design

## Purpose

Make a landed specification eligible for graph composition when its current
canonical requirements and compatible verification evidence are healthy. The
graph must retain historical MemPalace and delivery evidence without treating
that retained history as a current-graph failure.

This repair is a prerequisite for using the graph as an evidence source during
specification escalation. It does not change SAGE decision policy or make the
graph itself authoritative over the current source tree.

## Observed Failure

The browser-game workspace exposes three distinct lifecycle failures:

1. The canonical MemPalace drawers are complete, but older non-canonical
   documentation/evidence drawers for the same spec remain in the wing. The
   audit currently marks every such extra drawer as both stale and
   non-canonical, then fails the whole member graph.
2. The canonical verified-fulfillment ledger for spec 003 retains an early
   `UNVERIFIED` NFR-001 result even though later authoritative verification
   receipts prove the five-step journey. The later receipt was never reconciled
   into the published ledger.
3. Older specs already declare a symbolic target and source path in `targets.yml`,
   but workspace composition only resolves that mapping through published-RE
   source maps. With no published RE source node, the otherwise valid path is
   reported unresolved.

The first is an incorrect audit classification. The second is a provenance
handoff gap. The third is incomplete topology migration. They must not be
solved by weakening requirement verification or deleting historical evidence.

## Goals

- Keep immutable historical memory and verification evidence queryable.
- Fail graph health only for current canonical evidence that is missing,
  malformed, stale, contradictory, or incorrectly scoped.
- Record compatible authoritative verification at delivery landing.
- Reconcile legacy receipts only under deterministic compatibility proof,
  including immutable inventory reconstruction when a pre-fingerprint receipt
  lacks a direct product-content fingerprint.
- Resolve a graph target from a declared unique source path without inventing
  an ambiguous mapping.
- Make `graph workspace refresh --write` followed by `graph workspace audit`
  a useful, explainable health check.

## Non-Goals

- Do not delete, rewrite, or silently promote historical MemPalace drawers.
- Do not infer verification success from a Markdown claim, an implementation
  status, or commit ancestry alone.
- Do not make graph refresh mutate a spec's fulfillment ledger.
- Do not change delivery quality gates, SAGE defaults, or the active animation
  specification in this change.

## Design

### 1. Canonical-memory audit separates history from corruption

The audit already knows the expected canonical drawer identities. It will
validate each expected drawer exactly as today: identity, scope, wing, room,
lifecycle, and content hashes remain blocking checks.

For drawers outside that expected set, classification changes only after their
metadata positively scopes them to this same spec and current wing. The audit
must not let a malformed or unscoped drawer in a shared collection alter an
unrelated member's health.

| Extra drawer state | Audit result | Graph health |
| --- | --- | --- |
| Scoped, explicitly non-canonical or terminal/superseded lifecycle | `historical` finding | warning only |
| Canonical and duplicates a current requirement/evidence identity | `duplicate_canonical` finding | error |
| Canonical but claims the active spec/scope without a valid expected identity | `scope_collision` finding | error |
| Positively scoped malformed metadata or mismatched active wing/room | `malformed_extra` finding | error |
| Unscoped or foreign malformed extra | `global_memory_integrity` finding | workspace warning; does not fail this member |

The report will retain distinct `historical` and blocking collections so UI and
graph audit can explain why history is preserved but ignored. Existing callers
that need a boolean health result consume the blocking collection, not every
extra record.

### 2. Verified-fulfillment reconciliation has explicit provenance

Introduce a pure reconciliation service that accepts a canonical spec ledger
and candidate authoritative verification receipts. The ledger moves to schema
version 2 and records immutable receipt references, receipt hashes, normalized
candidate-content fingerprints, and the selected evidence set per requirement.

A candidate can replace an unresolved row only when all of the following hold:

- it is a harness-owned, successful verification receipt with named evidence;
- its direct normalized product-content fingerprint equals the canonical landed
  product fingerprint, or a legacy adapter reconstructs an equivalent
  fingerprint from its immutable product inventory and a fresh canonical-target
  inventory;
- its spec-input and requirement-set fingerprints equal the current canonical
  spec inputs, directly or from an immutable spec snapshot retained beside the
  legacy verification run; and
- its requirement row covers the same requirement identifier with complete
  evidence.

Commit SHA is retained as provenance but is not equality authority: a merge-only
commit is compatible when the normalized product content is unchanged. A legacy
inventory is eligible only when its file paths, kinds, executable flags, and
content hashes exactly match a freshly generated canonical-target inventory;
the fallback Markdown report is explanatory only, never sufficient evidence.
If a legacy run lacks an immutable compatible spec snapshot, reconciliation
returns `reverify_required` rather than upgrading from its prose report.

Multiple compatible successful receipts corroborate one another. Reconciliation
retains every validated reference, selects a stable primary receipt by
verification time then receipt hash, and records the aggregation in its own
receipt. A conflict exists only when a candidate fails compatibility, lacks
complete requirement evidence, or presents a contradictory result for the same
compatible content—not merely because more than one success exists.

New delivery landing calls this service as part of finalization and writes the
resulting verified-fulfillment ledger in the same durable publication step as
the landing receipt. Thus a spec cannot be marked landed while its successful
authoritative verification is stranded in a run directory.

For historical specs, add an explicit `echelon spec reconcile-fulfillment
<spec> --write` command. It previews candidate receipts, their direct or
inventory-reconstructed compatibility proof, and rejected reasons by default.
It writes only the deterministic result with a reconciliation receipt. Graph
refresh remains read/graph-write only and reports the command when an unresolved
current ledger has compatible historical evidence.

### 3. Workspace target resolution uses declared source paths

Add a topology resolver for graph composition. Its precedence is:

1. the canonical per-spec `targets.yml` entry, when its path exists inside a
   configured workspace source root;
2. explicit current workspace target registry mapping;
3. one published landing receipt source path inside a configured source root.

The resolver writes the selected path, resolution source, and a fresh source
snapshot fingerprint into the graph. When a valid `targets.yml` path has no
published RE graph, composition creates a path-validated `SourceSnapshot` node
rather than requiring a fabricated registry entry. A later published RE source
graph can attach to that stable snapshot. Multiple candidates or paths outside
configured source roots remain `target_unresolved` warnings; Echelon never
selects by a directory-name guess.

This supports legacy symbolic target names while preserving a clear migration
path to explicit target registration.

## Data Flow

```text
MemPalace history ──> canonical-memory audit ──> member graph health
                                  │
                                  └── historical warnings (non-blocking)

authoritative verifier receipt ──> fulfillment reconciliation ──> canonical ledger
                                                                  │
spec source path / landing receipt ──> target resolver ──────────┤
                                                                  v
                                                     workspace graph + audit
```

## Error Handling and Safety

- A missing current drawer, wrong wing/room, malformed active identity, or
  canonical duplicate remains an error.
- A receipt cannot improve a requirement status without matching direct or
  inventory-reconstructed content proof, matching input fingerprints, and
  complete requirement-level evidence.
- Reconciliation writes are atomic and create a receipt containing selected and
  rejected candidates with reasons.
- Existing historical drawers are never deleted or rewritten.
- Graph generation remains available for diagnosis even when audit is unhealthy;
  workspace composition excludes only genuinely unhealthy members.

## Verification Plan

Unit and integration coverage will prove:

1. complete current drawers plus historical non-canonical extras yield graph
   health `pass` with historical warnings;
2. active canonical duplicates, wrong scope, and malformed extras still fail;
3. a matching later verifier receipt updates an unresolved ledger row;
4. a legacy receipt updates an unresolved row only when its immutable inventory
   exactly matches the canonical target and it retains a matching immutable spec
   snapshot; a changed file, missing entry, changed executable flag, or absent
   spec snapshot rejects it with `reverify_required`;
5. multiple compatible successful receipts aggregate deterministically;
6. changed product content, changed spec inputs, incomplete evidence, and
   contradictory receipt candidates do not update it;
7. landing writes compatible verification evidence into the canonical ledger;
8. `targets.yml` resolves to a path-validated source snapshot when published RE
   is absent, while zero or multiple candidates remain unresolved; and
9. the browser-game workspace can publish/refresh/audit its graph without
   excluding specs 003 or 006 for historical-memory contamination.

## Rollout

1. Implement and test the lifecycle services in Echelon.
2. Run the legacy reconciliation preview against the browser-game workspace.
3. Apply only its fingerprint-compatible result, refresh the member and
   workspace graphs, and inspect the resulting audit.
4. Only then use the healthy graph in the evidence-led escalation design.
