# EGR-035 Project Context and Memory Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic project-context and memory-reconciliation path so finalized specs become safe durable context, WIP artifacts remain run-local, stale MemPalace drawers are excluded, and GOLDDIGGER Mode 2 is actually executable.

**Architecture:** Disk artifacts remain the source of truth. New Python helpers extract canonical feature metadata, compute artifact hashes, reconcile MemPalace results against disk, and render prompt-ready context files under `runs/<run-id>/context/`. Finalization mines only published `specs/<id>-*/` artifacts into MemPalace with strong metadata, while the squad executor processes GOLDDIGGER Mode 2 requests through a deterministic queue.

**Tech Stack:** Python standard library, PyYAML where already used, existing `src/codegen/memory` MemPalace wrapper, existing `src/harness` squad runtime, pytest.

## Global Constraints

- Canonical truth is `specs/<id>-*/` after finalize; WIP artifacts under `runs/<run-id>/specs/<id>/` are never durably mined to MemPalace in v1.
- Generated run-local context files live under `runs/<run-id>/context/`.
- Do not add `.specify/echelon/context/`.
- MemPalace unavailability or stale data must not block Phase A; disk artifact context must still be generated.
- Stale MemPalace drawers must not appear in prompt context.
- Lifecycle statuses are `active`, `changed`, `deprecated`, `superseded`, and `removed`.
- GOLDDIGGER Mode 2 must respect cache/coverage state and be configurable by policy.

---

## File Structure

- Create `src/echelon/context_metadata.py`: canonical feature metadata dataclasses, artifact hashing, best-effort `spec.md` parser, metadata YAML read/write.
- Create `src/echelon/context_reconciliation.py`: reconcile MemPalace drawer-like records against canonical disk metadata and lifecycle policy.
- Create `src/echelon/context_builder.py`: build `runs/<run-id>/context/*` files from canonical specs, WIP artifacts, and reconciled MemPalace results.
- Modify `src/codegen/memory/mempalace_writer.py`: allow extra drawer metadata without changing existing callers.
- Modify `src/codegen/memory/requirements_miner.py`: accept optional artifact metadata and pass it through to the writer.
- Modify `src/harness/squad.py`: after publish in Phase 4, write `feature-metadata.yml` and mine finalized canonical artifacts.
- Modify `src/harness/squad_executors.py`: process `golddigger_mode2_queue` pre-dispatch action and include run-local context files in prompts when listed.
- Modify `extension/workflow/definition.yaml`: include generated context files in relevant Phase 1 context packs and declare/allow new GOLDDIGGER state fields.
- Modify `extension/config-template.yml` and `extension/echelon-config.yml`: add `golddigger.mode2_policy`.
- Modify `CHANGELOG.md`: add EGR-035 entry when implementation is complete.
- Modify `docs/findings/echelon-grounded-review-register.md`: track EGR-035 status and evidence.
- Test with new/updated tests under `tests/unit/`, `tests/kernel/`, and `tests/integration/`.

---

### Task 1: Register EGR-035 and Preserve the Design Contract

**Files:**
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `docs/superpowers/specs/2026-06-26-project-context-memory-reconciliation-design.md`
- Create: `docs/superpowers/plans/2026-06-27-egr-035-project-context-memory-reconciliation.md`

**Interfaces:**
- Consumes: existing EGR register format.
- Produces: EGR-035 tracking entry with status `in-progress`.

- [x] **Step 1: Add EGR-035 to Current Findings**

Insert this row after `EGR-034`:

```markdown
| EGR-035 | P1 | in-progress | Project context and memory reconciliation are not first-class in the squad path: GOLDDIGGER Mode 2 is documented but not executed, canonical prior specs are not reliably converted into next-run context, WIP artifacts are not consistently summarized for later phases, and MemPalace lacks hash/lifecycle reconciliation before reuse. | Design: `docs/superpowers/specs/2026-06-26-project-context-memory-reconciliation-design.md`; plan: `docs/superpowers/plans/2026-06-27-egr-035-project-context-memory-reconciliation.md`; code evidence currently includes documented-but-unimplemented `golddigger_mode2_queue` in `extension/workflow/definition.yaml` and pre-dispatch executor behavior in `src/harness/squad_executors.py`. | Implement metadata extraction, run-local context generation, MemPalace hash/lifecycle reconciliation, finalized-artifact mining, and executable GOLDDIGGER Mode 2 queue processing. |
```

- [x] **Step 2: Replace the Backlog Row**

Replace the `Next EGR Backlog` single-row table with:

```markdown
| Priority | Recommendation | Why it matters | Suggested files/modules to change | Expected impact |
|---|---|---|---|---|
| P3 | EGR-009: Integrate external RCA pipeline from source. | Adds incident/RCA capability without inventing duplicate behavior. | Future RCA integration adapter, workflow namespace, docs/tests after source is available | Source-grounded RCA flow tied into Echelon. |
```

No EGR-035 backlog row remains because EGR-035 is now in-progress in Current Findings.

- [x] **Step 3: Add Review Note**

Append this row to Review Notes:

```markdown
| 2026-06-27 | `working tree on main` | Added EGR-035 for project context and memory reconciliation: finalized canonical specs must become safe durable context, WIP artifacts remain run-local, MemPalace retrieval must be reconciled against artifact hashes/lifecycle metadata, and GOLDDIGGER Mode 2 queue processing must become executable. Design and implementation plan were drafted before code changes. |
```

- [x] **Step 4: Verify register references**

Run:

```bash
rg -n "EGR-035|project context and memory reconciliation|2026-06-27-egr-035" docs/findings/echelon-grounded-review-register.md docs/superpowers/specs/2026-06-26-project-context-memory-reconciliation-design.md docs/superpowers/plans/2026-06-27-egr-035-project-context-memory-reconciliation.md
```

Expected: matches in the register, design, and plan.

---

### Task 2: Add Canonical Feature Metadata Extraction

**Files:**
- Create: `src/echelon/context_metadata.py`
- Create: `tests/unit/test_context_metadata.py`

**Interfaces:**
- Produces:
  - `artifact_hash(path: Path) -> str`
  - `FeatureMetadata.from_spec_dir(spec_dir: Path, run_id: str | None = None) -> FeatureMetadata`
  - `FeatureMetadata.to_dict() -> dict[str, Any]`
  - `write_feature_metadata(spec_dir: Path, metadata: FeatureMetadata) -> Path`
  - `read_feature_metadata(spec_dir: Path) -> FeatureMetadata | None`

