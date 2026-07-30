# MemPalace In Echelon

Echelon uses MemPalace as a semantic retrieval layer for canonical specification requirements and supporting spec context. The normal pipeline owns its public commands under `echelon spec memory`; `codegen requirements` is a deprecated compatibility surface for older raw-file workflows.

## Manual Reconciliation

Run this after publishing or amending a canonical spec:

```bash
echelon spec memory refresh 003-my-feature --write
```

`refresh` writes missing exact canonical drawers, adopts exact existing drawers, removes stale deterministic drawers for the selected spec artifacts, and then audits the result. It does not overwrite drifted deterministic drawers.

For read-only verification:

```bash
echelon spec memory audit 003-my-feature --json
```

Exit codes:

- `0`: pass, warn, or complete
- `1`: fail or partial
- `2`: unavailable memory backend or invalid invocation

Semantic retrieval probes are optional:

```bash
echelon spec memory audit 003-my-feature --probe-retrieval
```

Probe failures can warn about retrieval quality, but they are never storage proof.
