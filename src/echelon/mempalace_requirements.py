from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from echelon.context_metadata import artifact_hash


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
    requirement_id: str
    room: str
    source: str
    artifact_hash: str
    canonical_spec_sha256: str
    requirement_content_sha256: str


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
    unavailable_count: int = 0
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
            "unavailable_count": self.unavailable_count,
            "drawer_ids": list(self.drawer_ids),
            "expected_drawer_ids": list(self.expected_drawer_ids),
            "errors": list(self.errors),
        }


SUPPORTING_MEMORY_ARTIFACTS: frozenset[str] = frozenset(
    {
        "plan.md",
        "tasks.md",
        "coverage-map.md",
        "research.md",
        "quality-gates.md",
        "test-strategy.md",
        "test-architecture.md",
        "issues.md",
        "fulfillment-gaps.md",
        "contradictions-and-gaps.md",
        "critical-path.md",
        "mvp-scope.md",
        "prioritization.md",
    }
)


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
    digest = artifact_hash(spec_file)
    return CanonicalSpecSnapshot(
        spec_id=relative_dir.parts[1],
        spec_dir=resolved_dir,
        spec_file=spec_file,
        content=content,
        spec_sha256=digest.removeprefix("sha256:"),
        source=f"{relative_dir.as_posix()}/spec.md",
        artifact_metadata={
            "scope": "canonical",
            "canonical": True,
            "artifact_path": f"{relative_dir.as_posix()}/spec.md",
            "artifact_hash": digest,
            "source_file": f"{relative_dir.as_posix()}/spec.md",
            "lifecycle_status": "active",
            "provenance_type": "requirements_mine",
            "added_by": "echelon",
        },
    )


def load_supporting_artifact_snapshots(
    project_root: Path,
    spec_dir: Path,
) -> list[CanonicalSpecSnapshot]:
    root = project_root.resolve()
    resolved_dir = spec_dir.resolve()
    try:
        relative_dir = resolved_dir.relative_to(root)
    except ValueError as exc:
        raise SpecMemoryError("spec directory is outside the project") from exc
    if len(relative_dir.parts) != 2 or relative_dir.parts[0] != "specs":
        raise SpecMemoryError("spec directory must be under canonical specs/")

    snapshots: list[CanonicalSpecSnapshot] = []
    for artifact in sorted(resolved_dir.iterdir(), key=lambda path: path.name):
        if not artifact.is_file() or artifact.name not in SUPPORTING_MEMORY_ARTIFACTS:
            continue
        content = artifact.read_bytes()
        digest = artifact_hash(artifact)
        source = f"{relative_dir.as_posix()}/{artifact.name}"
        snapshots.append(
            CanonicalSpecSnapshot(
                spec_id=relative_dir.parts[1],
                spec_dir=resolved_dir,
                spec_file=artifact,
                content=content,
                spec_sha256=digest.removeprefix("sha256:"),
                source=source,
                artifact_metadata={
                    "scope": "canonical-support",
                    "canonical": True,
                    "artifact_kind": "supporting-context",
                    "artifact_path": source,
                    "artifact_hash": digest,
                    "source_file": source,
                    "lifecycle_status": "active",
                    "provenance_type": "requirements_mine",
                    "added_by": "echelon",
                },
            )
        )
    return snapshots


def _read_mempalace_wing(project_root: Path) -> str:
    canonical = project_root / ".echelon" / "config.yml"
    legacy = (
        project_root
        / ".specify"
        / "extensions"
        / "echelon"
        / "echelon-config.yml"
    )
    config_path = canonical if canonical.exists() else legacy
    if not config_path.exists():
        raise SpecMemoryError(
            "Echelon config is missing; run 'echelon workspace init'"
        )
    try:
        import yaml

        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise SpecMemoryError(
            f"cannot parse Echelon config at {config_path}"
        ) from exc
    if not isinstance(config, dict):
        raise SpecMemoryError(f"invalid Echelon config at {config_path}")
    mempalace = config.get("mempalace")
    wing = mempalace.get("wing") if isinstance(mempalace, dict) else None
    if not isinstance(wing, str) or not wing.strip():
        raise SpecMemoryError(
            f"mempalace.wing is not set in {config_path}"
        )
    return wing.strip()


