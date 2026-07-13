"""Deterministic source-domain inventories for reverse-engineering runs."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from harness.re_planner import RePlanSource


_SOURCE_SUFFIXES = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".gql",
        ".go",
        ".graphql",
        ".h",
        ".hpp",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".swift",
        ".ts",
        ".tsx",
    }
)
_MANIFEST_NAMES = frozenset(
    {
        "Cargo.toml",
        "go.mod",
        "package.json",
        "pom.xml",
        "pyproject.toml",
    }
)
_IGNORED_PARTS = frozenset(
    {".agents", ".git", ".specify", ".venv", "build", "dist", "node_modules", "vendor"}
)
_NON_DOMAIN_ROOTS = frozenset(
    {
        "__mocks__",
        "__tests__",
        "certificates",
        "docs",
        "generated",
        "mocks",
        "public",
        "specs",
        "styles",
        "test",
        "test-helpers",
        "tests",
    }
)
_LOGICAL_DOMAIN_MIN_FILES = 2
_LOGICAL_DOMAIN_MAX_LEAVES = 12
_LOGICAL_DOMAIN_MAX_DEPTH = 3
_MAX_DOMAIN_SOURCE_FILES = 96
_MAX_DOMAIN_SOURCE_LINES = 6_400
DOMAIN_PARTITION_VERSION = 3
_SAFE_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ReDomain:
    """One independently documented source component."""

    domain_id: str
    root: str
    source_file_count: int
    source_line_count: int

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReDomainManifest:
    """A source-owned list of every domain that requires a staged spec."""

    source_id: str
    source_path: str
    domains: tuple[ReDomain, ...]
    partition_version: int = DOMAIN_PARTITION_VERSION

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "partition_version": self.partition_version,
            "source_id": self.source_id,
            "source_path": self.source_path,
            "domains": [domain.to_json_dict() for domain in self.domains],
        }

    @classmethod
    def from_json_dict(cls, data: object) -> "ReDomainManifest":
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise ValueError("unsupported domain manifest schema")
        source_id = data.get("source_id")
        source_path = data.get("source_path")
        raw_domains = data.get("domains")
        partition_version = data.get("partition_version", 1)
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("domain manifest source_id must be a non-empty string")
        if not isinstance(source_path, str) or not source_path:
            raise ValueError("domain manifest source_path must be a non-empty string")
        if not isinstance(raw_domains, list):
            raise ValueError("domain manifest domains must be a list")
        if not isinstance(partition_version, int) or partition_version < 1:
            raise ValueError("domain manifest partition_version must be a positive integer")

        domains: list[ReDomain] = []
        seen_ids: set[str] = set()
        seen_roots: set[str] = set()
        for raw in raw_domains:
            if not isinstance(raw, dict):
                raise ValueError("domain manifest domain must be an object")
            domain_id = raw.get("domain_id")
            root = raw.get("root")
            file_count = raw.get("source_file_count")
            line_count = raw.get("source_line_count")
            if not isinstance(domain_id, str) or not re.fullmatch(
                r"\d{3}-re-[a-z0-9][a-z0-9-]*", domain_id
            ):
                raise ValueError(f"invalid domain ID: {domain_id!r}")
            if not isinstance(root, str) or not _safe_relative_root(root):
                raise ValueError(f"invalid domain root: {root!r}")
            if not isinstance(file_count, int) or file_count <= 0:
                raise ValueError("domain source_file_count must be a positive integer")
            if not isinstance(line_count, int) or line_count < 0:
                raise ValueError("domain source_line_count must be a non-negative integer")
            if domain_id in seen_ids or root in seen_roots:
                raise ValueError("domain IDs and roots must be unique")
            seen_ids.add(domain_id)
            seen_roots.add(root)
            domains.append(
                ReDomain(
                    domain_id=domain_id,
                    root=root,
                    source_file_count=file_count,
                    source_line_count=line_count,
                )
            )
        return cls(
            source_id=source_id,
            source_path=source_path,
            domains=tuple(domains),
            partition_version=partition_version,
        )


def domain_manifest_path(run_re_dir: Path, source_id: str) -> Path:
    return run_re_dir / "sources" / source_id / "domain-manifest.json"


def discover_source_domains(source: RePlanSource) -> ReDomainManifest:
    """Derive stable documentation domains from independently buildable roots.

    A source is not delegated wholesale to one model invocation. Every source
    component with code beneath a language/package manifest becomes a required
    domain. Repositories without component manifests fall back to their
    top-level code roots, then to the source root itself.
    """
    source_root = Path(source.absolute_path).resolve()
    domain_roots = _component_roots(source_root)
    domains: list[ReDomain] = []
    for index, root in enumerate(domain_roots, start=1):
        files = _source_files(source_root / root) if root != "." else _source_files(source_root)
        if not files:
            continue
        slug = _slug(root)
        domains.append(
            ReDomain(
                domain_id=f"{index:03d}-re-{slug}",
                root=root,
                source_file_count=len(files),
                source_line_count=sum(_line_count(path) for path in files),
            )
        )
    return ReDomainManifest(
        source_id=source.id,
        source_path=source.path,
        domains=tuple(domains),
        partition_version=DOMAIN_PARTITION_VERSION,
    )


def load_domain_manifest(path: Path) -> ReDomainManifest:
    try:
        return ReDomainManifest.from_json_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid domain manifest {path}: {exc}") from exc


def write_domain_manifest(path: Path, manifest: ReDomainManifest) -> None:
    """Atomically write a controller-owned domain manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(manifest.to_json_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _component_roots(source_root: Path) -> list[str]:
    manifest_roots: set[str] = set()
    if source_root.is_dir():
        for path in _visible_files(source_root):
            if not path.is_file() or path.name not in _MANIFEST_NAMES:
                continue
            relative = path.relative_to(source_root)
            root = relative.parent.as_posix() or "."
            if _source_files(path.parent):
                manifest_roots.add(root)

    # The repository root describes the workspace; prefer its independently
    # buildable children unless it also owns source files outside them.
    nested_roots = {root for root in manifest_roots if root != "."}
    if "." in manifest_roots and nested_roots:
        # A repository-root package/pom is normally the build workspace, not
        # an independently documented component. Its children own the code.
        manifest_roots.remove(".")
    if manifest_roots:
        component_roots = _prune_nested_component_roots(source_root, manifest_roots)
        roots = (
            component_roots
            | _uncovered_component_roots(source_root, component_roots)
        )
        # Multiple package roots are already independently buildable components.
        # Retain those boundaries unless one is too large for a source-evidenced
        # deep spec. Oversized roots are split into code-bearing children before
        # quality targets are calculated; a fixed requirements cap must never
        # turn a 70k-line directory into a one-page summary.
        return _partition_component_roots(source_root, roots)

    top_level = {
        path.relative_to(source_root).parts[0]
        for path in _source_files(source_root)
        if len(path.relative_to(source_root).parts) > 1
    }
    if top_level:
        return _logical_domain_roots(source_root, top_level)
    return ["."] if _source_files(source_root) else []


def _logical_domain_roots(source_root: Path, roots: set[str]) -> list[str]:
    """Split large package roots into bounded code-bearing documentation domains."""
    domains: set[str] = set()
    for root in sorted(roots):
        domains.update(_split_logical_domain_root(source_root, root, depth=0))
    return sorted(domains)


def _partition_component_roots(source_root: Path, roots: set[str]) -> list[str]:
    """Keep component roots unless their size exceeds deep-spec capacity."""
    if len(roots) == 1:
        initial_roots = set(_logical_domain_roots(source_root, roots))
    else:
        initial_roots = roots
    return _refine_oversized_roots(source_root, initial_roots)


def _refine_oversized_roots(source_root: Path, roots: set[str]) -> list[str]:
    """Recursively partition safe oversized roots from an initial component set."""
    domains: set[str] = set()
    for root in sorted(roots):
        if _domain_root_exceeds_capacity(source_root, root):
            domains.update(
                _split_logical_domain_root(
                    source_root,
                    root,
                    depth=0,
                    preserve_direct_source_files=True,
                )
            )
        else:
            domains.add(root)
    return sorted(domains)


def _domain_root_exceeds_capacity(source_root: Path, root: str) -> bool:
    path = source_root if root == "." else source_root / root
    files = _source_files(path)
    return len(files) > _MAX_DOMAIN_SOURCE_FILES or (
        sum(_line_count(file) for file in files) > _MAX_DOMAIN_SOURCE_LINES
    )


def _split_logical_domain_root(
    source_root: Path,
    root: str,
    *,
    depth: int,
    preserve_direct_source_files: bool = False,
) -> set[str]:
    component_path = source_root if root == "." else source_root / root
    if depth >= _LOGICAL_DOMAIN_MAX_DEPTH or not component_path.is_dir():
        return {root}
    # Capacity refinement must retain a root that owns direct source files.
    # Splitting its children would otherwise drop those files or create
    # overlapping source ownership. Initial logical discovery keeps the
    # established workspace behavior and can still descend through a root.
    if preserve_direct_source_files and any(
        path.parent == component_path for path in _source_files(component_path)
    ):
        return {root}
    children = [
        path
        for path in sorted(component_path.iterdir())
        if path.is_dir()
        and not _is_ignored_directory(path.name)
        and path.name not in _NON_DOMAIN_ROOTS
        and len(_source_files(path)) >= _LOGICAL_DOMAIN_MIN_FILES
    ]
    if not children:
        return {root}

    child_roots = {
        child.relative_to(source_root).as_posix()
        for child in children
    }
    if len(children) == 1:
        return _split_logical_domain_root(
            source_root,
            next(iter(child_roots)),
            depth=depth + 1,
            preserve_direct_source_files=preserve_direct_source_files,
        )

    leaves: set[str] = set()
    for child_root in child_roots:
        leaves.update(
            _split_logical_domain_root(
                source_root,
                child_root,
                depth=depth + 1,
                preserve_direct_source_files=preserve_direct_source_files,
            )
        )
    # Preserve a useful top-level boundary when recursive splitting would
    # create a noisy directory inventory instead of documentation domains.
    return child_roots if len(leaves) > _LOGICAL_DOMAIN_MAX_LEAVES else leaves


def _uncovered_component_roots(source_root: Path, roots: set[str]) -> set[str]:
    """Return stable fallback roots for code not owned by a package manifest."""
    fallback: set[str] = set()
    for path in _source_files(source_root):
        relative = path.relative_to(source_root)
        relative_text = relative.as_posix()
        if any(
            root == "." or relative_text.startswith(root + "/") for root in roots
        ):
            continue
        if len(relative.parts) == 1:
            # Root files in a workspace with independently buildable children
            # are tooling, not a catch-all domain. A root domain would overlap
            # every child and let the agent escape manifest-bound scope.
            continue
        top = relative.parts[0]
        # Monorepo conventions put independently deployed components below a
        # common container such as apps/, services/, or libs/. Avoid assigning
        # an uncovered sibling to that whole container when it has manifest
        # owned children.
        if any(root.startswith(top + "/") for root in roots) and len(relative.parts) > 2:
            fallback.add("/".join(relative.parts[:2]))
        else:
            fallback.add(top)
    return fallback


def _prune_nested_component_roots(source_root: Path, roots: set[str]) -> set[str]:
    """Keep a parent component when it owns code beyond nested helper packages."""
    kept: set[str] = set()
    for root in sorted(roots, key=lambda value: (len(Path(value).parts), value)):
        if any(root.startswith(parent + "/") for parent in kept):
            continue
        descendants = {
            candidate[len(root) + 1 :]
            for candidate in roots
            if candidate.startswith(root + "/")
        }
        if descendants and not _files_outside_roots(source_root / root, descendants):
            continue
        kept.add(root)
    return kept


def _files_outside_roots(source_root: Path, roots: set[str]) -> bool:
    for path in _source_files(source_root):
        relative = path.relative_to(source_root).as_posix()
        if not any(relative.startswith(root + "/") for root in roots):
            return True
    return False


def _source_files(root: Path) -> list[Path]:
    return [
        path
        for path in _visible_files(root)
        if path.suffix.lower() in _SOURCE_SUFFIXES
    ]


def _visible_files(root: Path) -> list[Path]:
    """List files while pruning generated and hidden directories before descent."""
    if not root.is_dir():
        return []

    files: list[Path] = []
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames if not _is_ignored_directory(name)
        )
        files.extend(Path(directory) / name for name in filenames)
    return sorted(files)


def _is_ignored_directory(name: str) -> bool:
    return name.startswith(".") or name in _IGNORED_PARTS


def _line_count(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _slug(root: str) -> str:
    value = "root" if root == "." else root.lower().replace("_", "-")
    value = _SAFE_SLUG.sub("-", value).strip("-")
    return value or "root"


def _safe_relative_root(value: str) -> bool:
    path = Path(value)
    return value == "." or (
        not path.is_absolute()
        and ".." not in path.parts
        and not any(_is_ignored_directory(part) for part in path.parts)
        and value == path.as_posix()
        and value != ""
    )
