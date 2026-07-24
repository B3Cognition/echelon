"""
mempalace_writer.py — MemPalace drawer write and run_outcome back-fill.

ADR-004 (revised): Uses direct Python mempalace SDK imports, not MCP calls.
Non-fatal: MemPalace unavailability is graceful degradation.

FRs: FR-MP-006, NFR-REL-002, NFR-PERF-005
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from codegen.memory.context import MemPalaceContext

logger = logging.getLogger(__name__)

WRITE_TIMEOUT_SECONDS = 2.0
_SHA256_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")

try:
    from mempalace.miner import add_drawer  # type: ignore[import]
except ImportError:
    add_drawer = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ExactDrawerWriteResult:
    """Bounded result for an identity-checked deterministic drawer write."""

    outcome: str
    drawer_id: str | None


def deterministic_requirement_drawer_id(
    *,
    wing: str,
    room: str,
    spec_sha256: str,
    requirement_id: str,
    content: str,
) -> str:
    """Derive one path/run-independent ID from canonical requirement identity."""
    if (
        type(wing) is not str
        or not wing
        or len(wing) > 256
        or type(room) is not str
        or not room
        or len(room) > 256
        or type(requirement_id) is not str
        or not requirement_id
        or len(requirement_id) > 512
        or type(content) is not str
        or type(spec_sha256) is not str
        or _SHA256_PATTERN.fullmatch(spec_sha256) is None
        or any(
            character in value
            for value in (wing, room)
            for character in ("/", "\\", "\x00", "\n", "\r")
        )
    ):
        raise ValueError("invalid deterministic drawer identity")
    content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    identity = json.dumps(
        {
            "schema_version": 1,
            "wing": wing,
            "room": room,
            "canonical_spec_sha256": spec_sha256,
            "requirement_id": requirement_id,
            "requirement_content_sha256": content_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return (
        f"drawer_{wing}_{room}_"
        f"{hashlib.sha256(identity).hexdigest()}"
    )


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

    def write_exact(
        self,
        *,
        room: str,
        content: str,
        phase: str,
        drawer_id: str,
        spec_sha256: str,
        requirement_id: str,
        provenance_type: str = "requirements_mine",
        embedding_model: str = "all-MiniLM-L6-v2@1.0",
        status: str = "pending",
        source_file: Optional[str] = None,
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> ExactDrawerWriteResult:
        """Write or adopt only one exact deterministic requirement drawer."""
        try:
            expected_id = deterministic_requirement_drawer_id(
                wing=self.ctx.wing,
                room=room,
                spec_sha256=spec_sha256,
                requirement_id=requirement_id,
                content=content,
            )
        except (UnicodeError, ValueError):
            self.write_failures += 1
            return ExactDrawerWriteResult("failed", None)
        if (
            type(drawer_id) is not str
            or drawer_id != expected_id
            or len(drawer_id) > 1_024
            or type(phase) is not str
            or not phase
        ):
            self.write_failures += 1
            return ExactDrawerWriteResult("failed", None)
        if add_drawer is None:
            return ExactDrawerWriteResult("unavailable", None)

        content_sha256 = hashlib.sha256(
            content.encode("utf-8")
        ).hexdigest()
        stable_metadata: dict[str, object] = {
            "deterministic_identity_schema_version": 1,
            "wing": self.ctx.wing,
            "room": room,
            "scope": "canonical",
            "canonical": True,
            "artifact_hash": f"sha256:{spec_sha256}",
            "canonical_spec_sha256": spec_sha256,
            "requirement_id": requirement_id,
            "requirement_content_sha256": content_sha256,
        }
        metadata: dict[str, object] = {
            "wing": self.ctx.wing,
            "room": room,
            "run_id": self.ctx.run_id,
            "phase": phase,
            "run_outcome": "in_progress",
            "provenance_type": provenance_type,
            "embedding_model": embedding_model,
            "status": status,
            "added_by": "codegen",
            **stable_metadata,
        }
        if source_file is not None:
            metadata["source_file"] = source_file
        if extra_metadata:
            metadata.update(
                {
                    key: value
                    for key, value in extra_metadata.items()
                    if value is not None
                }
            )
        metadata.update(stable_metadata)

        def readback(collection: object) -> str:
            observed = collection.get(  # type: ignore[attr-defined]
                ids=[drawer_id],
                include=["documents", "metadatas"],
            )
            if type(observed) is not dict:
                return "drift"
            ids = observed.get("ids")
            documents = observed.get("documents")
            metadatas = observed.get("metadatas")
            if ids == [] and documents == [] and metadatas == []:
                return "missing"
            if (
                type(ids) is not list
                or type(documents) is not list
                or type(metadatas) is not list
                or ids != [drawer_id]
                or documents != [content]
                or len(metadatas) != 1
                or type(metadatas[0]) is not dict
                or any(
                    metadatas[0].get(key) != value
                    for key, value in stable_metadata.items()
                )
            ):
                return "drift"
            return "exact"

        try:
            collection = self._get_collection()
            state = readback(collection)
            if state == "exact":
                return ExactDrawerWriteResult(
                    "already_present",
                    drawer_id,
                )
            if state != "missing":
                self.write_failures += 1
                return ExactDrawerWriteResult("drift", None)
            try:
                collection.add(  # type: ignore[attr-defined]
                    documents=[content],
                    ids=[drawer_id],
                    metadatas=[metadata],
                )
            except Exception:
                raced_state = readback(collection)
                if raced_state == "exact":
                    return ExactDrawerWriteResult(
                        "already_present",
                        drawer_id,
                    )
                if raced_state != "missing":
                    self.write_failures += 1
                    return ExactDrawerWriteResult("drift", None)
                raise
            if readback(collection) != "exact":
                self.write_failures += 1
                return ExactDrawerWriteResult("failed", None)
            self.drawers_written.append(drawer_id)
            return ExactDrawerWriteResult("written", drawer_id)
        except ImportError:
            return ExactDrawerWriteResult("unavailable", None)
        except Exception:
            self.write_failures += 1
            return ExactDrawerWriteResult("failed", None)

    def verify_exact(
        self,
        *,
        room: str,
        content: str,
        drawer_id: str,
        spec_sha256: str,
        requirement_id: str,
    ) -> ExactDrawerWriteResult:
        """Read back an exact deterministic drawer without ever writing."""
        try:
            expected_id = deterministic_requirement_drawer_id(
                wing=self.ctx.wing,
                room=room,
                spec_sha256=spec_sha256,
                requirement_id=requirement_id,
                content=content,
            )
        except (UnicodeError, ValueError):
            return ExactDrawerWriteResult("failed", None)
        if type(drawer_id) is not str or drawer_id != expected_id:
            return ExactDrawerWriteResult("failed", None)
        if add_drawer is None:
            return ExactDrawerWriteResult("unavailable", None)
        content_sha256 = hashlib.sha256(
            content.encode("utf-8")
        ).hexdigest()
        stable_metadata = {
            "deterministic_identity_schema_version": 1,
            "wing": self.ctx.wing,
            "room": room,
            "scope": "canonical",
            "canonical": True,
            "artifact_hash": f"sha256:{spec_sha256}",
            "canonical_spec_sha256": spec_sha256,
            "requirement_id": requirement_id,
            "requirement_content_sha256": content_sha256,
        }
        try:
            collection = self._get_collection()
            observed = collection.get(
                ids=[drawer_id],
                include=["documents", "metadatas"],
            )
            if (
                type(observed) is not dict
                or observed.get("ids") != [drawer_id]
                or observed.get("documents") != [content]
                or type(observed.get("metadatas")) is not list
                or len(observed["metadatas"]) != 1
                or type(observed["metadatas"][0]) is not dict
                or any(
                    observed["metadatas"][0].get(key) != value
                    for key, value in stable_metadata.items()
                )
            ):
                return ExactDrawerWriteResult("drift", None)
            return ExactDrawerWriteResult(
                "already_present",
                drawer_id,
            )
        except ImportError:
            return ExactDrawerWriteResult("unavailable", None)
        except Exception:
            return ExactDrawerWriteResult("failed", None)

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
