# Normal Pipeline MemPalace Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build normal-pipeline `echelon spec memory mine|audit|refresh` support that proves canonical spec requirements are present and current in MemPalace before graph-engineering work begins.

**Architecture:** Add an Echelon-owned requirement memory service that delegates deterministic parsing, drawer IDs, writing, and postimage verification to the existing `RequirementsMiner` path. Add a separate audit service that consumes the same expected drawer plan and inspects MemPalace by exact deterministic IDs, then expose it through the Typer CLI and route existing Phase A mining through the shared service.

**Tech Stack:** Python 3, Typer, pytest, existing `codegen.memory` MemPalace primitives, `echelon.context_reconciliation`, canonical `specs/<id>/spec.md` artifacts.

## Global Constraints

- Public normal-pipeline commands live under `echelon`, not `codegen`.
- Do not introduce a second requirement parser, drawer identity algorithm, or Phase A mining side effect.
- Expected drawers must come from the same canonical planner used before mining.
- `mine` and `refresh` are additive and idempotent; they must not overwrite drifted deterministic drawers.
- `audit` is read-only by default and must not use semantic search as storage proof.
- Automatic normal-pipeline integration defaults to `off`; no existing spec run is blocked in this slice.
- MemPalace unavailability is reported as `unavailable` with exit code `2`, not as a failed spec.
- Do not delete or auto-clean drawers during audit.
- Do not design or implement the graph schema in this slice.

---

## File Structure

- Create `src/echelon/mempalace_requirements.py`: canonical spec selector, artifact metadata builder, expected drawer planning, mining, postimage verification, and report dataclasses for normal Echelon.
- Create `src/echelon/mempalace_audit.py`: exact drawer inspection, reconciliation classification, optional retrieval probes, JSON/Markdown report rendering.
- Modify `src/echelon/cli_app.py`: add `spec memory` Typer subgroup and commands.
- Modify `src/harness/squad_completion.py`: route completion mining factory through the Echelon requirement memory service while preserving existing receipt behavior.
- Modify `src/harness/squad.py`: route `_mine_published_spec_best_effort()` through the Echelon requirement memory service.
- Create `tests/unit/test_mempalace_requirements.py`: selector, planning, mining result mapping, and drift behavior with fakes.
- Create `tests/unit/test_mempalace_audit.py`: exact inspection classification and report status ordering.
- Create `tests/unit/test_cli_spec_memory.py`: Typer command exposure, JSON output, and exit code mapping.
- Modify `tests/unit/test_squad_completion.py`: add coverage that the default completion miner factory returns the shared service adapter.
- Modify `tests/integration/test_squad_context_memory.py`: update mocks to patch the Echelon service path instead of direct `RequirementsMiner` where behavior is normal-pipeline owned.
- Create `docs/mempalace.md`: document manual `refresh` and `audit` workflow.

---

### Task 1: Shared Requirement Memory Service

**Files:**
- Create: `src/echelon/mempalace_requirements.py`
- Test: `tests/unit/test_mempalace_requirements.py`

**Interfaces:**
- Consumes: `codegen.memory.context.MemPalaceContext.from_project`, `codegen.memory.requirements_miner.RequirementsMiner`, `codegen.memory.requirements_miner.plan_canonical_requirement_drawer_ids`, `echelon.context_metadata.artifact_hash`
- Produces:
  - `resolve_spec_dir(project_root: Path, selector: str) -> Path`
  - `load_canonical_spec_snapshot(project_root: Path, spec_dir: Path) -> CanonicalSpecSnapshot`
  - `create_requirement_memory_adapter(project_root: Path, run_id: str) -> RequirementMemoryAdapter`
  - `RequirementMemoryAdapter.plan_canonical_bytes(content: bytes, *, source: str, artifact_metadata: dict[str, Any]) -> list[str]`
  - `RequirementMemoryAdapter.mine_canonical_bytes(content: bytes, *, source: str, artifact_metadata: dict[str, Any]) -> MineResult`
  - `RequirementMemoryAdapter.verify_canonical_bytes(content: bytes, *, source: str, artifact_metadata: dict[str, Any], drawer_ids: list[str]) -> bool`
  - `mine_spec_requirements(project_root: Path, spec_selector: str | Path, *, run_id: str) -> SpecMemoryMineReport`

- [ ] **Step 1: Write selector and snapshot tests**

Add `tests/unit/test_mempalace_requirements.py`:

```python
from pathlib import Path

import pytest


def write_workspace(tmp_path: Path) -> Path:
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "mempalace:\n  wing: demo-wing\n",
        encoding="utf-8",
    )
    spec_dir = tmp_path / "specs" / "003-demo"
    spec_dir.mkdir(parents=True)
    spec_dir.joinpath("spec.md").write_text(
        "# Demo\n\nFR-001: Upload a photo.\nNFR-001: Respond within 1s.\n",
        encoding="utf-8",
    )
    return spec_dir


@pytest.mark.unit
def test_resolve_spec_dir_accepts_id_slug_and_path(tmp_path: Path) -> None:
    spec_dir = write_workspace(tmp_path)
    from echelon.mempalace_requirements import resolve_spec_dir

    assert resolve_spec_dir(tmp_path, "003") == spec_dir
    assert resolve_spec_dir(tmp_path, "003-demo") == spec_dir
    assert resolve_spec_dir(tmp_path, "specs/003-demo") == spec_dir


@pytest.mark.unit
def test_resolve_spec_dir_rejects_run_local_path(tmp_path: Path) -> None:
    run_spec = tmp_path / "runs" / "abc" / "specs" / "003-demo"
    run_spec.mkdir(parents=True)
    run_spec.joinpath("spec.md").write_text("FR-001: Draft.\n", encoding="utf-8")
    from echelon.mempalace_requirements import SpecMemoryError, resolve_spec_dir

    with pytest.raises(SpecMemoryError, match="run-local specs are not supported"):
        resolve_spec_dir(tmp_path, "runs/abc/specs/003-demo")


@pytest.mark.unit
def test_snapshot_contains_canonical_artifact_metadata(tmp_path: Path) -> None:
    spec_dir = write_workspace(tmp_path)
    from echelon.mempalace_requirements import load_canonical_spec_snapshot

    snapshot = load_canonical_spec_snapshot(tmp_path, spec_dir)

    assert snapshot.source == "specs/003-demo/spec.md"
    assert snapshot.artifact_metadata["canonical"] is True
    assert snapshot.artifact_metadata["scope"] == "canonical"
    assert snapshot.artifact_metadata["artifact_path"] == "specs/003-demo/spec.md"
    assert snapshot.artifact_metadata["artifact_hash"].startswith("sha256:")
    assert snapshot.artifact_metadata["added_by"] == "echelon"
```

