# Incremental RE Quality and Published-Baseline Refinement

**Date:** 2026-07-20
**Status:** Approved

## Problem

The `md_distribution` run shows that RE semantic validation is resumable but
not yet cost-effective. Seventeen domains produced fourteen first-pass repair
verdicts and twenty-six findings. The findings are mostly genuine, but they are
predictable categories: omitted behavior, universal claims contradicted by one
branch, configuration constraints, error/recovery paths, and public operations.
The specifier prompt mentions these concerns, while `echelon re check-domain`
primarily verifies document shape, counts, acceptance syntax, and citations.
A document can therefore pass the deterministic gate and still be very likely
to fail the semantic validator.

New runs also underuse the published `re/` snapshot. The planner can retain an
unchanged published source or refresh a changed source, but it cannot stage an
unchanged published specification as the starting point for a deeper quality
pass. An unchanged workspace may consequently return `no_work` even when the
operator deliberately selects a stronger execution profile.

## Goals

- Reduce first-pass semantic repair rate below 30% on the fixed
  `md_distribution` benchmark.
- Keep the validator's source-evidence standard; do not turn real findings into
  warnings merely to improve the metric.
- Make the specifier anticipate the validator's exact completeness taxonomy.
- Route exact findings and evidence to a narrow domain repair without rewriting
  unrelated specifications.
- Bound semantic validation and repair according to `fast`, `balanced`, and
  `high` execution profiles.
- Use the current published `re/` snapshot as the default baseline for every new
  RE run when it is usable.
- Start cleanly when no published snapshot exists or `--no-reuse` is supplied.
- Keep canonical published artifacts immutable until explicit publication.
- Record enough provenance and telemetry to compare quality per token and
  dispatch across runs.

## Non-Goals

- Do not discover or link predecessor run directories.
- Do not require a `fast -> balanced -> high` sequence.
- Do not reuse budgets, repair counters, in-flight state, or run telemetry.
- Do not mutate canonical `re/` during execution.
- Do not reuse a published source whose manifest or artifacts fail integrity
  validation.
- Do not require a particular LLM model for a profile in this change.
- Do not claim that deterministic checks can prove semantic completeness.

## Chosen Architecture

### Published baseline

`re/index.json` remains the only baseline locator. A new run loads it once and
records its generation and content fingerprint. There is no run search and no
profile ancestry.

For each selected source, the planner chooses:

- `improve`: the source fingerprint matches a usable published source. Copy its
  durable source-owned documents into run staging, skip static extraction and
  initial specification, and enter the selected profile's quality policy.
- `refresh`: the source is new, changed, incompatible, or deliberately clean.
  Run normal analysis/specification. If a published source with the same stable
  ID exists, expose it as read-only comparison context but do not treat its
  claims or audits as current evidence.
- `skip-empty`, `missing`, or `exclude`: preserve existing semantics.

The staged copy is editable. The canonical published tree remains immutable.
Publication continues to use the existing generation guard and atomic
transaction.

`--no-reuse` makes the planner behave as if no baseline artifacts were usable,
while still retaining the real published generation for concurrency checks.
It does not delete or hide canonical artifacts from other commands.

### Shared semantic completeness contract

One versioned contract defines the categories used by prompts, deterministic
preflight, repair packets, telemetry, and analysis:

1. public operations and observable outputs;
2. configuration keys, accepted values, and rejected values;
3. errors, recovery, and partial-failure behavior;
4. boundaries and edge cases;
5. warnings, exit status, and other operator-visible behavior;
6. tests demonstrating special cases;
7. evidence scope for universal claims.

Every deep source-domain spec contains a `Behavior Coverage` section with one
row per category. A row has a status of `observed`, `not-observed`, or
`not-applicable`, a concise scope statement, and source evidence when observed.
This is a reasoning checklist, not a demand to invent content.

Requirements containing universal terms such as `all`, `always`, `every`, or
`never` must include `Evidence Scope: exhaustive` and cite the branches or tests
that justify the scope. Otherwise the specifier must use bounded observational
language. The deterministic gate checks the declaration and citations; the
semantic validator remains responsible for deciding whether the claim is true.

### Deterministic preflight

`echelon re check-domain` gains versioned, inexpensive checks:

- `behavior_coverage_missing`
- `behavior_coverage_category_missing`
- `behavior_coverage_evidence_invalid`
- `unscoped_universal_claim`
- `public_surface_coverage_missing`

