# CARTOGRAPHER GOLDDIGGER Deep Dive Reference

Load this appendix only for brownfield work when CARTOGRAPHER cannot write testable acceptance criteria from the existing DISCOVER artifacts and GOLDDIGGER Mode 1 output.

## When To Request Mode 2

GOLDDIGGER Mode 1 provides function bodies, business logic, and error handling patterns at 99% coverage. That is enough to write precise acceptance criteria for most domains.

Request Mode 2 only when the domain has external integrations where the full topology cannot be determined from function bodies alone, making complete error-case requirements impossible. Examples include auth-provider flows, message-queue routing, and third-party API error surfaces.

Do not request Mode 2 for:

- Domains where internal behavior is unclear at signature level; `logic` depth already provides function bodies and business logic.
- General uncertainty about a domain; if the answer is in existing artifacts, use those artifacts.

## Before Requesting

Check `state.json.golddigger_completed_domains`. If a deep dive was already completed by a prior agent request, read the cached result at `$SQUAD_DIR/golddigger-cache/<domain>.md`.

## Request Format

Read the existing `state.json.golddigger_requests` list and return the full updated request queue in `echelon_result.state_updates.golddigger_requests`; the harness writes it to `${SQUAD_DIR}/state.json`.

```yaml
echelon_result:
  state_updates:
    golddigger_requests:
      - domain: "<domain-name>"
        repo: "<repo-name-or-null>"
        requested_by: "speckit-echelon-cartographer (CARTOGRAPHER)"
        reason: "<specific gap, e.g. cannot write testable AC without full payment provider integration topology>"
```

speckit-echelon-commander (COMMANDER) processes the queue after CARTOGRAPHER dispatch completes.
