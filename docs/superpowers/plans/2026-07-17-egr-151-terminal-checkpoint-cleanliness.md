# EGR-151: terminal checkpoint cleanliness

**Goal:** A successful Phase A terminal checkpoint leaves no Echelon-owned
published-spec metadata or approved knowledge-base mutation unstaged, while
preserving unrelated user changes.

## 1. Keep published specs free of runtime metadata

**Files:** `src/harness/squad.py`, `tests/integration/test_squad_controller.py`

- Copy only publishable Phase A artifacts from the run-local spec tree.
- Delete a legacy published `.echelon` directory during republishing.
- Regress with a terminal Phase 4 publication test containing a run-local
  checkpoint ledger.

## 2. Commit verified KB mutations at the terminal checkpoint

**Files:** `src/echelon/kb_proposals.py`, `src/harness/phase_checkpoints.py`,
`src/harness/squad.py`, `tests/unit/test_phase_checkpoints.py`,
`tests/unit/test_kb_proposals.py`, `tests/unit/test_squad_phase_checkpoints.py`

- Read the run-local KB apply report and resolve only accepted, known canonical
  KB target files beneath the project root.
- Extend checkpoint staging with exact additional owned paths; do not stage an
  entire knowledge-base directory or unrelated worktree changes.
- Pass those verified paths only for a successful Phase 4 terminal checkpoint.
- Cover accepted, malformed, and unrelated-change cases with no-LLM Git tests.

## Verification

- Run focused Phase A checkpoint, KB proposal, and squad checkpoint tests.
- Run the existing terminal publication integration regression and whitespace
  checks.