- [ ] **Step 1: Write failing hash test**

Add to `tests/unit/test_context_metadata.py`:

```python
from pathlib import Path

from echelon.context_metadata import artifact_hash


def test_artifact_hash_uses_sha256_prefix(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text("# Spec\n\nFR-001: Upload a photo.\n", encoding="utf-8")

    digest = artifact_hash(spec)

    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
pytest tests/unit/test_context_metadata.py::test_artifact_hash_uses_sha256_prefix -q
```

Expected: FAIL with `ModuleNotFoundError` for `echelon.context_metadata`.

- [ ] **Step 3: Implement artifact hash and metadata dataclasses**

Create `src/echelon/context_metadata.py`:

```python
"""Feature metadata extraction for canonical and run-local Echelon specs."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any
import re

import yaml

ACTIVE_STATUSES = {"active", "changed"}
LIFECYCLE_STATUSES = {"active", "changed", "deprecated", "superseded", "removed"}


def artifact_hash(path: Path) -> str:
    digest = sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


@dataclass(frozen=True)
class RequirementMetadata:
    id: str
    status: str
    artifact_path: str
    artifact_hash: str
    use_cases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "artifact_path": self.artifact_path,
            "artifact_hash": self.artifact_hash,
            "use_cases": list(self.use_cases),
        }


@dataclass(frozen=True)
class UseCaseMetadata:
    id: str
    title: str
    status: str = "active"
    source_requirements: list[str] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    superseded_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "source_requirements": list(self.source_requirements),
            "supersedes": list(self.supersedes),
            "superseded_by": list(self.superseded_by),
        }


@dataclass(frozen=True)
class FeatureMetadata:
    schema_version: int
    feature_id: str
    spec_id: str
    slug: str
    status: str = "active"
    created_in_run: str | None = None
    last_changed_in_run: str | None = None
    supersedes: list[str] = field(default_factory=list)
    superseded_by: list[str] = field(default_factory=list)
    related_features: list[str] = field(default_factory=list)
    use_cases: list[UseCaseMetadata] = field(default_factory=list)
    requirements: list[RequirementMetadata] = field(default_factory=list)

    @classmethod
    def from_spec_dir(cls, spec_dir: Path, run_id: str | None = None) -> "FeatureMetadata":
        spec_id, slug = _split_spec_dir_name(spec_dir.name)
        spec_file = spec_dir / "spec.md"
        text = spec_file.read_text(encoding="utf-8") if spec_file.exists() else ""
        spec_hash = artifact_hash(spec_file) if spec_file.exists() else ""
        reqs = _extract_requirements(text, spec_file, spec_hash)
        use_cases = _extract_use_cases(text, reqs)
        return cls(
            schema_version=1,
            feature_id=f"{spec_id}-{slug}" if slug else spec_id,
            spec_id=spec_id,
            slug=slug,
            created_in_run=run_id,
            last_changed_in_run=run_id,
            use_cases=use_cases,
            requirements=reqs,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "feature_id": self.feature_id,
            "spec_id": self.spec_id,
            "slug": self.slug,
            "status": self.status,
            "created_in_run": self.created_in_run,
            "last_changed_in_run": self.last_changed_in_run,
            "supersedes": list(self.supersedes),
            "superseded_by": list(self.superseded_by),
            "related_features": list(self.related_features),
            "use_cases": [u.to_dict() for u in self.use_cases],
            "requirements": [r.to_dict() for r in self.requirements],
        }


def write_feature_metadata(spec_dir: Path, metadata: FeatureMetadata) -> Path:
    path = spec_dir / "feature-metadata.yml"
    path.write_text(yaml.safe_dump(metadata.to_dict(), sort_keys=False), encoding="utf-8")
    return path


def read_feature_metadata(spec_dir: Path) -> FeatureMetadata | None:
    path = spec_dir / "feature-metadata.yml"
    if not path.exists():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return FeatureMetadata(
        schema_version=int(raw.get("schema_version", 1)),
        feature_id=str(raw.get("feature_id", "")),
        spec_id=str(raw.get("spec_id", "")),
        slug=str(raw.get("slug", "")),
        status=str(raw.get("status", "active")),
        created_in_run=raw.get("created_in_run"),
        last_changed_in_run=raw.get("last_changed_in_run"),
        supersedes=list(raw.get("supersedes") or []),
        superseded_by=list(raw.get("superseded_by") or []),
        related_features=list(raw.get("related_features") or []),
        use_cases=[
            UseCaseMetadata(
                id=str(u.get("id", "")),
                title=str(u.get("title", "")),
                status=str(u.get("status", "active")),
                source_requirements=list(u.get("source_requirements") or []),
                supersedes=list(u.get("supersedes") or []),
                superseded_by=list(u.get("superseded_by") or []),
            )
            for u in raw.get("use_cases", []) or []
        ],
        requirements=[
            RequirementMetadata(
                id=str(r.get("id", "")),
                status=str(r.get("status", "active")),
                artifact_path=str(r.get("artifact_path", "")),
                artifact_hash=str(r.get("artifact_hash", "")),
                use_cases=list(r.get("use_cases") or []),
            )
            for r in raw.get("requirements", []) or []
        ],
    )


def _split_spec_dir_name(name: str) -> tuple[str, str]:
    match = re.match(r"^([0-9]{3})(?:-(.*))?$", name)
    if not match:
        return name, ""
    return match.group(1), match.group(2) or ""


def _extract_requirements(
    text: str,
    spec_file: Path,
    spec_hash: str,
) -> list[RequirementMetadata]:
    ids = sorted(set(re.findall(r"\b(FR-[A-Za-z0-9_.-]+|NFR-[A-Za-z0-9_.-]+|REQ-[A-Za-z0-9_.-]+)\b", text)))
    return [
        RequirementMetadata(
            id=req_id,
            status="active",
            artifact_path=spec_file.as_posix(),
            artifact_hash=spec_hash,
        )
        for req_id in ids
    ]


def _extract_use_cases(text: str, reqs: list[RequirementMetadata]) -> list[UseCaseMetadata]:
    use_cases: list[UseCaseMetadata] = []
    for index, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.lower().startswith(("### user story", "## user story", "- user story")):
            use_cases.append(
                UseCaseMetadata(
                    id=f"UC-{len(use_cases) + 1:03d}",
                    title=stripped.lstrip("#- ").strip() or f"User story line {index}",
                    source_requirements=[r.id for r in reqs],
                )
            )
    return use_cases
```

