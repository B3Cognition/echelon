# CARTOGRAPHER GOLDDIGGER Deep Dive Reference

Load this appendix only for brownfield work when CARTOGRAPHER cannot write testable acceptance criteria from the existing DISCOVER artifacts and GOLDDIGGER Mode 1 output.

## When To Request Mode 2

GOLDDIGGER Mode 1 provides function bodies, business logic, and error handling patterns at 99% coverage. That is enough to write precise acceptance criteria for most domains.

Request Mode 2 only when the domain has external integrations where the full topology cannot be determined from function bodies alone, making complete error-case requirements impossible. Examples include auth-provider flows, message-queue routing, and third-party API error surfaces.

Do not request Mode 2 for:

- Domains where internal behavior is unclear at signature level; `logic` depth already provides function bodies and business logic.
- General uncertainty about a domain; if the answer is in existing artifacts, use those artifacts.

## Before Requesting

Check `state.json.golddigger_completed_domains`. If a deep dive was already completed by a prior agent request, read the cached result at `.specify/squad/golddigger-cache/<domain>.md`.

## Request Format

Append the request to `${SQUAD_DIR}/state.json` with JSON-safe Python output. Keep stdout JSON-only; do not add `print()` statements because stray stdout corrupts captured `state.json` data.

```bash
python3 -c "
import json
with open('${SQUAD_DIR}/state.json', 'r') as f:
    s = json.load(f)

s.setdefault('golddigger_requests', []).append({
    'domain': '<domain-name>',
    'repo': '<repo-name-or-null>',
    'requester': 'speckit-echelon-cartographer (CARTOGRAPHER)',
    'reason': '<specific gap - e.g., cannot write testable AC for payment error cases without knowing full payment provider integration topology>'
})

with open('${SQUAD_DIR}/state.json', 'w') as f:
    json.dump(s, f, indent=2)
"
```

speckit-echelon-commander (COMMANDER) processes the queue after CARTOGRAPHER dispatch completes.
