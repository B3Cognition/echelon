# Browser Three.js (npm)

Use TypeScript, Vite, plain Three.js, and npm for browser-first 3D clients.
This stack does not require React, React Three Fiber, Drei, or pnpm.
Keep frame-rate rendering, animation, and transient scene state in browser
memory; keep durable/network boundaries outside render loops.

## Verification and coverage evidence

ALWAYS expose `test:unit` (Vitest) and `test:e2e` (Playwright) in `package.json`.
Keep project selection, repeat counts, and other test policy in those scripts
and their configuration. Echelon's isolated observers invoke the scripts and
append JSON reporter options, retaining reports outside the product candidate.
NEVER replace ordinary verification or semantic visual acceptance with a JSON
report, screenshot capture, or snapshot-update run.

ALWAYS put the exact `[echelon:<case-id>]` tag at the end of each coverage-linked
test title. Contract tests may run under Vitest or Playwright; both observers
are required. Give each case one physical source test identity; repeated
Playwright executions and projects do not create new source tests.
NEVER claim a planned case is implemented merely because its ID appears in a
document, unexecuted source, or an ambiguous/duplicate test tag.

## User-runnability contract

ALWAYS author the candidate-owned `.echelon/runnability.yml` with exact install,
bootstrap, start, readiness, primary browser journey, and stop commands. This
stack requires a fresh Linux-container journey binding real requirements to a
harness-observed `browser_dom` result, using the existing local runner contract
for reproducible user-facing commands.
NEVER substitute route mocks, observer success, or static stack readiness for
the required runtime journey and visual acceptance.
