# Browser 3D Game

Use TypeScript, pnpm, Vite, React, Three.js, React Three Fiber, and Drei for
browser-first 3D games. Keep frame-rate rendering, input handling, animation,
and other transient scene state in browser memory.

Use React Three Fiber and Drei for scene composition before adding custom Three
wrappers. Keep game UI in React and place durable/network interactions at a
clear boundary outside render loops.

When combined with `game-persistence-postgres`, call the persistence or API
boundary only for deliberate durable state transitions. Browser storage can be
a cache or offline aid, never the authoritative source of player progression.

## User-runnability contract

This stack requires a fresh Linux-container user journey before delivery may
converge. The candidate owns `.echelon/runnability.yml`; declare the exact
install, bootstrap, start, readiness, browser journey, and stop commands there.
The primary journey must bind real requirements to a harness-observed
`browser_dom` result and must not replace API/data boundaries with browser route
mocks.

Echelon executes the contract in an isolated sandbox and writes immutable
evidence under the delivery run. Use `echelon delivery status <spec_id>` for the
successful local provision/start/open/stop commands a user should run. If the
owner explicitly accepts follow-up work, use
`echelon spec defer-runnability <spec_id> --reason "<reason>"`; the generated
proposal remains advisory and does not silently weaken this stack.