- [ ] **Step 2: Run selector tests to verify they fail**

Run:

```bash
pytest tests/unit/test_mempalace_requirements.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'echelon.mempalace_requirements'`.

- [ ] **Step 3: Implement selector and snapshot dataclasses**

Create `src/echelon/mempalace_requirements.py` with this initial structure:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import hashlib
from typing import Any


class SpecMemoryError(RuntimeError):
    """Bounded operator-facing error for spec memory commands."""


@dataclass(frozen=True)
class CanonicalSpecSnapshot:
    spec_id: str
    spec_dir: Path
    spec_file: Path
    content: bytes
    spec_sha256: str
    source: str
    artifact_metadata: dict[str, Any]


@dataclass(frozen=True)
class PlannedRequirementDrawer:
    drawer_id: str
    requirement_id: str | None
    room: str | None
    source: str
    artifact_hash: str


@dataclass(frozen=True)
class SpecMemoryMineReport:
    schema_version: int
    spec_id: str
    spec_dir: str
    wing: str | None
    palace_path: str | None
    status: str
    expected_count: int
    written_count: int
    adopted_count: int
    skipped_count: int
    failed_count: int
    drifted_count: int
    drawer_ids: list[str] = field(default_factory=list)
    expected_drawer_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "spec_id": self.spec_id,
            "spec_dir": self.spec_dir,
            "wing": self.wing,
            "palace_path": self.palace_path,
            "status": self.status,
            "expected_count": self.expected_count,
            "written_count": self.written_count,
            "adopted_count": self.adopted_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "drifted_count": self.drifted_count,
            "drawer_ids": list(self.drawer_ids),
            "expected_drawer_ids": list(self.expected_drawer_ids),
            "errors": list(self.errors),
        }


def resolve_spec_dir(project_root: Path, selector: str | Path) -> Path:
    root = project_root.resolve()
    raw = Path(str(selector))
    if raw.is_absolute():
        try:
            rel = raw.resolve().relative_to(root)
        except ValueError as exc:
            raise SpecMemoryError("spec selector is outside the project") from exc
    else:
        rel = raw
    if rel.parts and rel.parts[0] == "runs":
        raise SpecMemoryError("run-local specs are not supported by default")
    specs_root = root / "specs"
    candidates: list[Path]
    if len(rel.parts) >= 2 and rel.parts[0] == "specs":
        candidates = [root / rel]
    elif len(rel.parts) == 1 and str(selector).isdigit():
        candidates = sorted(specs_root.glob(f"{selector}-*"))
    elif len(rel.parts) == 1:
        candidates = [specs_root / rel.parts[0]]
    else:
        raise SpecMemoryError("spec selector must be a canonical specs/<id> path or spec id")
    matches = [path for path in candidates if path.is_dir() and path.joinpath("spec.md").is_file()]
    if len(matches) != 1:
        raise SpecMemoryError(f"could not resolve one canonical spec for {selector}")
    return matches[0]


def load_canonical_spec_snapshot(project_root: Path, spec_dir: Path) -> CanonicalSpecSnapshot:
    root = project_root.resolve()
    resolved_dir = spec_dir.resolve()
    try:
        relative_dir = resolved_dir.relative_to(root)
    except ValueError as exc:
        raise SpecMemoryError("spec directory is outside the project") from exc
    if len(relative_dir.parts) != 2 or relative_dir.parts[0] != "specs":
        raise SpecMemoryError("spec directory must be under canonical specs/")
    spec_file = resolved_dir / "spec.md"
    content = spec_file.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    source = f"{relative_dir.as_posix()}/spec.md"
    return CanonicalSpecSnapshot(
        spec_id=relative_dir.parts[1],
        spec_dir=resolved_dir,
        spec_file=spec_file,
        content=content,
        spec_sha256=digest,
        source=source,
        artifact_metadata={
            "scope": "canonical",
            "canonical": True,
            "artifact_path": source,
            "artifact_hash": f"sha256:{digest}",
            "source_file": source,
            "lifecycle_status": "active",
            "provenance_type": "requirements_mine",
            "added_by": "echelon",
        },
    )
```

- [ ] **Step 4: Run selector tests to verify they pass**

Run:

```bash
pytest tests/unit/test_mempalace_requirements.py -q
```

Expected: PASS.

- [ ] **Step 5: Write adapter and mining report tests**

Append to `tests/unit/test_mempalace_requirements.py`:

```python
@pytest.mark.unit
def test_adapter_plan_matches_existing_canonical_miner(tmp_path: Path, monkeypatch) -> None:
    spec_dir = write_workspace(tmp_path)
    from codegen.memory.requirements_miner import plan_canonical_requirement_drawer_ids
    from echelon.mempalace_requirements import (
        create_requirement_memory_adapter,
        load_canonical_spec_snapshot,
    )

    snapshot = load_canonical_spec_snapshot(tmp_path, spec_dir)
    adapter = create_requirement_memory_adapter(tmp_path, run_id="manual")

    assert adapter.plan_canonical_bytes(
        snapshot.content,
        source=snapshot.source,
        artifact_metadata=snapshot.artifact_metadata,
    ) == plan_canonical_requirement_drawer_ids(
        snapshot.content,
        source=snapshot.source,
        artifact_metadata=snapshot.artifact_metadata,
        wing="demo-wing",
    )


