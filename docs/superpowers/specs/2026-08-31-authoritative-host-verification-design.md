# Authoritative Host Verification Design

**Status:** Approved

## Purpose

Allow Phase B delivery to recover autonomously when an AI coding provider cannot
execute a host-bound verifier such as Chromium, PostgreSQL, Docker, Xcode, or a
device simulator. Ralph already executes configured verification outside the AI
provider. This change makes that execution the sole verification authority,
retains commit-bound evidence, and lets fulfillment consume that evidence.

The coding provider remains responsible for implementation and repair. It may
report that its own environment cannot execute verification, but it cannot
declare verification successful.

## Problem

The current control flow returns immediately when a build or repair agent writes
`BUILD_BLOCKED`. Ralph therefore never reaches `_exec_verify_locally()`, even
when the blocker is only that the managed AI-provider sandbox cannot launch a
browser or reach a test service. A successful host execution performed outside
the delivery run is also invisible to fulfillment because Ralph emits no durable
receipt and fulfillment receives no trusted evidence path.

This conflates two outcomes:

- implementation is genuinely blocked; and
- implementation is ready, but provider-local verification is unavailable.

The browser 3D smoke run reproduced the second outcome: the same candidate
passed the full verifier and five repeated browser journeys on the host, while
the coding provider stopped because macOS denied Chromium bootstrap inside its
sandbox.

## Decision

Configured harness verification is authoritative by default. The authority is
deterministic Ralph code executing the actual command, never an AI-provider
claim. A provider-local verification limitation is a recoverable handoff to
Ralph. A genuine implementation blocker remains terminal.

No new opt-in flag is required. `verify_command` already means that Ralph is
authorized to execute that command against the candidate worktree. Automatic
package-manager verification keeps the same authority when no explicit command
is configured.

## Considered approaches

### Typed verification deferral plus a Ralph receipt — selected

Add a machine-readable `verification_environment` blocker kind. Ralph recognizes
only that kind as recoverable, executes its verifier, writes a receipt, and then
runs fulfillment with the receipt as an explicit input. This preserves the
existing fail-closed behavior for every other blocker.

### Prompt-only instruction — rejected

Tell agents not to block when browser or database execution is unavailable.
This is useful guidance but is not a control-plane guarantee: providers can
still return inconsistent prose or status markers, and fulfillment still lacks
durable evidence.

### Ignore every build blocker and always verify — rejected

This maximizes continuation but erases the distinction between an environmental
limitation and missing credentials, unresolved requirements, destructive action
approval, or an incomplete implementation. Ralph must not overrule those cases.

## Status contract

`BuildResult` gains an optional `blocker_kind`. The only new recognized value is
`verification_environment`.

A build-status payload may report:

```json
{
  "verdict": "BLOCKED",
  "reason": "Chromium cannot launch in the managed provider sandbox",
  "blocker_kind": "verification_environment",
  "completed_task_ids": []
}
```

Ralph treats this as `verification_deferred`, not as successful verification.
It continues only to harness-owned verification. Unknown blocker kinds and a
plain `BLOCKED` retain the current terminal `build_blocked` behavior.

The build and repair prompts state paired rules:

- ALWAYS defer provider-local verification limitations to Ralph with the typed
  blocker kind after completing all safe implementation work.
- NEVER use `verification_environment` for missing implementation, ambiguous
  requirements, credentials needed by the product, destructive approval, or a
  verifier that ran and failed.

Misclassification cannot create false success: Ralph still runs the real
verifier. A failed or unavailable Ralph verifier remains a failure.

## Verification receipt

Ralph writes an atomic JSON receipt under the delivery run, outside the candidate
Git worktree:

```text
runs/targets/<target>/runs/<build-id>/evidence/<strategy>/host-verification.json
```

The receipt schema is versioned and contains:

- authority: `ralph-host-verifier`;
- spec, target, build, and strategy identifiers;
- candidate Git commit and bounded candidate-content fingerprint;
- verifier source: configured or automatically detected;
- ordered stages with display command, start/completion timestamps, duration,
  exit code, status, stdout/stderr SHA-256 digests, and bounded output tails;
- aggregate pass/fail status;
- receipt SHA-256 calculated over canonical JSON without the digest field.

Environment values are never serialized. Output tails are bounded and passed
through the existing sensitive-value redaction boundary before persistence.
Receipt publication uses a temporary sibling file, `fsync`, and atomic replace.

A receipt is current only when its candidate commit and content fingerprint
match the worktree being assessed. Ralph never reuses a passing receipt after
source changes. Failed receipts are retained as repair evidence but cannot
satisfy fulfillment.

## Data flow

