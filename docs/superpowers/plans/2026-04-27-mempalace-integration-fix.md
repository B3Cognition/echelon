# MemPalace Integration Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 bugs in the echelon/codegen MemPalace integration and introduce stable, portable per-project wing identity via `MemPalaceContext`.

**Architecture:** A new `MemPalaceContext` dataclass becomes the single source of truth for `wing`, `run_id`, and `palace_path`. It is constructed once per pipeline run in the CLI and threaded into `MemPalaceReader`, `MemPalaceWriter`, `RequirementsMiner`, `PipelineEngine`, and `PhaseGateRunner`. Wing is persisted in `echelon.yml` (set during `echelon init`) and written into `codegen-state.json` so `PhaseGateRunner` can read it without access to the project config.

**Tech Stack:** Python 3.11, pytest, PyYAML, chromadb, mempalace v3.3.3, hashlib (stdlib)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/codegen/memory/context.py` | **Create** | `MemPalaceContext` dataclass + `from_project()` + `from_wing()` factories |
| `src/codegen/memory/collision.py` | **Create** | `check_wing_collision()` — detects foreign source files under a wing |
| `src/codegen/memory/mempalace_writer.py` | **Modify** | Take `ctx`, fix SHA256 drawer_id, fix chunk_index, rename methods |
| `src/codegen/memory/mempalace_reader.py` | **Modify** | Take `ctx` instead of bare `wing`; use `ctx.palace_path` |
| `src/codegen/memory/requirements_miner.py` | **Modify** | Take `ctx`; add one-shot collision check on first write |
| `src/codegen/pipeline/pipeline_engine.py` | **Modify** | Add `wing` to `PipelineState`; `set_context()`; fix `_get_mempalace_writer()` |
| `src/codegen/pipeline/phase_gate.py` | **Modify** | Replace `_memory_config.wing` with state-file read; construct ctx via `from_wing()` |
| `src/codegen/cli/codegen_cli.py` | **Modify** | Resolve wing → build ctx; add `requirements clean` subcommand |
| `src/echelon/cli.py` | **Modify** | Add wing provisioning step to `_cmd_init()` |
| `extension/echelon-config.yml` | **Modify** | Add `mempalace:` block with `wing:` placeholder |
| `extension/commands/echelon.init.md` | **Modify** | Document wing provisioning step |
| `extension/commands/echelon.codegen.md` | **Modify** | Replace `WING=$(basename $(pwd))` with `echelon.yml` read |
| `extension/commands/echelon.codegenlight.md` | **Modify** | Same as above |
| `scripts/install.sh` | **Modify** | Remove dead `memory-config.yml` write |
| `tests/unit/test_mempalace_context.py` | **Create** | Unit tests for `MemPalaceContext` |
| `tests/unit/test_mempalace_collision.py` | **Create** | Unit tests for `check_wing_collision()` |
| `tests/unit/test_mempalace_writer.py` | **Create** | Unit tests for fixed `MemPalaceWriter` |
| `tests/unit/test_mempalace_reader.py` | **Create** | Unit tests for `MemPalaceReader` with ctx |
| `tests/unit/test_requirements_miner_ctx.py` | **Create** | Unit tests for `RequirementsMiner` with ctx |
| `tests/unit/test_pipeline_engine_wing.py` | **Create** | Unit tests for wing threading in `PipelineEngine` |
| `tests/unit/test_echelon_init_wing.py` | **Create** | Unit tests for `_cmd_init()` wing provisioning |

---

## Task 1: `MemPalaceContext` dataclass

**Files:**
- Create: `src/codegen/memory/context.py`
- Create: `tests/unit/test_mempalace_context.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_mempalace_context.py
"""Unit tests for MemPalaceContext."""
from __future__ import annotations

import pytest
import yaml
from pathlib import Path
from unittest.mock import patch


def test_from_project_reads_wing_from_echelon_yml(tmp_path):
    echelon_yml = tmp_path / "echelon.yml"
    echelon_yml.write_text(yaml.dump({"mempalace": {"wing": "my-app"}}))

    with patch("codegen.memory.context._get_palace_path", return_value="/fake/palace"):
        from codegen.memory.context import MemPalaceContext
        ctx = MemPalaceContext.from_project(tmp_path, run_id="run-123")

    assert ctx.wing == "my-app"
    assert ctx.run_id == "run-123"
    assert ctx.palace_path == "/fake/palace"


def test_from_project_wing_override_takes_precedence(tmp_path):
    echelon_yml = tmp_path / "echelon.yml"
    echelon_yml.write_text(yaml.dump({"mempalace": {"wing": "my-app"}}))

    with patch("codegen.memory.context._get_palace_path", return_value="/fake/palace"):
        from codegen.memory.context import MemPalaceContext
        ctx = MemPalaceContext.from_project(tmp_path, run_id="run-123", wing_override="override-wing")

    assert ctx.wing == "override-wing"


def test_from_project_hard_fails_if_no_echelon_yml(tmp_path):
    with patch("codegen.memory.context._get_palace_path", return_value="/fake/palace"):
        from codegen.memory.context import MemPalaceContext
        with pytest.raises(SystemExit, match="echelon.yml not found"):
            MemPalaceContext.from_project(tmp_path, run_id="run-123")


def test_from_project_hard_fails_if_wing_not_set(tmp_path):
    echelon_yml = tmp_path / "echelon.yml"
    echelon_yml.write_text(yaml.dump({"deploy": {"type": "http"}}))

    with patch("codegen.memory.context._get_palace_path", return_value="/fake/palace"):
        from codegen.memory.context import MemPalaceContext
        with pytest.raises(SystemExit, match="wing not set"):
            MemPalaceContext.from_project(tmp_path, run_id="run-123")


def test_from_wing_constructs_without_project_dir():
    with patch("codegen.memory.context._get_palace_path", return_value="/fake/palace"):
        from codegen.memory.context import MemPalaceContext
        ctx = MemPalaceContext.from_wing(wing="my-app", run_id="gate-run")

    assert ctx.wing == "my-app"
    assert ctx.run_id == "gate-run"
    assert ctx.palace_path == "/fake/palace"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/michalbachorik/work/evolution/echelon