@pytest.mark.unit
def test_mine_spec_requirements_maps_drift_without_overwrite(tmp_path: Path, monkeypatch) -> None:
    spec_dir = write_workspace(tmp_path)

    class FakeResult:
        total = 2
        written = 1
        already_present = 0
        skipped = 0
        failed = 1
        unavailable = 0
        drawer_ids = ["drawer-ok"]
        expected_drawer_ids = ["drawer-ok", "drawer-drift"]
        errors = ["deterministic_write_failed"]

    class FakeAdapter:
        wing = "demo-wing"
        palace_path = tmp_path / ".mempalace"

        def mine_canonical_bytes(self, content, *, source, artifact_metadata):
            return FakeResult()

    monkeypatch.setattr(
        "echelon.mempalace_requirements.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(),
    )
    from echelon.mempalace_requirements import mine_spec_requirements

    report = mine_spec_requirements(tmp_path, spec_dir, run_id="manual")

    assert report.status == "partial"
    assert report.written_count == 1
    assert report.drifted_count == 1
    assert report.expected_drawer_ids == ["drawer-ok", "drawer-drift"]
```

- [ ] **Step 6: Run adapter tests to verify they fail**

Run:

```bash
pytest tests/unit/test_mempalace_requirements.py -q
```

Expected: FAIL because `create_requirement_memory_adapter()` and `mine_spec_requirements()` are undefined.

- [ ] **Step 7: Implement adapter and mine report mapping**

Append to `src/echelon/mempalace_requirements.py`:

```python
class RequirementMemoryAdapter:
    def __init__(self, project_root: Path, run_id: str) -> None:
        from codegen.memory.context import MemPalaceContext
        from codegen.memory.requirements_miner import RequirementsMiner

        self.context = MemPalaceContext.from_project(project_root, run_id=run_id)
        self.miner = RequirementsMiner(self.context, project_dir=project_root)
        self.wing = self.context.wing
        self.palace_path = self.context.palace_path

    def plan_canonical_bytes(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> list[str]:
        return self.miner.plan_canonical_bytes(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
        )

    def mine_canonical_bytes(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> object:
        return self.miner.mine_canonical_bytes(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
        )

    def verify_canonical_bytes(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
        drawer_ids: list[str],
    ) -> bool:
        return self.miner.verify_canonical_bytes(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
            drawer_ids=drawer_ids,
        )


def create_requirement_memory_adapter(project_root: Path, run_id: str) -> RequirementMemoryAdapter:
    return RequirementMemoryAdapter(project_root, run_id)


def _read_int(result: object, name: str) -> int:
    value = getattr(result, name, 0)
    if type(value) is not int or value < 0:
        return 0
    return value


def _read_str_list(result: object, name: str) -> list[str]:
    value = getattr(result, name, [])
    if type(value) is not list or any(type(item) is not str for item in value):
        return []
    return sorted(set(value))


def mine_spec_requirements(
    project_root: Path,
    spec_selector: str | Path,
    *,
    run_id: str,
) -> SpecMemoryMineReport:
    spec_dir = resolve_spec_dir(project_root, spec_selector)
    snapshot = load_canonical_spec_snapshot(project_root, spec_dir)
    try:
        adapter = create_requirement_memory_adapter(project_root, run_id)
    except Exception as exc:
        return SpecMemoryMineReport(
            schema_version=1,
            spec_id=snapshot.spec_id,
            spec_dir=str(snapshot.spec_dir),
            wing=None,
            palace_path=None,
            status="unavailable",
            expected_count=0,
            written_count=0,
            adopted_count=0,
            skipped_count=0,
            failed_count=0,
            drifted_count=0,
            errors=[type(exc).__name__],
        )
    result = adapter.mine_canonical_bytes(
        snapshot.content,
        source=snapshot.source,
        artifact_metadata=snapshot.artifact_metadata,
    )
    expected = _read_str_list(result, "expected_drawer_ids")
    drawer_ids = _read_str_list(result, "drawer_ids")
    written = _read_int(result, "written")
    adopted = _read_int(result, "already_present")
    skipped = _read_int(result, "skipped")
    failed = _read_int(result, "failed")
    unavailable = _read_int(result, "unavailable")
    drifted = max(0, len(expected) - len(drawer_ids) - unavailable)
    status = "complete"
    if unavailable and not drawer_ids:
        status = "unavailable"
    elif failed or drifted or unavailable:
        status = "partial"
    return SpecMemoryMineReport(
        schema_version=1,
        spec_id=snapshot.spec_id,
        spec_dir=str(snapshot.spec_dir),
        wing=str(getattr(adapter, "wing", "")) or None,
        palace_path=str(getattr(adapter, "palace_path", "")) or None,
        status=status,
        expected_count=len(expected),
        written_count=written,
        adopted_count=adopted,
        skipped_count=skipped,
        failed_count=failed,
        drifted_count=drifted,
        drawer_ids=drawer_ids,
        expected_drawer_ids=expected,
        errors=[str(error) for error in getattr(result, "errors", []) if isinstance(error, str)],
    )
```

- [ ] **Step 8: Run service tests**

Run:

```bash
pytest tests/unit/test_mempalace_requirements.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit shared service**

Run:

```bash
git add src/echelon/mempalace_requirements.py tests/unit/test_mempalace_requirements.py
git commit -m "feat: add normal spec memory requirement service"
```

Expected: commit succeeds.

---

### Task 2: Exact MemPalace Audit Service

**Files:**
- Create: `src/echelon/mempalace_audit.py`
- Test: `tests/unit/test_mempalace_audit.py`

**Interfaces:**
- Consumes: `load_canonical_spec_snapshot()`, `create_requirement_memory_adapter()`, `echelon.context_reconciliation.reconcile_drawers()`
- Produces:
  - `SpecMemoryAuditReport.to_dict() -> dict[str, Any]`
  - `audit_spec_memory(project_root: Path, spec_selector: str | Path, *, probe_retrieval: bool = False) -> SpecMemoryAuditReport`
  - `render_audit_markdown(report: SpecMemoryAuditReport) -> str`
  - `write_audit_reports(report: SpecMemoryAuditReport, spec_dir: Path) -> tuple[Path, Path]`

- [ ] **Step 1: Write exact inspection classification tests**

Create `tests/unit/test_mempalace_audit.py`:

```python
from pathlib import Path

import pytest


def make_spec(tmp_path: Path) -> Path:
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "mempalace:\n  wing: demo-wing\n",
        encoding="utf-8",
    )
    spec_dir = tmp_path / "specs" / "003-demo"
    spec_dir.mkdir(parents=True)
    spec_dir.joinpath("spec.md").write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    return spec_dir


class FakeCollection:
    def __init__(self, rows):
        self.rows = rows

    def get(self, ids=None, where=None, include=None):
        if ids is not None:
            found = [(drawer_id, self.rows[drawer_id]) for drawer_id in ids if drawer_id in self.rows]
            return {
                "ids": [drawer_id for drawer_id, _row in found],
                "documents": [row["document"] for _drawer_id, row in found],
                "metadatas": [row["metadata"] for _drawer_id, row in found],
            }
        return {"ids": [], "documents": [], "metadatas": []}


class FakeAdapter:
    wing = "demo-wing"
    palace_path = Path(".mempalace")

    def __init__(self, collection):
        self.collection = collection

    def plan_canonical_bytes(self, content, *, source, artifact_metadata):
        return ["drawer-fr-001"]


@pytest.mark.unit
def test_audit_reports_missing_exact_drawer(tmp_path: Path, monkeypatch) -> None:
    spec_dir = make_spec(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(FakeCollection({})),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "fail"
    assert report.expected_count == 1
    assert report.missing == ["drawer-fr-001"]


@pytest.mark.unit
def test_audit_passes_matching_exact_drawer(tmp_path: Path, monkeypatch) -> None:
    spec_dir = make_spec(tmp_path)
    from echelon.mempalace_requirements import load_canonical_spec_snapshot

    snapshot = load_canonical_spec_snapshot(tmp_path, spec_dir)
    rows = {
        "drawer-fr-001": {
            "document": "FR-001: Upload a photo.",
            "metadata": {
                "wing": "demo-wing",
                "room": "functional-requirements",
                "canonical": True,
                "artifact_path": snapshot.source,
                "artifact_hash": snapshot.artifact_metadata["artifact_hash"],
                "requirement_id": "FR-001",
                "requirement_content_sha256": "content-hash",
                "lifecycle_status": "active",
            },
        }
    }
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(FakeCollection(rows)),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "pass"
    assert report.present_current_count == 1
    assert report.missing == []


@pytest.mark.unit
def test_audit_classifies_wrong_wing_and_stale_hash(tmp_path: Path, monkeypatch) -> None:
    spec_dir = make_spec(tmp_path)
    rows = {
        "drawer-fr-001": {
            "document": "FR-001: Upload a photo.",
            "metadata": {
                "wing": "wrong-wing",
                "room": "functional-requirements",
                "canonical": True,
                "artifact_path": "specs/003-demo/spec.md",
                "artifact_hash": "sha256:" + "0" * 64,
                "requirement_id": "FR-001",
                "lifecycle_status": "active",
            },
        }
    }
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(FakeCollection(rows)),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "fail"
    assert report.wrong_wing == ["drawer-fr-001"]
    assert report.stale == ["drawer-fr-001"]
```

- [ ] **Step 2: Run audit tests to verify they fail**

Run:

```bash
pytest tests/unit/test_mempalace_audit.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'echelon.mempalace_audit'`.

- [ ] **Step 3: Implement audit dataclasses and exact inspection**

Create `src/echelon/mempalace_audit.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
from typing import Any

from echelon.mempalace_requirements import (
    SpecMemoryError,
    create_requirement_memory_adapter,
    load_canonical_spec_snapshot,
    resolve_spec_dir,
)


@dataclass(frozen=True)
class SpecMemoryAuditReport:
    schema_version: int
    spec_id: str
    spec_dir: str
    wing: str | None
    palace_path: str | None
    status: str
    expected_count: int
    present_current_count: int
    missing: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    wrong_wing: list[str] = field(default_factory=list)
    wrong_room: list[str] = field(default_factory=list)
    duplicate: list[str] = field(default_factory=list)
    non_canonical: list[str] = field(default_factory=list)
    lifecycle_excluded: list[str] = field(default_factory=list)
    retrieval_probe: dict[str, Any] | None = None
    recommendations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "spec_id": self.spec_id,
            "spec_dir": self.spec_dir,
            "wing": self.wing,
            "palace_path": self.palace_path,
            "status": self.status,
            "expected_count": self.expected_count,
            "present_current_count": self.present_current_count,
            "missing": list(self.missing),
            "stale": list(self.stale),
            "wrong_wing": list(self.wrong_wing),
            "wrong_room": list(self.wrong_room),
            "duplicate": list(self.duplicate),
            "non_canonical": list(self.non_canonical),
            "lifecycle_excluded": list(self.lifecycle_excluded),
            "retrieval_probe": self.retrieval_probe,
            "recommendations": list(self.recommendations),
            "errors": list(self.errors),
        }


def _collection_from_adapter(adapter: object) -> object:
    collection = getattr(adapter, "collection", None)
    if collection is not None:
        return collection
    miner = getattr(adapter, "miner", None)
    writer = getattr(miner, "_get_writer", lambda: None)()
    getter = getattr(writer, "_get_collection", None)
    if callable(getter):
        return getter()
    raise SpecMemoryError("MemPalace collection is unavailable")


def _as_collection_rows(raw: object) -> dict[str, tuple[str, dict[str, Any]]]:
    if type(raw) is not dict:
        return {}
    ids = raw.get("ids")
    documents = raw.get("documents")
    metadatas = raw.get("metadatas")
    if type(ids) is not list or type(documents) is not list or type(metadatas) is not list:
        return {}
    result: dict[str, tuple[str, dict[str, Any]]] = {}
    for drawer_id, document, metadata in zip(ids, documents, metadatas):
        if type(drawer_id) is str and type(document) is str and type(metadata) is dict:
            result[drawer_id] = (document, metadata)
    return result


def _status_for_failures(report: SpecMemoryAuditReport) -> str:
    fail_lists = (
        report.missing,
        report.stale,
        report.wrong_wing,
        report.wrong_room,
        report.non_canonical,
        report.lifecycle_excluded,
    )
    if any(fail_lists):
        return "fail"
    if report.duplicate or (report.retrieval_probe or {}).get("status") == "warn":
        return "warn"
    return "pass"


def audit_spec_memory(
    project_root: Path,
    spec_selector: str | Path,
    *,
    probe_retrieval: bool = False,
) -> SpecMemoryAuditReport:
    spec_dir = resolve_spec_dir(project_root, spec_selector)
    snapshot = load_canonical_spec_snapshot(project_root, spec_dir)
    try:
        adapter = create_requirement_memory_adapter(project_root, run_id="audit")
        expected = adapter.plan_canonical_bytes(
            snapshot.content,
            source=snapshot.source,
            artifact_metadata=snapshot.artifact_metadata,
        )
        collection = _collection_from_adapter(adapter)
        raw = collection.get(ids=expected, include=["documents", "metadatas"])
    except Exception as exc:
        return SpecMemoryAuditReport(
            schema_version=1,
            spec_id=snapshot.spec_id,
            spec_dir=str(snapshot.spec_dir),
            wing=None,
            palace_path=None,
            status="unavailable",
            expected_count=0,
            present_current_count=0,
            errors=[type(exc).__name__],
        )
    rows = _as_collection_rows(raw)
    missing = [drawer_id for drawer_id in expected if drawer_id not in rows]
    stale: list[str] = []
    wrong_wing: list[str] = []
    wrong_room: list[str] = []
    non_canonical: list[str] = []
    lifecycle_excluded: list[str] = []
    present = 0
    for drawer_id in expected:
        row = rows.get(drawer_id)
        if row is None:
            continue
        _document, metadata = row
        if metadata.get("wing") != getattr(adapter, "wing", None):
            wrong_wing.append(drawer_id)
        if metadata.get("room") not in {"functional-requirements", "non-functional-requirements", "acceptance-criteria", "user-stories"}:
            wrong_room.append(drawer_id)
        if metadata.get("canonical") is not True:
            non_canonical.append(drawer_id)
        if metadata.get("artifact_hash") != snapshot.artifact_metadata["artifact_hash"]:
            stale.append(drawer_id)
        if metadata.get("lifecycle_status", metadata.get("status", "active")) in {"deprecated", "superseded", "removed", "delivered"}:
            lifecycle_excluded.append(drawer_id)
        if drawer_id not in stale and drawer_id not in wrong_wing and drawer_id not in wrong_room and drawer_id not in non_canonical and drawer_id not in lifecycle_excluded:
            present += 1
    report = SpecMemoryAuditReport(
        schema_version=1,
        spec_id=snapshot.spec_id,
        spec_dir=str(snapshot.spec_dir),
        wing=str(getattr(adapter, "wing", "")) or None,
        palace_path=str(getattr(adapter, "palace_path", "")) or None,
        status="pass",
        expected_count=len(expected),
        present_current_count=present,
        missing=missing,
        stale=stale,
        wrong_wing=wrong_wing,
        wrong_room=wrong_room,
        non_canonical=non_canonical,
        lifecycle_excluded=lifecycle_excluded,
        retrieval_probe={"status": "skipped"} if not probe_retrieval else {"status": "warn", "checked": 0},
    )
    return SpecMemoryAuditReport(**{**report.to_dict(), "status": _status_for_failures(report)})


def render_audit_markdown(report: SpecMemoryAuditReport) -> str:
    lines = [
        f"# MemPalace Audit: {report.spec_id}",
        "",
        f"- Status: {report.status}",
        f"- Expected drawers: {report.expected_count}",
        f"- Present current drawers: {report.present_current_count}",
        f"- Missing: {len(report.missing)}",
        f"- Stale: {len(report.stale)}",
        f"- Wrong wing: {len(report.wrong_wing)}",
    ]
    return "\n".join(lines) + "\n"


def write_audit_reports(report: SpecMemoryAuditReport, spec_dir: Path) -> tuple[Path, Path]:
    json_path = spec_dir / "mempalace-audit.json"
    md_path = spec_dir / "mempalace-audit.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_audit_markdown(report), encoding="utf-8")
    return json_path, md_path
```

- [ ] **Step 4: Run audit tests**

Run:

```bash
pytest tests/unit/test_mempalace_audit.py -q
```

Expected: PASS.

- [ ] **Step 5: Add report rendering test**

Append to `tests/unit/test_mempalace_audit.py`:

```python
@pytest.mark.unit
def test_write_audit_reports_are_stable(tmp_path: Path) -> None:
    from echelon.mempalace_audit import SpecMemoryAuditReport, write_audit_reports

    spec_dir = tmp_path / "specs" / "003-demo"
    spec_dir.mkdir(parents=True)
    report = SpecMemoryAuditReport(
        schema_version=1,
        spec_id="003-demo",
        spec_dir=str(spec_dir),
        wing="demo-wing",
        palace_path=".mempalace",
        status="pass",
        expected_count=1,
        present_current_count=1,
    )

    json_path, md_path = write_audit_reports(report, spec_dir)

    assert json_path.read_text(encoding="utf-8").startswith("{\n")
    assert "MemPalace Audit: 003-demo" in md_path.read_text(encoding="utf-8")
```

- [ ] **Step 6: Run audit service tests**

Run:

```bash
pytest tests/unit/test_mempalace_audit.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit audit service**

Run:

```bash
git add src/echelon/mempalace_audit.py tests/unit/test_mempalace_audit.py
git commit -m "feat: add exact spec memory audit service"
```

Expected: commit succeeds.

---

### Task 3: Typer CLI Commands

**Files:**
- Modify: `src/echelon/cli_app.py`
- Test: `tests/unit/test_cli_spec_memory.py`

**Interfaces:**
- Consumes: `mine_spec_requirements()`, `audit_spec_memory()`, `write_audit_reports()`
- Produces:
  - `echelon spec memory mine <spec-id-or-path> [--write-report]`
  - `echelon spec memory audit <spec-id-or-path> [--json] [--write] [--probe-retrieval]`
  - `echelon spec memory refresh <spec-id-or-path> [--audit] [--write]`

- [ ] **Step 1: Write CLI tests**

Create `tests/unit/test_cli_spec_memory.py`:

```python
from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.mark.unit
def test_spec_memory_help_is_exposed() -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "--help"])

    assert result.exit_code == 0
    assert "mine" in result.output
    assert "audit" in result.output
    assert "refresh" in result.output


