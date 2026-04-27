"""Wing collision detection — finds foreign source files stored under a wing."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_collection(palace_path: str):
    """Get ChromaDB collection. Raises ImportError if mempalace not installed."""
    from mempalace.miner import get_collection  # type: ignore[import]
    return get_collection(palace_path)


def check_wing_collision(wing: str, project_dir: Path, palace_path: str) -> list[str]:
    """
    Return list of foreign source_file paths stored under this wing, or [].

    A "foreign" path is one that neither starts with project_dir nor is a
    synthetic codegen path like "codegen/RE".
    """
    try:
        collection = _get_collection(palace_path)
    except (ImportError, Exception) as exc:
        logger.debug("[collision] MemPalace unavailable, skipping collision check: %s", exc)
        return []

    try:
        results = collection.get(
            where={"wing": {"$eq": wing}},
            limit=20,
            include=["metadatas"],
        )
    except Exception as exc:
        logger.debug("[collision] Collision check query failed: %s", exc)
        return []

    project_prefix = str(project_dir.resolve())
    foreign: list[str] = []
    seen: set[str] = set()

    for meta in results.get("metadatas") or []:
        source = (meta or {}).get("source_file", "")
        if not source:
            continue
        if source.startswith("codegen/"):
            continue
        if source.startswith(project_prefix):
            continue
        if source not in seen:
            seen.add(source)
            foreign.append(source)

    return foreign