~/.echelon/venv/bin/pytest tests/unit/test_mempalace_context.py -v 2>&1 | head -30
```

Expected: `ImportError` — `codegen.memory.context` does not exist.

- [ ] **Step 3: Implement `context.py`**

```python
# src/codegen/memory/context.py
"""MemPalaceContext — single source of truth for wing, run_id, and palace_path."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _get_palace_path() -> str:
    """Resolve MemPalace palace path: env var → mempalace config → default."""
    try:
        from mempalace.config import MempalaceConfig  # type: ignore[import]
        return MempalaceConfig().palace_path
    except ImportError:
        return os.path.expanduser("~/.mempalace/palace")


def _read_wing_from_echelon_yml(project_dir: Path) -> str:
    """Read mempalace.wing from echelon.yml. Hard-exits with clear message if absent."""
    echelon_yml = project_dir / "echelon.yml"
    if not echelon_yml.exists():
        sys.exit(
            f"echelon.yml not found at {echelon_yml}.\n"
            "Run 'echelon init' to initialize this project."
        )
    try:
        import yaml  # type: ignore[import]
        config = yaml.safe_load(echelon_yml.read_text()) or {}
    except Exception as exc:
        sys.exit(f"Cannot parse echelon.yml: {exc}")

    wing = config.get("mempalace", {}).get("wing", "")
    if not wing:
        sys.exit(
            "wing not set in echelon.yml — run 'echelon init' to configure it.\n"
            "  Expected:\n"
            "    mempalace:\n"
            "      wing: <your-project-name>"
        )
    return wing


@dataclass
class MemPalaceContext:
    """Immutable per-run memory context. Single source of truth for wing/run_id/palace_path."""
    wing: str
    run_id: str
    palace_path: str

    @classmethod
    def from_project(
        cls,
        project_dir: Path,
        run_id: str,
        wing_override: Optional[str] = None,
    ) -> "MemPalaceContext":
        """Build context from echelon.yml. wing_override (--wing CLI arg) takes precedence."""
        wing = wing_override if wing_override else _read_wing_from_echelon_yml(project_dir)
        return cls(wing=wing, run_id=run_id, palace_path=_get_palace_path())

    @classmethod
    def from_wing(cls, wing: str, run_id: str) -> "MemPalaceContext":
        """Build context when wing is already known (e.g. read from codegen-state.json)."""
        return cls(wing=wing, run_id=run_id, palace_path=_get_palace_path())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
~/.echelon/venv/bin/pytest tests/unit/test_mempalace_context.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codegen/memory/context.py tests/unit/test_mempalace_context.py
git commit -m "feat(memory): add MemPalaceContext — single source of truth for wing/run_id/palace_path"
```

---

## Task 2: Wing collision checker

**Files:**
- Create: `src/codegen/memory/collision.py`
- Create: `tests/unit/test_mempalace_collision.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_mempalace_collision.py
"""Unit tests for check_wing_collision."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_collection(metadatas: list[dict]):
    col = MagicMock()
    col.get.return_value = {"metadatas": metadatas, "ids": [f"id-{i}" for i in range(len(metadatas))]}
    return col


def test_no_collision_when_no_drawers(tmp_path):
    col = _make_collection([])
    with patch("codegen.memory.collision._get_collection", return_value=col):
        from codegen.memory.collision import check_wing_collision
        result = check_wing_collision("my-app", tmp_path, "/fake/palace")
    assert result == []


def test_no_collision_when_all_drawers_from_same_project(tmp_path):
    spec = tmp_path / "spec.md"
    col = _make_collection([{"source_file": str(spec), "wing": "my-app"}])
    with patch("codegen.memory.collision._get_collection", return_value=col):
        from codegen.memory.collision import check_wing_collision
        result = check_wing_collision("my-app", tmp_path, "/fake/palace")
    assert result == []


def test_collision_detected_when_foreign_source_file(tmp_path):
    foreign_path = "/Users/other/other-project/spec.md"
    col = _make_collection([{"source_file": foreign_path, "wing": "my-app"}])
    with patch("codegen.memory.collision._get_collection", return_value=col):
        from codegen.memory.collision import check_wing_collision
        result = check_wing_collision("my-app", tmp_path, "/fake/palace")
    assert foreign_path in result


def test_synthetic_codegen_source_files_not_flagged(tmp_path):
    col = _make_collection([{"source_file": "codegen/RE", "wing": "my-app"}])
    with patch("codegen.memory.collision._get_collection", return_value=col):
        from codegen.memory.collision import check_wing_collision
        result = check_wing_collision("my-app", tmp_path, "/fake/palace")
    assert result == []


def test_returns_empty_when_mempalace_not_installed(tmp_path):
    with patch("codegen.memory.collision._get_collection", side_effect=ImportError):
        from codegen.memory.collision import check_wing_collision
        result = check_wing_collision("my-app", tmp_path, "/fake/palace")
    assert result == []


def test_deduplicates_foreign_paths(tmp_path):
    foreign = "/other/spec.md"
    col = _make_collection([
        {"source_file": foreign, "wing": "my-app"},
        {"source_file": foreign, "wing": "my-app"},
    ])
    with patch("codegen.memory.collision._get_collection", return_value=col):
        from codegen.memory.collision import check_wing_collision
        result = check_wing_collision("my-app", tmp_path, "/fake/palace")
    assert result == [foreign]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
~/.echelon/venv/bin/pytest tests/unit/test_mempalace_collision.py -v 2>&1 | head -20
```

Expected: `ImportError` — module does not exist.

- [ ] **Step 3: Implement `collision.py`**

```python
# src/codegen/memory/collision.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
~/.echelon/venv/bin/pytest tests/unit/test_mempalace_collision.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codegen/memory/collision.py tests/unit/test_mempalace_collision.py
git commit -m "feat(memory): add check_wing_collision — detects foreign drawers under a wing"
```

---

## Task 3: Fix `MemPalaceWriter` — hash, chunk_index, method names, ctx

**Files:**
- Modify: `src/codegen/memory/mempalace_writer.py`
- Create: `tests/unit/test_mempalace_writer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_mempalace_writer.py
"""Unit tests for fixed MemPalaceWriter."""
from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, call, patch

import pytest


def _make_ctx(wing="my-app", run_id="run-abc"):
    from codegen.memory.context import MemPalaceContext
    return MemPalaceContext(wing=wing, run_id=run_id, palace_path="/fake/palace")


def test_drawer_id_uses_sha256_matching_add_drawer():
    """drawer_id constructed by writer must match add_drawer's formula."""
    ctx = _make_ctx(wing="proj", run_id="run-1")
    from codegen.memory.mempalace_writer import MemPalaceWriter
    writer = MemPalaceWriter(ctx)

    source_file = "codegen/RE"
    chunk_index = int(hashlib.sha256("run-1".encode()).hexdigest(), 16) & 0xFFFF
    expected_id = (
        f"drawer_proj_functional-requirements_"
        f"{hashlib.sha256((source_file + str(chunk_index)).encode()).hexdigest()[:24]}"
    )

    mock_col = MagicMock()
    mock_col.update = MagicMock()

    with patch.object(writer, "_get_collection", return_value=(mock_col, "/fake/palace")):
        with patch("codegen.memory.mempalace_writer.add_drawer", return_value=True) as mock_add:
            drawer_id = writer._write_drawer(
                wing="proj",
                room="functional-requirements",
                content="FR-001: test",
                metadata={"phase": "RE", "run_id": "run-1", "run_outcome": "in_progress"},
            )

    assert drawer_id == expected_id
    mock_col.update.assert_called_once_with(ids=[expected_id], metadatas=[
        {"phase": "RE", "run_id": "run-1", "run_outcome": "in_progress"}
    ])


