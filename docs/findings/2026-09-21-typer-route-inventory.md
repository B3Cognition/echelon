# Typer Route Inventory

Baseline: `60e91d91` (`main` after S2)

## Summary

- Public Typer commands: 104
- Public commands already using modular services: 95
- Public commands delegating into `echelon.cli`: 9
- Hidden commands: 23
- Hidden commands directly consuming `_legacy_cli()`: 2

The executable `typer.main.get_command(app)` tree was recounted on 2026-09-23:
walk `click.Group.commands` recursively, count leaf commands, and inherit each
parent's `hidden` flag. This treats all commands below hidden `harness` and
`admin` groups as hidden, even when their own decorators are not hidden.
Inspect each unwrapped leaf callback for `_legacy_cli()` consumption; the nine
public consumers are the active RE routes below, and the two hidden consumers
are `re execute-run` and `re check-domain`. Compatibility aliases can still
reach legacy RE code indirectly through their canonical routes.

Current S3 progress after the benchmark, stack, workspace, phase/version,
compatibility, spec, and Delivery slices: 95 public commands use modular
services and 9 still delegate into `echelon.cli`. The active RE facade is the
next and final Typer cutover slice; RE protocol consolidation remains owned by
S6.

Delivery cutover verification used merge base `3abca341`: the structural
ownership search returned no legacy `cli.py` definitions and the boundary suite
passed 13 tests. The broader focused Delivery suite passed 287 tests; the CLI
regression gate recorded 1,672 passes and one known pre-existing failure. The
repository gate recorded 9,822 passed, 0 skipped, 11,434 deselected, and 0
failures in 29m34.11s after its ownership validator moved with the service.
Receipt:
`tests/reports/merge-verification/receipt-0741dd4c9f62-d59ac9b2a44647fa8e97504443ecff94.json`.

The compatibility cleanup removed the hidden retired `build` and `cicd`
routes. Retained root and hidden `harness` aliases now call their canonical
Typer commands rather than duplicating private-handler argument translation;
the unmatched hidden `review` alias is contained behind one explicitly named
compatibility adapter.

## Public modular-service routes

| Group | Commands |
| --- | --- |
| root | `version` |
| `benchmark` | `list`, `show`, `run` |
| `stack` | `list`, `detect`, `preflight`, `provision`, `enable`, `disable`, `select`, `selected` |
| `workspace` | `init`, `doctor`, `migrate-to-prosaic`, `migrate` |
| `workspace sources` | `sync` |
| `phase` | `list`, `run` |
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
| `spec` | `run`, `retarget`, `status`, `continue`, `resume`, `add-input`, `resolve`, `rewind`, `repair-traceability`, `drop-target`, `targets`, `artifacts`, `reopen`, `bugfix`, `change`, `amend`, `switch`, `publish`, `verify`, `reconcile-fulfillment`, `defer`, `defer-runnability`, `plan-runnability`, `plan` |
| `delivery` | `init`, `target`, `verify-local`, `cleanup-local`, `run`, `resume`, `continue`, `land` |
| `delivery checkpoint` | `list` |
| `delivery` | `status` (`echelon.delivery_status` public facade; its status kernel belongs to `echelon.delivery_service`) |

## Baseline public routes delegated into `cli.py`

| Group | Commands | Classification |
| --- | --- | --- |
| root | `version` | Cut over to `echelon.version` |
| `benchmark` | `list`, `show`, `run` | Cut over to modular services |
| `stack` | `list`, `detect`, `preflight`, `provision`, `enable`, `disable`, `select`, `selected` | Cut over to modular services |
| `workspace` | `init`, `doctor`, `migrate-to-prosaic`, `migrate` | Cut over to modular services |
| `workspace sources` | `sync` | Cut over to modular services |
| `phase` | `list`, `run` | Cut over to `echelon.phase_service`; replay temporarily reuses shared spec/recovery helpers in `cli.py` pending the spec slice |
| `re` | `run`, `refresh`, `deepen`, `status`, `continue`, `resume`, `publish`, `finalize`, `synthesize` | Active; keep protocol consolidation in S6 |
| hidden `harness` group | `run`, `land` | Compatibility aliases |

## Hidden routes

| Route | Classification |
| --- | --- |
| root `init`, `artifacts`, `status`, `land`, `continue`, `rewind`, `resume`, `run`, `review`, `verify-spec`, `reopen`, `bugfix`, `change` | Compatibility aliases; canonical forwarding is isolated from active route implementations |
| `harness run`, `harness land`, `harness continue`, `harness resume` | Compatibility aliases forwarding to canonical `delivery` commands |
| `re execute-run`, `re check-domain` | Active internal workflow entry points |
| `re analyze`, `spec analyze` | Modular diagnostic entry points |
| `spec target` | Retired mutation guard isolated in `echelon.spec_service`; no `cli.py` delegation |
| `admin commands` | Modular command inventory below the hidden `admin` group |

## Recommended cutover order

1. `benchmark`: three isolated commands with an existing typed domain module.
2. `stack`: one cohesive public family with typed stack modules already present.
3. `workspace`: move initialization, doctor, migration, and source sync behind a
   workspace service boundary.
4. `phase` and `version`: small remaining general-purpose routes.
5. Compatibility and retired routes: completed; error-only commands are deleted
   and aliases call canonical commands rather than duplicating private-handler
   dispatch.
6. `spec`: move the 16 active delegations behind the Phase A service boundary.
7. `delivery`: move the nine active delegations behind the controlled-delivery
   service boundary without changing its state contract.
8. `re`: establish a typed facade only; protocol deletion and consolidation remain
   owned by S6.

Each slice must delete its corresponding private `cli.py` handler, move focused
tests to the Typer surface, and pass focused verification before the next slice.
