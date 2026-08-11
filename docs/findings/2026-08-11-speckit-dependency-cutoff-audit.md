# Spec-Kit Dependency Cutoff Audit

**Review date:** 2026-08-11
**Scope:** installer, packaging, Markdown prose, runtime, and delivery harness
**Conclusion:** normal Echelon operation is Prosaic-first and has no active
Spec-Kit runtime dependency.

## Installer

`echelon workspace init` installs Echelon's pinned Prosaic CLI, stages the
versioned `prosaic/` and `runtime/` bundles, and deploys them through `prosaic
package deploy`. It does not invoke `specify`, inspect Spec-Kit extension state,
or copy `.specify/extensions/echelon`.

`echelon workspace migrate-to-prosaic` is the only intentional legacy import
surface. It may read an old Echelon config, constitution, deployment state, and
Spec-Kit Git-extension state, then writes canonical Echelon-owned equivalents.
The command leaves the old tree untouched except for disabling legacy Git
mutation and moving legacy global deployment state. Normal commands do not use
that tree after migration.

## Packaging

`setup.py` and `MANIFEST.in` include only the canonical `prosaic/` and `runtime/`
bundle trees. Wheel installation exposes them under
`echelon/bundles/{prosaic,runtime}`. Root templates, old specifications, tests,
and migration fixtures are not deployed as provider prose or runtime assets.

## Markdown Prose And Runtime

The committed `prosaic/` and `runtime/` trees contain no `speckit`, `spec-kit`,
`.specify`, `specify extension`, or `speckit-echelon-*` runtime instructions.
The workflow registry dispatches neutral `echelon.*` subagents, and provider
worktrees receive `.echelon/prosaic` plus `.echelon/runtime` only.

The final active text leaks found by this audit were stale constitution examples
in `AGENTS.md` and `CLAUDE.md`, three unused root recovery templates, and the
generator identity in `knowledge-base/confidence-thresholds.yaml`. They were
removed or normalized to the Echelon CHIEF/COMMANDER identities.

## Harness

The delivery harness reads canonical `.echelon/config.yml`, deployed Prosaic
prose, deployed runtime workflow/templates/scripts, and `runs/` state. Its
normal execution path does not fall back to `.specify`.

Remaining source references are compatibility boundaries, not dependencies:

- one-shot import: `workspace migrate-to-prosaic`, constitution import,
  deployment-state import, and legacy RE-default normalization;
- migration tooling: workspace Git/source-split migration of existing repos;
- safety: reject old `SPECKIT_HARNESS_*` variables and prevent source discovery
  inside `.specify`;
- historical tests/specifications and durable provenance records.

## Cutoff Decision

Existing repositories should be migrated with `echelon workspace
migrate-to-prosaic`, verified to contain `.echelon/prosaic` and
`.echelon/runtime`, and then operated only through Echelon commands. No runtime
fallback to Spec-Kit should be reintroduced.

The legacy import modules can be removed after the supported repository set has
been migrated and a deliberate compatibility-support decision is made. Their
presence today does not block the cutoff because they are unreachable from the
normal initialized-workspace path.