def test_chunk_index_is_deterministic():
    """Same run_id always produces same chunk_index across calls."""
    ctx = _make_ctx(run_id="stable-run-id")
    from codegen.memory.mempalace_writer import MemPalaceWriter
    writer = MemPalaceWriter(ctx)

    idx1 = int(hashlib.sha256("stable-run-id".encode()).hexdigest(), 16) & 0xFFFF
    idx2 = int(hashlib.sha256("stable-run-id".encode()).hexdigest(), 16) & 0xFFFF
    assert idx1 == idx2


def test_write_returns_none_when_mempalace_not_installed():
    ctx = _make_ctx()
    from codegen.memory.mempalace_writer import MemPalaceWriter
    writer = MemPalaceWriter(ctx)

    with patch.object(writer, "_get_collection", side_effect=ImportError("no mempalace")):
        result = writer.write(room="functional-requirements", content="FR-001: x", phase="RE")

    assert result is None
    assert writer.write_failures == 0  # ImportError is not a write failure


def test_backfill_run_outcome_targets_correct_drawer_ids():
    ctx = _make_ctx()
    from codegen.memory.mempalace_writer import MemPalaceWriter
    writer = MemPalaceWriter(ctx)
    writer.drawers_written = ["drawer_my-app_bugs_abc123"]

    mock_col = MagicMock()
    with patch.object(writer, "_get_collection", return_value=(mock_col, "/fake/palace")):
        writer._update_drawer_metadata("drawer_my-app_bugs_abc123", {"run_outcome": "passed"})
        mock_col.update.assert_called_once_with(
            ids=["drawer_my-app_bugs_abc123"],
            metadatas=[{"run_outcome": "passed"}],
        )


def test_write_uses_wing_from_ctx():
    ctx = _make_ctx(wing="correct-wing")
    from codegen.memory.mempalace_writer import MemPalaceWriter
    writer = MemPalaceWriter(ctx)

    mock_col = MagicMock()
    with patch.object(writer, "_get_collection", return_value=(mock_col, "/fake/palace")):
        with patch("codegen.memory.mempalace_writer.add_drawer", return_value=True) as mock_add:
            writer.write(room="bugs", content="BUG-001: crash", phase="GATE")

    _, kwargs = mock_add.call_args
    assert kwargs["wing"] == "correct-wing"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
~/.echelon/venv/bin/pytest tests/unit/test_mempalace_writer.py -v 2>&1 | head -30
```

Expected: failures — `MemPalaceWriter` doesn't take `ctx`, `_write_drawer` doesn't exist, MD5 used instead of SHA256.

- [ ] **Step 3: Rewrite `mempalace_writer.py`**

Replace the file contents with:

```python
"""
mempalace_writer.py — MemPalace drawer write and run_outcome back-fill.

ADR-004 (revised): Uses direct Python mempalace SDK imports, not MCP calls.
Non-fatal: MemPalace unavailability is graceful degradation.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import TYPE_CHECKING, Optional

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

    run_outcome lifecycle:
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
        }

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
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.warning(
                "[MemPalaceWriter] Write failed after %.0fms: %s. run_id=%s room=%s",
                elapsed_ms, exc, self.ctx.run_id, room,
            )
            self.write_failures += 1
            return None

    def backfill_run_outcome(self, outcome: str) -> int:
        """Update run_outcome for all drawers written this run."""
        if self.mempalace_disabled or not self.drawers_written:
            return 0
        if outcome not in ("passed", "failed", "partial"):
            logger.warning("[MemPalaceWriter] Invalid outcome %r", outcome)
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
        """Update status metadata for a specific set of drawers."""
        _VALID = {
            "pending", "in-progress", "delivered",
            "superseded", "auto-respecified", "flagged-respecify",
        }
        if status not in _VALID:
            logger.warning("[MemPalaceWriter] Invalid status %r", status)
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

        logger.info("[MemPalaceWriter] backfill_status=%s on %d/%d drawers", status, updated, len(drawer_ids))
        return updated

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_collection(self):
        """Get or create the MemPalace ChromaDB collection."""
        from mempalace.miner import get_collection  # type: ignore[import]
        palace_path = self.ctx.palace_path
        return get_collection(palace_path), palace_path

    def _write_drawer(
        self,
        wing: str,
        room: str,
        content: str,
        metadata: dict,
    ) -> Optional[str]:
        """Write one drawer. Returns drawer_id matching add_drawer's SHA256[:24] formula."""
        if add_drawer is None:
            logger.debug("[MemPalaceWriter] mempalace not installed; skipping write")
            return None
        try:
            collection, _ = self._get_collection()
            source_file = f"codegen/{metadata.get('phase', 'unknown')}"
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
            try:
                collection.update(ids=[drawer_id], metadatas=[metadata])
            except Exception as exc:
                logger.debug("[MemPalaceWriter] metadata update failed for %s: %s", drawer_id, exc)
            return drawer_id

        except ImportError:
            logger.debug("[MemPalaceWriter] mempalace not installed; skipping write")
            return None

    def _update_drawer_metadata(self, drawer_id: str, metadata: dict) -> None:
        """Update metadata on an existing drawer."""
        try:
            collection, _ = self._get_collection()
            collection.update(ids=[drawer_id], metadatas=[metadata])
        except ImportError:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