- [ ] **Step 4: Add extraction/read-write tests**

Append:

```python
from echelon.context_metadata import (
    FeatureMetadata,
    read_feature_metadata,
    write_feature_metadata,
)


def test_feature_metadata_from_spec_dir_extracts_requirements(tmp_path: Path) -> None:
    spec_dir = tmp_path / "001-photo-album"
    spec_dir.mkdir()
    (spec_dir / "spec.md").write_text(
        "# Photo Album\n\n### User Story 1\n\nFR-001: Upload a photo.\nNFR-002: Finish quickly.\n",
        encoding="utf-8",
    )

    metadata = FeatureMetadata.from_spec_dir(spec_dir, run_id="spec-run")

    assert metadata.feature_id == "001-photo-album"
    assert [r.id for r in metadata.requirements] == ["FR-001", "NFR-002"]
    assert metadata.requirements[0].artifact_hash.startswith("sha256:")
    assert metadata.use_cases[0].id == "UC-001"


def test_feature_metadata_round_trips_yaml(tmp_path: Path) -> None:
    spec_dir = tmp_path / "001-photo-album"
    spec_dir.mkdir()
    (spec_dir / "spec.md").write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    metadata = FeatureMetadata.from_spec_dir(spec_dir, run_id="spec-run")

    path = write_feature_metadata(spec_dir, metadata)
    loaded = read_feature_metadata(spec_dir)

    assert path == spec_dir / "feature-metadata.yml"
    assert loaded is not None
    assert loaded.to_dict() == metadata.to_dict()
```

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/unit/test_context_metadata.py -q
```

Expected: PASS.

---

### Task 3: Add MemPalace Reconciliation Primitives

**Files:**
- Create: `src/echelon/context_reconciliation.py`
- Create: `tests/unit/test_context_reconciliation.py`

**Interfaces:**
- Consumes: drawer-like objects with `drawer_id`, `content`, `metadata`, `room`, `distance`.
- Produces:
  - `ReconciliationReport`
  - `reconcile_drawers(drawers: Sequence[Any], project_root: Path, include_statuses: set[str] | None = None) -> ReconciliationReport`

- [ ] **Step 1: Write reconciliation tests**

Create `tests/unit/test_context_reconciliation.py`:

```python
from dataclasses import dataclass
from pathlib import Path

from echelon.context_metadata import artifact_hash
from echelon.context_reconciliation import reconcile_drawers


@dataclass
class Drawer:
    drawer_id: str
    content: str
    metadata: dict
    room: str = "functional-requirements"
    distance: float = 0.1


def test_reconcile_keeps_matching_artifact_hash(tmp_path: Path) -> None:
    spec = tmp_path / "specs" / "001-photo-album" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    drawer = Drawer(
        drawer_id="d1",
        content="FR-001: Upload a photo.",
        metadata={
            "artifact_path": "specs/001-photo-album/spec.md",
            "artifact_hash": artifact_hash(spec),
            "status": "active",
            "wing": "demo",
        },
    )

    report = reconcile_drawers([drawer], tmp_path)

    assert [d.drawer_id for d in report.accepted] == ["d1"]
    assert report.rejected == []


def test_reconcile_rejects_stale_hash(tmp_path: Path) -> None:
    spec = tmp_path / "specs" / "001-photo-album" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    drawer = Drawer(
        drawer_id="d1",
        content="FR-001: Old wording.",
        metadata={
            "artifact_path": "specs/001-photo-album/spec.md",
            "artifact_hash": "sha256:" + "0" * 64,
            "status": "active",
        },
    )

    report = reconcile_drawers([drawer], tmp_path)

    assert report.accepted == []
    assert report.rejected[0]["reason"] == "hash_mismatch"


def test_reconcile_excludes_removed_by_default(tmp_path: Path) -> None:
    spec = tmp_path / "specs" / "001-photo-album" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    drawer = Drawer(
        drawer_id="d1",
        content="FR-001: Upload a photo.",
        metadata={
            "artifact_path": "specs/001-photo-album/spec.md",
            "artifact_hash": artifact_hash(spec),
            "status": "removed",
        },
    )

    report = reconcile_drawers([drawer], tmp_path)

    assert report.accepted == []
    assert report.rejected[0]["reason"] == "lifecycle_excluded"
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pytest tests/unit/test_context_reconciliation.py -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement reconciliation**

Create `src/echelon/context_reconciliation.py`:

```python
"""Reconcile MemPalace retrievals against canonical disk artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from echelon.context_metadata import ACTIVE_STATUSES, artifact_hash


@dataclass(frozen=True)
class ReconciliationReport:
    accepted: list[Any] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_count": len(self.accepted),
            "rejected": list(self.rejected),
        }


def reconcile_drawers(
    drawers: Sequence[Any],
    project_root: Path,
    include_statuses: set[str] | None = None,
) -> ReconciliationReport:
    include = include_statuses or ACTIVE_STATUSES
    accepted: list[Any] = []
    rejected: list[dict[str, str]] = []

    for drawer in drawers:
        metadata = _metadata(drawer)
        drawer_id = str(getattr(drawer, "drawer_id", metadata.get("id", "unknown")))
        artifact_rel = str(metadata.get("artifact_path") or metadata.get("source_file") or "")
        expected_hash = str(metadata.get("artifact_hash") or "")
        status = str(metadata.get("status") or "active")

        if status not in include:
            rejected.append({"drawer_id": drawer_id, "reason": "lifecycle_excluded", "status": status})
            continue
        if not artifact_rel:
            rejected.append({"drawer_id": drawer_id, "reason": "missing_artifact_path"})
            continue

        artifact_path = (project_root / artifact_rel).resolve()
        try:
            artifact_path.relative_to(project_root.resolve())
        except ValueError:
            rejected.append({"drawer_id": drawer_id, "reason": "artifact_outside_project", "artifact_path": artifact_rel})
            continue

        if not artifact_path.exists():
            rejected.append({"drawer_id": drawer_id, "reason": "artifact_missing", "artifact_path": artifact_rel})
            continue
        actual_hash = artifact_hash(artifact_path)
        if expected_hash and actual_hash != expected_hash:
            rejected.append({"drawer_id": drawer_id, "reason": "hash_mismatch", "artifact_path": artifact_rel})
            continue

        accepted.append(drawer)

    return ReconciliationReport(accepted=accepted, rejected=rejected)


def _metadata(drawer: Any) -> dict[str, Any]:
    metadata = getattr(drawer, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    if isinstance(drawer, dict):
        raw = drawer.get("metadata") or {}
        return raw if isinstance(raw, dict) else {}
    return {}
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/unit/test_context_reconciliation.py -q
```

