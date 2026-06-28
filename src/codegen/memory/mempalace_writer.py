"""
mempalace_writer.py — MemPalace drawer write and run_outcome back-fill.

ADR-004 (revised): Uses direct Python mempalace SDK imports, not MCP calls.
Non-fatal: MemPalace unavailability is graceful degradation.

FRs: FR-MP-006, NFR-REL-002, NFR-PERF-005
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from codegen.memory.context import MemPalaceContext

logger = logging.getLogger(__name__)

WRITE_TIMEOUT_SECONDS = 2.0

try:
    from mempalace.miner import add_drawer  # type: ignore[import]
except ImportError:
    add_drawer = None  # type: ignore[assignment]


class MemPalaceWriter:
    """
    Writes drawers to MemPalace and back-fills run_outcome at run end.

    run_outcome lifecycle (FR-MP-006):
      - All drawers written during a run start with run_outcome=in_progress.
      - At run end, backfill_run_outcome() updates them to passed/failed/partial.
    """

    def __init__(self, ctx: "MemPalaceContext") -> None:
        self.ctx = ctx
        self.mempalace_disabled: bool = False
        self.write_failures: int = 0
        self.drawers_written: list[str] = []

    def write(
        self,
        room: str,
        content: str,
        phase: str,
        provenance_type: str = "agent_generated",
        embedding_model: str = "all-MiniLM-L6-v2@1.0",
        status: str = "pending",
        source_file: Optional[str] = None,
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[str]:
        """Write a drawer. Returns drawer_id on success, None on failure."""
        if self.mempalace_disabled:
            return None

        metadata = {
            "run_id": self.ctx.run_id,
            "phase": phase,
            "run_outcome": "in_progress",
            "provenance_type": provenance_type,
            "embedding_model": embedding_model,
            "status": status,
            "source_file": source_file,
        }
        if extra_metadata:
            metadata.update(extra_metadata)

        start = time.monotonic()
        try:
            drawer_id = self._write_drawer(
                wing=self.ctx.wing,
                room=room,
                content=content,
                metadata=metadata,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            if elapsed_ms > WRITE_TIMEOUT_SECONDS * 1000:
                logger.warning(
                    "[MemPalaceWriter] Write timeout (%.0fms > %dms). run_id=%s room=%s",
                    elapsed_ms, WRITE_TIMEOUT_SECONDS * 1000, self.ctx.run_id, room,
                )
                self.write_failures += 1
            if drawer_id:
                self.drawers_written.append(drawer_id)
            return drawer_id
        except ImportError:
            # mempalace not installed — graceful degradation, not a failure
            return None
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.warning(
                "[MemPalaceWriter] Write failed after %.0fms: %s. run_id=%s room=%s",
                elapsed_ms, exc, self.ctx.run_id, room,
            )
            self.write_failures += 1
            return None

    def backfill_run_outcome(self, outcome: str) -> int:
        """Update run_outcome for all drawers written during this run."""
        if self.mempalace_disabled or not self.drawers_written:
            return 0
        if outcome not in ("passed", "failed", "partial"):
            logger.warning("[MemPalaceWriter] Invalid outcome %r — expected passed/failed/partial", outcome)
            return 0

        updated = 0
        for drawer_id in self.drawers_written:
            try:
                self._update_drawer_metadata(drawer_id, {"run_outcome": outcome})
                updated += 1
            except Exception as exc:
                logger.warning("[MemPalaceWriter] backfill failed on %s: %s", drawer_id, exc)
                self.write_failures += 1

        logger.info(
            "[MemPalaceWriter] Back-filled %d/%d drawers run_outcome=%s run_id=%s",
            updated, len(self.drawers_written), outcome, self.ctx.run_id,
        )
        return updated

    def backfill_status(self, drawer_ids: list[str], status: str) -> int:
        """Update status metadata for a specific set of drawers. FR-007."""
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
                self._update_drawer_metadata(drawer_id, {"status": status})
                updated += 1
            except Exception as exc:
                logger.warning("[MemPalaceWriter] backfill_status failed on %s: %s", drawer_id, exc)
                self.write_failures += 1

        logger.info(
            "[MemPalaceWriter] backfill_status=%s on %d/%d drawers",
            status, updated, len(drawer_ids),
        )
        return updated

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_collection(self):
        """Get the MemPalace ChromaDB collection."""
        from mempalace.miner import get_collection  # type: ignore[import]
        return get_collection(self.ctx.palace_path)

    def _write_drawer(
        self,
        wing: str,
        room: str,
        content: str,
        metadata: dict,
    ) -> Optional[str]:
        """
        Write one drawer. Returns drawer_id using same SHA256[:24] formula as add_drawer.

        The drawer_id is deterministic: same wing+room+phase+run_id always
        produces the same ID, enabling correct collection.update() and backfill.
        """
        if add_drawer is None:
            logger.debug("[MemPalaceWriter] mempalace not installed; skipping write")
            return None

        collection = self._get_collection()
        source_file = metadata.get("source_file") or f"codegen/{metadata.get('phase', 'unknown')}"
        chunk_index = int(hashlib.sha256(self.ctx.run_id.encode()).hexdigest(), 16) & 0xFFFF

        ok = add_drawer(
            collection=collection,
            wing=wing,
            room=room,
            content=content,
            source_file=source_file,
            chunk_index=chunk_index,
            agent="codegen",
        )
        if not ok:
            return None

        # Reconstruct drawer_id using same SHA256[:24] formula as add_drawer
        drawer_id = (
            f"drawer_{wing}_{room}_"
            f"{hashlib.sha256((source_file + str(chunk_index)).encode()).hexdigest()[:24]}"
        )
        # Strip source_file from the metadata update — add_drawer already stores it natively.
        # Also filter out None values to avoid ChromaDB type errors.
        update_metadata = {k: v for k, v in metadata.items() if k != "source_file" and v is not None}
        try:
            collection.update(ids=[drawer_id], metadatas=[update_metadata])
        except Exception as exc:
            logger.debug("[MemPalaceWriter] metadata update failed for %s: %s", drawer_id, exc)
        return drawer_id

    def _update_drawer_metadata(self, drawer_id: str, metadata: dict) -> None:
        """Update metadata on an existing drawer."""
        try:
            collection = self._get_collection()
            collection.update(ids=[drawer_id], metadatas=[metadata])
        except ImportError:
            pass
