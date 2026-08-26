# Leaderboard — Sample Specification (SUE walkthrough)

A deliberately tiny specification used by `docs/sue-walkthrough.md` to
demonstrate the SUE tools end to end. It looks fine, but it hides two real
ambiguities on purpose — SUE's job is to surface them.

## Requirements

- **FR-001**: When a player opens the leaderboard, the system MUST show the top 5 players ranked by their highest score.
- **FR-002**: A banned player MUST never appear on the leaderboard.
- **FR-003**: When two players have the same score, the system MUST place them in a stable order.
- **NFR-001**: The leaderboard MUST load within 2 seconds for up to 10000 players.

## Acceptance Criteria

- **AC-001**: Given at least 5 active players, when a player opens the leaderboard, then exactly 5 rows are shown, ordered from highest score to lowest.
- **AC-002**: Given a player has been banned, when any player opens the leaderboard, then the banned player is absent from every row.
