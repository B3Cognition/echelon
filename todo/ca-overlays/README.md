# Quarantined CA Overlay Prototypes

These files are retained for possible future review but are not part of the Echelon runtime.
They are also excluded from the installation bundle, Prosaic source, and provider execution.

Retained prototypes:

- `goal_stack.py`
- `episodic_memory.py`
- `gwt_workspace.py`

They were originally created for the U-CA-004 experiment. Repository audit on
2026-08-10 found no runtime imports or callers. The experiment runner only
listed their former paths as metadata and did not execute them.

## Review before reactivation

Before moving either prototype back into active source:

1. Define the current Echelon capability it serves and its owner.
2. Replace `.specify/squad` persistence with the canonical `runs/` contract.
3. Integrate it through an explicit runtime boundary rather than prompt claims.
4. Add unit and end-to-end tests proving that the controller invokes it.
5. Decide whether its state duplicates the journal, SOAR, or VETERAN memory.

Until that review is complete, code outside this folder must not import these
modules or advertise them as deployable overlays.
