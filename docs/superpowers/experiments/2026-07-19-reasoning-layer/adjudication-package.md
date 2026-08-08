# Zaslepeny adjudikacni balicek — reasoning experiment

Ohodnot kazdou polozku: zavaznost 0-3 (0=ne-nalez, 1=definicni, 2=behavioralni mezera, 3=rozpor/blokujici)
a lokalizaci 0-2 (0=vagni, 1=oznacuje pozadavek, 2=pojmenovava minimalni chybejici rozhodnuti).

**N01.** [APORIA_CONTRADICTED] seed 'whether incremental journal loading is optional or mandatory, given th': The specification never states an explicit definition of the modality; it only exhibits it through usage, and the usages pull in opposite directions. Line 71 phrases incremental loading with SHOULD ('the workbench SHOULD load journal entrie

**N02.** [APORIA_CONTRADICTED] seed 'which prompt a bare Esc with unsaved changes opens': The text does contain an alternative reading, but it cannot cleanly supply a single corrected understanding — it supports two incompatible routings for a bare Esc with unsaved changes. Side 1 (dominant, post-ISS-064-012): FR-070 (line 195) 

**N03.** [CONFLICT] The cursor-mode keyboard chords (g w / g d / g f, second key within 500 ms) work in BOTH edit mode and non-edit mode.  ×  The extended isInputLikeActive() guard (detecting INPUT/TEXTAREA/SELECT/contentEditable plus combobox/listbox/data-state=open) suppresses gl

**N04.** [CONTRADICTED] The glossary defines the responsibility-profile gate as 'returning true when operator owns at minimum WHO+WHERE', while FR-001 says the gate opens for any single responsibility. If the glossary is a normative reference for `useIsRowEditingAllowed()`, which definition governs the 

**N05.** [APORIA_CONTRADICTED] seed 'which operators are permitted to enter row-edit mode': The spec's primary definition is FR-001 (line 179): row-edit affordances render when `session.mode === 'collector'` AND the operator's session responsibilities include at least one of who, where, what, or when; a responsibility-less collect

**N06.** [CONTRADICTED] FR-066 says the g+w/g+d/g+f chords 'work in both edit mode and non-edit mode', but FR-029 extends isInputLikeActive() to suppress global keyboard handling whenever an input, combobox, or open listbox is active — which is precisely the state during editing. When the operator types

**N07.** [CONFLICT] Editing soft-deleted rows (TrxOperator='D') is a non-goal: such rows bypass enterRowEdit and fall through to read-only click-to-seek; the op  ×  Per EC-003, when another operator soft-deletes the row mid-edit, the editor REMAINS OPEN and Save submits a patch targeting a deleted row (r

**N08.** [CONFLICT] Soft-deleted rows (TrxOperator='D') and synthetic rows are not editable: they bypass enterRowEdit and fall through to read-only click-to-see  ×  Per EC-003, when the editing row is concurrently soft-deleted by another operator, the editor remains open and on Save the patch targets the

**N09.** [UNANSWERABLE] An undo (FR-031) submits a reverse patch that by definition overwrites a non-null value in a REQUIRED_DIM_FIELDS field. Does every Ctrl+Z therefore trigger FIELD_ALREADY_SET and an OverwriteDialog, and what is the specified behaviour when an undo patch is rejected — does the undo

**N10.** [CONTRADICTED] FR-066 says the g-chord shortcuts 'work in both edit mode and non-edit mode', yet FR-029's extended isInputLikeActive() guard exists precisely to suppress global key handling while an input is focused. When the operator is typing 'g' into a focused text cell (e.g. the HH:MM:SS.mm

**N11.** [CONFLICT] Soft-deleted rows (TrxOperator='D') and synthetic rows (StatTypeID in SYNTHETIC_TE_IDX or < 0) are not editable: clicks bypass enterRowEdit   ×  EC-003 keeps the inline editor open when the editing row is concurrently soft-deleted by another operator, and on Save the patch is submitte

**N12.** [UNANSWERABLE] SR-014 adds te_idx, period, and team_side to REQUIRED_DIM_FIELDS, but aren't these fields non-null on virtually every event from the moment of creation? If so, doesn't every single WHAT/Period/Team inline edit now trigger FIELD_ALREADY_SET and an OverwriteDialog, defeating G-1's 

**N13.** [CONFLICT] The decision-trail view MUST present reasoning-journal entries in time order, each showing entry type, phase, owning agent, and summary.  ×  The decision-trail view for large journals must render the most recent entries first, must not read the whole file before first paint, and m

**N14.** [CONFLICT] Row-level edit mode opens for any collector session with at least one of WHO/WHERE/WHAT/WHEN responsibilities (FR-001, widened from the orig  ×  AC-5 states that an operator with only WHO responsibility (no WHERE) who clicks a row sees NO edit affordances — the pre-widening gate behav

**N15.** [UNANSWERABLE] FR-023 defines a conflict as the same player at coordinates 'more than 30 metres apart', but the glossary defines XPos/YPos as a normalised signed-integer system in [-100, 100] with no physical dimensions. What conversion from normalised units to metres is the implementer meant t

**N16.** [CONFLICT] Pressing Esc with uncommitted row-draft changes triggers a 2-option prompt (Discard/Cancel) that deliberately offers NO Save option; saving   ×  FR-025(b) states that Esc with no cell focused triggers row-level cancel 'per FR-012/AC-6' — routing Esc to the 3-option Save/Discard/Cancel

**N17.** [CONFLICT] Inline row-edit mode SHALL open for any collector-mode operator whose session responsibilities include at least one of WHO/WHERE/WHAT/WHEN;   ×  AC-5 requires that an operator with only WHO responsibility (no WHERE) sees no edit affordances at all when clicking any row.

**N18.** [CONFLICT] When no dispatch is in progress, saving the spec persists the edited file directly to the run staging directory and records and displays the  ×  The workbench never writes the run state file or the reasoning journal directly — those are orchestrator-owned — and its OUTPUT commits more

**N19.** [CONFLICT] When reading run state during an active dispatch, the workbench MUST tolerate a partially written or momentarily unavailable state file, kee  ×  A run whose state file is missing or unparsable is marked unreadable (ERR-RUN-UNREADABLE) while the rest of the run list stays usable — whic

**N20.** [CONFLICT] Row-level inline-edit mode opens for any collector-mode operator whose session responsibilities include at least one of WHO, WHERE, WHAT, or  ×  The glossary defines the responsibility-profile gate as `useIsRowEditingAllowed()` returning true only when the operator owns at minimum WHO

**N21.** [CONFLICT] Row-level inline-edit mode opens for any collector-mode operator whose session responsibilities include at least one of WHO, WHERE, WHAT, or  ×  Per AC-5, an operator with only WHO responsibility (no WHERE) who clicks any row sees no edit affordances.

**N22.** [CONFLICT] Row-level edit mode opens for any collector session with at least one of WHO/WHERE/WHAT/WHEN responsibilities (FR-001, widened from the orig  ×  The glossary defines the responsibility-profile gate as `useIsRowEditingAllowed()` returning true only when the operator owns 'at minimum WH

**N23.** [APORIA_CONTRADICTED] seed 'which operators are permitted to enter row-edit mode': The text does contain an explicit corrected understanding, but it also retains unreconciled text asserting the incompatible old rule. The correction: FR-001 (line 179) states that inline-edit affordances render when session.mode === 'collec

**N24.** [APORIA_CONTRADICTED] seed 'which prompt a bare Esc with unsaved changes opens': The specification commits to an explicit definition in FR-070 (line 195): pressing Esc while the row-draft has uncommitted changes opens a confirmation with exactly two actions — 'Discard' (clears draft, exits edit mode, returns to IDLE) an

**N25.** [APORIA_CONTRADICTED] seed 'which operators are permitted to enter row-edit mode': The spec commits to an explicit definition: inline row-edit entry is permitted when `session.mode === 'collector'` AND the operator's session responsibilities include at least one of WHO, WHERE, WHAT, or WHEN (FR-001, line 179; restated in 

**N26.** [CONFLICT] The decision-trail view presents reasoning-journal entries in time order, each showing its entry type, phase, owning agent, and summary.  ×  For large journals the decision-trail view loads entries incrementally and renders the most recent entries first, with initial paint at most

**N27.** [CONFLICT] For journals past one thousand entries, incremental (paginated) loading is recommended but optional: the THEN clause uses SHOULD, not MUST.  ×  The decision-trail view for large journals must render the most recent entries first, must not read the whole file before first paint, and m

**N28.** [CONTRADICTED] FR-001 widens the gate to 'any collector with at least one of WHO/WHERE/WHAT/WHEN', yet the Glossary still defines the responsibility-profile gate as 'true when operator owns at minimum WHO+WHERE'. Which definition should an implementer of useIsRowEditingAllowed() trust, and how 

**N29.** [APORIA_CONTRADICTED] seed 'whether incremental journal loading is optional or mandatory, given th': The text supports a counterexample, but it cuts against the stated understanding rather than confirming it. The understanding calls the 2-second first-paint constraint 'unconditional'; line 73 conditions it on 'journals up to 10000 entries'

**N30.** [APORIA_UNDERDETERMINED] seed 'how the workbench reliably detects an in-progress dispatch from a stat': The text treats four distinct cases, split by two axes: what the state file says, and whether it can be read at all. Case 1 — state readable, no dispatch in progress: the save is permitted and persisted with a save-time confirmation (REQ-02

**N31.** [CONFLICT] Incremental (paginated, most-recent-first) journal loading is only a SHOULD-level recommendation, with the 2-second first-paint constraint s  ×  AC-010 makes incremental loading a mandatory observable behavior — for a 12000-entry journal (beyond the 10000-entry constraint scope of lin

**N32.** [UNANSWERABLE] SR-006-ACK correlates success by matching any re-broadcast EventFrame's event_id against the oldest in-flight clientPatchId. What prevents an EventFrame caused by a different operator's concurrent update to the same event_id from falsely ACKing this client's still-pending (or abo

**N33.** [CONFLICT] Inline row-edit mode SHALL open for any collector-mode operator whose session responsibilities include at least one of WHO/WHERE/WHAT/WHEN;   ×  The glossary defines the responsibility-profile gate (useIsRowEditingAllowed) as returning true only when the operator owns at minimum WHO+W

**N34.** [CONFLICT] When the state file is partially written or momentarily unavailable during an active dispatch, the workbench MUST keep presenting the last c  ×  When a selected run directory has a missing or unparsable state file, the workbench marks that run as unreadable while keeping the rest of t

**N35.** [CONTRADICTED] FR-025(b) says Esc with no cell focused 'triggers row-level cancel per FR-012/AC-6', but FR-012 is the row-SWITCH three-option prompt and AC-6 is ACK-rejection recovery; the Esc-with-changes flow is actually FR-070's two-option prompt. Which prompt does a bare Esc actually open, 

**N36.** [CONFLICT] Pressing Esc with uncommitted row-draft changes triggers a 2-option prompt (Discard / Cancel) with deliberately NO Save option (FR-070), dis  ×  FR-025(b) states that Esc with no cell focused 'triggers row-level cancel per FR-012/AC-6' — routing Esc to the 3-option Save/Discard/Cancel

**N37.** [UNANSWERABLE] FR-031's undo submits a reverse patch that by definition overwrites a non-null value in fields that SR-014 now places in REQUIRED_DIM_FIELDS. Does the undo path send force:true, and if not, is the operator expected to answer an OverwriteDialog for every Ctrl+Z? Neither behaviour 

**N38.** [CONFLICT] Three cursor modes exist (incomplete-only default, display-order, filter-aware) selectable via a header segmented control and via two-key g-  ×  The extended isInputLikeActive() guard suppresses the global keyboard handler whenever an input-like element (INPUT, TEXTAREA, SELECT, conte

**N39.** [CONTRADICTED] FR-001 widens the gate so any collector with at least one of WHO/WHERE/WHAT/WHEN can enter row-edit, yet AC-5 still asserts that an operator with only WHO responsibility sees no edit affordances at all. Which behaviour is the implementer supposed to test against — the widened gat

**N40.** [CONTRADICTED] NG-002 declares editing soft-deleted rows out of scope, yet EC-003 keeps the editor open after a concurrent soft-delete and lets Save submit a patch targeting the deleted row. How is submitting field patches to a TrxOperator='D' row not editing a soft-deleted row, and what value 

**N41.** [APORIA_UNDEFINED] seed 'what the run list shows when the active-run pointer is absent or names': The text establishes no criterion for this case. REQ-002's condition (lines 13-14) only covers 'a run list in which one run is named by the active-run pointer', and its output criterion (line 16) — 'exactly one row carries the current-run m

**N42.** [APORIA_UNDERDETERMINED] seed 'what the run list shows when the active-run pointer is absent or names': The text does not divide this situation; it defines only one case. Case 1 — the pointer names a run present in the list: REQ-002 (lines 13–16) conditions on 'a run list in which one run is named by the active-run pointer' and requires that 

**N43.** [APORIA_UNDERDETERMINED] seed 'how the workbench reliably detects an in-progress dispatch from a stat': The text separates the composite into four cases it treats under different provisions. Case 1 — state readable and reporting an in-progress dispatch: REQ-023 (lines 163-168) forbids writing the staging artifact and requires a blocked-save n

**N44.** [CONTRADICTED] AC-5 asserts that an operator with only WHO responsibility sees no edit affordances when clicking a row, but FR-001 explicitly grants row-edit entry to any operator with at least one of WHO/WHERE/WHAT/WHEN. If AC-5 were used as the acceptance test, wouldn't a correct FR-001 imple

**N45.** [CONTRADICTED] FR-025(b) says Esc with no cell focused 'triggers row-level cancel per FR-012/AC-6', but FR-012 is the three-option row-switch prompt and FR-070 defines the two-option Esc-with-changes prompt. Which prompt does the operator see when pressing Esc with uncommitted changes and no fo

**N46.** [CONFLICT] When the state file is partially written or momentarily unavailable during an active dispatch, the workbench tolerates it, keeps presenting   ×  A selected run directory with a missing or unparsable state file is marked unreadable (ERR-RUN-UNREADABLE) while the rest of the run list st