@pytest.mark.unit
def test_spec_memory_audit_json_exit_zero_for_warn(monkeypatch, tmp_path: Path) -> None:
    from echelon.mempalace_audit import SpecMemoryAuditReport

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_audit.audit_spec_memory",
        lambda project_root, selector, probe_retrieval=False: SpecMemoryAuditReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="warn",
            expected_count=1,
            present_current_count=1,
        ),
        raising=False,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "audit", "003-demo", "--json"])

    assert result.exit_code == 0
    assert '"status": "warn"' in result.output


@pytest.mark.unit
def test_spec_memory_audit_exit_codes(monkeypatch, tmp_path: Path) -> None:
    from echelon.mempalace_audit import SpecMemoryAuditReport

    monkeypatch.chdir(tmp_path)

    def fake_audit(project_root, selector, probe_retrieval=False):
        return SpecMemoryAuditReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing=None,
            palace_path=None,
            status="unavailable",
            expected_count=0,
            present_current_count=0,
        )

    monkeypatch.setattr("echelon.mempalace_audit.audit_spec_memory", fake_audit, raising=False)
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "audit", "003-demo"])

    assert result.exit_code == 2


@pytest.mark.unit
def test_spec_memory_refresh_runs_mine_then_audit(monkeypatch, tmp_path: Path) -> None:
    from echelon.mempalace_audit import SpecMemoryAuditReport
    from echelon.mempalace_requirements import SpecMemoryMineReport

    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_requirements.mine_spec_requirements",
        lambda project_root, selector, run_id: calls.append(("mine", selector)) or SpecMemoryMineReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="complete",
            expected_count=1,
            written_count=1,
            adopted_count=0,
            skipped_count=0,
            failed_count=0,
            drifted_count=0,
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "echelon.mempalace_audit.audit_spec_memory",
        lambda project_root, selector, probe_retrieval=False: calls.append(("audit", selector)) or SpecMemoryAuditReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="pass",
            expected_count=1,
            present_current_count=1,
        ),
        raising=False,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "refresh", "003-demo"])

    assert result.exit_code == 0
    assert calls == [("mine", "003-demo"), ("audit", "003-demo")]