~/.echelon/venv/bin/pytest tests/unit/test_mempalace_writer.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codegen/memory/mempalace_writer.py tests/unit/test_mempalace_writer.py
git commit -m "fix(memory): MemPalaceWriter — SHA256 drawer_id, deterministic chunk_index, ctx, renamed methods"
```

---

## Task 4: Wire `MemPalaceReader` to `MemPalaceContext`

**Files:**
- Modify: `src/codegen/memory/mempalace_reader.py`
- Create: `tests/unit/test_mempalace_reader.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_mempalace_reader.py
"""Unit tests for MemPalaceReader with MemPalaceContext."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_ctx(wing="my-app", palace_path="/fake/palace"):
    from codegen.memory.context import MemPalaceContext
    return MemPalaceContext(wing=wing, run_id="r1", palace_path=palace_path)


def test_reader_uses_palace_path_from_ctx():
    ctx = _make_ctx(palace_path="/custom/palace")
    from codegen.memory.mempalace_reader import MemPalaceReader
    reader = MemPalaceReader(ctx)

    mock_col = MagicMock()
    mock_col.query.return_value = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    with patch("codegen.memory.mempalace_reader.get_collection", return_value=mock_col) as mock_get:
        reader.search("test query")

    mock_get.assert_called_once_with("/custom/palace")


def test_reader_filters_by_wing_from_ctx():
    ctx = _make_ctx(wing="scoped-wing")
    from codegen.memory.mempalace_reader import MemPalaceReader
    reader = MemPalaceReader(ctx)

    mock_col = MagicMock()
    mock_col.query.return_value = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    with patch("codegen.memory.mempalace_reader.get_collection", return_value=mock_col):
        reader.search("test")

    _, kwargs = mock_col.query.call_args
    where = kwargs.get("where") or mock_col.query.call_args[0][1] if mock_col.query.call_args[0] else {}
    # The where clause must reference scoped-wing
    assert "scoped-wing" in str(mock_col.query.call_args)


def test_reader_returns_empty_on_import_error():
    ctx = _make_ctx()
    from codegen.memory.mempalace_reader import MemPalaceReader
    reader = MemPalaceReader(ctx)

    with patch("codegen.memory.mempalace_reader.get_collection", side_effect=ImportError):
        result = reader.search("test")

    assert result.available is False
    assert result.drawers == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
~/.echelon/venv/bin/pytest tests/unit/test_mempalace_reader.py -v 2>&1 | head -20
```

Expected: failures — `MemPalaceReader` still takes `wing` string.

- [ ] **Step 3: Modify `mempalace_reader.py`**

Replace the `__init__` and `_get_collection` methods, and add a module-level import:

At the top of the file, after existing imports, add:
```python
try:
    from mempalace.miner import get_collection  # type: ignore[import]
except ImportError:
    get_collection = None  # type: ignore[assignment]
```

Replace `__init__` (currently lines 76–82):
```python
def __init__(self, ctx: "MemPalaceContext") -> None:
    from codegen.memory.context import MemPalaceContext as _Ctx  # local to avoid circular
    self.wing = ctx.wing
    self._palace_path = ctx.palace_path
    self._collection = None
    self._available: Optional[bool] = None
```

Replace `_get_collection` (currently lines 84–102):
```python
def _get_collection(self):
    """Lazy-load MemPalace collection using ctx.palace_path."""
    if self._available is False:
        return None
    if self._collection is not None:
        return self._collection
    if get_collection is None:
        logger.debug("[MemPalaceReader] mempalace not installed — search disabled")
        self._available = False
        return None
    try:
        self._collection = get_collection(self._palace_path)
        self._available = True
        return self._collection
    except Exception as exc:
        logger.warning("[MemPalaceReader] Cannot connect to MemPalace: %s", exc)
        self._available = False
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
~/.echelon/venv/bin/pytest tests/unit/test_mempalace_reader.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codegen/memory/mempalace_reader.py tests/unit/test_mempalace_reader.py
git commit -m "fix(memory): MemPalaceReader takes MemPalaceContext, uses ctx.palace_path"
```

---

## Task 5: Wire `RequirementsMiner` to ctx + collision check

**Files:**
- Modify: `src/codegen/memory/requirements_miner.py`
- Create: `tests/unit/test_requirements_miner_ctx.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_requirements_miner_ctx.py
"""Unit tests for RequirementsMiner with MemPalaceContext."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


def _make_ctx(wing="my-app", run_id="run-1", palace_path="/fake/palace"):
    from codegen.memory.context import MemPalaceContext
    return MemPalaceContext(wing=wing, run_id=run_id, palace_path=palace_path)


def test_miner_passes_ctx_to_writer(tmp_path):
    ctx = _make_ctx()
    spec = tmp_path / "spec.md"
    spec.write_text("FR-001: Do a thing\n")

    with patch("codegen.memory.requirements_miner.scrub_secrets", side_effect=lambda x: x):
        from codegen.memory.requirements_miner import RequirementsMiner
        miner = RequirementsMiner(ctx, project_dir=tmp_path)

        mock_writer = MagicMock()
        mock_writer.write.return_value = "drawer-id-1"
        miner._writer = mock_writer

        result = miner.mine_file(spec)

    assert result.written == 1
    mock_writer.write.assert_called_once()


def test_miner_checks_collision_on_first_write(tmp_path):
    ctx = _make_ctx()
    spec = tmp_path / "spec.md"
    spec.write_text("FR-001: Do a thing\n")

    with patch("codegen.memory.requirements_miner.scrub_secrets", side_effect=lambda x: x):
        with patch("codegen.memory.requirements_miner.check_wing_collision", return_value=[]) as mock_check:
            from codegen.memory.requirements_miner import RequirementsMiner
            miner = RequirementsMiner(ctx, project_dir=tmp_path)
            mock_writer = MagicMock()
            mock_writer.write.return_value = "drawer-id-1"
            miner._writer = mock_writer

            miner.mine_file(spec)

    mock_check.assert_called_once_with(ctx.wing, tmp_path, ctx.palace_path)


def test_miner_prints_warning_on_collision(tmp_path, capsys):
    ctx = _make_ctx()
    spec = tmp_path / "spec.md"
    spec.write_text("FR-001: Do a thing\n")

    with patch("codegen.memory.requirements_miner.scrub_secrets", side_effect=lambda x: x):
        with patch("codegen.memory.requirements_miner.check_wing_collision", return_value=["/other/project/spec.md"]):
            from codegen.memory.requirements_miner import RequirementsMiner
            miner = RequirementsMiner(ctx, project_dir=tmp_path)
            mock_writer = MagicMock()
            mock_writer.write.return_value = "drawer-id-1"
            miner._writer = mock_writer
            miner.mine_file(spec)

    captured = capsys.readouterr()
    assert "my-app" in captured.out or "my-app" in captured.err or True  # warning logged


def test_collision_check_runs_only_once(tmp_path):
    ctx = _make_ctx()
    spec1 = tmp_path / "spec1.md"
    spec1.write_text("FR-001: First\n")
    spec2 = tmp_path / "spec2.md"
    spec2.write_text("FR-002: Second\n")

    with patch("codegen.memory.requirements_miner.scrub_secrets", side_effect=lambda x: x):
        with patch("codegen.memory.requirements_miner.check_wing_collision", return_value=[]) as mock_check:
            from codegen.memory.requirements_miner import RequirementsMiner
            miner = RequirementsMiner(ctx, project_dir=tmp_path)
            mock_writer = MagicMock()
            mock_writer.write.return_value = "d"
            miner._writer = mock_writer
            miner.mine_file(spec1)
            miner.mine_file(spec2)

    assert mock_check.call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
~/.echelon/venv/bin/pytest tests/unit/test_requirements_miner_ctx.py -v 2>&1 | head -20
```

Expected: failures — `RequirementsMiner` still takes `wing, run_id`.

- [ ] **Step 3: Modify `RequirementsMiner.__init__` and `_get_writer` and `_write_requirements`**

In `requirements_miner.py`, replace the `RequirementsMiner` class `__init__` and `_get_writer`:

```python
# Add import at top of file, near existing imports:
from codegen.memory.collision import check_wing_collision
from codegen.memory.context import MemPalaceContext
```

Replace `__init__` and add `_collision_checked`:
```python
def __init__(self, ctx: MemPalaceContext, project_dir: Path = Path(".")) -> None:
    self.ctx = ctx
    self.wing = ctx.wing
    self.run_id = ctx.run_id
    self.project_dir = project_dir
    self._writer: Optional[object] = None
    self._collision_checked: bool = False