1. The coding provider implements a build or repair slice.
2. It reports `done`, or reports `BLOCKED` with
   `blocker_kind=verification_environment` when only its execution environment
   prevents verification.
3. Ralph checkpoints eligible implementation progress using the existing task
   ledger rules.
4. Ralph executes the configured or detected verifier in the candidate
   worktree.
5. Ralph persists the verification receipt regardless of pass or failure.
6. On failure, Ralph feeds the authoritative failure back into the normal
   repair loop. On an unavailable verifier, Ralph preserves the existing
   `verify_command_needed` stop.
7. On success, Ralph passes the receipt path and digest into
   `FulfillmentRunner.refresh()`.
8. Fulfillment receives read-only access to the exact receipt, validates its
   authority, digest, pass status, commit, and content fingerprint, and includes
   it in the verification cache key and verified-ledger input.
9. Fulfillment may use the receipt's measured output as evidence for test and
   journey requirements. It must still judge whether the executed tests cover
   the requirement; a generic green command does not automatically implement
   every requirement.
10. Existing fulfillment, documentation, task-progress, publication, and merge
    gates continue unchanged.

## Ralph control-flow changes

Both outer build handling and inner repair handling use one helper that returns
whether a failed build result is eligible for authoritative verification. The
helper accepts only:

- an explicit completion marker;
- normalized status `blocked`;
- blocker kind `verification_environment`; and
- an available candidate worktree.

Eligible results record the deferral in run state and proceed to `_exec_verify`.
They do not count as a successful AI build invocation. Ineligible blockers use
the existing banners, salvage behavior, and terminal states.

When host verification passes after a deferral, the delivery loop proceeds to
fulfillment in the same iteration. When it fails, its structured failures—not
the provider's environment prose—become the repair input.

## Fulfillment contract

`FulfillmentRunner.refresh()` accepts an optional verification-evidence
descriptor containing the absolute receipt path and expected digest. The direct
and provider-backed verify-spec paths share the same validation function.

Validation fails closed when the receipt is missing, malformed, non-passing,
digest-invalid, from another authority, or stale for the candidate. The receipt
parent is added as a read-only provider root; it is never added to write paths.
The verify-spec prompt names the receipt explicitly, so agents do not search
arbitrary run directories.

The receipt digest participates in the fulfillment cache key. A cached report
created without the current receipt cannot hide newly available measured
evidence, and a receipt for another candidate cannot be reused.

## Error handling

- Provider reports an ordinary blocker: stop as `build_blocked`.
- Provider reports typed verification deferral and Ralph verifier passes:
  continue autonomously.
- Provider reports typed verification deferral and Ralph verifier fails: enter
  the normal bounded repair loop with Ralph's failures.
- Configured verifier cannot start or times out: write a failed receipt and use
  the existing structured verify failure behavior.
- No verifier can be configured or detected: stop as `verify_command_needed`.
- Receipt write or validation fails: fail closed with a dedicated
  `verification-evidence-invalid` failure; do not invoke fulfillment.
- Candidate changes after receipt creation: invalidate the receipt and execute
  verification again.

## Security and trust boundary

The AI provider cannot write a trusted receipt. Only Ralph's deterministic
receipt writer owns the authority string and receipt location. Fulfillment gets
read-only access to that exact artifact. A receipt proves command execution and
result for one candidate; it does not prove that the configured command is a
complete test strategy, so requirement-level judgment remains in fulfillment.

Host verification executes only commands already authorized by existing
configuration or high-confidence detection. This design does not broaden
network access, expose environment values, or allow provider-selected commands
to escape the configured verifier.

## Testing

Unit and integration coverage must demonstrate:

- status parsing preserves the typed blocker kind;
- an ordinary blocker still terminates before verification;
- a typed environment blocker reaches Ralph verification in outer and repair
  loops;
- a passing host verifier writes a current, digest-valid receipt and reaches
  fulfillment;
- a failing host verifier writes a failed receipt and enters repair;
- a stale or tampered receipt is rejected;
- provider permissions expose the receipt read-only and do not broaden writes;
- the receipt digest invalidates fulfillment caching;
- a smoke fixture with a verifier unavailable to the coding provider but
  available to Ralph converges without manual debt acceptance.

Tests use tiny local commands and fixtures; they do not require a real browser,
database, network, or Docker daemon.

## Out of scope

- Remote CI attestation, signing, or third-party provenance standards.
- Arbitrary user-supplied evidence imports.
- Automatically installing browsers, databases, simulators, or system tools.
- Treating a passing verifier as proof of requirements it does not exercise.
- Recovering blockers other than the explicit verification-environment class.
