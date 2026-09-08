# Echelon Agent Role Catalog

This catalog reconciles Echelon's public architecture with its canonical
Prosaic prose and runtime workflow. It distinguishes roles referenced by the
structured workflow graph from roles invoked directly by controllers, commands,
or supporting workflows.

## Source Of Truth

- Neutral agent prose: `prosaic/subagents/*.md`
- Executable workflow graph: `runtime/workflow/definition.yaml`
- Companion prose: `prosaic/agents/**/*.md`

Current grounded counts:

| Surface | Count | Meaning |
|---|---:|---|
| Neutral Prosaic agent roles | 65 | Canonical subagent files with neutral `echelon.*` identities |
| Workflow-referenced roles | 40 | Neutral IDs used by structured `agent` or nested dispatch contracts, including two disabled internal roles |
| Direct-use roles | 25 | Available roles invoked outside ordinary workflow agent nodes |
| Support prose files | 14 | Appendices and templates that are not independent agent entry points |

Every workflow-referenced ID resolves to a canonical Prosaic subagent. RE-DISCOVERER
and RE-DISCOVERY-REVIEWER are internal contracts with installed routing disabled; the other 38
workflow-referenced roles retain their existing routing. Direct-use
does not mean unused: COMMANDER, for example, is invoked by the Python controller
for judgment and routing rather than declared as an ordinary agent phase.

## Layer Inventory

| Layer | Prosaic roles | Workflow-referenced | Direct-use |
|---|---:|---:|---:|
| Control | 7 | 3 | 4 |
| Exploration | 7 | 6 | 1 |
| Feasibility | 2 | 1 | 1 |
| Solution | 3 | 3 | 0 |
| Specialists | 6 | 6 | 0 |
| Learning | 8 | 0 | 8 |
| Build | 15 | 10 | 5 |
| Reverse engineering | 17 | 11 | 6 |

## Workflow-Referenced Roles

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
| Reverse engineering | RE-ANALYZER, RE-SPECIFIER, RE-VERIFIER, RE-EXPANDER, RE-VALIDATOR, RE-CHECKLISTER, RE-CONSTITUTER, RE-PLANNER, RE-TASKER, RE-DISCOVERER and RE-DISCOVERY-REVIEWER (disabled internal contracts) |

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
| Reverse engineering | RE-BASELINER, RE-DEEPENER, RE-RESOLVER, RE-SYNTHESIZER, RE-EXHAUSTIVE-ANALYST, RE-EXHAUSTIVE-VERIFIER |

## Companion Prose

The files under `prosaic/agents/` are appendices and templates used by canonical
subagents. They are deployed as companion prose and are not counted as agent
roles.