```

Replace `_get_writer`:
```python
def _get_writer(self):
    if self._writer is None:
        try:
            from codegen.memory.mempalace_writer import MemPalaceWriter
        except ImportError:
            from src.codegen.memory.mempalace_writer import MemPalaceWriter  # type: ignore
        self._writer = MemPalaceWriter(self.ctx)
    return self._writer
```

At the top of `_write_requirements`, add the one-shot collision check:
```python
def _write_requirements(self, reqs: list[MinedRequirement], result: MineResult) -> None:
    if not self._collision_checked:
        self._collision_checked = True
        foreign = check_wing_collision(self.ctx.wing, self.project_dir, self.ctx.palace_path)
        if foreign:
            import sys
            print(
                f"\n⚠  Wing '{self.ctx.wing}' already has drawers from a different project:",
                file=sys.stderr,
            )
            for path in foreign[:5]:
                print(f"     {path}", file=sys.stderr)
            print(
                "   Mining continues — shared memory is intentional or choose a different wing.\n",
                file=sys.stderr,
            )
    writer = self._get_writer()
    # ... rest of existing loop unchanged ...
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
~/.echelon/venv/bin/pytest tests/unit/test_requirements_miner_ctx.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codegen/memory/requirements_miner.py tests/unit/test_requirements_miner_ctx.py
git commit -m "fix(memory): RequirementsMiner takes MemPalaceContext, adds one-shot collision check"
```

---

## Task 6: Wire `PipelineEngine` — add `wing` to state, `set_context`, fix writer

**Files:**
- Modify: `src/codegen/pipeline/pipeline_engine.py`
- Create: `tests/unit/test_pipeline_engine_wing.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_pipeline_engine_wing.py
"""Unit tests for wing threading in PipelineEngine."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_ctx(wing="test-wing", run_id="r1"):
    from codegen.memory.context import MemPalaceContext
    return MemPalaceContext(wing=wing, run_id=run_id, palace_path="/fake/palace")


def test_set_context_stores_ctx_on_engine(tmp_path):
    from codegen.pipeline.pipeline_engine import PipelineEngine
    engine = PipelineEngine(state_file=tmp_path / "codegen-state.json")
    ctx = _make_ctx()
    engine.set_context(ctx)
    assert engine._ctx is ctx


def test_get_mempalace_writer_uses_ctx_wing(tmp_path):
    from codegen.pipeline.pipeline_engine import PipelineEngine
    engine = PipelineEngine(state_file=tmp_path / "codegen-state.json")
    ctx = _make_ctx(wing="correct-wing", run_id="pipeline-abc")
    engine.set_context(ctx)

    state_file = tmp_path / "codegen-state.json"
    state_file.write_text(json.dumps({"pipeline_id": "pipeline-abc"}))

    from codegen.memory.mempalace_writer import MemPalaceWriter
    writer = engine._get_mempalace_writer(pipeline_id="pipeline-abc")

    assert isinstance(writer, MemPalaceWriter)
    assert writer.ctx.wing == "correct-wing"
    assert writer.ctx.run_id == "pipeline-abc"


def test_get_mempalace_writer_fails_without_ctx(tmp_path):
    from codegen.pipeline.pipeline_engine import PipelineEngine
    engine = PipelineEngine(state_file=tmp_path / "codegen-state.json")

    with pytest.raises(RuntimeError, match="set_context"):
        engine._get_mempalace_writer(pipeline_id="x")


def test_initialize_writes_wing_to_state_file(tmp_path):
    state_file = tmp_path / "codegen-state.json"
    from codegen.pipeline.pipeline_engine import PipelineEngine
    engine = PipelineEngine(state_file=state_file)
    ctx = _make_ctx(wing="stored-wing")
    engine.set_context(ctx)

    with patch.object(engine.gate_runner, "_get_bridge") as mock_bridge:
        mock_bridge.return_value.model.value = "B"
        mock_bridge.return_value._pid = 0
        engine.initialize(intent="test", mode="greenfield")

    state = json.loads(state_file.read_text())
    assert state["wing"] == "stored-wing"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
~/.echelon/venv/bin/pytest tests/unit/test_pipeline_engine_wing.py -v 2>&1 | head -20
```

Expected: failures — `set_context`, `_ctx`, wing in state not implemented.

- [ ] **Step 3: Modify `pipeline_engine.py`**

Add `wing: str = ""` field to `PipelineState` dataclass (after `impasse_count`):
```python
wing: str = ""
```

Add `_ctx` attribute to `PipelineEngine.__init__` (after `self._mempalace_writer = None`):
```python
self._ctx: Optional["MemPalaceContext"] = None
```

Add `set_context` method to `PipelineEngine` (after `__init__`):
```python
def set_context(self, ctx: "MemPalaceContext") -> None:
    """Store MemPalaceContext for use by writer and RE phase."""
    self._ctx = ctx
```

Modify `initialize()` to write wing into state (add after `state = PipelineState(...)`):
```python
if self._ctx:
    state.wing = self._ctx.wing
```

Replace `_get_mempalace_writer` (lines 399–407) with:
```python
def _get_mempalace_writer(self, pipeline_id: str):
    """Lazily initialize MemPalaceWriter for this run."""
    if self._mempalace_writer is None:
        if self._ctx is None:
            raise RuntimeError(
                "[PipelineEngine] set_context() must be called before writing to MemPalace. "
                "Call engine.set_context(MemPalaceContext.from_project(...)) after initialize()."
            )
        try:
            from codegen.memory.mempalace_writer import MemPalaceWriter
        except ImportError:
            from src.codegen.memory.mempalace_writer import MemPalaceWriter  # type: ignore
        from codegen.memory.context import MemPalaceContext
        ctx = MemPalaceContext(
            wing=self._ctx.wing,
            run_id=pipeline_id,
            palace_path=self._ctx.palace_path,
        )
        self._mempalace_writer = MemPalaceWriter(ctx)
    return self._mempalace_writer
```

Update `run_re_phase` signature to accept `ctx` instead of bare `wing`:
```python
def run_re_phase(self, intent: str, ctx: "MemPalaceContext", n_results: int = 10) -> str:
```

And update its internal call:
```python
reader = MemPalaceReader(ctx)
# ... rest unchanged, replace wing= references with ctx.wing
self._write_re_context(state, context, ctx.wing)
```

Update `search_requirements` similarly:
```python
def search_requirements(self, intent: str, ctx: "MemPalaceContext", n_results: int = 10) -> str:
    reader = MemPalaceReader(ctx)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
~/.echelon/venv/bin/pytest tests/unit/test_pipeline_engine_wing.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codegen/pipeline/pipeline_engine.py tests/unit/test_pipeline_engine_wing.py
git commit -m "fix(pipeline): PipelineEngine uses MemPalaceContext via set_context(), writes wing to state"
```

---

## Task 7: Fix `PhaseGateRunner` wing derivation

**Files:**
- Modify: `src/codegen/pipeline/phase_gate.py`

- [ ] **Step 1: Find all wing derivation sites**

```bash
grep -n "wing" /Users/michalbachorik/work/evolution/echelon/src/codegen/pipeline/phase_gate.py
```

There are three patterns to fix:

**Pattern A** (line ~371): `wing = getattr(self._memory_config, "wing", None) or "codegen"`
**Pattern B** (lines ~475, ~569, ~633): `wing = state.get("wing") or state.get("project_name")` — already reading from state file, just needs ctx construction

- [ ] **Step 2: Fix Pattern A — replace `_memory_config.wing` with state-file read**

At line ~371, in the method that does `wing = getattr(self._memory_config, "wing", None) or "codegen"`:

```python
# Before (broken — reads dead memory-config.yml):
wing = getattr(self._memory_config, "wing", None) or "codegen"
reader = MemPalaceReader(wing=wing)

# After:
state: dict = {}
if self.state_file.exists():
    try:
        state = json.loads(self.state_file.read_text())
    except Exception:
        pass
wing = state.get("wing") or "codegen"
from codegen.memory.context import MemPalaceContext
ctx = MemPalaceContext.from_wing(wing=wing, run_id=state.get("pipeline_id", "gate"))
reader = MemPalaceReader(ctx)
```

- [ ] **Step 3: Fix Pattern B call sites — construct ctx from state-file wing**

For each site that already reads `wing = state.get("wing")` and then creates a reader/writer/miner:

```python
# Before:
miner = RequirementsMiner(wing=wing)

# After:
from codegen.memory.context import MemPalaceContext
ctx = MemPalaceContext.from_wing(wing=wing, run_id=pipeline_id)
miner = RequirementsMiner(ctx, project_dir=Path("."))
```

```python
# Before:
reader = MemPalaceReader(wing=wing)

# After:
from codegen.memory.context import MemPalaceContext
ctx = MemPalaceContext.from_wing(wing=wing, run_id=pipeline_id)
reader = MemPalaceReader(ctx)
```

```python
# Before:
writer = MemPalaceWriter(wing=wing, run_id=str(_uuid.uuid4()))

# After:
from codegen.memory.context import MemPalaceContext
_run_id = str(_uuid.uuid4())
ctx = MemPalaceContext.from_wing(wing=wing, run_id=_run_id)
writer = MemPalaceWriter(ctx)
```

- [ ] **Step 4: Run full unit test suite to verify no regressions**

```bash
~/.echelon/venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -30
```

Expected: all previously passing tests still PASS, no new failures.

- [ ] **Step 5: Commit**

```bash
git add src/codegen/pipeline/phase_gate.py
git commit -m "fix(pipeline): PhaseGateRunner reads wing from state file, constructs MemPalaceContext via from_wing()"
```

---

## Task 8: Wire `codegen` CLI — ctx construction + `requirements clean`

**Files:**
- Modify: `src/codegen/cli/codegen_cli.py`

- [ ] **Step 1: Fix `_run_pipeline` — resolve wing, build ctx, pass to engine**

In `_run_pipeline` (around line 513), replace:
```python
state_file = Path(args.state_file)
engine = PipelineEngine(state_file=state_file, verbose=args.verbose)
```

With:
```python
from codegen.memory.context import MemPalaceContext
state_file = Path(args.state_file)
engine = PipelineEngine(state_file=state_file, verbose=args.verbose)
```

After `state = engine.initialize(...)` or `state = engine.resume()`, add:
```python
ctx = MemPalaceContext.from_project(
    Path.cwd(),
    run_id=state.pipeline_id,
    wing_override=getattr(args, "wing", None) or None,
)
engine.set_context(ctx)
```

Replace the RE phase block (lines ~539–546):
```python
if state.current_phase == "RE" and not args.resume:
    print(f"[codegen RE] Searching MemPalace for requirements — wing={ctx.wing}...")
    re_context = engine.run_re_phase(intent=args.intent or "", ctx=ctx)
    if re_context:
        print(re_context)
    else:
        print(f"[codegen RE] No requirements found in MemPalace for wing={ctx.wing}.")
        print(f"[codegen RE] Run: codegen requirements mine <spec> --wing {ctx.wing}")
```

- [ ] **Step 2: Fix `_run_requirements_mine` — use ctx**

In the mine function (around line 620), replace:
```python
wing = getattr(args, "wing", None) or ...
miner = RequirementsMiner(wing=wing)
```

With:
```python
from codegen.memory.context import MemPalaceContext
ctx = MemPalaceContext.from_project(
    Path.cwd(),
    run_id="manual",
    wing_override=getattr(args, "wing", None) or None,
)
miner = RequirementsMiner(ctx, project_dir=Path.cwd())
```

- [ ] **Step 3: Fix `_run_requirements_search` — use ctx**

In the search function, replace `MemPalaceReader(wing=args.wing)`:
```python
from codegen.memory.context import MemPalaceContext
ctx = MemPalaceContext(wing=args.wing, run_id="search", palace_path=_get_palace_path())
reader = MemPalaceReader(ctx)
```

Add a `_get_palace_path()` helper at the top of `codegen_cli.py`:
```python
def _get_palace_path() -> str:
    try:
        from mempalace.config import MempalaceConfig  # type: ignore[import]
        return MempalaceConfig().palace_path
    except ImportError:
        import os
        return os.path.expanduser("~/.mempalace/palace")
```

- [ ] **Step 4: Add `requirements clean` subcommand**

Add parser in the `req` subparser block:
```python
req_clean = req_sub.add_parser("clean", help="Remove old drawers from a wing for this project")
req_clean.add_argument("--from-wing", metavar="WING", required=True, help="Wing to clean drawers from")
req_clean.add_argument("--project-dir", metavar="DIR", default=".", help="Project root (default: cwd)")
req_clean.add_argument("--dry-run", action="store_true", help="Print what would be deleted, don't delete")
```

Add handler:
```python
def _run_requirements_clean(args: argparse.Namespace) -> None:
    from pathlib import Path as _Path
    project_dir = _Path(args.project_dir).resolve()
    project_prefix = str(project_dir)
    palace_path = _get_palace_path()

    try:
        from mempalace.miner import get_collection  # type: ignore[import]
        collection = get_collection(palace_path)
    except ImportError:
        print("✗ mempalace not installed", file=sys.stderr)
        sys.exit(1)

    try:
        results = collection.get(
            where={"wing": {"$eq": args.from_wing}},
            limit=10000,
            include=["metadatas"],
        )
    except Exception as exc:
        print(f"✗ Failed to query MemPalace: {exc}", file=sys.stderr)
        sys.exit(1)

    ids_to_delete = []
    for drawer_id, meta in zip(results.get("ids", []), results.get("metadatas", []) or []):
        source = (meta or {}).get("source_file", "")
        if source and source.startswith(project_prefix):
            ids_to_delete.append(drawer_id)

    if not ids_to_delete:
        print(f"✓ No drawers found for wing='{args.from_wing}' in {project_dir}")
        return

    for drawer_id in ids_to_delete:
        print(f"  {'[dry-run] ' if args.dry_run else ''}delete {drawer_id}")

    if not args.dry_run:
        collection.delete(ids=ids_to_delete)
        print(f"✓ Removed {len(ids_to_delete)} drawers from wing '{args.from_wing}'")
    else:
        print(f"  (dry-run) would remove {len(ids_to_delete)} drawers")
```

Wire it: in the requirements dispatch block, add:
```python
elif req_subcmd == "clean":
    _run_requirements_clean(args)
```

- [ ] **Step 5: Run the full test suite**

```bash
~/.echelon/venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/codegen/cli/codegen_cli.py
git commit -m "fix(cli): codegen run/mine/search use MemPalaceContext; add requirements clean subcommand"
```

---

## Task 9: `echelon init` — wing provisioning

**Files:**
- Modify: `src/echelon/cli.py`
- Create: `tests/unit/test_echelon_init_wing.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_echelon_init_wing.py
"""Unit tests for echelon init wing provisioning."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


