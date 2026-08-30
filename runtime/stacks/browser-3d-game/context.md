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
