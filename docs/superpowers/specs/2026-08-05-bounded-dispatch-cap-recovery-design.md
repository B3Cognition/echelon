# Bounded Dispatch-Cap Recovery Design

## Problem

When a phase exceeds its dispatch limit, Echelon reads eligible findings from
`issues.md` and turns each finding into a `HumanInputOption`. The current
implementation copies the complete issue title into the option label and
serializes the complete resolution candidate into the option description.

Those generated values are then validated against the human-input transport
limits: labels may contain at most 256 UTF-8 bytes and descriptions at most
1,024 UTF-8 bytes. A valid issue can exceed either presentation limit. In the
observed failure, a 289-byte issue title caused option construction to raise
`HumanInputPolicyError`; the controller then misclassified that internal option
construction failure as `phase_dispatch_limit_evidence_malformed` and terminally
blocked an otherwise recoverable run.

The active run was recovered without content loss by rewinding to its latest
`phase1-why2` checkpoint at the current commit. The permanent fix must ensure
that controller-generated recovery options always conform to transport bounds
without weakening evidence integrity.

## Goals

- Accept any valid dispatch-cap issue that fits the existing bounded
  `issues.md` artifact contract, regardless of title or resolution-text length.
- Keep option labels and descriptions within the existing human-input limits.
- Preserve the complete, exact evidence-backed candidate used for resolution.
- Detect evidence changes between decision creation and resolution.
- Distinguish malformed issue evidence from controller option-contract defects.
- Preserve existing guided, semi, and banzai decision semantics.

## Non-Goals

- Raising or removing the general human-input transport limits.
- Changing the `issues.md` authoring schema.
- Changing phase dispatch limits or issue-selection policy.
- Automatically editing issue artifacts during recovery.

## Design

### Compact option presentation

Each recovery option keeps the stable issue ID as its option ID. Its label is
controller-generated from the issue ID and title, shortened on UTF-8 code-point
boundaries to fit `HUMAN_INPUT_OPTION_LABEL_MAX_BYTES`. The shortening function
must reserve space for an ellipsis and must never split a multi-byte character.

The label is presentation only. It is not resolution authority.

### Evidence reference

The controller computes a canonical JSON representation of the complete parsed
candidate using sorted keys and compact separators, then hashes those bytes with
SHA-256. The option description contains only a compact versioned reference:

```json
{"evidence_sha256":"<64 lowercase hex characters>","issue_id":"ISS-001","schema_version":1}
```

This representation is deterministic and remains far below the 1,024-byte
description limit. Full titles, guidance, suggestions, and evidence citations
remain in `issues.md`; they are not truncated or duplicated into durable option
state.

### Resolution rehydration

When resolving a dispatch-cap option, the controller rereads the authoritative
bounded `issues.md`, parses the eligible candidates through the existing parser,
selects the candidate matching the option's issue ID, recomputes its canonical
digest, and compares it with the sealed reference.

Resolution proceeds only when both issue ID and digest match. Missing evidence,
changed evidence, duplicate IDs, or digest mismatch fail closed without applying
a decision. This preserves the existing evidence-backed resolution contract
while keeping transport fields bounded.

### Error classification

Evidence reading and parsing continue to use the existing
`phase_dispatch_limit_evidence_*` reason codes. A failure while constructing or
validating a controller-generated option uses a distinct
`phase_dispatch_limit_option_contract_failed` reason code. Evidence-reference
drift during resolution is reported as a decision-context/evidence-change error,
not as malformed source evidence.

The controller must not catch a general `HumanInputPolicyError` and relabel it as
malformed evidence.

## Data Flow

1. Dispatch limit is exceeded.
2. Controller reads and parses bounded `issues.md` candidates.
3. For each eligible candidate, controller creates:
   - stable option ID: issue ID;
   - bounded UTF-8 label: issue ID plus shortened title;
   - compact description: schema version, issue ID, candidate digest.
4. The prepared human-input decision is sealed normally.
5. Guided/semi waits for the user; banzai follows its existing resolver policy.
6. Resolution rereads candidates and verifies the selected reference digest.
7. The exact rehydrated candidate drives the existing issue-resolution state
   update and repair route.

## Recovery Compatibility

Existing pending dispatch-cap decisions that contain the legacy full-candidate
description remain readable during a bounded compatibility window. New decisions
always use the versioned compact reference. This prevents installation of the
fix from invalidating a decision that was already successfully sealed.

The currently affected run has no pending decision; its state was reset through
the checkpoint API and therefore needs no legacy-state mutation.

## Testing

Regression coverage must prove:

- a title longer than 256 bytes produces a valid, bounded, recognizable label;
- shortening does not split multi-byte UTF-8 characters;
- resolution guidance large enough to exceed the old description capacity still
  produces a valid compact option;
- an unchanged issue rehydrates and resolves to the exact original candidate;
- changed or missing issue evidence fails closed;
- legacy full-candidate descriptions still resolve;
- option-construction defects report
  `phase_dispatch_limit_option_contract_failed`, not malformed evidence;
- existing guided, semi, and banzai routing tests remain green.

Every production behavior change follows red-green TDD: add the focused failing
regression first, verify the expected failure, make the minimal implementation,
then run the focused human-input and squad-controller suites.

## Deployment and Live-Run Completion

Implementation lands on the main checkout. After tests pass, reinstall the
Python CLI from main using the repository installer and verify that
`~/.echelon/venv/bin/echelon` imports `harness.squad` from the main checkout, not
the unrelated `source-topology-foundation` worktree.

Then run `echelon spec continue` in `md_distribution` and follow the controller's
reported next action until the run reaches completion or a genuine human or
external prerequisite block.