class RequirementMemoryAdapter:
    def __init__(self, project_root: Path, run_id: str) -> None:
        from codegen.memory.context import MemPalaceContext
        from echelon.spec_memory_miner import SpecMemoryMiner

        wing = _read_mempalace_wing(project_root)
        self.context = MemPalaceContext.from_wing(wing, run_id=run_id)
        self.miner = SpecMemoryMiner(self.context, project_dir=project_root)
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

    def plan_canonical_rows(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> list[PlannedRequirementDrawer]:
        return [
            PlannedRequirementDrawer(
                drawer_id=row.drawer_id,
                requirement_id=row.requirement_id,
                room=row.room,
                source=row.source,
                artifact_hash=row.artifact_hash,
                canonical_spec_sha256=row.canonical_spec_sha256,
                requirement_content_sha256=row.requirement_content_sha256,
            )
            for row in self.miner.plan_canonical_rows(
                content,
                source=source,
                artifact_metadata=artifact_metadata,
            )
        ]

    def plan_canonical_support_rows(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> list[PlannedRequirementDrawer]:
        return [
            PlannedRequirementDrawer(
                drawer_id=row.drawer_id,
                requirement_id=row.requirement_id,
                room=row.room,
                source=row.source,
                artifact_hash=row.artifact_hash,
                canonical_spec_sha256=row.canonical_spec_sha256,
                requirement_content_sha256=row.requirement_content_sha256,
            )
            for row in self.miner.plan_canonical_support_rows(
                content,
                source=source,
                artifact_metadata=artifact_metadata,
            )
        ]

    def open_collection_read_only(self) -> object:
        opener = getattr(self.miner, "open_collection_read_only", None)
        if not callable(opener):
            raise SpecMemoryError(
                "installed MemPalace does not support read-only collection access"
            )
        return opener()

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

    def mine_canonical_support_bytes(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> object:
        return self.miner.mine_canonical_support_bytes(
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

    def verify_canonical_bytes_outcome(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
        drawer_ids: list[str],
    ) -> str:
        return self.miner.verify_canonical_bytes_outcome(
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
    except SpecMemoryError:
        raise
    except (Exception, SystemExit) as exc:
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
    try:
        result = adapter.mine_canonical_bytes(
            snapshot.content,
            source=snapshot.source,
            artifact_metadata=snapshot.artifact_metadata,
        )
        support_results = []
        for support_snapshot in load_supporting_artifact_snapshots(
            project_root,
            spec_dir,
        ):
            support_results.append(
                adapter.mine_canonical_support_bytes(
                    support_snapshot.content,
                    source=support_snapshot.source,
                    artifact_metadata=support_snapshot.artifact_metadata,
                )
            )
    except ValueError as exc:
        return SpecMemoryMineReport(
            schema_version=1,
            spec_id=snapshot.spec_id,
            spec_dir=str(snapshot.spec_dir),
            wing=str(getattr(adapter, "wing", "")) or None,
            palace_path=str(getattr(adapter, "palace_path", "")) or None,
            status="partial",
            expected_count=0,
            written_count=0,
            adopted_count=0,
            skipped_count=0,
            failed_count=1,
            drifted_count=0,
            errors=[type(exc).__name__],
        )
    except (ImportError, OSError, RuntimeError, SpecMemoryError, SystemExit) as exc:
        return SpecMemoryMineReport(
            schema_version=1,
            spec_id=snapshot.spec_id,
            spec_dir=str(snapshot.spec_dir),
            wing=str(getattr(adapter, "wing", "")) or None,
            palace_path=str(getattr(adapter, "palace_path", "")) or None,
            status="unavailable",
            expected_count=0,
            written_count=0,
            adopted_count=0,
            skipped_count=0,
            failed_count=0,
            drifted_count=0,
            errors=[type(exc).__name__],
        )
    results = [result, *support_results]
    expected = sorted(
        {
            drawer_id
            for item in results
            for drawer_id in _read_str_list(item, "expected_drawer_ids")
        }
    )
    drawer_ids = sorted(
        {
            drawer_id
            for item in results
            for drawer_id in _read_str_list(item, "drawer_ids")
        }
    )
    written = sum(_read_int(item, "written") for item in results)
    adopted = sum(_read_int(item, "already_present") for item in results)
    skipped = sum(_read_int(item, "skipped") for item in results)
    failed = sum(_read_int(item, "failed") for item in results)
    drifted = sum(_read_int(item, "drifted") for item in results)
    unavailable = sum(_read_int(item, "unavailable") for item in results)
    status = "complete"
    if unavailable:
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
        unavailable_count=unavailable,
        drawer_ids=drawer_ids,
        expected_drawer_ids=expected,
        errors=[
            str(error)
            for item in results
            for error in getattr(item, "errors", [])
            if isinstance(error, str)
        ],
    )
