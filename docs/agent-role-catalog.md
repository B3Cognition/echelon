# Echelon Agent Role Catalog

This catalog reconciles Echelon's public architecture with its canonical
Prosaic prose and runtime workflow. It distinguishes roles referenced by the
structured workflow graph from roles invoked directly by controllers, commands,
or supporting workflows.

## Source Of Truth

- Neutral agent prose: `prosaic/subagents/*.md`
- Structured workflow references: `runtime/workflow/definition.yaml`
- Python-owned profiles: `src/harness/discovery_producer.py`,
  `delivery_slice_runner.py`, `delivery_documentation.py`,
  `semantic_visual_validator.py`, `controlled_fulfillment.py`, and `review_loop.py`
- Companion prose: `prosaic/agents/**/*.md`

Current grounded counts:

| Surface | Count | Meaning |
|---|---:|---|
| Neutral Prosaic agent roles | 99 | Canonical subagent files with neutral `echelon.*` identities |
| Workflow-referenced roles | 34 | Neutral IDs used by structured `agent` or nested dispatch contracts, including three disabled internal roles |
| Roles outside the workflow graph | 65 | Controller-owned profiles and retained direct-use prose, not an assertion that every role has an active route |
| Support prose files | 14 | Appendices and templates that are not independent agent entry points |

Every workflow-referenced ID resolves to a canonical Prosaic subagent. RE-DISCOVERER
and RE-DISCOVERY-REVIEWER, plus RE-KNOWLEDGE-RECONCILER, are internal contracts with installed routing disabled. Membership in this inventory is not evidence that a
role is enabled in a particular run. Outside the graph does not mean unused:
COMMANDER, for example, is invoked by the Python controller
for judgment and routing rather than declared as an ordinary agent phase.

## Layer Inventory

| Layer | Prosaic roles | Workflow-referenced | Outside graph |
|---|---:|---:|---:|
| Control | 7 | 3 | 4 |
| Exploration | 7 | 6 | 1 |
| Feasibility | 2 | 1 | 1 |
| Solution | 3 | 3 | 0 |
| Specialists | 6 | 6 | 0 |
| Learning | 8 | 0 | 8 |
| Delivery, fulfillment and PR review | 27 | 3 | 24 |
| Reverse engineering | 18 | 12 | 6 |
| Managed authoring profiles | 21 | 0 | 21 |

## Workflow-Referenced Roles

These roles occur in structured dispatch fields in
`runtime/workflow/definition.yaml`.

| Layer | Roles |
|---|---|
| Control | `echelon.chief`, `echelon.strategist`, `echelon.tracker` |
| Exploration | `echelon.scout`, `echelon.synthesizer`, `echelon.cartographer`, `echelon.lexicon-deriver`, `echelon.sage`, `echelon.modeler` |
| Feasibility | `echelon.gatekeeper` |
| Solution | `echelon.architect`, `echelon.orchestrator`, `echelon.sentinel` |
| Specialists | `echelon.investigator`, `echelon.guardian`, `echelon.benchmark`, `echelon.advocate`, `echelon.oracle`, `echelon.maverick` |
| Delivery-related supporting workflows | `echelon.spec-guard`, `echelon.implementation-mapper`, `echelon.debugger` |
| Reverse engineering | `echelon.re-analyzer`, `echelon.re-specifier`, `echelon.re-verifier`, `echelon.re-expander`, `echelon.re-validator`, `echelon.re-checklister`, `echelon.re-constituter`, `echelon.re-planner`, `echelon.re-tasker`, `echelon.re-discoverer`, `echelon.re-discovery-reviewer`, `echelon.re-knowledge-reconciler` |

## Roles Outside The Workflow Graph

These roles have canonical Prosaic prompts but no structured dispatch field in
the YAML graph. This includes Python-owned profiles and retained supporting
prose. Availability alone does not activate a route. In particular, generic
build prose does not restore the deleted command-driven Phase B graph:
`echelon delivery run` uses the bounded controlled-delivery profiles listed below.

| Layer | Roles |
|---|---|
| Control | `echelon.commander`, `echelon.scorekeeper`, `echelon.checkpoint`, `echelon.summarizer` |
| Exploration | `echelon.golddigger` |
| Feasibility | `echelon.validator` |
| Learning | `echelon.adaptive`, `echelon.auditor`, `echelon.consolidator`, `echelon.internalizer`, `echelon.mirror`, `echelon.monitor`, `echelon.realist`, `echelon.veteran` |
| Retained delivery/support prose | `echelon.change-controller`, `echelon.engineering-manager`, `echelon.spec-fulfillment-auditor`, `echelon.verification`, `echelon.visual-validator`, `echelon.implementer`, `echelon.code-reviewer`, `echelon.test-guardian`, `echelon.tech-writer`, `echelon.docs-verifier`, `echelon.integrator`, `echelon.progress-tracker` |
| Controlled delivery | `echelon.delivery-implementer`, `echelon.delivery-spec-guard`, `echelon.delivery-code-reviewer`, `echelon.delivery-test-guardian`, `echelon.delivery-tech-writer`, `echelon.delivery-docs-verifier`, `echelon.delivery-visual-validator` |
| Controlled fulfillment | `echelon.fulfillment-mapper`, `echelon.fulfillment-judge` |
| PR triage | `echelon.review-debugger`, `echelon.review-sentinel`, `echelon.review-spec-guard` |
| Reverse engineering | `echelon.re-baseliner`, `echelon.re-deepener`, `echelon.re-resolver`, `echelon.re-synthesizer`, `echelon.re-exhaustive-analyst`, `echelon.re-exhaustive-verifier` |
| Managed discovery and synthesis | `echelon.discovery-producer`, `echelon.discovery-reviewer`, `echelon.synthesis-producer` |
| Managed intent and policy | `echelon.tracker-producer`, `echelon.tracker-reviewer`, `echelon.constitution-producer`, `echelon.constitution-reviewer`, `echelon.lexicon-producer`, `echelon.lexicon-reviewer` |
| Managed requirements and challenge | `echelon.what-producer`, `echelon.what-reviewer`, `echelon.why1-producer`, `echelon.why1-reviewer`, `echelon.why2-producer`, `echelon.why2-reviewer` |
| Managed feasibility and alignment | `echelon.feasibility-producer`, `echelon.feasibility-reviewer`, `echelon.alignment-producer`, `echelon.alignment-reviewer`, `echelon.strategy-producer`, `echelon.strategy-reviewer` |

## Companion Prose

The files under `prosaic/agents/` are appendices and templates used by canonical
subagents. They are deployed as companion prose and are not counted as agent
roles.
