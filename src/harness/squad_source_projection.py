"""Pure final selected-source projection for a sealed publication."""

from __future__ import annotations

from pathlib import Path

from harness import squad_publication as publication
from harness.squad_publication_snapshot import PublicationImageDescriptor
from harness.squad_source_baseline_codec import encode_initial_publication_sources
from harness.squad_source_manifest import (
    SourceManifestSnapshot,
    snapshot_source_manifest,
)
from harness.squad_source_snapshot import (
    ProjectDirectorySnapshot,
    ProjectFileSnapshot,
    ProjectPathSnapshot,
    ProjectTreeSnapshot,
    PublicationSourcesSnapshot,
)


def _parts(path: str) -> tuple[str, ...]:
    return tuple(Path(path).parts)


def _is_at_or_below(path: tuple[str, ...], root: tuple[str, ...]) -> bool:
    return path[:len(root)] == root


def _missing() -> PublicationImageDescriptor:
    return PublicationImageDescriptor("missing", None, None)


def _invalid() -> None:
    raise publication.PublicationError("manifest_invalid")


def project_publication_source_manifest(
    initial: PublicationSourcesSnapshot,
) -> SourceManifestSnapshot:
    """Project the exact selected-source metadata after every sealed operation."""
    encode_initial_publication_sources(initial)

    try:
        operations = tuple(
            (operation, _parts(operation.target))
            for operation in initial.publication.operations
        )
        tree_roots = tuple((tree, _parts(tree.path)) for tree in initial.trees)
        selected_files = tuple((item, _parts(item.path)) for item in initial.files)

        for operation, target in operations:
            if operation.action != "write":
                continue
            if any(_is_at_or_below(root, target) for _, root in tree_roots):
                _invalid()
            if any(
                target != selected
                and (
                    _is_at_or_below(target, selected)
                    or _is_at_or_below(selected, target)
                )
                for _, selected in selected_files
            ):
                _invalid()

        projected_trees: list[ProjectTreeSnapshot] = []
        for tree, root in tree_roots:
            directories = {item.path: item for item in tree.directories}
            files = {item.path: item for item in tree.files}
            exists = tree.exists
            for operation, target in operations:
                if not _is_at_or_below(target, root) or target == root:
                    continue
                if operation.action == "delete":
                    files.pop(operation.target, None)
                    continue
                postimage_bytes = operation.postimage_bytes
                if type(postimage_bytes) is not bytes:
                    _invalid()
                exists = True
                for length in range(len(root), len(target)):
                    path = Path(*target[:length]).as_posix()
                    directories.setdefault(
                        path,
                        ProjectDirectorySnapshot(
                            path, publication.PUBLICATION_DIRECTORY_MODE,
                        ),
                    )
                files[operation.target] = ProjectFileSnapshot(
                    operation.target, operation.postimage, postimage_bytes,
                )
            projected_trees.append(ProjectTreeSnapshot(
                tree.path,
                exists,
                tuple(sorted(directories.values(), key=lambda item: item.path)),
                tuple(sorted(files.values(), key=lambda item: item.path)),
            ))

        projected_files: list[ProjectPathSnapshot] = []
        operation_by_target = {
            operation.target: operation for operation, _ in operations
        }
        for item, _ in selected_files:
            operation = operation_by_target.get(item.path)
            if operation is None:
                projected_files.append(item)
            elif operation.action == "delete":
                projected_files.append(ProjectPathSnapshot(
                    item.path, _missing(), None,
                ))
            else:
                postimage_bytes = operation.postimage_bytes
                if type(postimage_bytes) is not bytes:
                    _invalid()
                projected_files.append(ProjectPathSnapshot(
                    item.path, operation.postimage, postimage_bytes,
                ))

        return snapshot_source_manifest(
            trees=tuple(projected_trees), files=tuple(projected_files),
        )
    except publication.PublicationError:
        raise
    except Exception:
        raise publication.PublicationError("manifest_invalid") from None
