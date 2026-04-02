# Echelon Proto — Glossary

## Agent Directory (42 Agents across 7 Tiers)

### TIER 1: CONTROL (Orchestration & Learning)
| Codename | Full Name | Function | Responsibility |
|----------|-----------|----------|-----------------|
| COMMANDER | MANAGER | Global dispatcher and state machine | Routes all 41 agents; maintains state.json; enforces quality gates; applies EVOI analysis; handles token budgets |
| SCOREKEEPER | SCORING ENGINE | Performance tracking | Records agent quality metrics; builds historical calibration data; tracks confidence scores |
| TRACKER | INTENT-TRACKER | User intent alignment | Validates that scope stays true to user intent; detects scope drift |
| STRATEGIST | OVERVIEW | Strategic context | Provides high-level system summary and goal stack context |
| CHECKPOINT | INTERNALIZE-GATE | Internalization verification | Verifies agent absorb specs and validate understanding before proceeding |
| PROSPECTOR | SURVEY | Lightweight discovery | Performs survey-mode discovery when deep analysis not needed |

### TIER 2: EXPLORATION (Discovery & Requirements)
| Codename | Full Name | Function | Responsibility |
|----------|-----------|----------|-----------------|
| SCOUT | DISCOVER | Domain reconnaissance | Maps codebases, identifies boundaries, builds mental models, catalogs domain unknowns |
| SAGE | WHY | Challenge & validation | Adversarially challenges assumptions; validates reasoning; performs Understanding metrics analysis |
| SYNTHESIZER | FUSE | Knowledge fusion | Merges discovery fragments; detects cross-source contradictions; requests GOLDDIGGER deep dives |
| CARTOGRAPHER | WHAT | Requirements analyst | Transforms discovery into testable, technology-agnostic specifications |
| GOLDDIGGER | REVERSE-ENG | Reverse engineering | Deep structural code analysis; function signature extraction; dependency mapping; call graph tracing |
| MODELER | MENTAL-MODEL | Concept mapper | Builds refined entity-relationship models; identifies implicit patterns; maps concept hierarchies |

### TIER 3: FEASIBILITY (Assessment & Gating)
| Codename | Full Name | Function | Responsibility |
|----------|-----------|----------|-----------------|
| GATEKEEPER | ASSESS | Strategic PM / kill gate | Evaluates feasibility; estimates effort via FPA; prioritizes features; makes PASS/DEFER/KILL decisions |
| VALIDATOR | INTERNALIZATION-GATE | Specification validator | Validates spec quality gates; runs Understanding metrics; escalates failing requirements |

### TIER 4: SOLUTION (Architecture & Design)
| Codename | Full Name | Function | Responsibility |
|----------|-----------|----------|-----------------|
| ARCHITECT | HOW | Solution designer | Defines technology-specific architecture; designs data models; specifies interfaces and contracts |
| ORCHESTRATOR | PLAN | Implementation planner | Breaks architecture into tasks; defines task dependencies; creates Gantt paths; task sequencing |
| SENTINEL | TEST-ARCHITECT | Test strategy designer | Designs test architecture; identifies test cases; specifies test contracts and coverage targets |

### TIER 5: BUILD & VERIFICATION
| Codename | Full Name | Function | Responsibility |
|----------|-----------|----------|-----------------|
| IMPLEMENTER | BUILDER | Code writer | Writes actual implementation; follows architecture; adheres to style guides |
| CODE-REVIEWER | CODE-REVIEW | Code quality gate | Reviews code against style, tests, architecture alignment; blocks low-quality commits |
| DEBUGGER | DEBUG | Defect resolution | Analyzes failures; roots causes; fixes bugs; validates fixes |
| TEST-GUARDIAN | TEST-EXECUTOR | Testing gate | Executes tests; validates coverage; verifies acceptance criteria; blocks inadequate test suites |
| SPEC-GUARD | SPEC-CHECK | Specification compliance | Validates implementation matches spec; flags deviations; blocks spec violations |
| INTEGRATOR | INTEGRATION | System composition | Integrates modules into system; validates interfaces work; performs cross-module testing |
| CHANGE-CONTROLLER | CHANGE-CONTROL | Change management | Tracks design changes; manages technical debt; approves or blocks changes to architecture |
| VERIFICATION | BACKPROPAGATION-CHECK | Consistency check | Validates that implementation satisfies requirements top-to-bottom; catches regressions |
| VISUAL-VALIDATOR | VISUAL-VALIDATION | UI/UX validation | Tests visual output; validates accessibility; confirms layout correctness |
| PROGRESS-TRACKER | BUILD-TRACKER | Build progress monitoring | Tracks build phase progress; detects stalls; escalates blockers |
| ENGINEERING-MANAGER | BUILD-MANAGER | Build phase lead | Manages build phase overall; coordinates specialist interactions; handles escalations |

