"""
mempalace_writer.py — MemPalace drawer write and run_outcome back-fill.
Spec 024 T-021: MemPalace run_outcome back-fill at run end.

ADR-004: MemPalace integration uses MCP tool calls, not direct Python SDK import.
Non-fatal: MemPalace unavailability is graceful degradation (writes disabled,
pipeline continues). Timeouts increment mempalace_write_failures counter.

FRs: FR-MP-006, NFR-REL-002, NFR-PERF-005
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

WRITE_TIMEOUT_SECONDS = 2.0  # NFR-PERF-005


@dataclass
class MemPalaceWriter:
    """
    Writes drawers to MemPalace and back-fills run_outcome at run end.

    run_outcome lifecycle (FR-MP-006):
      - All drawers written during a run start with run_outcome=in_progress.
      - At run end, backfill_run_outcome() updates them to passed/failed/partial.
    """
    wing: str  # Project/repo name
    run_id: str
    mempalace_disabled: bool = False
    write_failures: int = 0
    drawers_written: list[str] = field(default_factory=list)  # drawer IDs

    def write(
        self,
        room: str,
        content: str,
        phase: str,
        provenance_type: str = "agent_generated",
        embedding_model: str = "all-MiniLM-L6-v2@1.0",
        status: str = "pending",
    ) -> Optional[str]:
        """
        Write a drawer to MemPalace.

        Returns drawer_id on success, None on failure.
        Increments write_failures on timeout/error (NFR-REL-002).
        Does NOT write when run_outcome would be on GATE RETRY (FR-MP-003 — caller guard).

        Args:
            status: FR lifecycle status (FR-001, FR-002). Valid values:
                "pending", "in-progress", "delivered", "superseded",
                "auto-respecified", "flagged-respecify". Default: "pending".
        """
        if self.mempalace_disabled:
            return None

        metadata = {
            "run_id": self.run_id,
            "phase": phase,
            "run_outcome": "in_progress",
            "provenance_type": provenance_type,
            "embedding_model": embedding_model,
            "status": status,
        }

        start = time.monotonic()
        try:
            drawer_id = self._mcp_write(
                wing=self.wing,
                room=room,
                content=content,
                metadata=metadata,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            if elapsed_ms > WRITE_TIMEOUT_SECONDS * 1000:
                logger.warning(
                    "[MemPalaceWriter] Write timeout (%.0fms > %dms limit) — "
                    "drawer written but slow. run_id=%s room=%s",
                    elapsed_ms, WRITE_TIMEOUT_SECONDS * 1000, self.run_id, room,
                )
                self.write_failures += 1

            if drawer_id:
                self.drawers_written.append(drawer_id)
            return drawer_id

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.warning(
                "[MemPalaceWriter] Write failed after %.0fms: %s. "
                "run_id=%s room=%s — continuing without MemPalace write.",
                elapsed_ms, exc, self.run_id, room,
            )
            self.write_failures += 1
            return None

    def backfill_run_outcome(self, outcome: str) -> int:
        """
        Update run_outcome for all drawers written during this run.

        Args:
            outcome: "passed" | "failed" | "partial"

        Returns:
            Number of drawers successfully back-filled.
        """
        if self.mempalace_disabled or not self.drawers_written:
            return 0

        if outcome not in ("passed", "failed", "partial"):
            logger.warning(
                "[MemPalaceWriter] Invalid outcome %r — expected passed/failed/partial", outcome
            )
            return 0

        updated = 0
        for drawer_id in self.drawers_written:
            try:
                self._mcp_update_metadata(
                    drawer_id=drawer_id,
                    metadata={"run_outcome": outcome},
                )
                updated += 1
            except Exception as exc:
                logger.warning(
                    "[MemPalaceWriter] Failed to back-fill drawer %s: %s", drawer_id, exc
                )
                self.write_failures += 1

        logger.info(
            "[MemPalaceWriter] Back-filled %d/%d drawers with run_outcome=%s for run_id=%s",
            updated, len(self.drawers_written), outcome, self.run_id,
        )
        return updated

    def backfill_status(self, drawer_ids: list[str], status: str) -> int:
        """
        Update status metadata for a specific set of drawers. FR-007.

        Args:
            drawer_ids: List of drawer IDs to update.
            status: New status value (FR-002 valid set).

        Returns:
            Number of drawers successfully updated.
        """
        _VALID_STATUSES = {
            "pending", "in-progress", "delivered",
            "superseded", "auto-respecified", "flagged-respecify",
        }
        if status not in _VALID_STATUSES:
            logger.warning(
                "[MemPalaceWriter] Invalid status %r — expected one of %s",
                status, sorted(_VALID_STATUSES),
            )
            return 0

        if self.mempalace_disabled or not drawer_ids:
            return 0

        updated = 0
        for drawer_id in drawer_ids:
            try:
                self._mcp_update_metadata(
                    drawer_id=drawer_id,
                    metadata={"status": status},
                )
                updated += 1
            except Exception as exc:
                logger.warning(
                    "[MemPalaceWriter] backfill_status failed on drawer %s: %s",
                    drawer_id, exc,
                )
                self.write_failures += 1

        logger.info(
            "[MemPalaceWriter] backfill_status=%s on %d/%d drawers",
            status, updated, len(drawer_ids),
        )
        return updated

    # ------------------------------------------------------------------
    # MCP integration stubs (ADR-004)
    # These call MemPalace MCP tools. Real MCP calls are made via the
    # MCP client when available; when unavailable, raise an exception
    # which is caught by write() and backfill_run_outcome() above.
    # ------------------------------------------------------------------

    def _get_collection(self):
        """Get or create the MemPalace ChromaDB collection."""
        from mempalace.miner import get_collection  # type: ignore[import]
        from mempalace.config import MempalaceConfig  # type: ignore[import]
        palace_path = MempalaceConfig().palace_path
        return get_collection(palace_path), palace_path

    def _mcp_write(
        self,
        wing: str,
        room: str,
        content: str,
        metadata: dict,
    ) -> Optional[str]:
        """
        Write a drawer to MemPalace via the miner.add_drawer() API.
        Returns drawer_id or None.
        """
        try:
            import hashlib
            from mempalace.miner import add_drawer  # type: ignore[import]
            collection, _ = self._get_collection()

            # add_drawer generates drawer_id from source_file + chunk_index
            source_file = f"codegen/{metadata.get('phase', 'unknown')}"
            chunk_index = hash(self.run_id) & 0xFFFF
            ok = add_drawer(
                collection=collection,
                wing=wing,
                room=room,
                content=content,
                source_file=source_file,
                chunk_index=chunk_index,
                agent="codegen",
            )
            if ok:
                drawer_id = (
                    f"drawer_{wing}_{room}_"
                    f"{hashlib.md5((source_file + str(chunk_index)).encode()).hexdigest()[:16]}"
                )
                # Store codegen-specific metadata via collection.update()
                try:
                    collection.update(ids=[drawer_id], metadatas=[metadata])
                except Exception:
                    pass
                return drawer_id
            return None
        except ImportError:
            logger.debug("[MemPalaceWriter] mempalace not installed; skipping write")
            return None

    def _mcp_update_metadata(self, drawer_id: str, metadata: dict) -> None:
        """Update metadata on an existing drawer via ChromaDB collection.update()."""
        try:
            collection, _ = self._get_collection()
            collection.update(ids=[drawer_id], metadatas=[metadata])
        except ImportError:
            pass  # Not installed — back-fill is a no-op