```

- [ ] **Step 2: Run CLI tests to verify they fail**

Run:

```bash
pytest tests/unit/test_cli_spec_memory.py -q
```

Expected: FAIL because `spec memory` is not registered.

- [ ] **Step 3: Register command group and commands**

Modify `src/echelon/cli_app.py` near existing Typer group declarations:

```python
spec_memory_app = typer.Typer(
    add_completion=False,
    help="Mine and audit canonical spec requirements in MemPalace.",
    no_args_is_help=True,
)
```

Register it near `spec_app.add_typer(spec_checkpoint_app, name="checkpoint")`:

```python
spec_app.add_typer(spec_memory_app, name="memory")
```

Add helpers and commands below the existing spec command section imports:

```python
def _memory_exit_code(status: str) -> int:
    if status in {"pass", "warn", "complete"}:
        return 0
    if status in {"fail", "partial"}:
        return 1
    return 2


def _echo_json(data: dict) -> None:
    import json

    typer.echo(json.dumps(data, indent=2, sort_keys=True))


@spec_memory_app.command("mine")
def spec_memory_mine(
    spec_selector: str,
    write_report: bool = typer.Option(False, "--write-report"),
) -> None:
    from echelon.mempalace_requirements import mine_spec_requirements

    report = mine_spec_requirements(Path.cwd(), spec_selector, run_id="manual")
    typer.echo(
        f"MemPalace mine {report.status}: expected={report.expected_count} "
        f"written={report.written_count} adopted={report.adopted_count} "
        f"drifted={report.drifted_count} failed={report.failed_count}"
    )
    if write_report:
        spec_dir = Path(report.spec_dir)
        spec_dir.joinpath("mempalace-mine.json").write_text(
            __import__("json").dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    raise typer.Exit(code=_memory_exit_code(report.status))


@spec_memory_app.command("audit")
def spec_memory_audit(
    spec_selector: str,
    as_json: bool = typer.Option(False, "--json"),
    write: bool = typer.Option(False, "--write"),
    probe_retrieval: bool = typer.Option(False, "--probe-retrieval"),
) -> None:
    from echelon.mempalace_audit import audit_spec_memory, render_audit_markdown, write_audit_reports

    report = audit_spec_memory(Path.cwd(), spec_selector, probe_retrieval=probe_retrieval)
    if write and report.status != "unavailable":
        write_audit_reports(report, Path(report.spec_dir))
    if as_json:
        _echo_json(report.to_dict())
    else:
        typer.echo(render_audit_markdown(report).rstrip())
    raise typer.Exit(code=_memory_exit_code(report.status))


@spec_memory_app.command("refresh")
def spec_memory_refresh(
    spec_selector: str,
    audit: bool = typer.Option(True, "--audit/--no-audit"),
    write: bool = typer.Option(False, "--write"),
) -> None:
    from echelon.mempalace_audit import audit_spec_memory, render_audit_markdown, write_audit_reports
    from echelon.mempalace_requirements import mine_spec_requirements

    mine_report = mine_spec_requirements(Path.cwd(), spec_selector, run_id="manual")
    typer.echo(
        f"MemPalace mine {mine_report.status}: expected={mine_report.expected_count} "
        f"written={mine_report.written_count} adopted={mine_report.adopted_count} "
        f"drifted={mine_report.drifted_count} failed={mine_report.failed_count}"
    )
    if not audit:
        raise typer.Exit(code=_memory_exit_code(mine_report.status))
    audit_report = audit_spec_memory(Path.cwd(), spec_selector)
    if write and audit_report.status != "unavailable":
        write_audit_reports(audit_report, Path(audit_report.spec_dir))
    typer.echo(render_audit_markdown(audit_report).rstrip())
    raise typer.Exit(code=max(_memory_exit_code(mine_report.status), _memory_exit_code(audit_report.status)))
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
pytest tests/unit/test_cli_spec_memory.py -q
```

Expected: PASS.

- [ ] **Step 5: Run existing Typer front-door tests**

Run:

```bash
pytest tests/unit/test_cli_typer_app.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit CLI commands**

Run:

```bash
git add src/echelon/cli_app.py tests/unit/test_cli_spec_memory.py
git commit -m "feat: expose normal spec memory commands"
```

Expected: commit succeeds.

---

### Task 4: Route Existing Normal Mining Through Shared Service

**Files:**
- Modify: `src/harness/squad_completion.py`
- Modify: `src/harness/squad.py`
- Modify: `tests/unit/test_squad_completion.py`
- Modify: `tests/integration/test_squad_context_memory.py`

**Interfaces:**
- Consumes: `create_requirement_memory_adapter(project_root: Path, run_id: str)`
- Produces: unchanged public behavior for `apply_or_verify_completion_mining()` and `_mine_published_spec_best_effort()`

- [ ] **Step 1: Add completion factory test**

Append to `tests/unit/test_squad_completion.py`:

```python
def test_default_completion_miner_factory_uses_echelon_requirement_adapter(monkeypatch, tmp_path):
    from harness import squad_completion as completion_module

    calls = []
    sentinel = object()
    monkeypatch.setattr(
        "echelon.mempalace_requirements.create_requirement_memory_adapter",
        lambda project_root, run_id: calls.append((project_root, run_id)) or sentinel,
    )

    result = completion_module._default_completion_miner_factory(tmp_path, "run-123")

    assert result is sentinel
    assert calls == [(tmp_path, "run-123")]
```

- [ ] **Step 2: Run focused completion test to verify it fails**

Run:

```bash
pytest tests/unit/test_squad_completion.py::test_default_completion_miner_factory_uses_echelon_requirement_adapter -q
```

Expected: FAIL because `_default_completion_miner_factory()` imports `RequirementsMiner` directly.

- [ ] **Step 3: Refactor completion factory**

Modify `src/harness/squad_completion.py` `_default_completion_miner_factory()`:

```python
def _default_completion_miner_factory(
    project_root: Path,
    run_id: str,
) -> object:
    from echelon.mempalace_requirements import create_requirement_memory_adapter

    return create_requirement_memory_adapter(project_root, run_id)
```

Keep `_completion_local_mining_plan()` unchanged so offline deterministic receipt checks still use `plan_canonical_requirement_drawer_ids()` without opening MemPalace.

- [ ] **Step 4: Run completion mining tests**

Run:

```bash
pytest tests/unit/test_squad_completion.py -q
```

Expected: PASS.

- [ ] **Step 5: Add published spec mining test**

In `tests/integration/test_squad_context_memory.py`, update the test that currently patches `codegen.memory.requirements_miner.RequirementsMiner` for published spec mining to patch `echelon.mempalace_requirements.create_requirement_memory_adapter` instead. The fake adapter must expose:

```python
class FakeAdapter:
    wing = "demo-wing"
    palace_path = ".mempalace"

    def mine_canonical_bytes(self, content, *, source, artifact_metadata):
        return MineResult(
            wing="demo-wing",
            total=1,
            written=1,
            skipped=0,
            failed=0,
            drawer_ids=["drawer-1"],
            expected_drawer_ids=["drawer-1"],
        )
```

Assert that the call receives `source == "specs/<id>/spec.md"` and `artifact_metadata["canonical"] is True`.

- [ ] **Step 6: Refactor published spec mining**

Modify `src/harness/squad.py` `_mine_published_spec_best_effort()` to import the shared adapter:

```python
from echelon.mempalace_requirements import create_requirement_memory_adapter
```

Replace the context and `RequirementsMiner` construction with:

```python
miner = create_requirement_memory_adapter(self._project_root, run_id)
```

Keep the existing result validation logic so return values remain `written`, `already_present`, `failed`, and `unavailable`.

- [ ] **Step 7: Run focused normal mining tests**

Run:

```bash
pytest tests/integration/test_squad_context_memory.py -q
pytest tests/unit/test_squad_completion.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit normal mining refactor**

Run:

```bash
git add src/harness/squad_completion.py src/harness/squad.py tests/unit/test_squad_completion.py tests/integration/test_squad_context_memory.py
git commit -m "refactor: route normal mempalace mining through echelon service"
```

Expected: commit succeeds.

---

### Task 5: Reports, Documentation, and Robust Error Boundaries

**Files:**
- Modify: `src/echelon/mempalace_requirements.py`
- Modify: `src/echelon/mempalace_audit.py`
- Modify: `src/echelon/cli_app.py`
- Create or modify: `docs/mempalace.md`
- Test: `tests/unit/test_mempalace_requirements.py`
- Test: `tests/unit/test_mempalace_audit.py`
- Test: `tests/unit/test_cli_spec_memory.py`

**Interfaces:**
- Consumes: report dataclasses from Tasks 1 and 2
- Produces: bounded errors, stable JSON/Markdown reports, documented manual workflow

- [ ] **Step 1: Add bounded error tests**

Append to `tests/unit/test_cli_spec_memory.py`:

```python
@pytest.mark.unit
def test_spec_memory_audit_invalid_selector_is_bounded(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "audit", "runs/x/specs/003-demo"])

    assert result.exit_code == 2
    assert "run-local specs are not supported" in result.output
    assert "Traceback" not in result.output
