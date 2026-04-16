"""
repair.py — Memory store repair utility.
Spec 024 T-035: `codegen memory repair --store <epmem|smem>` subcommand.

Repair procedure:
  1. Attempt WAL replay by opening a SQLite connection.
  2. Run PRAGMA integrity_check.
  3. If passes: report ok.
  4. If fails: restore from .bak backup and report restoration.

FRs: NFR-MIG-007, NFR-REL-005, NFR-REL-006
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path


def repair_store(db_path: Path, store_name: str) -> tuple[bool, str]:
    """
    Attempt to repair a SOAR EPMEM or SMEM SQLite database.

    Args:
        db_path: Path to the SQLite database file.
        store_name: "epmem" or "smem" (used in messages only).

    Returns:
        (ok: bool, message: str)
          ok=True  → store is healthy or was restored from backup.
          ok=False → store is corrupt and no backup is available.
    """
    db_path = Path(db_path)
    bak_path = Path(str(db_path) + ".bak")

    if not db_path.exists():
        return False, (
            f"[memory repair] ERROR: {store_name} database not found at {db_path}. "
            f"Run a codegen pipeline first to create the database."
        )

    # Step 1+2: WAL replay + integrity check
    try:
        with sqlite3.connect(str(db_path)) as conn:
            # Opening the connection triggers WAL recovery automatically
            result = conn.execute("PRAGMA integrity_check").fetchone()
            integrity = result[0] if result else "unknown"
    except sqlite3.DatabaseError as exc:
        integrity = f"error: {exc}"

    if integrity == "ok":
        return True, (
            f"[memory repair] {store_name} integrity check: ok. No repair needed.\n"
            f"  Path: {db_path}"
        )

    # Step 3: Corrupt — try to restore from .bak
    if not bak_path.exists():
        return False, (
            f"[memory repair] ERROR: {store_name} database is corrupt "
            f"(integrity_check={integrity!r}) and no backup found at {bak_path}.\n"
            f"  Manual intervention required. Do NOT delete {db_path} — preserve for forensics.\n"
            f"  Run `codegen run` again to create a fresh database."
        )

    # Restore from backup
    try:
        # Verify backup integrity first
        with sqlite3.connect(str(bak_path)) as bak_conn:
            bak_result = bak_conn.execute("PRAGMA integrity_check").fetchone()
            bak_integrity = bak_result[0] if bak_result else "unknown"

        if bak_integrity != "ok":
            return False, (
                f"[memory repair] ERROR: {store_name} backup is also corrupt "
                f"(integrity_check={bak_integrity!r}). Cannot restore.\n"
                f"  Path: {bak_path}\n"
                f"  Manual intervention required."
            )

        shutil.copy2(str(bak_path), str(db_path))
        return True, (
            f"[memory repair] {store_name} restored from backup.\n"
            f"  Backup: {bak_path}\n"
            f"  Restored to: {db_path}\n"
            f"  Original integrity_check was: {integrity!r}"
        )

    except OSError as exc:
        return False, (
            f"[memory repair] ERROR: failed to restore {store_name} from backup: {exc}\n"
            f"  Backup: {bak_path}\n"
            f"  Target: {db_path}"
        )
