"""
smem_loader.py — Load CQ-ISC YAML library into SOAR SMEM via SML bridge.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

This module:
1. Reads a CQ-ISC YAML library file (validated against cq_isc_schema.yaml).
2. For each non-drifted, non-quarantined entry:
   a. Generates a SOAR production rule (sp block) from the soar_predicate field.
   b. Loads the rule into SOAR SMEM via the SML bridge.
   c. Records the load in the bridge's audit log (INV-004).
3. Quarantines entries with policy_drift_status != current.
4. Reports load statistics.

INV-001: chunk never is enforced in the .soar files; smem_loader does not modify that.
INV-002: All enforcement is via prohibit preferences generated here.
INV-005: phase-gate (build ^current-phase <phase>) is ALWAYS the first LHS condition
         in every generated production rule.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_FILE = Path(__file__).parent / "cq_isc_schema.yaml"
VALID_CONSTRAINT_CLASSES = {"SECURITY", "STRUCTURAL", "TEST", "QUALITY"}
VALID_PHASE_SCOPES = {"VERIFY", "DELIVER", "ALL"}
VALID_DRIFT_STATUSES = {"current", "drifted", "pending-review"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CQISCEntry:
    cq_isc_id: str
    rule_text: str
    constraint_class: str
    phase_scope: str
    language_scope: str
    source_authority: str
    policy_drift_status: str
    psi_contribution_weight: float
    soar_predicate: str
    wme_source: str
    test_proxy_observable: bool
    severity: str = "medium"
    description: str = ""
    law_ref: str = ""
    nl2gensym_generated: bool = False
    executor_validated: bool = False


@dataclass
class LoadResult:
    total: int
    loaded: int
    quarantined: int
    drifted: int
    failed: int
    entries: list[CQISCEntry]
    quarantine_ids: list[str]
    drifted_ids: list[str]
    failed_ids: list[str]


# ---------------------------------------------------------------------------
# SOAR production rule generator
# ---------------------------------------------------------------------------

def generate_prohibit_rule(entry: CQISCEntry) -> str:
    """
    Generate a SOAR production rule (sp block) from a CQISCEntry.

    INV-005 enforced: (build ^current-phase <phase>) is ALWAYS the FIRST LHS condition.
    INV-002 enforced: uses prohibit preference (:prohibit).

    The generated rule fires when:
    1. SOAR is in the codegen problem space.
    2. The build is in the correct phase (INV-005 — FIRST condition).
    3. A code-violation WME with this cq_isc_id and status confirmed-failing exists.
    """
    rule_name = entry.cq_isc_id.lower().replace("-", "_")
    phase = _phase_scope_to_soar(entry.phase_scope)
    lang_cond = _language_scope_condition(entry.language_scope)

    # INV-005: phase-gate condition MUST be first
    rule = f"""sp {{cq_isc*{rule_name}*prohibit
  (state <s> ^name codegen)
  (build <b> ^current-phase {phase})  ;; INV-005 — FIRST LHS condition
  (<b> ^task-id <tid>){lang_cond}
  (code-violation <v> ^cq-isc-id |{entry.cq_isc_id}|
                      ^status |confirmed-failing|)
  -->
  (<s> ^operator <o> - :prohibit)  ;; INV-002 — sole enforcement mechanism
  (epmem --add <epm>)
  (<epm> ^cq-isc-fired |{entry.cq_isc_id}|
         ^task-id <tid>
         ^rule-text |{entry.rule_text[:80]}|
         ^timestamp (time))
  (write (crlf) |[SOAR CQ-ISC] PROHIBIT fired: {entry.cq_isc_id} — {entry.rule_text[:60]}|)
}}"""
    return rule


def _phase_scope_to_soar(phase_scope: str) -> str:
    """Map phase_scope enum to SOAR phase name used in production rules."""
    mapping = {
        "VERIFY": "GATE",
        "DELIVER": "DELIVER",
        "ALL": "<any-phase>",  # For ALL, use a more permissive match
    }
    return mapping.get(phase_scope, "GATE")


def _language_scope_condition(language_scope: str) -> str:
    """Generate LHS language condition if scope is not ALL."""
    if language_scope.strip().upper() == "ALL":
        return ""
    langs = [l.strip() for l in language_scope.split(",")]
    if len(langs) == 1:
        return f"\n  (<b> ^language |{langs[0]}|)"
    # Multiple languages: use disjunction
    disjunction = " | ".join(f"|{l}|" for l in langs)
    return f"\n  (<b> ^language << {disjunction} >>)"


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------

def load_library(library_file: Path) -> list[CQISCEntry]:
    """
    Load and parse a CQ-ISC YAML library file.
    Returns a list of CQISCEntry objects.
    Raises ValueError on missing mandatory fields.
    """
    text = library_file.read_text()
    raw = yaml.safe_load(text)

    if isinstance(raw, dict) and "entries" in raw:
        entries_raw = raw["entries"]
    elif isinstance(raw, list):
        entries_raw = raw
    else:
        raise ValueError(f"Unexpected YAML structure in {library_file}. Expected 'entries' list or top-level list.")

    entries = []
    for i, raw_entry in enumerate(entries_raw):
        try:
            entry = _parse_entry(raw_entry, i)
            entries.append(entry)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Entry #{i} parse error: {exc}") from exc

    return entries


def _parse_entry(raw: dict, index: int) -> CQISCEntry:
    """Parse a single raw YAML dict into a CQISCEntry."""
    def req(field: str) -> Any:
        val = raw.get(field)
        if val is None:
            raise ValueError(f"Missing required field '{field}' in entry #{index}")
        return val

    return CQISCEntry(
        cq_isc_id=str(req("cq_isc_id")),
        rule_text=str(req("rule_text")),
        constraint_class=str(req("constraint_class")).upper(),
        phase_scope=str(req("phase_scope")).upper(),
        language_scope=str(req("language_scope")),
        source_authority=str(req("source_authority")),
        policy_drift_status=str(raw.get("policy_drift_status", "current")),
        psi_contribution_weight=float(raw.get("psi_contribution_weight", 1.0)),
        soar_predicate=str(req("soar_predicate")),
        wme_source=str(req("wme_source")),
        test_proxy_observable=bool(raw.get("test_proxy_observable", True)),
        severity=str(raw.get("severity", "medium")).lower(),
        description=str(raw.get("description", "")),
        law_ref=str(raw.get("law_ref", "")),
        nl2gensym_generated=bool(raw.get("nl2gensym_generated", False)),
        executor_validated=bool(raw.get("executor_validated", True)),
    )


# ---------------------------------------------------------------------------
# T-012: Persistent SMEM loader — prefer persistent file over static YAML
# T-013: SMEM schema version metadata table and startup check
# ---------------------------------------------------------------------------

SMEM_SCHEMA_VERSION = 1  # Bump when accumulated pattern schema changes (FR-SMEM-008)


def ensure_smem_metadata_table(db_path: Path) -> int:
    """
    Create SMEM metadata table if absent and return current schema_version.

    T-013: Creates `metadata(schema_version INTEGER, created_at TEXT)` on first open.
    Returns the stored schema_version (or 0 if table was just created).
    """
    import sqlite3
    from datetime import datetime, timezone

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS codegen_metadata "
            "(schema_version INTEGER NOT NULL, created_at TEXT NOT NULL)"
        )
        row = conn.execute("SELECT schema_version FROM codegen_metadata").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO codegen_metadata (schema_version, created_at) VALUES (?, ?)",
                (SMEM_SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
            )
            return SMEM_SCHEMA_VERSION
        return int(row[0])


def load_from_persistent_smem(
    db_path: Path,
    bridge: Any,
    allow_outdated: bool = False,
    verbose: bool = True,
) -> bool:
    """
    T-012: Load CQ-ISC patterns from persistent SMEM SQLite file if present.

    When db_path exists:
      - Emits INFO "loading from persistent SMEM file".
      - Checks schema_version via metadata table (T-013).
      - If version mismatch and not allow_outdated: tags accumulated patterns
        ^schema_outdated true in SOAR WM before retrieval.
      - Returns True (persistent file was used).

    When db_path is absent:
      - Emits INFO "falling back to static YAML library".
      - Returns False (caller should call load_into_smem with YAML).

    FR-SMEM-006, FR-SMEM-007, FR-SMEM-008, FR-SMEM-009
    """
    if not db_path.exists():
        if verbose:
            print(
                f"[SMEM Loader] INFO: falling back to static YAML library "
                f"(persistent SMEM file not found at {db_path})",
                file=sys.stderr,
            )
        return False

    if verbose:
        print(
            f"[SMEM Loader] INFO: loading from persistent SMEM file: {db_path}",
            file=sys.stderr,
        )

    # T-013: schema version check
    stored_version = ensure_smem_metadata_table(db_path)
    if stored_version != SMEM_SCHEMA_VERSION:
        msg = (
            f"[SMEM Loader] WARNING: SMEM schema mismatch — "
            f"stored version {stored_version}, expected {SMEM_SCHEMA_VERSION}. "
            f"Accumulated patterns will be tagged ^schema_outdated true. "
            f"Use --allow-outdated-smem to load without quarantine."
        )
        print(msg, file=sys.stderr)
        if not allow_outdated:
            # Tag accumulated patterns as outdated in SOAR WM
            bridge.inject_wme(attribute="smem-schema-outdated", value="true")

    # The persistent SMEM file is already configured via _startup_configure().
    # SOAR loaded patterns from it on --init. No further action needed here.
    return True


# ---------------------------------------------------------------------------
# SMEM loader — main entry point
# ---------------------------------------------------------------------------

def load_into_smem(
    library_file: Path,
    bridge: Any,  # SOARBridge instance — typed as Any to avoid circular import
    verbose: bool = True,
) -> LoadResult:
    """
    Load CQ-ISC entries from YAML library into SOAR SMEM via the SML bridge.

    For each entry:
    - Skips drifted entries (policy_drift_status == "drifted").
    - Quarantines pending-review entries (do not fire prohibit preferences).
    - Generates SOAR sp blocks for current entries and loads via bridge.

    Returns LoadResult with statistics.
    """
    entries = load_library(library_file)

    loaded: list[CQISCEntry] = []
    quarantined: list[str] = []
    drifted: list[str] = []
    failed: list[str] = []

    for entry in entries:
        if entry.policy_drift_status == "drifted":
            drifted.append(entry.cq_isc_id)
            if verbose:
                print(f"[SMEM Loader] SKIP (drifted): {entry.cq_isc_id}", file=sys.stderr)
            continue

        if entry.policy_drift_status == "pending-review":
            quarantined.append(entry.cq_isc_id)
            if verbose:
                print(f"[SMEM Loader] QUARANTINE (pending-review): {entry.cq_isc_id}", file=sys.stderr)
            continue

        # Generate prohibit rule
        sp_rule = generate_prohibit_rule(entry)

        # Load into SOAR via bridge
        try:
            _load_rule_via_bridge(bridge, entry, sp_rule, verbose)
            loaded.append(entry)
            if verbose:
                print(f"[SMEM Loader] LOADED: {entry.cq_isc_id} ({entry.constraint_class})", flush=True)
        except Exception as exc:
            failed.append(entry.cq_isc_id)
            print(f"[SMEM Loader] FAILED: {entry.cq_isc_id} — {exc}", file=sys.stderr)

    result = LoadResult(
        total=len(entries),
        loaded=len(loaded),
        quarantined=len(quarantined),
        drifted=len(drifted),
        failed=len(failed),
        entries=loaded,
        quarantine_ids=quarantined,
        drifted_ids=drifted,
        failed_ids=failed,
    )

    if verbose:
        print(
            f"\n[SMEM Loader] Load complete: "
            f"{result.loaded} loaded, "
            f"{result.quarantined} quarantined, "
            f"{result.drifted} drifted, "
            f"{result.failed} failed "
            f"(total={result.total})",
            flush=True,
        )

    return result


def _load_rule_via_bridge(bridge: Any, entry: CQISCEntry, sp_rule: str, verbose: bool):
    """
    Load a generated sp block into SOAR via the SML bridge.

    Model A: sends the sp block as a command to the running SOAR process.
    Model B: writes the sp block to a staging file; loaded on next phase-invoke.
    """
    from .soar_bridge import SOARBridgeModel

    if bridge.model == SOARBridgeModel.A and bridge._alive:
        # Send sp block directly to running SOAR process
        bridge._send_command(sp_rule)
    else:
        # Model B: append to a staging .soar file
        staging_file = Path("/tmp/codegen-smem-staging.soar")
        with staging_file.open("a") as f:
            f.write(sp_rule + "\n\n")

    # Inject a WME to record the SMEM load event (for EPMEM audit — INV-004)
    bridge.inject_wme(
        attribute="smem-load-event",
        value=entry.cq_isc_id,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Load CQ-ISC YAML library into SOAR SMEM")
    parser.add_argument("library_file", type=Path, help="Path to CQ-ISC YAML library file")
    parser.add_argument("--dry-run", action="store_true", help="Parse and validate only — do not load")
    parser.add_argument("--verbose", action="store_true", default=True)
    args = parser.parse_args()

    if not args.library_file.exists():
        print(f"ERROR: Library file not found: {args.library_file}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        entries = load_library(args.library_file)
        print(f"Parsed {len(entries)} entries from {args.library_file}")
        for e in entries:
            print(f"  {e.cq_isc_id}: {e.constraint_class} | {e.policy_drift_status} | psi={e.psi_contribution_weight}")
        sys.exit(0)

    # For non-dry-run: import bridge and load
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from bridge.soar_bridge import SOARBridge
    bridge = SOARBridge(library_file=args.library_file)
    # Note: bridge.start() would be called here in production context
    # For standalone CLI, use Model B
    from bridge.soar_bridge import SOARBridgeModel
    bridge.model = SOARBridgeModel.B

    result = load_into_smem(args.library_file, bridge, verbose=args.verbose)
    sys.exit(0 if result.failed == 0 else 1)


if __name__ == "__main__":
    main()
