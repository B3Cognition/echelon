# Spec 017: NS-003 Prototype and U-CA-004 CA Overlay Experiment — Domain Overview

**Spec ID**: 017
**Date**: 2026-04-03
**Status**: WHAT-phase

---

## Summary

Spec 017 delivers two parallel capability expansions for the Echelon prototype system, each independently executable but sharing three integration points.

The first expansion is the **NS-003 prototype**: a write-time artifact quality enforcement system composed of a Generator-Critic schema validator (NS-003-A) and an AGM belief revision engine (NS-003-B). NS-003-A validates agent-produced Markdown artifacts against deterministic JSON schemas across six Echelon pipeline artifact categories. NS-003-B maintains a persistent belief graph across a spec run and emits pre-commit ConflictSignals when new assertions contradict existing beliefs. The NS-003 experiment runner measures the First-Pass Compliance Rate (FPCR) across N=30 invocations and reports against two thresholds per constitution P-022: PROTOTYPE_VIABLE (≥ 0.70) for continued build-phase authorization, and PATENT_GRADE (≥ 0.80) for patent filing eligibility. The Generator-Critic plus AGM belief revision combination applied to multi-agent artifact stores has zero prior literature (systematic search U-015-008), making it the project's primary IP asset per P-019.

The second expansion is the **U-CA-004 experiment infrastructure**: a controlled N=20 per-condition experiment comparing BASELINE Echelon runs against CA-ACTIVE runs that inject one cognitive architecture overlay per batch. The experiment uses an automated AQS proxy scorer (LLM judge, authorized by P-021) to evaluate artifact quality across five dimensions, applies the Mann-Whitney U test for statistical significance, and produces a binary POSITIVE/NEGATIVE verdict. A POSITIVE verdict (p < 0.05, Cohen's d ≥ 0.5) gates implementation of all five cognitive architecture overlays: Goal Stack, ACT-R Typed Buffer, LIDA Broadcast, GWT Bounded Workspace, and Episodic Memory. A NEGATIVE verdict produces a terminal findings report with no overlay implementation code committed, per P-020.

The three shared integration points — the endocrine event system, the COMMANDER dispatch protocol, and the Echelon artifact store — require careful co-design so that NS-003 hooks and CA overlay hooks coexist in COMMANDER without interference. The write-time interception mechanism for NS-003 pre-commit mode is the highest-priority unresolved architectural question (OQ-001 / IS-003) and is the first concern for the HOW phase.

---

## Dependency Graph

```
Spec 014 (CA framing) → Spec 015 (outcomes validation + experiment designs)
                              ↓
                    Spec 017 (THIS SPEC)
                    ┌─────────────────────────────┐
                    │                             │
              NS-003 Sub-System           U-CA-004 Sub-System
              ┌──────────┐               ┌──────────────────┐
              │ NS-003-A │               │ Experiment Runner│
              │ Critic   │               │ (N=20/condition) │
              └──────────┘               └──────────────────┘
              ┌──────────┐                        │
              │ NS-003-B │               POSITIVE verdict
              │ AGM      │                        ↓
              └──────────┘               CA Overlay Implementations
                    │                   (CONDITIONAL — P-020)
                    └─────────┬─────────────────┘
                    Shared integration points:
                    • Endocrine system (endocrine.sh event hooks)
                    • COMMANDER dispatch protocol (commander.md additions)
                    • Artifact store (.specify/specs/<run>/ Markdown files)
```

---

## Stakeholders

| Role | Interests | Key Scenarios |
|------|-----------|---------------|
| Squad Researcher | Measuring NS-003 FPCR and CCR to determine experiment verdict | Scenarios 1, 2, 3 |
| Patent Track Researcher | Reproducible experiment evidence at PATENT_GRADE threshold (≥ 0.80 FPCR) | Scenario 3 |
| Experiment Runner | Automated U-CA-004 execution producing a POSITIVE/NEGATIVE verdict | Scenario 4 |
| Squad Engineer (post-POSITIVE only) | Deploying CA overlays that improve agent context quality | Scenario 5 |
| Third-Party Validator | Reproducing experiment results using commit hash and requirements.txt | Scenario 6 |

---

## Domain Areas

| Area | Description | Complexity | MVP? |
|------|-------------|------------|------|
| NS-003-A Schema Validator | Deterministic JSON schema validation of agent artifact outputs across 6 categories | High — requires Markdown parsing layer + schema calibration | Yes |
| NS-003-B Belief Revision Engine | AGM-postulate-compliant belief graph with pre-commit ConflictSignal and post-hoc scanning | High — novel architecture; write-time interception mechanism is unresolved (OQ-001) | Yes |
| NS-003 Experiment Runner | N=30 invocations measuring FPCR, CCR, FPR with dual threshold reporting | Medium — orchestration script with structured output | Yes |
| U-CA-004 Experiment Infrastructure | N=20/condition controlled experiment with LLM AQS proxy and Mann-Whitney U | High — automated LLM judge + statistical analysis + audit trail | Yes |
| CA Overlay Implementations | 5 cognitive architecture overlays integrating with COMMANDER dispatch | Very High — CONDITIONAL on POSITIVE verdict | No (conditional) |
| Dependency Management | requirements.txt + setup.sh enabling reproducible one-command setup | Low | Yes |

---

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Write-time interception hook is architecturally infeasible (RSK-002) | Medium | Critical — NS-003-B pre-commit novelty claim collapses | HOW phase must audit COMMANDER dispatch before designing NS-003-B integration; `--mode post-hoc` default provides a working fallback |
| Schema over-specification causes false rejections > 5% (RSK-004) | Medium | High — inflates FAIL counts, pushes FPCR below PROTOTYPE_VIABLE | Phase 1 pilot: validate schemas against calibration set before full N=30 run |
| Known-good samples from runs 008-014 unavailable (RSK-012) | Medium | High — Phase 1 calibration gate cannot be satisfied as pre-registered | HOW phase designs a documented fallback using runs 015-016 as calibration set |
| Codebase changes between NS-003 and U-CA-004 experiments (RSK-005) | Low-Medium | High — cross-experiment comparability compromised | Lock test codebase to commit hash before either experiment begins; record hash in both results files |
| ANTHROPIC_API_KEY not propagated into subagent environment (IS-009) | Medium | High — all experiment API calls fail at authentication | HOW phase inspects extension.yml invocation pattern; FR-DEP-003 ensures clear error messaging |
| U-CA-004 NEGATIVE verdict eliminates CA overlay program | Medium | Medium — overlay implementation work is gated and may not proceed | NEGATIVE path is defined (uca004-negative-report.md); findings documented for future research |
