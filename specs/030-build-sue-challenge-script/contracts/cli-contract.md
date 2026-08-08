# Contract: Operator CLI

## Metadata

- Spec: 030-build-sue-challenge-script
- Boundary: Operator ↔ `scripts/sue_challenge.py` (process argv / stdout / stderr / exit code)
- Architect: speckit-echelon-architect (ARCHITECT)
- Date: 2026-07-18

## Boundary Index

| Boundary | Type | Provider | Consumers | Auth | Contract File |
|----------|------|----------|-----------|------|---------------|
| Operator CLI | CLI | sue_challenge.py | script operator; later SUE tiers (stable v1 interface) | none (trusted local operator) | this file |
| Model command | CLI (outbound) | operator-supplied command (default `claude`) | sue_challenge.py | operator's model session | model-command-contract.md |
| Report / debug artifacts | Filesystem | sue_challenge.py | spec authors, reviewers | filesystem perms | report-format.md |

## Contract: Operator CLI

- Type: CLI
- Provider: `scripts/sue_challenge.py` (invoked as `python3 scripts/sue_challenge.py …` or via its `#!` shebang)
- Consumers: script operator (manual); pytest seam tests (in-process `main(argv)`)
- Versioning: v1 surface is frozen — 1 positional argument, 3 options, 4 exit codes; later
  SUE tiers extend behind this interface without changing it (spec Out of Scope)
- Authentication / authorization: none; single trusted local operator (boundaries.md)
- Rate limits: none

### Operations

| Operation | Request / Input | Response / Output | Errors | Idempotency |
|-----------|-----------------|-------------------|--------|-------------|
| Challenge run | see Invocation below | exit 0; report written; stdout summary | exit 1/2/3 per table below | rerun overwrites the report (U-010); safe to repeat |
| `--help` | argparse-generated | usage text; MUST contain exactly 1 egress disclosure (NFR-003) | — | pure |

### Invocation

```
sue_challenge.py SPEC_PATH [--questions N] [--claude-cmd CMD] [--timeout SECONDS]
```

| Argument / Option | FR | Default | Meaning |
|-------------------|----|---------|---------|
| `SPEC_PATH` (positional, exactly 1) | FR-001 | — | Path of the markdown specification to challenge; never written (FR-042) |
| `--questions N` | FR-002 | 15 | Cap on round-1 questions; valid round-1 output above N is truncated to the first N with a report note (FR-019) |
| `--claude-cmd CMD` | FR-003, FR-007, FR-043 | `claude` | Model command line, split per shell quoting conventions (`shlex.split`); word 1 is the availability-checked executable. Test seam: any operator-supplied command substitutes for the default. MUST NOT be sourced from configuration files or the network (spec Limitations) |
| `--timeout SECONDS` | FR-004 | 300 | Per-subprocess-call budget; each corrective retry gets a fresh budget (FR-013) |

Option names follow the design's interface (`--claude-cmd` per glossary "Test seam"); the
spec's generic wording "model-command option" refers to this flag.

### Exit codes (complete — SC-003)

| Code | Class | Trigger | Guarantees |
|------|-------|---------|------------|
| 0 | success | report written (incl. zero-question FR-020 and zero-finding FR-041 outcomes) | report exists; stdout summary printed (FR-040) |
| 1 | bad input | spec missing/unreadable (FR-005) or spec directory not writable (FR-006) | exactly 0 model calls launched (ERR-001/ERR-002) |
| 2 | model command unavailable | executable (word 1) not found (FR-012) | exactly 1 stderr message containing an installation pointer; 0 reports written (ERR-003) |
| 3 | unusable model output | second parse failure in one round, incl. timeouts (FR-030) | raw output saved to `.sue-debug/`; 0 reports written (ERR-004) |

Every non-zero exit prints exactly 1 diagnostic line to stderr naming the failure class
(NFR-005). Stdout carries only the success summary (human-oriented, no machine contract —
A-011).

### Input surface (FR-045)

The script reads exactly 2 kinds of input: its command-line arguments and the challenged
specification file. It reads 0 orchestration configuration or state files and imports 0
project modules (review gate — feasibility.md risk 5).

## Internal Interfaces

See `internal-interfaces.md`.