### TIER 6: SPECIALISTS (Domain Experts & Innovation)
| Codename | Full Name | Function | Responsibility |
|----------|-----------|----------|-----------------|
| GUARDIAN | SECURITY | Security gate | Identifies security risks; mandates mitigations; blocks unsafe code |
| BENCHMARK | PERFORMANCE | Performance gate | Profiles performance; identifies bottlenecks; validates non-functional requirements |
| INVESTIGATOR | SCIENTIST | Research & investigation | Investigates unknowns; researches novel approaches; resolves critical ambiguities |
| MAVERICK | INNOVATE | Creative exploration | Explores unconventional solutions; stress-tests assumptions; surfaces creative alternatives |
| ADVOCATE | UX-A11Y | User experience & accessibility | Validates accessibility; tests user workflows; ensures inclusive design |
| ORACLE | DOMAIN-EXPERT | Domain specialist | Provides deep domain knowledge; validates domain assumptions; teaches domain concepts |

### TIER 7: LEARNING & EVOLUTION (Improvement Loop)
| Codename | Full Name | Function | Responsibility |
|----------|-----------|----------|-----------------|
| MIRROR | REFLECT | Post-run analysis | Analyzes run outcomes; extracts learnings; identifies patterns and anti-patterns |
| AUDITOR | CALIBRATE | Accuracy calibration | Audits prior estimate accuracy; computes correction factors; refines baselines |
| ADAPTIVE | EVOLVE | Evolutionary adaptation | Detects signal degradation; recommends agent prompt evolution; tracks improvement trends |
| REALIST | GROUND | Reality check | Validates assumptions against ground truth; flags invalid assumptions discovered during build |
| VETERAN | PROJECT-SCOPING | Historical learning | Applies lessons from prior projects; suggests scope patterns; warns of known pitfalls |
| INTERNALIZER | INTERNALIZE-METRICS | Understanding measurement | Measures agent understanding via diagnostic matrices; validates absorption thresholds |
| MONITOR | METACOGNITION-MONITOR | Self-awareness | Performs periodic health checks; detects cognitive drift; validates reasoning consistency |
| GLOBAL-MEMORY | KNOWLEDGE-VAULT | Historical knowledge base | Maintains project memory; stores artifacts; enables cross-run retrieval |

---

## Key Architecture Terms

### Agent Taxonomy

| Term | Definition | Context |
|------|-----------|---------|
| **Tier** | A horizontal grouping of agents by responsibility phase (CONTROL, EXPLORE, ASSESS, SOLVE, BUILD, SPECIALIST, LEARN). One agent per tier per dispatch round. | 7 tiers × 6 dispatches max per phase = 42 agents total |
| **Phase** | DISCOVER (maps domain) → WHY (validates assumptions) → WHAT (writes specs) → ASSESS (kills or greenlight) → HOW (designs solution) → PLAN (tasks) → BUILD (codes) → LEARN (extracts lessons) | 8 macro phases; COMMANDER sequence gates between them |
| **Dispatch** | A single agent invocation. COMMANDER dispatches one agent at a time (or up to 5 in parallel via BANZAI). | `state.json.dispatch_history` logs all dispatches |
| **Stage** | Within a phase, the logical step (e.g., DISCOVER stage 1 = SCOUT runs first, stage 2 = SYNTHESIZER runs) | Defines agent sequencing within a phase |
| **Archetype** | Agent personality class affecting hormone baselines: exploration, validation, feasibility, solution, build, innovation, learning, control | squad-config.yml defines baselines per archetype |

### State & Quality Management

| Term | Definition | Context |
|------|-----------|---------|
| **state.json** | Master state file. Tracks run_id, phase, dispatch_history, golddigger_artifacts, golddigger_requests, errors, escalations, calibration_data. Shared across all agents. | Located at `.specify/squad/state.json` |
| **Quality Gate** | Pass/Fail threshold on output. SAGE runs Understanding metrics (7 dimensions: structure, testability, semantic, cognitive, readability, behavioral, depth). Spec fails if any dimension scores below config threshold. | squad-config.yml defines thresholds per dimension |
| **EVOI** | Expected Value of Information. COMMANDER uses EVOI to decide: dispatch this agent for more information, or escalate to human? | Calculated per unknown's impact × resolution difficulty |
| **Token Budget** | Running total of tokens spent. BANZAI mode sets unlimited (`token_budget_k: 999999`). Normal mode allocates percentages per tier. | squad-config.yml; tracked via token-logger.py |

### Knowledge Base & Evolution

