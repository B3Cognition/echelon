# Echelon Agent Role Catalog

This catalog reconciles the public architecture narrative with the executable
source tree. It distinguishes agent entry points from support prompt files and
separates roles that are actively routed by the workflow from roles that are
registered for manual, future, or command-specific use.

## Source Of Truth

- Agent registry: `extension/extension.yml`
- Executable Phase A workflow: `extension/workflow/definition.yaml`
- Agent prompt files: `extension/agents/**/*.md`

Current grounded counts:

| Surface | Count | Meaning |
|---|---:|---|
| Registered agent roles | 53 | `extension.yml` entries whose `file` is under `agents/` |
| Active-routed manifest roles | 45 | Registered roles referenced by `definition.yaml` |
| Manifest-only roles | 8 | Registered roles not currently referenced by `definition.yaml` |
| Workflow-only dispatch aliases | 1 | Dispatch identifiers in `definition.yaml` that are not separate manifest roles |
| Support prompt files | 15 | Markdown appendices/templates under `extension/agents/` that are not agent entry points |

The previous public agent-count phrasing was stale. It does not match the
current source tree and appears closer to the number of command entries than the
number of agent roles.

## Layer Inventory

| Layer | Registered roles | Active-routed | Manifest-only |
|---|---:|---:|---:|
| Control | 6 | 5 | 1 |
| Exploration | 6 | 6 | 0 |
| Feasibility | 2 | 2 | 0 |
| Solution | 3 | 3 | 0 |
| Specialists | 6 | 6 | 0 |
| Learning | 8 | 3 | 5 |
| Build | 13 | 11 | 2 |
| Reverse engineering | 9 | 9 | 0 |

## Active-Routed Manifest Roles

These registered roles are referenced by `extension/workflow/definition.yaml`.

| Layer | Roles |
|---|---|
| Control | COMMANDER, CHIEF, SCOREKEEPER, STRATEGIST, TRACKER |
| Exploration | SCOUT, GOLDDIGGER, SYNTHESIZER, CARTOGRAPHER, SAGE, MODELER |
| Feasibility | GATEKEEPER, VALIDATOR |
| Solution | ARCHITECT, ORCHESTRATOR, SENTINEL |
| Specialists | INVESTIGATOR, GUARDIAN, BENCHMARK, ADVOCATE, ORACLE, MAVERICK |
| Learning | AUDITOR, REALIST, MIRROR |
| Build | IMPLEMENTER, SPEC GUARD, SPEC FULFILLMENT AUDITOR, IMPLEMENTATION MAPPER, CODE REVIEWER, TEST GUARDIAN, INTEGRATOR, PROGRESS TRACKER, DEBUGGER, VERIFICATION, VISUAL VALIDATOR |
| Reverse engineering | RE-ANALYZER, RE-SPECIFIER, RE-VERIFIER, RE-EXPANDER, RE-VALIDATOR, RE-CHECKLISTER, RE-CONSTITUTER, RE-PLANNER, RE-TASKER |

## Manifest-Only Roles

These roles are registered in `extension.yml` and have prompt files, but are not
currently referenced by the executable workflow graph. They should be treated as
available platform capabilities, not as guaranteed participants in every squad
run.

| Role | File | Current interpretation |
|---|---|---|
| CHECKPOINT | `agents/control/checkpoint.md` | Internalization quality assessor available outside the main workflow graph |
| INTERNALIZER | `agents/learning/internalizer.md` | Internalization metrics role; registered but not active-routed |
| ADAPTIVE | `agents/learning/adaptive.md` | Quality trajectory analysis role; registered but not active-routed |
| MONITOR | `agents/learning/monitor.md` | Metacognition watchdog; registered but not active-routed |
| VETERAN | `agents/learning/veteran.md` | Cross-project knowledge curator; registered but not active-routed |
| CONSOLIDATOR | `agents/learning/consolidator.md` | Episodic-to-schema learning role; registered but not active-routed |
| ENGINEERING MANAGER | `agents/build/engineering-manager.md` | Build convergence coordination role; registered but not active-routed |
| CHANGE CONTROLLER | `agents/build/change-controller.md` | Spec-change blast-radius role; registered but not active-routed |

## Workflow-Only Alias

`definition.yaml` references `speckit-echelon-gatekeeper-assess2`. This is not a
separate role in `extension.yml`; it is a Gatekeeper ASSESS2 dispatch/mode alias.
Do not count it as an additional registered agent unless it gets its own
manifest entry and prompt file.

## Support Prompt Files

The remaining markdown files under `extension/agents/` are appendices and
templates. They are not agent entry points and should not be counted as roles.
Examples include `agents/control/appendices/*`,
`agents/exploration/appendices/*`, and `agents/exploration/templates/*`.