Public-surface comparison uses the existing domain manifest and extracted
analysis symbol inventory when present. It reports named exported/public
operations absent from both requirements and the Behavior Coverage section.
When the analysis format has no reliable public symbol inventory, the check is
explicitly `unavailable` and does not fail. Configuration and error semantics
remain checklist/evidence checks rather than speculative static analysis.

### Repair packets

Semantic findings become structured controller-owned repair packets containing:

- source and domain identity;
- stable finding ID derived from category, normalized finding text, and evidence;
- category;
- exact finding text;
- owned source evidence;
- current spec fingerprint;
- repair attempt number.

The specifier receives only the packet for the current domain and is instructed
to preserve unrelated content. After repair, only that domain audit becomes
stale. A repeated finding with the same stable ID is recorded as a repeated
finding and consumes the profile's repair allowance.

### Profile-aware quality policy

Profiles govern both resource limits and validation depth:

| Profile | Deterministic preflight | Semantic audit | Semantic repair rounds |
|---|---|---|---:|
| `fast` | every domain | none | 0 |
| `balanced` | every domain | every domain once | 1 |
| `high` | every domain | every domain until pass/debt | up to 5 |

`fast` publication records semantic coverage as `not_evaluated`; it must not
claim a semantic PASS. `balanced` performs one repair and revalidation for each
failed domain, then records remaining findings as blocking quality debt. `high`
uses the existing bounded per-domain repair mechanism. Hard token/time ceilings
still stop new dispatches before convergence limits do.

Publication records `quality_profile`, deterministic contract version,
semantic coverage (`not_evaluated`, `complete`, or `debt`), audited domain count,
and unresolved finding count. Passing the selected policy is a profile-relative
quality result, not proof that a lower profile equals `high`.

### Telemetry and benchmark

Dispatch spans add attempt kind/number, stable finding IDs, repair category,
baseline generation, and baseline action. Run analysis adds:

- first-pass repair rate;
- validator dispatches per accepted domain;
- repeated findings after repair;
- tokens per accepted domain;
- reused/improved/refreshed domain counts;
- semantic coverage and unresolved blocking findings.

The minimized `md_distribution` run fixture is the fixed pre-change baseline:
17 audited domains, 14 first-pass repairs, and 26 findings at the time of
capture. A live A/B run is required before claiming the target is achieved.

## Data Flow

1. Resolve a fresh execution profile and budgets.
2. Load the current published index unless `--no-reuse` is set.
3. Build a plan with `improve` for usable unchanged published sources and
   `refresh` for everything requiring source analysis.
4. Copy `improve` artifacts into run staging and record baseline provenance.
5. Generate/repair refreshed sources using the shared completeness contract.
6. Run deterministic preflight for every staged domain.
7. Apply the selected semantic policy and persist each granular audit.
8. Route structured domain repair packets within the profile allowance.
9. Produce telemetry, analysis, and explicit quality debt.
10. Publish only through the existing atomic publication transaction.

## Failure Handling

- Missing or corrupt published artifacts downgrade that source from `improve`
  to `refresh` and record the reason.
- Baseline copy failure blocks run creation before provider dispatch.
- A changed source never inherits a passing audit from published output.
- Invalid public-symbol analysis disables that one deterministic comparison and
  emits a diagnostic; other checks continue.
- Budget exhaustion checkpoints staged artifacts and repair packets without
  modifying the published snapshot.
- Generation drift blocks publication exactly as it does today.
- `--no-reuse` always yields fresh staging and fresh counters.

## Acceptance Criteria

- An unchanged published source is staged as `improve`, not returned as
  `no_work`, when an RE run is explicitly requested.
- No published index produces the existing clean-run behavior.
- `--no-reuse` performs a clean refresh while preserving publication generation
  safety.
- Canonical `re/` bytes do not change before publication.
- The specifier and validator consume the same taxonomy version.
- `check-domain` rejects missing coverage categories and unscoped universal
  claims without pretending to validate their truth.
- Repair prompts include exact structured findings/evidence and cannot edit
  sibling domains.
- Profile policies dispatch exactly the documented number of semantic rounds.
- Analyzer JSON and wiki pages expose baseline reuse and convergence metrics.
- Focused tests and the full regression suite show no new failures.
- A post-change `md_distribution` benchmark reports first-pass repair rate,
  validator dispatches/domain, repeated findings, tokens/domain, and blocking
  debt against the frozen baseline.