| Term | Definition | Context |
|----------|-----------|---------|
| **Calibration Profile** | Historical accuracy data for estimates. Tracks GATEKEEPER's estimation bias; stores correction factors per domain/tech-stack combo. | knowledge-base/calibration-profile.yaml |
| **Pattern Registry** | Validated reusable patterns from prior runs (PAT-001, PAT-002, etc.). Marketplace index tracks reuse counts and confidence. | knowledge-base/marketplace-index.yaml; CARTOGRAPHER consults before writing spec |
| **Knowledge Base Feedback** | Run-specific learnings: agent accuracy, common failure modes, assumption validity, scope drift. Accumulated post-run. | knowledge-base/feedback/NNN-*.yaml per spec run |
| **Belief Register** | Per-agent belief tracking table listing verified claims, expiry dates, confidence scores, severity. Updated via belief-parser.py. | config-belief-graph.json; parsed from @belief() annotations in YAML configs and agent Markdown ## Belief Register tables |

### Novel Mechanisms

| Term | Definition | Evidence |
|------|-----------|----------|
| **Endocrine System** | 6-hormone neuromodulation (adrenaline, dopamine, cortisol, serotonin, oxytocin, norepinephrine). Per-archetype baselines. Phase-gated activation. Propagates to downstream agents (30% boost). Decay rates calibrated per hormone. | scripts/bash/endocrine.sh (1047 lines); squad-config.yml hormone baselines |
| **Belief Annotation System** | @belief() YAML annotations + ## Belief Register tables in agent prompts. Tracks operational knowledge with expiry dates and confidence thresholds. belief-parser.py parses into config-belief-graph.json. | scripts/belief-parser.py (547 lines); documents freshness status (expired/approaching/low-confidence/fresh) |
| **Contradiction Scanner** | Pipeline-stage pair analysis (DISCOVER→ASSESS, ASSESS→HOW, etc.). Heuristic pattern matching: count mismatch, status mismatch, boolean mismatch. Upper-bound detection, requires manual precision sample review. | scripts/contradiction-scanner.py (778 lines); produces JSON report with per-pair contradiction rates |
| **RADAR SSE Monitoring** | Real-time agent state streaming via Server-Sent Events. Watches agent-states.json and agent-states-events.jsonl. Broadcasts changes to connected browsers. Record/replay JSONL mode for offline analysis. | radar/server.py, radar/emitter.py; port 7891 default; recording optional |
| **Pre-Dispatch Constitutional Gate** | COMMANDER performs pre-flight check before every agent dispatch. Verifies agent adheres to immutable constitution principles. Blocks agents that would violate governance rules. | agents/control/commander.md (EVOI + constraint validation section) |
| **Constitution Authority Hierarchy** | Human-authored immutable principles (constitution.md) outrank all agent decisions. Agents can recommend violations; only humans can approve. Three-tier escalation: FLAG → CONSULT → BLOCK. | Enforced at dispatch time; blocks take precedence over agent autonomy |
| **Calibration Data Injection** | Per-agent historical failure mode injection into prompts. Maps to FR-001 (failure records); used in spec 010 research. Primes agents to avoid known pitfalls. | Referenced in squad-config.yml; implemented via prompt engineering + reasoning-journal lookup |
| **Token-Gated CA Overlays** | Cognitive Architecture mechanisms gated behind U-CA-004 experiment. Cannot be activated until gate resolves positively. Five mechanisms blocked: Goal Stack, ACT-R Typed Buffer, LIDA Broadcast, GWT Workspace, Episodic Memory. | .specify/specs/015-ca-outcomes-validation/proof-status-table.md (rows 6-10 gate-conditioned) |
| **7-Tier Cognitive Specialization** | Strict tier separation: agents enforce "no agent does another's job" rule. SCOUT only does DISCOVER, SAGE only challenges assumptions, CARTOGRAPHER only writes specs, etc. Prevents role confusion and improves quality. | Enforced via NEVER rules in each agent prompt; COMMANDER validates tier boundaries |
| **Generator-Critic + AGM Belief Revision (NS-003)** | Combination of execution-grounded Generator-Critic (for schema compliance) with Doxastic Logic AGM belief revision (for contradiction resolution). Applied to multi-agent artifact stores. No prior literature found combining these two. | arxiv:2510.09355 (NL2GenSym); arxiv:2603.17244 (Kumiho); NS-003 confirmed novel via systematic search U-015-002 |

### Data Artifacts

