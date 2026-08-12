# Echelon Agent Role Catalog

This catalog reconciles Echelon's public architecture with its canonical
Prosaic prose and runtime workflow. It distinguishes roles dispatched by the
structured workflow graph from roles invoked directly by controllers, commands,
or supporting workflows.

## Source Of Truth

- Neutral agent prose: `prosaic/subagents/*.md`
- Executable workflow graph: `runtime/workflow/definition.yaml`
- Companion prose: `prosaic/agents/**/*.md`

Current grounded counts:

| Surface | Count | Meaning |
|---|---:|---|
| Neutral Prosaic agent roles | 57 | Canonical subagent files with neutral `echelon.*` identities |
| Workflow-dispatched roles | 38 | Neutral IDs used by structured `agent` or nested dispatch nodes |
| Direct-use roles | 19 | Available roles invoked outside ordinary workflow agent nodes |
| Support prose files | 14 | Appendices and templates that are not independent agent entry points |

Every workflow-dispatched ID resolves to a canonical Prosaic subagent. Direct-use
does not mean unused: COMMANDER, for example, is invoked by the Python controller
for judgment and routing rather than declared as an ordinary agent phase.

## Layer Inventory

| Layer | Prosaic roles | Workflow-dispatched | Direct-use |
|---|---:|---:|---:|
| Control | 7 | 3 | 4 |
| Exploration | 7 | 6 | 1 |
| Feasibility | 2 | 1 | 1 |
| Solution | 3 | 3 | 0 |
| Specialists | 6 | 6 | 0 |
| Learning | 8 | 0 | 8 |
| Build | 15 | 10 | 5 |
| Reverse engineering | 9 | 9 | 0 |

## Workflow-Dispatched Roles

These roles occur in structured dispatch fields in
`runtime/workflow/definition.yaml`.

| Layer | Roles |
|---|---|
| Control | CHIEF, STRATEGIST, TRACKER |
| Exploration | SCOUT, SYNTHESIZER, CARTOGRAPHER, LEXICON DERIVER, SAGE, MODELER |
| Feasibility | GATEKEEPER |
| Solution | ARCHITECT, ORCHESTRATOR, SENTINEL |
| Specialists | INVESTIGATOR, GUARDIAN, BENCHMARK, ADVOCATE, ORACLE, MAVERICK |
| Build | IMPLEMENTER, SPEC GUARD, IMPLEMENTATION MAPPER, CODE REVIEWER, TEST GUARDIAN, TECH WRITER, DOCS VERIFIER, INTEGRATOR, PROGRESS TRACKER, DEBUGGER |
| Reverse engineering | RE-ANALYZER, RE-SPECIFIER, RE-VERIFIER, RE-EXPANDER, RE-VALIDATOR, RE-CHECKLISTER, RE-CONSTITUTER, RE-PLANNER, RE-TASKER |

## Direct-Use Roles

These roles have canonical Prosaic prompts but are not ordinary structured agent
nodes in the runtime graph.

| Layer | Roles |
|---|---|
| Control | COMMANDER, SCOREKEEPER, CHECKPOINT, SUMMARIZER |
| Exploration | GOLDDIGGER |
| Feasibility | VALIDATOR |
| Learning | ADAPTIVE, AUDITOR, CONSOLIDATOR, INTERNALIZER, MIRROR, MONITOR, REALIST, VETERAN |
| Build | CHANGE CONTROLLER, ENGINEERING MANAGER, SPEC FULFILLMENT AUDITOR, VERIFICATION, VISUAL VALIDATOR |

SUMMARIZER selects and orders four to eight opaque IDs from an Echelon-authored
candidate list; it never authors terminal prose. Echelon deterministically builds
the outcome-first sentences from bounded durable lifecycle evidence, preserving
exact verification commands, lifecycle-attributed `short SHA — subject` commits,
provider limits, and recovery actions. Unknown, duplicate, incomplete, or
open-ended model output falls back to deterministic candidate ordering.

## Companion Prose

The files under `prosaic/agents/` are appendices and templates used by canonical
subagents. They are deployed as companion prose and are not counted as agent
roles.