```

Append to `tests/unit/test_mempalace_audit.py`:

```python
@pytest.mark.unit
def test_unavailable_audit_reports_error_class_without_traceback(tmp_path: Path, monkeypatch) -> None:
    spec_dir = make_spec(tmp_path)

    def boom(project_root, run_id):
        raise RuntimeError("backend details")

    monkeypatch.setattr("echelon.mempalace_audit.create_requirement_memory_adapter", boom)
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "unavailable"
    assert report.errors == ["RuntimeError"]
```

- [ ] **Step 2: Run bounded error tests to verify current failures**

Run:

```bash
pytest tests/unit/test_cli_spec_memory.py::test_spec_memory_audit_invalid_selector_is_bounded tests/unit/test_mempalace_audit.py::test_unavailable_audit_reports_error_class_without_traceback -q
```

Expected: FAIL if the CLI surfaces an exception or writes traceback-like output.

- [ ] **Step 3: Add CLI error handling**

Wrap each `spec_memory_*` command body in `try/except SpecMemoryError`:

```python
from echelon.mempalace_requirements import SpecMemoryError

try:
    report = audit_spec_memory(Path.cwd(), spec_selector, probe_retrieval=probe_retrieval)
except SpecMemoryError as exc:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=2) from exc
```

Apply the same pattern for `mine` and `refresh`. Do not catch broad `Exception` in the CLI; service layers already convert MemPalace backend failures to `unavailable`.

- [ ] **Step 4: Add documentation**

Create `docs/mempalace.md`:

````markdown
# MemPalace In Echelon

Echelon uses MemPalace as a semantic retrieval layer for canonical specification requirements. The normal pipeline owns its public commands under `echelon spec memory`; `codegen requirements` remains an alternate pipeline compatibility surface.

## Manual Reconciliation

Run this after publishing or amending a canonical spec:

```bash
echelon spec memory refresh 003-my-feature --write
```

`refresh` writes missing exact canonical drawers, adopts exact existing drawers, and then audits the result. It does not overwrite drifted deterministic drawers and it does not delete stale drawers.

For read-only verification:

```bash
echelon spec memory audit 003-my-feature --json
```

Exit codes:

- `0`: pass, warn, or complete
- `1`: fail or partial
- `2`: unavailable memory backend or invalid invocation

Semantic retrieval probes are optional:

```bash
echelon spec memory audit 003-my-feature --probe-retrieval
```

Probe failures can warn about retrieval quality, but they are never storage proof.
````

- [ ] **Step 5: Run documentation and error tests**

Run:

```bash
pytest tests/unit/test_cli_spec_memory.py tests/unit/test_mempalace_audit.py tests/unit/test_mempalace_requirements.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit reports and docs**