| Term | Definition | Location |
|------|-----------|----------|
| **Spec Directory** | Named `NNN-{feature}` where NNN is spec ID (001-999). Contains all phase outputs: spec.md, feasibility.md, plan.md, tasks.md, etc. | `.specify/specs/NNN-{feature}/` |
| **Staging Directory** | Temporary output location during discovery/requirements. CARTOGRAPHER moves staging/* to spec directory when spec is created. | `.specify/squad/staging/` |
| **Reasoning Journal** | JSON append-only log of all significant decisions. Entries track agent, timestamp, reasoning, confidence, evidence grade, implications. | `.specify/squad/staging/reasoning-journal.json` or per-spec `reasoning-journal.json` |
| **Artifact Protocol** | Spec 015 defines required JSON schema for all agent outputs. NS-003 Critic validates compliance. | .specify/specs/015-ca-outcomes-validation/spec.md |

---

## Overloaded Terms

| Term | Context A | Meaning A | Context B | Meaning B | Context C | Meaning C |
|------|-----------|-----------|-----------|-----------|-----------|-----------|
| **HOW** | Agent codename | ARCHITECT | Phase name | Solution design phase | Output artifact | Specification of technology and architecture |
| **WHAT** | Agent codename | CARTOGRAPHER | Phase name | Requirements definition | Output artifact | Feature specification |
| **WHY** | Agent codename | SAGE | Phase name | Assumption validation | Reasoning | Root cause or justification |
| **DISCOVER** | Agent codename | SCOUT | Phase name | Domain mapping | Output artifact | glossary.md, mental-model.md, etc. |
| **ASSESS** | Agent codename | GATEKEEPER | Phase name | Feasibility evaluation | Gate decision | PASS/DEFER/KILL verdict |
| **PLAN** | Agent codename | ORCHESTRATOR | Phase name | Task decomposition | Output artifact | plan.md and tasks.md |
| **BUILD** | Tier name | All build-phase agents | Phase name | Implementation | Generic action | To construct code/system |
| **Stage** | Within-phase sequence | Step 1, 2, 3... within a phase | Pipeline concept | DISCOVER→ASSESS→HOW→PLAN→BUILD | Not used interchangeably |
| **Tier** | Agent grouping | Horizontal: CONTROL, EXPLORE, etc. | Not applicable | — | — | — |

---

## Acronyms

| Acronym | Expansion | Context |
|---------|-----------|---------|
| BANZAI | Full autonomous, no kill threshold, unlimited token budget, all 6 hormones active | squad-config.yml execution mode |
| FPA | Function Point Analysis | GATEKEEPER estimation methodology |
| RICE | Reach/Impact/Confidence/Effort scoring | GATEKEEPER feature prioritization |
| AC-3 | Arc Consistency algorithm (Mackworth 1977) | Constraint propagation mechanism (not proven for LLM context) |
| AGM | Alchourrón, Gärdenfors, Makinson (belief revision postulates) | NS-003 belief revision logic |
| EVOI | Expected Value of Information | COMMANDER routing heuristic |
| GOLR | Generalized Occupational Language Relations | Not used; see GOLDDIGGER instead |
| RADAR | Real-time Agent Data Analysis and Record | SSE-based live monitoring system |
| NSR | Novelty Search Result | From NS-003 systematic literature search |
| GATE | Pre-experiment blocking condition | U-CA-004 blocks five CA overlays |

---

## Belief Terms

| Belief Term | Definition | Examples |
|--------------|-----------|----------|
| **Fresh** | Status: verified within expiry window AND confidence ≥ 0.5 | Most current assumptions; recent experiment results |
| **Approaching Expiry** | Status: verified but < 30 days until expiration; still valid but renewal needed | Calibration data from spec 012 (expires 2026-04-15) |
| **Low Confidence** | Status: confidence < 0.5 even if not expired | Estimates without calibration data; guesses |
| **Expired** | Status: expiry date has passed; belief invalidated | Assumptions from > 1 year ago in changing domains |
| **Verified** | Status: empirical evidence supports the claim | Run data confirms agent estimate was accurate |
| **Unvalidated** | Status: assumption made but not tested | Scope assumptions made without TRACKER verification |

---

## Endocrine Hormone Glossary

| Hormone | Function | Baseline Archetype | Effect on Output |
|---------|----------|-------------------|------------------|
| Adrenaline | Urgency signal | Lower in explore, higher in build (range 0.2–0.7) | Low: verbose, detailed; High: terse, skip preamble |
| Dopamine | Motivation/reward | Lowest validation (0.3), highest innovation (0.8) | Low: conservative, risk-averse; High: creative, exploratory |
| Cortisol | Stress/vigilance | Highest validation (0.8), lowest innovation (0.2) | Low: relaxed, creative; High: vigilant, critical, thorough |
| Serotonin | Contentment/stability | Highest learning (0.8), moderate others (0.4–0.7) | Low: anxious, reactive; High: calm, methodical, patient |
| Oxytocin | Collaboration/trust | High build (0.7), moderate others (0.4–0.7) | Low: individualistic; High: defers to peers, shares context |
| Norepinephrine | Attention/focus | Lowest innovation (0.3), highest build (0.9) | Low: scattered, unfocused; High: laser-focused on detail |
