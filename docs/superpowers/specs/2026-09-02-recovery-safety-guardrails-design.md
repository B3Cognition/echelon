# Recovery Safety Guardrails Design

## Goal

Prevent broad checkpoint or rollback operations from silently deleting Echelon
runtime behavior, CLI surfaces, or their regression coverage.

## Protected change classification

Checkpoint and recovery operations classify the resolved Git diff before making
any mutation. Protected paths are Python source, tests, `runtime/`, `prosaic/`,
and CLI/package entry-point files. A protected deletion is rejected by default.
An operator may use `--allow-code-deletions <reason>` only when the deletion is
intentional; the command records the reason in its checkpoint/recovery evidence.

## Recovery impact report

Before a destructive restore, Echelon renders a deterministic report of added,
modified, and deleted files, grouped into source, tests, workflow/runtime,
prompts, and other artifacts. The report calls out removed CLI registrations and
controller-runtime compatibility changes. Any protected deletion requires an
explicit confirmation after the report is shown.

## Compatibility contract

A fast deterministic regression suite protects the surfaces most vulnerable to
an accidental rollback: legacy CLI aliases, deployed runtime compatibility,
workflow controller contracts, and sandbox-owned Playwright verification. This
suite is suitable for CI and local pre-commit verification.

## Safety boundaries

The guards do not prohibit intentional refactors or removal of obsolete code.
They make those operations explicit, reasoned, and auditable. Normal changes
outside protected deletions remain non-interactive.

## Verification

Tests cover rejected protected deletions, accepted reasoned overrides, stable
impact-report classification, confirmation requirements, and the compatibility
contract command. Existing full-suite verification remains the final gate.
