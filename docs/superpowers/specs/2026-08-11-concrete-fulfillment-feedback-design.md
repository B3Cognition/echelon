# Concrete Fulfillment Feedback Design

## Goal

Make delivery repair consume exact unresolved fulfillment judgments and stop
deterministically when a repair changes neither those judgments nor bounded
product evidence.

## Boundary

`kernel.fulfillment` owns normalized extraction from the verified fulfillment
report. Each gap carries requirement ID, status, evidence summary, and a
recommended action from `fulfillment-gaps.md` when present.

Ralph retains the established `fulfillment-gaps` failure ID for compatibility,
but stores the normalized rows in `FailureEntry.details.gaps` and renders them
in the failure text passed to COMMANDER. Failure signatures therefore include
the concrete gap set instead of only the aggregate wrapper.

## No-Progress Rule

Before a fulfillment repair, Ralph fingerprints:

- the normalized concrete gap rows; and
- product and measured-evidence files inside the product inventory boundary.

After one COMMANDER repair and fresh verification, an unchanged pair is a
deterministic `fulfillment_no_progress` blocker. A changed gap set, changed
product/evidence fingerprint, or applied canonical task progress remains
eligible for normal continuation. Deployed `.echelon` control files, the
harness status marker, and generated Python caches do not count as evidence
progress.

## Compatibility

Legacy aggregate failures without structured gap details keep their prior loop
behavior. Existing escalation and CLI recommendation paths continue to match
the stable `fulfillment-gaps` failure ID.