Expected: PASS.

---

### Task 4: Build Run-Local Context Files

**Files:**
- Create: `src/echelon/context_builder.py`
- Create: `tests/unit/test_context_builder.py`

**Interfaces:**
- Consumes: canonical specs, active run spec/staging paths, optional reconciled drawers.
- Produces:
  - `ContextBuildResult`
  - `build_run_context(project_root: Path, run_dir: Path, user_request: str = "", drawers: Sequence[Any] = ()) -> ContextBuildResult`

- [ ] **Step 1: Write context builder test**

Create `tests/unit/test_context_builder.py`:

```python
from pathlib import Path

from echelon.context_builder import build_run_context


def test_build_run_context_writes_prior_and_current_files(tmp_path: Path) -> None:
    canonical = tmp_path / "specs" / "001-photo-album"
    canonical.mkdir(parents=True)
    (canonical / "spec.md").write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    run_dir = tmp_path / "runs" / "spec-1"
    wip = run_dir / "specs" / "002-share-album"
    wip.mkdir(parents=True)
    (wip / "spec.md").write_text("FR-002: Share an album.\n", encoding="utf-8")
    (run_dir / "staging").mkdir(parents=True)
    (run_dir / "staging" / "mental-model.md").write_text("Album has photos.\n", encoding="utf-8")

    result = build_run_context(tmp_path, run_dir, user_request="share albums")

    assert result.context_dir == run_dir / "context"
    assert (run_dir / "context" / "prior-spec-context.md").read_text(encoding="utf-8").count("001-photo-album") == 1
    assert "FR-002" in (run_dir / "context" / "current-feature-context.md").read_text(encoding="utf-8")
    assert (run_dir / "context" / "feature-registry.snapshot.json").exists()
```

- [ ] **Step 2: Run failing test**

Run:

