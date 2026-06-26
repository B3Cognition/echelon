# Echelon Delta Review After EGR-008

**Reviewed HEAD:** `665c7acbd3a6a2fae60a617e39c4a1aa7abfd808`
**Baseline:** `eeb490899655c0796ec9d9c187eb52fe1195427f`
**Date:** 2026-06-23

## Summary

EGR-001 through EGR-008 are now implemented with source changes, focused tests,
register notes, and `[Unreleased]` changelog entries. The core harness safety
surface is materially stronger than at the full review snapshot: malformed
agent results are blocked before state mutation, Phase A readiness is
deterministic, host LLM dispatch has an explicit tool policy, sandbox plans are
evidence-backed, blocked decisions are typed, repair loops have a reusable
bounded primitive, durable memory writes have a validator, and routed roles have
machine-checkable result/output contracts.

The full source review does not need to be regenerated yet. The architecture
shape is the same; the changes mostly harden the same boundaries the review
identified. The register should remain the living tracking surface.

## Closed Findings

- `EGR-001` through `EGR-008` remain fixed at this HEAD.
- Verification evidence is recorded in `CHANGELOG.md` and
  `docs/findings/echelon-grounded-review-register.md`.

## Newly Promoted Findings

### EGR-010: GitOps lacks a deterministic pre-push secret scan

`src/harness/gitops.py` enforces default-branch push safety, but `commit()`,
`push()`, and `push_prepared_branch()` do not run a deterministic secret scan
before publishing a branch. Existing GitOps tests cover commit messages,
force-with-lease push, and default-branch rejection, but not secret scanning.

This should be implemented before expanding into RCA automation because it is a
direct safety gate on generated code leaving the local machine.

### EGR-011: Per-phase `state_updates` allowlists are not enforced

`src/harness/echelon_result_schema.py` validates result shape and reserved
harness-owned state keys, and `src/harness/role_contracts.py` requires routed
roles to declare `state_updates`. Neither module currently enforces which
`state_updates` keys are legal for a specific phase/role. Phase specs describe
many expected keys in prose, but those contracts are not yet machine-checked.

This is a natural continuation of EGR-008, but it is separate from the routed
role result/output contract now in place.

## RCA Readiness

`EGR-009` is no longer blocked by the original "core harness safety first"
rationale, but it should follow `EGR-010` at minimum. RCA will introduce new
incident/evidence artifacts and probably external source adapters, so it should
start from a safer GitOps boundary.

## Recommended Next Step

Implement `EGR-010` next:

1. Add a small `src/harness/secret_scan.py` module with deterministic pattern
   checks over staged or changed files.
2. Call it from `GitOpsManager.commit()` before `git add -A`/`git commit`, or
   immediately after staging but before commit creation.
3. Block on high-confidence secret patterns; warn on low-confidence patterns if
   needed.
4. Add focused GitOps tests covering clean commits, blocked commits, and
   explicit allow/ignore behavior if an allowlist is introduced.
