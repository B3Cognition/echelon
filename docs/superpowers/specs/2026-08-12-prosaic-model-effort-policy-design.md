# Prosaic Model Tier and Effort Policy Design

**Status:** Approved for implementation

**Date:** 2026-08-12

## Goal

Give every executable Echelon Prosaic command and subagent an explicit
`model_tier` and `effort` matched to its actual reasoning responsibility.

## Scope

The migration covers all 56 files in `prosaic/subagents/` and all 41 files in
`prosaic/commands/`. The 14 appendices and templates in `prosaic/agents/` are
support prose rather than invocation entry points and receive no execution
metadata.

No prose body, workflow route, tool permission, provider mapping, or runtime
behavior changes in this migration.

## Policy

Model tier and effort are independent:

- `fast`: mechanical wrappers, status/reporting, deterministic tool execution;
- `balanced`: bounded analysis, mapping, transformation, or specialist review;
- `strong`: open-ended synthesis, architecture, implementation, adversarial
  review, or consequential decisions.
- `low`: an explicit procedure with little ambiguity;
- `medium`: several bounded judgments or careful artifact mutation;
- `high`: deep cross-artifact reasoning, uncertain diagnosis, design, or
  synthesis.

`ultra` is excluded. Claude can resolve it, but Codex currently cannot, and the
review found no role whose static default justifies provider-inconsistent
routing.

## Subagent Assignments

### Strong / High

`architect`, `cartographer`, `change-controller`, `chief`, `code-reviewer`,
`consolidator`, `debugger`, `gatekeeper`, `guardian`, `implementer`,
`investigator`, `oracle`, `orchestrator`, `re-constituter`, `re-expander`,
`re-planner`, `re-specifier`, `re-tasker`, `re-validator`, `realist`, `sage`,
`strategist`, `synthesizer`, `verification`, `veteran`.

### Strong / Medium

`commander`, `engineering-manager`, `integrator`, `sentinel`, `spec-guard`,
`test-guardian`.

### Balanced / High

`auditor`, `benchmark`, `maverick`, `visual-validator`.

### Balanced / Medium

`adaptive`, `advocate`, `checkpoint`, `docs-verifier`, `golddigger`,
`implementation-mapper`, `internalizer`, `lexicon-deriver`, `mirror`, `modeler`,
`re-analyzer`, `re-verifier`, `scout`, `spec-fulfillment-auditor`, `tech-writer`,
`tracker`, `validator`.

### Fast / Low

`monitor`, `progress-tracker`, `re-checklister`, `scorekeeper`.

## Command Assignments

### Strong / High

`build`, `change`, `codegen`, `codegenlight`, `verify`.

### Strong / Medium

`bugfix`, `review`.

### Balanced / Medium

`deploy`, `feedback`, `harness-init`, `health`, `init`, `re-extract`,
`re-plan-all`, `re-retarget`, `reopen`, `verify-spec`.

### Fast / Low

`cicd`, `ground`, `harness-resume`, `harness-run`, `harness-status`, `innovate`,
`investigate`, `re-analyze`, `re-checklist`, `re-constitute`, `re-expand`,
`re-plan`, `re-specify`, `re-tasks`, `re-validate`, `re-verify`, `resume`, `run`,
`status`, `understanding-batch`, `understanding-diagram`,
`understanding-energy`, `understanding-scan`, `understanding-validate`.

## Enforcement

A unit test owns the complete expected assignment map. It discovers every
top-level command and subagent Markdown file, requires exact set equality with
the policy, parses YAML frontmatter, and compares both fields. Adding or
removing executable prose therefore requires an explicit policy decision.

## Runtime Caveat

Echelon currently applies `model_tier` to Claude and Codex model selection.
Only the OpenAI-compatible backend currently sends `effort` as
`reasoning_effort`; Claude, Codex, Copilot, and OpenCode do not yet apply it.
Provider effort support is a separate runtime change.
