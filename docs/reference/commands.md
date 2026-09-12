# Echelon command reference

## Reverse-engineering knowledge

The normal RE interface has two actions:

```bash
echelon re run [--depth quick|standard|deep]
echelon re refresh [--source SOURCE ...] [--depth quick|standard|deep]
```

`run` analyzes all declared source repositories, independently reviews the
grounded results, synthesizes source and workspace documents, and atomically
publishes one generation. `standard` is the default depth for a source without
published knowledge. `quick` and `deep` change the analysis obligations, not the
published document family.

`refresh` compares immutable local source snapshots with the latest publication.
It never fetches, pulls, checks out, or edits a source repository. With no
`--source`, it checks all declared sources. Repeating `--source` creates one
targeted refresh. Changed selected sources are reanalyzed, compatible unchanged
knowledge is reused, dependent workspace documents are rebuilt, and the action
publishes exactly one new generation. If nothing selected changed, it records a
durable no-op and performs no provider dispatch. Unselected siblings are
explicitly `not_checked`.

Without `--depth`, refresh preserves each source's established depth. An
explicit depth applies to the selected sources. Published manifests distinguish
requested depth, retained depth, freshness, and accepted limitations.

```bash
echelon re status
echelon re status --json
```

Status uses operator-facing states: `analyzing`, `synthesizing`, `publishing`,
`complete`, `complete-with-limitations`, and `needs-attention`. An incomplete
durable projection is not described as complete merely because no process is
active. Errors identify the action and a concrete recovery step.

Provider selection comes from the standard Echelon configuration facade and
environment overrides. The selected provider/model is frozen into run authority.
An unsupported execution contract is rejected before dispatch; Echelon never
silently substitutes a different provider.

Resource overrides are advanced absolute ceilings:

```bash
echelon re run --re-token-limit N --re-time-limit-minutes N
echelon re refresh --re-token-limit N --re-time-limit-minutes N
```

They do not reset already charged usage. Raw prompts, responses, source secrets,
and provider diagnostics are excluded from ordinary status and publication.

### Advanced compatibility and recovery

`echelon re deepen`, `continue`, `resume`, `synthesize`, and `publish` remain
available for historical runs and explicit recovery. They expose protocol/layer
mechanics and are not part of the normal success path. Use
`echelon re <command> --help` and the
[RE v2 operator runbook](../re-v2-operator-runbook.md) when recovering one of
those runs.

### Release status

The reviewed two-action workflow is an M3 release candidate in the source
checkout. It has offline two-service, failure, replay, atomic publication,
refresh, and consumer-pinning coverage. Installing the new routing and live
multi-workspace provider evaluation are the separately authorized M4 release
gate. Until that gate is completed, an installed Echelon release retains the RE
routing shipped with that release.
