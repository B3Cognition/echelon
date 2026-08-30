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
