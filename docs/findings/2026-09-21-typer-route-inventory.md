# Typer Route Inventory

Baseline: `60e91d91` (`main` after S2)

## Summary

- Public Typer commands: 107
- Public commands already using modular services: 52
- Public commands delegating into `echelon.cli`: 55
- Hidden commands: 22
- Hidden commands delegating into `echelon.cli`: 18

The count treats commands below the hidden `harness` group as compatibility
routes even though the nested `run` and `land` decorators are not themselves
marked hidden.

Current S3 progress after the benchmark, stack, and workspace slices: 68 public
commands use modular services and 39 still delegate into `echelon.cli`.

## Public modular-service routes

| Group | Commands |
| --- | --- |
| `admin` | `commands` |
| `topology` | `audit`, `list-sources`, `search`, `explain`, `neighbors`, `impact` |
| `wiki` | `build`, `status`, `clean` |
| `kb` | `validate`, `apply` |
| `llm` | `smoke-openai-compatible` |
| `graph` | `build`, `query`, `explain`, `path`, `neighbors`, `impact`, `audit`, `refresh`, `export`, `view` |
| `graph workspace` | `build`, `audit`, `refresh`, `export`, `view` |
| `memory` | `search`, `list-rooms`, `list-specs`, `list-kinds` |
| `re memory` | `refresh`, `audit` |
| `spec checkpoint` | `list`, `accept`, `commit` |
| `spec memory` | `mine`, `audit`, `refresh` |
| `spec evidence` | `publish` |
| `spec evidence memory` | `refresh`, `audit` |
| `spec` | `switch`, `publish`, `verify`, `reconcile-fulfillment`, `defer`, `defer-runnability`, `plan-runnability`, `plan` |
| `delivery` | `status` |

## Baseline public routes delegated into `cli.py`

| Group | Commands | Classification |
| --- | --- | --- |
| root | `version` | Active |
| `benchmark` | `list`, `show`, `run` | Cut over to modular services |
| `stack` | `list`, `detect`, `preflight`, `provision`, `enable`, `disable`, `select`, `selected` | Cut over to modular services |
| `workspace` | `init`, `doctor`, `migrate-to-prosaic`, `migrate` | Cut over to modular services |
| `workspace sources` | `sync` | Cut over to modular services |
| `phase` | `list`, `run` | Active |
| `spec` | `run`, `retarget`, `status`, `continue`, `resume`, `add-input`, `resolve`, `rewind`, `repair-traceability`, `drop-target`, `targets`, `artifacts`, `reopen`, `bugfix`, `change`, `amend` | Active |
| `delivery` | `init`, `target`, `verify-local`, `cleanup-local`, `run`, `resume`, `continue`, `land` | Active |
| `delivery checkpoint` | `list` | Active |
| `re` | `run`, `refresh`, `deepen`, `status`, `continue`, `resume`, `publish`, `finalize`, `synthesize` | Active; keep protocol consolidation in S6 |
| hidden `harness` group | `run`, `land` | Compatibility aliases |

## Hidden routes

| Route | Classification |
| --- | --- |
| `cicd`, `build` | Retired error-only paths; delete after compatibility coverage is explicit |
| root `init`, `artifacts`, `status`, `land`, `continue`, `rewind`, `resume`, `run`, `review`, `verify-spec`, `reopen`, `bugfix`, `change` | Compatibility aliases |
| `harness continue`, `harness resume` | Compatibility aliases |
| `re execute-run`, `re check-domain` | Active internal workflow entry points |
| `re analyze`, `spec analyze` | Modular diagnostic entry points |
| `spec target` | Compatibility route |

## Recommended cutover order

1. `benchmark`: three isolated commands with an existing typed domain module.
2. `stack`: one cohesive public family with typed stack modules already present.
3. `workspace`: move initialization, doctor, migration, and source sync behind a
   workspace service boundary.
4. `phase` and `version`: small remaining general-purpose routes.
5. Compatibility and retired routes: delete error-only commands and make aliases
   call current services rather than private handlers.
6. `spec`: move the 16 active delegations behind the Phase A service boundary.
7. `delivery`: move the nine active delegations behind the controlled-delivery
   service boundary without changing its state contract.
8. `re`: establish a typed facade only; protocol deletion and consolidation remain
   owned by S6.

Each slice must delete its corresponding private `cli.py` handler, move focused
tests to the Typer surface, and pass focused verification before the next slice.