```bash
pytest tests/unit/test_context_builder.py -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement context builder**

Create `src/echelon/context_builder.py`:

```python
"""Build prompt-ready run-local context files for squad Phase A."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
import json

from echelon.context_metadata import FeatureMetadata, read_feature_metadata, write_feature_metadata
from echelon.context_reconciliation import reconcile_drawers


@dataclass(frozen=True)
class ContextBuildResult:
    context_dir: Path
    prior_context: Path
    current_context: Path
    feature_registry: Path
    reconciliation_json: Path
    stale_report: Path


def build_run_context(
    project_root: Path,
    run_dir: Path,
    user_request: str = "",
    drawers: Sequence[Any] = (),
) -> ContextBuildResult:
    context_dir = run_dir / "context"
    context_dir.mkdir(parents=True, exist_ok=True)

    canonical_metadata = _canonical_metadata(project_root)
    wip_metadata = _wip_metadata(run_dir)
    reconciliation = reconcile_drawers(drawers, project_root)

    prior_context = context_dir / "prior-spec-context.md"
    current_context = context_dir / "current-feature-context.md"
    feature_registry = context_dir / "feature-registry.snapshot.json"
    reconciliation_json = context_dir / "mempalace-reconciliation.json"
    stale_report = context_dir / "stale-memory-report.md"

    prior_context.write_text(_render_prior(canonical_metadata, reconciliation.accepted), encoding="utf-8")
    current_context.write_text(_render_current(wip_metadata, run_dir), encoding="utf-8")
    feature_registry.write_text(
        json.dumps(
            {
                "user_request": user_request,
                "features": [m.to_dict() for m in canonical_metadata],
                "wip_features": [m.to_dict() for m in wip_metadata],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    reconciliation_json.write_text(json.dumps(reconciliation.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    stale_report.write_text(_render_stale_report(reconciliation.rejected), encoding="utf-8")

    return ContextBuildResult(
        context_dir=context_dir,
        prior_context=prior_context,
        current_context=current_context,
        feature_registry=feature_registry,
        reconciliation_json=reconciliation_json,
        stale_report=stale_report,
    )


def _canonical_metadata(project_root: Path) -> list[FeatureMetadata]:
    result: list[FeatureMetadata] = []
    specs_dir = project_root / "specs"
    for spec_dir in sorted(specs_dir.glob("[0-9][0-9][0-9]-*")):
        metadata = read_feature_metadata(spec_dir)
        if metadata is None:
            metadata = FeatureMetadata.from_spec_dir(spec_dir)
            write_feature_metadata(spec_dir, metadata)
        result.append(metadata)
    return result


def _wip_metadata(run_dir: Path) -> list[FeatureMetadata]:
    result: list[FeatureMetadata] = []
    specs_dir = run_dir / "specs"
    for spec_dir in sorted(specs_dir.glob("[0-9][0-9][0-9]-*")):
        result.append(FeatureMetadata.from_spec_dir(spec_dir, run_id=run_dir.name))
    return result


def _render_prior(metadata: list[FeatureMetadata], drawers: Sequence[Any]) -> str:
    lines = ["# Prior Spec Context", ""]
    for feature in metadata:
        lines.append(f"## {feature.feature_id}")
        lines.append(f"Status: {feature.status}")
        for req in feature.requirements:
            lines.append(f"- {req.id} ({req.status}) from `{req.artifact_path}`")
        lines.append("")
    if drawers:
        lines.append("## Reconciled MemPalace Results")
        for drawer in drawers:
            label = getattr(drawer, "drawer_id", "unknown")
            content = getattr(drawer, "content", "")
            lines.append(f"- {label}: {content[:300]}")
    return "\n".join(lines).rstrip() + "\n"


def _render_current(metadata: list[FeatureMetadata], run_dir: Path) -> str:
    lines = ["# Current Feature Context", "", f"Run: `{run_dir.name}`", ""]
    for feature in metadata:
        lines.append(f"## {feature.feature_id}")
        for req in feature.requirements:
            lines.append(f"- {req.id} ({req.status})")
        lines.append("")
    staging = run_dir / "staging"
    if staging.exists():
        lines.append("## Staging Artifacts")
        for path in sorted(staging.glob("*.md")):
            lines.append(f"- `{path.name}`")
    return "\n".join(lines).rstrip() + "\n"


def _render_stale_report(rejected: list[dict[str, str]]) -> str:
    lines = ["# Stale Memory Report", ""]
    if not rejected:
        lines.append("No stale MemPalace drawers were rejected.")
    else:
        for item in rejected:
            lines.append(f"- {item.get('drawer_id', 'unknown')}: {item.get('reason', 'unknown')}")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/unit/test_context_builder.py tests/unit/test_context_metadata.py tests/unit/test_context_reconciliation.py -q
```

Expected: PASS.

---

### Task 5: Extend MemPalace Writer and Miner Metadata

**Files:**
- Modify: `src/codegen/memory/mempalace_writer.py`
- Modify: `src/codegen/memory/requirements_miner.py`
- Modify: `tests/unit/test_mempalace_writer.py`
- Modify: `tests/unit/test_requirements_miner_ctx.py`

**Interfaces:**
- Extends `MemPalaceWriter.write(room: str, content: str, phase: str, provenance_type: str = "agent_generated", embedding_model: str = "all-MiniLM-L6-v2@1.0", status: str = "pending", source_file: Optional[str] = None, extra_metadata: Optional[dict[str, Any]] = None) -> Optional[str]`
- Extends `RequirementsMiner.mine_file(path: Path, artifact_metadata: dict[str, Any] | None = None) -> MineResult`

- [ ] **Step 1: Add writer metadata test**

Append to `tests/unit/test_mempalace_writer.py`:

```python
def test_write_merges_extra_metadata(monkeypatch, tmp_path):
    from codegen.memory.context import MemPalaceContext
    from codegen.memory.mempalace_writer import MemPalaceWriter

    captured = {}
    ctx = MemPalaceContext(wing="demo", run_id="run-1", palace_path=str(tmp_path))
    writer = MemPalaceWriter(ctx)

    def fake_write_drawer(*, wing, room, content, metadata):
        captured.update(metadata)
        return "drawer_demo"

    monkeypatch.setattr(writer, "_write_drawer", fake_write_drawer)

    writer.write(
        room="functional-requirements",
        content="FR-001: Upload.",
        phase="RE",
        source_file="specs/001/spec.md",
        extra_metadata={"artifact_hash": "sha256:" + "1" * 64, "canonical": True},
    )

    assert captured["artifact_hash"] == "sha256:" + "1" * 64
    assert captured["canonical"] is True
    assert captured["run_id"] == "run-1"
```

- [ ] **Step 2: Run failing writer test**

Run:

```bash
pytest tests/unit/test_mempalace_writer.py::test_write_merges_extra_metadata -q
```

Expected: FAIL because `write()` does not accept `extra_metadata`.

- [ ] **Step 3: Modify writer signature**

Change `MemPalaceWriter.write` signature and insert the `extra_metadata` merge immediately after the existing `metadata` dictionary is created:

```python
from typing import Any

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
```

- [ ] **Step 4: Add miner test for artifact metadata**

Append to `tests/unit/test_requirements_miner_ctx.py`:

```python
def test_mine_file_passes_artifact_metadata(monkeypatch, tmp_path):
    from codegen.memory.context import MemPalaceContext
    from codegen.memory.requirements_miner import RequirementsMiner

    spec = tmp_path / "spec.md"
    spec.write_text("FR-001: Upload.\n", encoding="utf-8")
    ctx = MemPalaceContext(wing="demo", run_id="run-1", palace_path=str(tmp_path / "palace"))
    miner = RequirementsMiner(ctx, project_dir=tmp_path)
    calls = []

    class Writer:
        def write(self, **kwargs):
            calls.append(kwargs)
            return "drawer_demo"

    monkeypatch.setattr(miner, "_get_writer", lambda: Writer())
    monkeypatch.setattr("codegen.memory.requirements_miner.check_wing_collision", lambda *args, **kwargs: [])

    miner.mine_file(spec, artifact_metadata={"artifact_hash": "sha256:" + "2" * 64, "canonical": True})

    assert calls[0]["extra_metadata"]["artifact_hash"] == "sha256:" + "2" * 64
    assert calls[0]["extra_metadata"]["canonical"] is True
```

- [ ] **Step 5: Extend miner signature**

Change the `mine_file` signature and its write call:

```python
def mine_file(self, path: Path, artifact_metadata: dict[str, Any] | None = None) -> MineResult:
    result = MineResult(wing=self.wing, total=0, written=0, skipped=0, failed=0)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Cannot read {path}: {exc}"
        logger.warning("[RequirementsMiner] %s", msg)
        result.errors.append(msg)
        return result

    reqs = _parse_markdown(text, source=str(path))
    result.total = len(reqs)
    result.requirements = reqs
    self._write_requirements(reqs, result, artifact_metadata=artifact_metadata)
    logger.info(
        "[RequirementsMiner] %s: %d mined, %d written, %d failed",
        path.name, result.total, result.written, result.failed,
    )
    return result
```

Change `_write_requirements` signature and its writer call:

```python
def _write_requirements(
    self,
    reqs: list[MinedRequirement],
    result: MineResult,
    artifact_metadata: dict[str, Any] | None = None,
) -> None:
    drawer_id = writer.write(
        room=req.room,
        content=scrub_secrets(req.content),
        phase="RE",
        provenance_type="requirements_mine",
        source_file=req.source,
        extra_metadata=artifact_metadata,
    )
```

Also update internal calls from `mine_text`, `mine_jira_issues`, and `mine_bug` to pass no metadata by default.

- [ ] **Step 6: Run MemPalace tests**

Run:

```bash
pytest tests/unit/test_mempalace_writer.py tests/unit/test_requirements_miner_ctx.py tests/integration/test_mempalace_mine_search.py -q
```

Expected: PASS.

---

### Task 6: Mine Finalized Canonical Specs After Phase 4 Publish

**Files:**
- Modify: `src/harness/squad.py`
- Create: `tests/integration/test_squad_context_memory.py`

**Interfaces:**
- Consumes: `write_feature_metadata`, `artifact_hash`, `RequirementsMiner`.
- Produces: `feature-metadata.yml` in published spec dir and best-effort MemPalace mining.

- [ ] **Step 1: Write integration test for finalization metadata**

Create `tests/integration/test_squad_context_memory.py`:

```python
from pathlib import Path

from echelon.context_metadata import read_feature_metadata


def test_finalize_published_spec_metadata_can_be_generated(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-photo-album"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("FR-001: Upload a photo.\n", encoding="utf-8")

    from echelon.context_metadata import FeatureMetadata, write_feature_metadata

    metadata = FeatureMetadata.from_spec_dir(spec_dir, run_id="spec-run")
    write_feature_metadata(spec_dir, metadata)

    loaded = read_feature_metadata(spec_dir)

    assert loaded is not None
    assert loaded.feature_id == "001-photo-album"
    assert loaded.requirements[0].artifact_hash.startswith("sha256:")
```

- [ ] **Step 2: Add harness helper**

In `src/harness/squad.py`, add a helper near other Phase 4 helpers:

```python
def _refresh_published_context_metadata(project_root: Path, published_spec_dir: Path, run_id: str) -> None:
    from echelon.context_metadata import FeatureMetadata, write_feature_metadata

    metadata = FeatureMetadata.from_spec_dir(published_spec_dir, run_id=run_id)
    write_feature_metadata(published_spec_dir, metadata)
    _mine_published_spec_best_effort(project_root, published_spec_dir, run_id, metadata)


def _mine_published_spec_best_effort(project_root: Path, published_spec_dir: Path, run_id: str, metadata: object) -> None:
    try:
        from codegen.memory.context import MemPalaceContext
        from codegen.memory.requirements_miner import RequirementsMiner
    except Exception:
        return
    try:
        ctx = MemPalaceContext.from_project(project_root, run_id=run_id)
        miner = RequirementsMiner(ctx, project_dir=project_root)
        spec_file = published_spec_dir / "spec.md"
        if spec_file.exists():
            artifact_metadata = {
                "scope": "canonical",
                "canonical": True,
                "artifact_path": spec_file.relative_to(project_root).as_posix(),
                "artifact_hash": metadata.requirements[0].artifact_hash if getattr(metadata, "requirements", []) else "",
                "spec_id": getattr(metadata, "spec_id", ""),
                "feature_id": getattr(metadata, "feature_id", ""),
            }
            miner.mine_file(spec_file, artifact_metadata=artifact_metadata)
    except Exception:
        return
```

- [ ] **Step 3: Call helper after artifact publication**

In the `phase4-document` handling path where `write_artifact_index(published_spec_dir)` is called, add:

```python
_refresh_published_context_metadata(
    self._project_root,
    published_spec_dir,
    str(state.get("run_id", "")),
)
```

Place it after the published spec directory exists and before final build-readiness validation.

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/integration/test_squad_context_memory.py tests/integration/test_squad_controller.py -q
```

Expected: PASS.

---

### Task 7: Generate Run-Local Context at Phase A Init and Refresh Points

**Files:**
- Modify: `src/harness/squad_state.py`
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_executors.py`
- Modify: `extension/workflow/definition.yaml`
- Create: `tests/integration/test_squad_context_generation.py`

**Interfaces:**
- Consumes: `build_run_context(project_root, run_dir, user_request)`.
- Produces: `context_dir` in `state.json` and context files under `runs/<run-id>/context/`.

- [ ] **Step 1: Add state initialization test**

Create `tests/integration/test_squad_context_generation.py`:

```python
from pathlib import Path

from echelon.context_builder import build_run_context


def test_run_context_generation_uses_runs_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "spec-1"
    run_dir.mkdir(parents=True)
    result = build_run_context(tmp_path, run_dir, user_request="build photo sharing")

    assert result.context_dir == run_dir / "context"
    assert result.prior_context.exists()
    assert result.current_context.exists()
```

- [ ] **Step 2: Add `context_dir` to state defaults**

In `src/harness/squad_state.py`, when initializing state, add:

```python
"context_dir": str(self._squad_dir / "context"),
```

- [ ] **Step 3: Build context after state initialization**

In the squad run initialization path in `src/harness/squad.py`, call:

```python
from echelon.context_builder import build_run_context

build_run_context(
    self._project_root,
    Path(state.get("squad_dir", self._squad_dir)),
    user_request=str(state.get("user_request", "")),
)
```

Use the existing state load/save boundary nearest to run initialization. If context generation fails, catch the exception, log a warning, and continue.

- [ ] **Step 4: Add context files to Phase 1 context packs**

In `extension/workflow/definition.yaml`, add these context pack entries to Phase 1 nodes that need prior/current context:

```yaml
      - runs context prior-spec-context.md if present
      - runs context current-feature-context.md if present
      - runs context stale-memory-report.md if present
```

The executor resolves prose references poorly, so use explicit tokenized paths supported by prompt rewriting:

```yaml
      - "{context_dir}/prior-spec-context.md"
      - "{context_dir}/current-feature-context.md"
      - "{context_dir}/stale-memory-report.md"
```

- [ ] **Step 5: Teach prompt assembly `{context_dir}` replacement**

In `src/harness/squad_executors.py`, after `staging_dir_str` is loaded, add:

```python
context_dir_str = state.get("context_dir", str(self._squad_dir / "context"))
```

In context-pack item replacement and final prompt replacement, add:

```python
r = r.replace("{context_dir}", context_dir_str)
prompt = prompt.replace("{context_dir}", context_dir_str)
```

- [ ] **Step 6: Run context generation tests**

Run:

```bash
pytest tests/integration/test_squad_context_generation.py tests/kernel/test_phase_graph.py tests/kernel/test_squad_executors_journal.py -q
```

Expected: PASS.

---

### Task 8: Implement GOLDDIGGER Mode 2 Queue Processing

**Files:**
- Modify: `src/harness/squad_executors.py`
- Modify: `extension/workflow/definition.yaml`
- Modify: `extension/config-template.yml`
- Modify: `extension/echelon-config.yml`
- Create/modify: `tests/kernel/test_squad_executors_journal.py`

**Interfaces:**
- Consumes: `state["golddigger_requests"]`, `state["golddigger_completed_domains"]`, `golddigger.mode2_policy`.
- Produces: Mode 2 dispatch prompts, updated queue/completed domains.

- [ ] **Step 1: Add failing queue test**

Add to `tests/kernel/test_squad_executors_journal.py`:

```python
def test_golddigger_mode2_queue_dispatches_without_agent_field(tmp_path):
    from harness.phase_graph import PhaseNode
    from harness.squad_executors import AgentExecutor
    from harness.squad_provider import SquadAgentResult
    from harness.squad_state import SquadStateStore

    ext = tmp_path / "extension"
    agent = ext / "agents" / "exploration"
    agent.mkdir(parents=True)
    (agent / "golddigger.md").write_text("# GOLDDIGGER\n", encoding="utf-8")
    (ext / "extension.yml").write_text(
        "agents:\n  - name: speckit.echelon.golddigger\n    file: agents/exploration/golddigger.md\n",
        encoding="utf-8",
    )
    state_store = SquadStateStore(tmp_path / "runs" / "spec-1")
    state_store.initialize("run-1", "banzai", "build auth", 0, "phase1-what")
    state = state_store.load()
    state["golddigger_requests"] = [{"domain": "auth", "repo": None, "requested_by": "test", "reason": "need topology"}]
    state["golddigger_completed_domains"] = []
    state_store.save(state)
    calls = []

    class Provider:
        def exec_agent(self, cwd, prompt):
            calls.append(prompt)
            return SquadAgentResult(
                verdict="COMPLETE",
                output_files=[],
                state_updates={"golddigger_status": "complete", "golddigger_mode": "deep-dive"},
                journal_entries=[],
            )

    node = PhaseNode(
        id="phase1-what",
        label="WHAT",
        type="agent",
        agent="speckit-echelon-cartographer",
        pre_dispatch=[{"id": "golddigger_mode2_queue", "action": "process"}],
        allowed_state_updates=["golddigger_status", "golddigger_mode"],
    )
    executor = AgentExecutor(tmp_path, ext, Provider(), tmp_path / "runs" / "spec-1")

    result = executor._run_pre_dispatch(node, state_store.load(), state_store)

    updated = state_store.load()
    assert result is None
    assert "Mode 2 (Deep Dive)" in calls[0]
    assert updated["golddigger_requests"] == []
    assert updated["golddigger_completed_domains"] == ["auth"]
```

- [ ] **Step 2: Run failing test**

Run:

```bash
pytest tests/kernel/test_squad_executors_journal.py::test_golddigger_mode2_queue_dispatches_without_agent_field -q
```

Expected: FAIL because `_run_pre_dispatch` skips entries without `agent`.

- [ ] **Step 3: Implement special queue handler**

In `src/harness/squad_executors.py`, modify `_run_pre_dispatch`:

```python
if entry.get("id") == "golddigger_mode2_queue":
    result = self._process_golddigger_mode2_queue(node, state_store)
    if result is not None and result.blocked:
        return result
    continue
```

Add:

```python
def _process_golddigger_mode2_queue(self, node: "PhaseNode", state_store: "SquadStateStore") -> Optional["SquadAgentResult"]:
    state = state_store.load()
    requests = list(state.get("golddigger_requests") or [])
    if not requests:
        return None
    completed = list(state.get("golddigger_completed_domains") or [])
    rel = self._graph.agent_file("speckit-echelon-golddigger")
    if not rel:
        return None
    pre_path = self._ext_dir / rel
    if not pre_path.exists():
        return None
    remaining = []
    for raw in requests:
        request = {"domain": raw, "repo": None, "requested_by": "unknown", "reason": ""} if isinstance(raw, str) else dict(raw)
        domain = str(request.get("domain") or "").strip()
        repo = request.get("repo")
        cache_key = f"{repo}--{domain}" if repo else domain
        if not domain or cache_key in completed:
            continue
        prompt = self._assemble_golddigger_mode2_prompt(pre_path, state_store.load(), request, node.allowed_state_updates)
        result = self._provider.exec_agent(str(self._project_root), prompt)
        result = self._validate_result_state_updates(node, result)
        if result.blocked:
            remaining.append(request)
            state = state_store.load()
            state["golddigger_requests"] = remaining + requests[requests.index(raw) + 1:]
            state_store.save(state)
            return result
        self._write_journal_entries(result, node.id)
        state = state_store.load()
        for k, v in result.state_updates.items():
            state[k] = v
        completed = list(state.get("golddigger_completed_domains") or [])
        if cache_key not in completed:
            completed.append(cache_key)
        state["golddigger_completed_domains"] = completed
        state_store.save(state)
    state = state_store.load()
    state["golddigger_requests"] = remaining
    state_store.save(state)
    return None
```

Add prompt assembler:

```python
def _assemble_golddigger_mode2_prompt(
    self,
    agent_path: Path,
    state: dict,
    request: dict,
    allowed_state_updates: object = None,
) -> str:
    agent_text = agent_path.read_text(encoding="utf-8")
    squad_dir_str = state.get("squad_dir", str(self._squad_dir))
    staging_dir_str = state.get("staging_dir", str(self._squad_dir / "staging"))
    domain = request.get("domain")
    repo = request.get("repo")
    target_path = self._project_root / repo if repo else self._project_root
    return (
        _shared_agent_contract()
        + agent_text
        + "\n\n# Squad Run Context\n"
        + f"SQUAD_DIR={squad_dir_str}\n"
        + f"STAGING_DIR={staging_dir_str}\n"
        + f"PROJECT_ROOT={self._project_root}\n\n"
        + "<instructions>\n"
        + "You are GOLDDIGGER. Read agents/exploration/golddigger.md for your complete protocol.\n"
        + f"Run **Mode 2 (Deep Dive)** for domain `{domain}` in repo `{repo}` at target path `{target_path}`.\n"
        + f"Request reason: {request.get('reason', '')}\n"
        + "</instructions>\n"
        + _allowed_state_updates_contract(allowed_state_updates)
        + _canonical_echelon_result_contract(self._ext_dir)
    )
```

- [ ] **Step 4: Add config defaults**

In both `extension/config-template.yml` and `extension/echelon-config.yml`, add:

```yaml
golddigger:
  # Controls GOLDDIGGER Mode 2 deep-dive dispatch.
  # requested_only keeps Mode 2 explicit; default_for_unseen_domains can be enabled after coverage tracking matures.
  mode2_policy: requested_only
```

- [ ] **Step 5: Run queue tests**

Run:

```bash
pytest tests/kernel/test_squad_executors_journal.py::test_golddigger_mode2_queue_dispatches_without_agent_field -q
pytest tests/kernel/test_squad_executors_journal.py -q
```

Expected: PASS.

---

### Task 9: Wire Context Files into Workflow and Prompt Contracts

**Files:**
- Modify: `extension/workflow/definition.yaml`
- Modify: `src/harness/phase_graph.py` if context placeholders require validation changes.
- Modify: `tests/kernel/test_phase_graph.py`
- Modify: `tests/kernel/test_workflow_validator.py`

**Interfaces:**
- Consumes: `state.context_dir`.
- Produces: Phase 1 agents receive prior/current context files when present.

- [ ] **Step 1: Add phase graph test**

Append to `tests/kernel/test_phase_graph.py`:

```python
def test_phase1_context_packs_include_generated_context_files():
    graph = PhaseGraph.load(EXTENSION_ROOT / "workflow" / "definition.yaml")
    discover = graph.get("phase1-discover")
    what = graph.get("phase1-what")

    assert "{context_dir}/prior-spec-context.md" in discover.context_pack
    assert "{context_dir}/current-feature-context.md" in what.context_pack
```

- [ ] **Step 2: Run failing test**

Run:

```bash
pytest tests/kernel/test_phase_graph.py::test_phase1_context_packs_include_generated_context_files -q
```

Expected: FAIL until workflow is updated.

- [ ] **Step 3: Update workflow context packs**

Add to `phase1-discover.context_pack`:

```yaml
      - "{context_dir}/prior-spec-context.md"
      - "{context_dir}/stale-memory-report.md"
```

Add to `phase1-synthesizer`, `phase1-modeler`, `phase1-what`, and Phase 3 specialist context packs where relevant:

```yaml
      - "{context_dir}/prior-spec-context.md"
      - "{context_dir}/current-feature-context.md"
      - "{context_dir}/stale-memory-report.md"
```

- [ ] **Step 4: Run validation tests**

Run:

```bash
pytest tests/kernel/test_phase_graph.py tests/kernel/test_workflow_validator.py -q
```

Expected: PASS.

---

### Task 10: Add Lifecycle Transition Metadata at Finalize

**Files:**
- Modify: `src/echelon/context_metadata.py`
- Modify: `src/harness/squad.py`
- Modify: `tests/unit/test_context_metadata.py`

**Interfaces:**
- Produces lifecycle-safe metadata that can express changed/deprecated/superseded/removed items.

- [ ] **Step 1: Add lifecycle validation test**

Append to `tests/unit/test_context_metadata.py`:

```python
import pytest

from echelon.context_metadata import validate_lifecycle_status


def test_validate_lifecycle_status_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="unknown lifecycle status"):
        validate_lifecycle_status("archived")


def test_validate_lifecycle_status_accepts_removed() -> None:
    assert validate_lifecycle_status("removed") == "removed"
```

- [ ] **Step 2: Implement lifecycle validator**

Add to `src/echelon/context_metadata.py`:

```python
def validate_lifecycle_status(status: str) -> str:
    if status not in LIFECYCLE_STATUSES:
        raise ValueError(f"unknown lifecycle status: {status}")
    return status
```

Call it inside `FeatureMetadata.to_dict()`, `RequirementMetadata.to_dict()`, and `UseCaseMetadata.to_dict()` when serializing statuses.

- [ ] **Step 3: Run metadata tests**

Run:

```bash
pytest tests/unit/test_context_metadata.py -q
```

Expected: PASS.

---

### Task 11: Changelog and EGR Completion Update

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`

**Interfaces:**
- Consumes: final verified files and test outcomes.
- Produces: EGR completion gate docs.

- [ ] **Step 1: Add changelog entry**

Under `[Unreleased]`, add:

```markdown
- EGR-035: Added deterministic project context and memory reconciliation for squad Phase A. Finalized canonical specs now produce feature metadata and can be mined into MemPalace with artifact hashes; run-local context files are generated under `runs/<run-id>/context/`; stale MemPalace drawers are excluded from prompt context; GOLDDIGGER Mode 2 queue processing is executable.
```

- [ ] **Step 2: Update EGR-035 register row to fixed**

Change `Status` from `in-progress` to `fixed` and replace Next action with:

```markdown
Fixed: finalized canonical specs generate feature metadata and reconciled context, WIP artifacts remain run-local, MemPalace retrieval is hash/lifecycle checked before prompt use, and GOLDDIGGER Mode 2 queue processing is executable.
```

- [ ] **Step 3: Add completion review note**

Append:

```markdown
| 2026-06-27 | `working tree on main` | EGR-035 implemented project context and memory reconciliation. Verification: context metadata/reconciliation/builder tests passed; MemPalace writer/miner regression tests passed; GOLDDIGGER Mode 2 queue tests passed; focused workflow/context tests passed. |
```

- [ ] **Step 4: Run documentation check**

Run:

```bash
rg -n "EGR-035" CHANGELOG.md docs/findings/echelon-grounded-review-register.md docs/superpowers/specs/2026-06-26-project-context-memory-reconciliation-design.md docs/superpowers/plans/2026-06-27-egr-035-project-context-memory-reconciliation.md
```

Expected: EGR-035 appears in all four files.

---

### Task 12: Final Verification

**Files:**
- No new files.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: confidence that EGR-035 does not regress existing behavior.

- [ ] **Step 1: Run focused unit/kernel/integration set**

Run:

```bash
pytest \
  tests/unit/test_context_metadata.py \
  tests/unit/test_context_reconciliation.py \
  tests/unit/test_context_builder.py \
  tests/unit/test_mempalace_writer.py \
  tests/unit/test_requirements_miner_ctx.py \
  tests/kernel/test_squad_executors_journal.py \
  tests/kernel/test_phase_graph.py \
  tests/kernel/test_workflow_validator.py \
  tests/integration/test_squad_context_memory.py \
  tests/integration/test_squad_context_generation.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run broader regression suite**

Run:

```bash
pytest tests/unit -q
pytest tests/kernel -q
```

Expected: PASS.

- [ ] **Step 3: Run dry-run validation**

Run:

```bash
bash scripts/bash/dry-run.sh
```

Expected: PASS, including workflow validation.

- [ ] **Step 4: Inspect git diff**

Run:

```bash
git diff --stat
git diff -- docs/findings/echelon-grounded-review-register.md CHANGELOG.md
```

Expected: EGR register and changelog mention EGR-035 consistently.

---

## Self-Review

Spec coverage:

- GOLDDIGGER Mode 2 executable queue: Tasks 8 and 9.
- Canonical-only MemPalace mining: Tasks 5 and 6.
- WIP run-local context only: Tasks 4, 6, and 7.
- Hash/lifecycle reconciliation: Tasks 2, 3, and 10.
- Run-local prompt context under `runs/<run-id>/context/`: Tasks 4, 7, and 9.
- EGR tracking and completion gate: Tasks 1 and 11.

No placeholders remain in the plan. Function names introduced in earlier tasks are reused consistently in later tasks.
