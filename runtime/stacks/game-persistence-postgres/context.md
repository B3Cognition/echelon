# Game Persistence with Postgres

Use Postgres as the durable source of truth for player accounts, profiles,
inventories, progress, save snapshots, and durable leaderboards. Make every
schema change through a checked-in migration and include migrations in the
project verification path.

Treat rewards, inventory changes, and leaderboard submissions as privileged
server-side mutations. Clients may request an action, but the server validates
its input, authorizes the player, and writes the durable result.

Keep rendering and simulation state in the client or live game process. Persist
only at checkpoints, explicit save events, session end, or bounded periodic
snapshots. Never write database state for every render or simulation tick.

Browser storage may cache data or support offline play but is not the durable
source of truth. Do not add a second durable database, unauthenticated direct
database access, or client-only source-of-truth storage without an explicit
architecture amendment.

## Composed persistence observation

When combined with a required browser game stack, the candidate
`.echelon/runnability.yml` must declare a persistence probe. Echelon keeps the
attempt-scoped Postgres sidecar running, writes a unique marker through the real
application journey, restarts the declared application boundary, and verifies
the same marker with a harness-owned direct `postgres_query` observation.
`DATABASE_URL` is injected into the sandbox for this composition; do not require
the user to install project dependencies or a database on the host.

The candidate must also declare a complete `local_journey` in that same
contract: prerequisites, provision, readiness, disposable-state preparation,
verification, start, open, stop, and cleanup. These are candidate-owned local
instructions, not harness-generated Compose commands. Echelon reports them as
`unverified` unless a compatible runner actually executes them; never imply
that sandbox credentials or sidecars prove the host-local path.

The report under `evidence/user-runnability/` is authoritative. README commands
must match its sandbox facts and its separately declared local journey, including
the local verification status. The current report is shown by
`echelon delivery status <spec_id>` after a passing sandbox run.
