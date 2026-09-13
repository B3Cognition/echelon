# SDD ledger — plan: docs/superpowers/plans/2026-09-13-captured-artifact-memory-audits.md

## Scope and recovery

Approved durable-ID integration, offline only in delivery-controller-contract. Parent checkpoint 4981dc13; prior captured canonical audit is complete and must not be redispatched. This plan has one cohesive task. No main/global install/stopped-smoke mutation or live activation. Retain this workspace until whole-branch review and exhaustive final rulings.

## Preflight

Spec: docs/superpowers/specs/2026-09-12-durable-element-identities-design.md (approved, read completely in this execution).

| Tasks/interfaces checked | Producer versus consumer | Finding |
| --- | --- | --- |
| Task 1 self-consistency | Two public adapters, scoped private extractions and one new test module versus exact seven-module cover | All modified/new owners named; existing tests remain unchanged; no public runtime activation. |
| Task 1 canonical acquisition | Existing detached complete read/cohort helper versus canonical and artifact carriers | Preserve canonical parsing; explicitly convert existing carriers at boundary; no new scan policy. |
| Task 1 artifact classifiers | Native classification and bounded extras versus captured complete extras | Share classification, preserve native warning/status/count rules; only new acquisition gets strict completeness. |
| Task 1 evidence source/frontmatter | Captured logical bytes versus native lifecycle and metadata | Exact original hashes, universal newline parsing only, default landed gate before acquisition; unrelated target loading not claimed. |
| Task 1 RE catalogs | Pure descriptor validation versus native kind/room selection | Explicit legacy/catalog modes, all descriptors validated before filtering; index presence is not association proof. |
| Task 1 report conversion | Generic normal reports versus existing domain report constructors | Share normal conversion; new failures use valid domain fields; legacy exceptional behavior remains unchanged. |
| Task 1 graph consumer | Actual returned reports versus existing captured contributions | Tests only, retain returned origin and native statuses; no fabricated completeness/current-revision/publication authority. |

Ruling: 36 — Extend captured observation to evidence and RE with the native default landed gate and explicit allow_unlanded opt-in; select RE legacy mode only when no index witness exists, and catalog mode only with a nonempty fully validated supplied descriptor tuple, captured regular index witness and eligible selected artifact. Preserve native ordering, metadata and classification. Index presence is not catalog association proof; new operational failures return valid domain reports while legacy exceptional paths remain unchanged. — Captured bytes alone cannot establish lifecycle or registry authority, and missing/damaged catalog input must not silently downgrade to legacy selection. — If wrong, revise the inactive source/catalog/landed contract and parity tests or add an explicit captured-registry association; no IDs, revisions, graph keys, native legacy wire, journal receipts, canonical sources or live deployment need rewriting.

Task 1: pending dispatch. Ruling 36 is selected, not yet implemented or reviewed.