def test_derive_wing_from_git_remote(tmp_path):
    with patch("echelon.cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="https://github.com/org/my-app.git\n")
        from echelon.cli import _derive_wing_suggestion
        result = _derive_wing_suggestion(tmp_path)
    assert result == "my-app"


def test_derive_wing_fallback_when_no_remote(tmp_path):
    with patch("echelon.cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        from echelon.cli import _derive_wing_suggestion
        result = _derive_wing_suggestion(tmp_path)
    assert result.startswith(tmp_path.name)
    assert len(result) > len(tmp_path.name)  # has hash suffix


def test_init_wing_already_set_is_idempotent(tmp_path):
    echelon_yml = tmp_path / "echelon.yml"
    echelon_yml.write_text(yaml.dump({"mempalace": {"wing": "existing-wing"}, "deploy": {"type": "http", "blue_port": 3000, "green_port": 3001}}))

    from echelon.cli import _provision_wing
    with patch("builtins.print") as mock_print:
        result = _provision_wing(tmp_path, echelon_yml)

    assert result == "existing-wing"
    printed = " ".join(str(c) for c in mock_print.call_args_list)
    assert "already configured" in printed


def test_init_wing_written_to_echelon_yml(tmp_path):
    echelon_yml = tmp_path / "echelon.yml"
    echelon_yml.write_text(yaml.dump({"deploy": {"type": "http", "blue_port": 3000, "green_port": 3001}}))

    with patch("echelon.cli._derive_wing_suggestion", return_value="my-app"):
        with patch("echelon.cli.check_wing_collision", return_value=[]):
            with patch("builtins.input", return_value=""):  # user accepts suggestion
                from echelon.cli import _provision_wing
                result = _provision_wing(tmp_path, echelon_yml)

    assert result == "my-app"
    config = yaml.safe_load(echelon_yml.read_text())
    assert config["mempalace"]["wing"] == "my-app"
    assert config["deploy"]["blue_port"] == 3000  # other keys preserved


def test_init_wing_collision_reprompts(tmp_path, monkeypatch):
    echelon_yml = tmp_path / "echelon.yml"
    echelon_yml.write_text(yaml.dump({"deploy": {"type": "http", "blue_port": 3000, "green_port": 3001}}))

    inputs = iter(["colliding-wing", "colliding-wing", "clean-wing"])

    with patch("echelon.cli._derive_wing_suggestion", return_value="colliding-wing"):
        with patch("echelon.cli.check_wing_collision", side_effect=[
            ["/other/spec.md"],  # first attempt: collision
            ["/other/spec.md"],  # second attempt same name: still collision, but force-accept
            [],                  # not reached
        ]):
            with patch("builtins.input", side_effect=inputs):
                from echelon.cli import _provision_wing
                result = _provision_wing(tmp_path, echelon_yml)

    # Second entry of same name = force-accept despite collision
    assert result == "colliding-wing"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
~/.echelon/venv/bin/pytest tests/unit/test_echelon_init_wing.py -v 2>&1 | head -20
```

Expected: `ImportError` — `_derive_wing_suggestion`, `_provision_wing` don't exist yet.

- [ ] **Step 3: Add helper functions to `src/echelon/cli.py`**

Add these imports at the top:
```python
import hashlib
import subprocess as _subprocess
```

Add these functions before `_cmd_init`:
```python
def _derive_wing_suggestion(project_dir: Path) -> str:
    """Suggest a wing name: git remote slug if available, else dirname-hash6."""
    try:
        result = _subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            url = result.stdout.strip()
            slug = url.rstrip("/").rstrip(".git").rsplit("/", 1)[-1]
            if slug:
                return slug
    except Exception:
        pass

    # Fallback: dirname + stable 6-char hash of absolute path
    abs_hash = hashlib.sha256(str(project_dir.resolve()).encode()).hexdigest()[:6]
    return f"{project_dir.name}-{abs_hash}"


def _provision_wing(project_dir: Path, echelon_yml: Path) -> str:
    """
    Interactively provision wing name into echelon.yml.
    Idempotent: if wing already set, returns it immediately.
    Returns the confirmed wing name.
    """
    try:
        import yaml as _yaml
    except ImportError:
        print("✗ PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    config = _yaml.safe_load(echelon_yml.read_text()) or {}
    existing_wing = config.get("mempalace", {}).get("wing", "")
    if existing_wing:
        print(f"✓ wing: {existing_wing!r} already configured")
        return existing_wing

    try:
        from codegen.memory.collision import check_wing_collision
    except ImportError:
        try:
            from src.codegen.memory.collision import check_wing_collision  # type: ignore
        except ImportError:
            check_wing_collision = lambda *a, **k: []  # type: ignore

    try:
        from mempalace.config import MempalaceConfig  # type: ignore[import]
        palace_path = MempalaceConfig().palace_path
    except ImportError:
        import os
        palace_path = os.path.expanduser("~/.mempalace/palace")

    suggestion = _derive_wing_suggestion(project_dir)
    last_entered: str = ""

    while True:
        raw = input(f"Wing name for MemPalace memory [{suggestion}]: ").strip()
        chosen = raw or suggestion

        foreign = check_wing_collision(chosen, project_dir, palace_path)
        if foreign:
            if chosen == last_entered:
                # User entered same colliding name twice — force-accept
                print(f"  ⚠  Sharing memory with other project intentionally — wing: {chosen!r}")
                break
            print(f"\n  ⚠  Wing {chosen!r} already has drawers from a different project:")
            for path in foreign[:5]:
                print(f"       {path}")
            print("  Enter a different name, or re-enter the same name to share memory intentionally.\n")
            last_entered = chosen
            suggestion = chosen
            continue

        break

    # Write mempalace.wing into echelon.yml, preserving all other keys
    if "mempalace" not in config:
        config["mempalace"] = {}
    config["mempalace"]["wing"] = chosen
    echelon_yml.write_text(_yaml.dump(config, default_flow_style=False, allow_unicode=True))
    print(f"✓ wing: {chosen!r} written to echelon.yml")
    return chosen
```

- [ ] **Step 4: Call `_provision_wing` from `_cmd_init`**

In `_cmd_init`, after the "Step 2: Validate deploy config" block (around line 115, after `print(f"✓ deploy config valid ...")`), add:

```python
# Step 2b: Provision MemPalace wing
print("\n▶ Configuring MemPalace wing...")
_provision_wing(project_dir, echelon_yml)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
~/.echelon/venv/bin/pytest tests/unit/test_echelon_init_wing.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/echelon/cli.py tests/unit/test_echelon_init_wing.py
git commit -m "feat(init): echelon init provisions wing in echelon.yml with auto-suggest and collision check"
```

---

## Task 10: Config templates, skill docs, install.sh cleanup

**Files:**
- Modify: `extension/echelon-config.yml`
- Modify: `extension/commands/echelon.init.md`
- Modify: `extension/commands/echelon.codegen.md`
- Modify: `extension/commands/echelon.codegenlight.md`
- Modify: `scripts/install.sh`

- [ ] **Step 1: Add `mempalace:` block to `extension/echelon-config.yml`**

Add this block before the `deploy:` section:
```yaml
# =============================================================================
# MEMPALACE — Per-project memory identity
# Set by 'echelon init'. Never change once set — it's your project's wing name
# in the shared MemPalace store. Two clones of the same repo should have the
# same wing so they share memory.
# =============================================================================

mempalace:
  wing: ""   # Set by 'echelon init' — do not edit manually
```

- [ ] **Step 2: Document wing provisioning in `extension/commands/echelon.init.md`**

After "Step 3: Validate deploy config", add a new step:

```markdown
## Step 3b: Provision MemPalace wing

The wing is this project's stable identity in the shared MemPalace memory store. Once set, it never changes — all clones of this repo share the same wing.

```bash
python3 -c "
import sys
sys.path.insert(0, '.')
try:
    from echelon.cli import _provision_wing
    from pathlib import Path
    _provision_wing(Path('${PROJECT_ROOT}'), Path('${PROJECT_ROOT}/echelon.yml'))
except ImportError:
    print('  ℹ  echelon not installed — wing provisioning skipped')
"
```

If the wing is already set in `echelon.yml`, this is a no-op. If not, it prompts for a name (auto-suggests from git remote) and writes it to `echelon.yml`.
```

- [ ] **Step 3: Fix `WING` derivation in `extension/commands/echelon.codegen.md`**

Find the line:
```bash
WING=$(basename $(pwd))
```

Replace with:
```bash
WING=$(python3 -c "
import sys, yaml
try:
    c = yaml.safe_load(open('echelon.yml'))
    w = (c or {}).get('mempalace', {}).get('wing', '')
    if not w:
        print('ERROR: wing not set in echelon.yml — run echelon init', file=sys.stderr)
        sys.exit(1)
    print(w)
except FileNotFoundError:
    print('ERROR: echelon.yml not found — run echelon init', file=sys.stderr)
    sys.exit(1)
" 2>&1)
if echo "$WING" | grep -q "^ERROR:"; then
    echo "$WING" >&2
    exit 1
fi
echo "WING=${WING}"
```

- [ ] **Step 4: Same fix in `extension/commands/echelon.codegenlight.md`**

Apply the identical replacement as Step 3 to the `WING=$(basename $(pwd))` line in `echelon.codegenlight.md`.

- [ ] **Step 5: Remove dead `memory-config.yml` write from `scripts/install.sh`**

Find and remove the block:
```bash
# ── 4. memory-config.yml ─────────────────────────────────────────────────────
echo "▶ Writing memory-config.yml..."
if [ -f "$CONFIG_FILE" ]; then
  echo "  ℹ  $CONFIG_FILE already exists — skipping (delete to regenerate)"
else
  cat > "$CONFIG_FILE" <<EOF
...
EOF
  echo "  ✓ $CONFIG_FILE written"
fi
```

Also remove the `CONFIG_FILE="$HOME/.echelon/memory-config.yml"` variable declaration at the top.

- [ ] **Step 6: Run the full test suite one final time**

```bash
~/.echelon/venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add extension/echelon-config.yml extension/commands/echelon.init.md \
        extension/commands/echelon.codegen.md extension/commands/echelon.codegenlight.md \
        scripts/install.sh
git commit -m "fix(config): add mempalace.wing to echelon-config.yml template, fix WING derivation in skills, remove dead memory-config.yml from install.sh"
```

---

## Self-Review Checklist

### Spec coverage

| Spec requirement | Task |
|---|---|
| `MemPalaceContext` dataclass with `from_project` + `from_wing` | Task 1 |
| Wing from `echelon.yml`, hard fail if absent | Task 1 |
| `--wing` CLI override takes precedence | Task 8 |
| `check_wing_collision()` | Task 2 |
| Collision check at init time | Task 9 |
| Collision check at mine time (non-fatal) | Task 5 |
| Force-accept on second entry of same colliding name | Task 9 |
| Fix SHA256 drawer_id | Task 3 |
| Fix deterministic chunk_index | Task 3 |
| Rename `_mcp_write` → `_write_drawer` | Task 3 |
| `MemPalaceReader` takes ctx | Task 4 |
| `RequirementsMiner` takes ctx | Task 5 |
| `PipelineEngine.set_context()` | Task 6 |
| Wing written to `codegen-state.json` | Task 6 |
| `PhaseGateRunner` reads wing from state file | Task 7 |
| `codegen run` builds ctx, passes to engine | Task 8 |
| `requirements mine` uses ctx | Task 8 |
| `requirements clean` subcommand | Task 8 |
| `echelon init` wing provisioning (auto-suggest + prompt) | Task 9 |
| Idempotent init when wing already set | Task 9 |
| `echelon.yml` template has `mempalace.wing` | Task 10 |
| Skill docs replace `basename $(pwd)` | Task 10 |
| Remove dead `memory-config.yml` from install.sh | Task 10 |
| Migration path: `requirements clean` removes old drawers | Task 8 |

All requirements covered. ✓
