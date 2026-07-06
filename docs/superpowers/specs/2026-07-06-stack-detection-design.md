# Echelon Stack Detection Design

**Status:** Proposed
**Date:** 2026-07-06
**Related EGR:** EGR-102 / GitHub issue #126
**Deciders:** Echelon maintainers

## Context

Echelon now supports explicit, opt-in stacks through `stacks.selected`, stack
resolution, stack prompt context, and stack preflight. That helps when a user
already knows that a project should use Playbook, MSA, Stark, or another known
stack.

Brownfield and modernization work has a different shape. Existing source trees
and prior SCOUT/GOLDDIGGER/reverse-engineering artifacts already contain strong
technology evidence, but that evidence is narrative and not translated into the
stack model. Operators still have to manually decide whether a project is
already using a known stack, should adopt one going forward, or should modernize
toward one.

The initial motivating fixture is the older OG Platform reverse-engineering
artifact set under `specs/000-re-overview`. It shows the problem clearly:

- `overview.md` identifies a multi-repo source system with React, TypeScript,
  Nx, Playbook, Next.js, NestJS, C# .NET, Terraform, and ArgoCD.
- `constitution.md` contains structured legacy technology tables, architectural
  patterns, anti-patterns, and target-stack placeholders.
- `migration-strategy.md` contains repository-level and domain-level 6R/7R
  recommendations.
- `validation-report.md` explicitly records that target stack selection still
  requires human input.

Those artifacts are useful evidence, but they should not be treated as stack
selection by themselves.

## Goals

- Add deterministic stack detection for existing source code and generated RE
  artifacts.
- Distinguish current observed stack evidence from future modernization target
  recommendations.
- Let `echelon stack detect` run before any Echelon spec run, using only source
  files when no artifacts exist.
- Let `echelon stack detect` consume SCOUT, GOLDDIGGER, and RE artifacts when
  present, without making those artifacts mandatory.
- Produce machine-readable evidence and a concise human summary.
- Generate suggested `stacks:` config snippets only when confidence and intent
  are clear.
- Keep stack selection opt-in; detection must not silently mutate project
  config.

## Non-Goals

- Do not make detected stacks automatic defaults.
- Do not make SCOUT or GOLDDIGGER the stack detector.
- Do not require an LLM call for stack detection.
- Do not infer `statsperform-msa-service` merely because a backend service
  exists; MSA means the CAIC MSA/FastAPI stack specifically.
- Do not infer Stark from every Next.js app. Stark is a known modernization
  target only when evidence or user intent supports it.
- Do not implement migration execution or stack adoption in the first version.

## Design

Introduce `echelon stack detect`.

The command scans a project source root and optional Echelon artifacts, then
returns a deterministic stack detection report. The report has four separate
concepts:

- `observed_stacks`: what the source tree or artifacts show today.
- `matching_echelon_stacks`: known Echelon stacks that appear to match the
  current state.
- `modernization_candidates`: known Echelon stacks that could be a target but
  require an explicit modernization decision.
- `decisions_required`: unresolved choices that block safe recommendation.

The command does not edit `.echelon/config.yml`. When adoption is safe, it
prints a suggested config snippet. A future `echelon stack adopt` command may
write config after explicit confirmation.

Example:

```bash
echelon stack detect
echelon stack detect --target ./source-repo
echelon stack detect --artifacts specs/000-re-overview
echelon stack detect --json
```

Example human output:

```text
Observed stacks:
- playbook-design-system (confidence: high)
- nextjs-nx-webapp (confidence: high)
- nestjs-api-service (confidence: high)
- postgres-data-store (confidence: high)
- terraform-argocd-kubernetes-delivery (confidence: high)
- legacy-dotnet-api (confidence: high)

Matching Echelon stacks:
- statsperform-playbook (confidence: high)

Modernization candidates:
- statsperform-stark-webapp (confidence: medium; decision required)

Decisions required:
- Target stack is unresolved in RE artifacts.
- Backend is NestJS, not MSA/FastAPI; do not select statsperform-msa-service
  without an explicit replatforming decision.
```

## Architecture

Add a new deterministic stack-detection subsystem under `src/harness/stacks/`:

```text
src/harness/stacks/
  detection.py       # scoring model, report dataclasses, public API
  evidence.py        # evidence records and adapter protocol
  detectors/
    source_tree.py   # package files, lockfiles, imports, framework markers
    re_artifacts.py  # older RE markdown artifacts
```

The detector uses adapters. Each adapter emits normalized evidence records:

```yaml
kind: technology
value: nextjs
source: artifacts/000-re-overview/overview.md
location: "Tech Stack Summary"
confidence: high
```

The scorer maps evidence to stack recommendations. Stack definitions should
eventually own their own detection rules, but the first implementation can keep
rules in Python while the schema is stabilized.