Run:

```bash
git add src/echelon/mempalace_requirements.py src/echelon/mempalace_audit.py src/echelon/cli_app.py docs/mempalace.md tests/unit/test_cli_spec_memory.py tests/unit/test_mempalace_audit.py tests/unit/test_mempalace_requirements.py
git commit -m "docs: document normal mempalace reconciliation"
```

Expected: commit succeeds.

---

### Task 6: Final Verification

**Files:**
- No new files.
- Verify: all files touched by Tasks 1-5.

**Interfaces:**
- Consumes: full implementation from Tasks 1-5
- Produces: verified branch ready for code review

- [ ] **Step 1: Run focused Python tests**

Run:

```bash
pytest tests/unit/test_mempalace_requirements.py tests/unit/test_mempalace_audit.py tests/unit/test_cli_spec_memory.py tests/unit/test_cli_typer_app.py tests/unit/test_squad_completion.py tests/integration/test_squad_context_memory.py -q
```

Expected: PASS.

- [ ] **Step 2: Run static diff checks**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 3: Inspect public CLI help**

Run:

```bash
python -m echelon.cli spec memory --help
```

Expected: command exits `0` and lists `mine`, `audit`, and `refresh`.

- [ ] **Step 4: Run manual audit unavailable smoke**

Run from a temporary project that has a canonical spec but no MemPalace backend configured:

```bash
tmpdir="$(mktemp -d)"
mkdir -p "$tmpdir/.echelon" "$tmpdir/specs/003-demo"
printf 'mempalace:\n  wing: demo-wing\n' > "$tmpdir/.echelon/config.yml"
printf 'FR-001: Upload a photo.\n' > "$tmpdir/specs/003-demo/spec.md"
(cd "$tmpdir" && python -m echelon.cli spec memory audit 003-demo --json)
```

Expected: exit code `2` when MemPalace is unavailable, JSON output with `"status": "unavailable"`, and no traceback.

- [ ] **Step 5: Review design coverage**

Check the implementation against `docs/superpowers/specs/2026-07-27-normal-pipeline-mempalace-audit-design.md`:

```bash
rg -n "second parser|semantic search as storage proof|overwrite drifted|Automatic integration defaults|Do not design the graph" docs/superpowers/specs/2026-07-27-normal-pipeline-mempalace-audit-design.md
```

Expected: each constraint is implemented or explicitly preserved as a non-goal.

- [ ] **Step 6: Commit final verification note if docs changed**

If verification updates documentation, run:

```bash
git add docs/mempalace.md
git commit -m "docs: clarify mempalace audit verification"
```

Expected: commit succeeds only when documentation changed.
