# Banzai WHY2 Protocol-Upgrade Retry Design

## Purpose

Recover one specific legacy failure safely: a Banzai run made one controller-owned
WHY2 reassessment before the deployed workspace had the typed
`autonomous_default_candidate` protocol. If that reassessment still ends at an
otherwise eligible human gate, Echelon must be able to give the *updated,
deployed* protocol one further chance. It must not turn a Banzai clarification
into an unbounded retry loop or alter semi, guided, or ordinary Banzai flows.

The current marker, `banzai_default_reassessment`, records that a legacy WHY2
gate was reassessed but not the active protocol bundle. Consequently it cannot
distinguish “the same protocol failed again” from “the workspace has since been
refreshed with a new protocol.”

## Decision

Add a controller-owned, versioned reassessment ledger and permit exactly one
additional reassessment only when a legacy first reassessment has no recorded
protocol fingerprint and the current workspace has a complete candidate-protocol
fingerprint. Because the legacy record has no baseline fingerprint, the retry
is a bounded migration recovery rather than a claim that byte-level change can
be proven. The retry is consumed atomically before the phase is dispatched.

This directly recovers the browser-game run after `echelon workspace
migrate-to-prosaic`: its existing v1 ledger represents the pre-fingerprint
attempt; the refreshed workspace supplies the one permitted upgrade attempt.

## Protocol Fingerprint

The controller computes `sha256` over the active workspace files below, in
lexicographic path order, with length-delimited UTF-8 path and raw-byte content
records. The digest is prefixed `sha256:`.

1. `.echelon/runtime/workflow/definition.yaml`
2. `.echelon/runtime/workflow/phases/phase1-why2.md`
3. `.echelon/prosaic/subagents/echelon.sage.md`

These are the deployed artifacts that respectively authorize the WHY2 route,
define the typed candidate envelope, and instruct SAGE to emit it. The Python
validator remains part of the installed controller and is not a workspace
artifact; a different installed controller version therefore cannot by itself
unlock another retry.

Fingerprint calculation fails closed. Each file must be a regular file, must
be readable without following an unexpected missing path, and must be at most
1 MiB. Any missing, unreadable, non-regular, or oversized file yields no
upgrade retry. The status output explains that the active candidate protocol
cannot be verified and recommends `echelon workspace migrate-to-prosaic`; it
does not dispatch an agent or mutate the decision.

## Eligibility and Boundaries

The controller may consume the upgrade retry only when all of the following are
true:

1. The run is Banzai and the blocked decision is a valid, current WHY2
   `awaiting_human` decision.
2. The ordinary controller policy authorizes `phase1-why2` to reassess itself.
3. The decision remains a bounded, candidate-eligible product calibration. It
   may not be a fact, security/privacy/legal policy, safety boundary, scope or
   architecture decision, external prerequisite, or quality waiver.
4. The run has the existing v1 legacy reassessment marker, and it records no
   protocol fingerprint.
5. The active fingerprint is complete and valid.
6. The ledger has not consumed an upgrade retry.

The transition clears the old human-input authority, returns the run to
`running` at `phase1-why2`, and writes the upgrade attempt in one state-store
commit. The subsequent SAGE result is handled by the normal candidate
validation and controller-resolution path. A new human gate remains blocked
unless the typed candidate is valid and policy-eligible.

No later bundle change grants another retry. This feature has a fixed lifetime:
one original legacy reassessment plus one protocol-upgrade reassessment. A
non-eligible question, an unchanged v2 record, an absent marker, a malformed
ledger, or a second attempt is never silently retried.

## Ledger and Compatibility

The existing exact v1 marker remains readable. It is interpreted as one
historical reassessment with an unknown bundle fingerprint. On an approved
upgrade retry it is atomically replaced by a schema-v2 record:

```json
{
  "schema_version": 2,
  "source_phase": "phase1-why2",
  "initial_attempt": {
    "decision_id": "dec-...",
    "question_sha256": "<sha256>",
    "protocol_fingerprint": null
  },
  "upgrade_attempt": {
    "decision_id": "dec-...",
    "question_sha256": "<sha256>",
    "protocol_fingerprint": "sha256:<hex>",
    "reassessed_at": "<RFC 3339 timestamp>"
  }
}
```

The current decision's ID and question hash belong to `upgrade_attempt`; they
need not equal the first question's wording. This preserves a truthful audit
trail when SAGE refined the question between attempts. The v2 parser accepts no
extra keys, validates IDs, SHA-256 strings, timestamps, and the exact
`phase1-why2` ownership. Generic state writes remain unable to create, modify,
or remove either schema.

## Control Flow and Reporting

`resume_pending_human_input()` evaluates this route after the original legacy
reassessment check and before ordinary Banzai resolution. It asks the state
store to consume the retry using an expected state revision, so competing CLI
invocations cannot both reopen the gate.

The CLI presents one unambiguous recovery action:

- When eligible: `echelon spec continue` and a note that one refreshed
  candidate-protocol reassessment will run.
- When the deployed bundle cannot be fingerprinted: no retry action; explain
  the precise file failure and show `echelon workspace migrate-to-prosaic`.
- When already consumed or not eligible: retain the existing human-answer
  action without implying an automatic retry is available.

The protocol fingerprint is diagnostic provenance, not a product decision and
not a substitute for candidate validation. It is shown only in durable state
and detailed status, never treated as proof that the agent selected a safe
answer.

## Non-Goals

- Refreshing a workspace automatically.
- Granting retries to fresh runs, normal Banzai runs, semi/guided runs, or
  non-WHY2 decisions.
- Supporting repeated retries after future prompt edits.
- Adding or implementing the separately discussed `super-banzai` authority.
- Changing candidate eligibility, human-input policy, or agent prompts.

## Tests and Verification

Tests will cover the narrow state and controller boundary:

1. A v1 legacy marker plus a valid fingerprint consumes exactly one upgrade
   retry and records the v2 ledger atomically.
2. A v2 marker, a malformed ledger, invalid decision, policy mismatch, missing
   file, non-regular file, oversized file, or unreadable file does not mutate
   state or dispatch WHY2.
3. The second CLI invocation is blocked at the ordinary human decision and
   cannot consume another retry.
4. The CLI reports the correct action for eligible, unavailable, and consumed
   states.
5. Existing legacy reassessment, normal Banzai candidate resolution, and
   non-Banzai human-input routing tests remain green unchanged.

Focused unit and integration suites will run first, followed by the relevant
human-input routing suite. The demo workspace will then be checked read-only to
confirm that its refreshed v1 ledger becomes one v2 upgrade attempt and no
regular flow receives this route.