## Evidence Adapters

### Source Tree Adapter

Reads source files directly:

- `package.json`, lockfiles, `nx.json`, `project.json`
- `pyproject.toml`, `uv.lock`, `requirements*.txt`
- Dockerfiles and compose files
- Terraform and Kubernetes manifests
- dependency names, scripts, and framework markers

This mode must work without any prior Echelon run.

### RE Artifact Adapter

Reads known artifact names when present:

- `overview.md`
- `constitution.md`
- `migration-strategy.md`
- `gap-analysis.md`
- `validation-report.md`
- ADRs under `adrs/`
- future `codegraph-analysis.json` and `codegraph-summary.json`

The first parser should support heading- and table-based extraction from older
markdown artifacts. It should prefer structured tables over free prose.

### Future Agent Evidence

SCOUT and GOLDDIGGER should eventually emit a compact machine-readable artifact,
for example:

```text
.echelon/context/stacks/observed-evidence.json
```

or a run-local equivalent. That file should not replace source/artifact
parsing; it should be another adapter input.

## Output Model

JSON output should be stable enough for future automation:

```json
{
  "target": ".",
  "observed_stacks": [
    {
      "id": "nextjs-nx-webapp",
      "confidence": 0.92,
      "evidence": [
        "overview.md: Tech Stack Summary contains Next.js and Nx"
      ]
    }
  ],
  "matching_echelon_stacks": [
    {
      "id": "statsperform-playbook",
      "confidence": 0.88,
      "recommendation": "adopt",
      "evidence": [
        "overview.md: repository map identifies Playbook design system",
        "constitution.md: UI stack uses Radix, CVA, Tailwind, Playbook tooling"
      ]
    }
  ],
  "modernization_candidates": [
    {
      "id": "statsperform-stark-webapp",
      "confidence": 0.65,
      "recommendation": "consider",
      "decision_required": "Target stack unresolved"
    }
  ],
  "decisions_required": [
    {
      "code": "TARGET_STACK_UNRESOLVED",
      "message": "RE artifacts explicitly mark target stack as requiring input."
    }
  ],
  "suggested_config": null
}
```

## Scoring Rules

Scoring should favor false negatives over false positives.

Recommended thresholds:

- `>= 0.85`: strong match; safe to suggest config if no conflicting evidence or
  unresolved target decision exists.
- `0.60-0.84`: plausible match or modernization candidate; show evidence and
  require human confirmation.
- `< 0.60`: evidence only; do not recommend.

Hard blockers for adoption:

- Artifact explicitly says target stack is unresolved.
- Observed stack conflicts with known stack identity.
- Multiple incompatible known stacks match the same target archetype.
- The known stack would imply a replatform, not a refactor, and no modernization
  intent is present.

## OG Fixture Interpretation

For the OG sample, the expected first report should be conservative:

- `statsperform-playbook`: strong match for the Playbook/fet-frontend-libs
  track.
- `statsperform-stark-webapp`: modernization candidate only, not automatic,
  because the artifacts describe Next.js/Nx/Playbook evidence but also state the
  target stack is unresolved.
- `statsperform-msa-service`: not recommended. The backend evidence is NestJS,
  tRPC, and TypeScript, not CAIC MSA/FastAPI.
- Future infrastructure stacks could be observed for PostgreSQL, Terraform,
  ArgoCD/Kubernetes, AWS S3/CloudFront, and legacy .NET API retirement, but
  those stacks do not exist yet in bundled definitions.

## Error Handling

- Missing source root: exit nonzero with a clear target-not-found message.
- No evidence: exit zero with `status: no_match` and no suggested config.
- Malformed artifact: warn and continue with other evidence.
- Unknown stack definitions: reuse existing stack loader/resolver errors.
- Conflicting evidence: report `decisions_required`, do not emit a config
  snippet.

## Testing

Add focused tests for:

- Source-only detection of Playbook, Next.js/Nx, NestJS, PostgreSQL, and .NET
  markers.
- Artifact-enhanced detection from a compact fixture based on
  `000-re-overview`.
- Target-stack unresolved blocker.
- MSA not recommended for NestJS evidence.
- Stark emitted as modernization candidate, not selected stack, when target is
  unresolved.
- JSON output shape stability.
- CLI text output and `--json` output.

The OG fixture should be reduced to small test fixtures that preserve the
important tables and target-stack placeholder rather than vendoring the full
external artifact set.

## Open Questions

- Should stack detection write a run-local report by default, such as
  `.echelon/context/stacks/detected.json`, or only print to stdout in the first
  implementation?
- Should stack definitions gain declarative `detection:` rules in the same
  implementation, or should Python rules ship first while the evidence schema is
  proven?
- Should `echelon stack preflight` accept `--from-detect` later, or should stack
  adoption remain an explicit separate step?
