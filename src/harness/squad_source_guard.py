"""Internal physical progress checks for one retained selected-source baseline."""

from pathlib import Path

from harness.squad_publication import PublicationError
from harness.squad_publication_snapshot import PublicationOperationSnapshot
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_projection import _transform_selected_sources
from harness.squad_source_snapshot import PublicationSourcesSnapshot


def _validate_source_progress(
    initial: PublicationSourcesSnapshot, current: PublicationSourcesSnapshot,
) -> None:
    original, observed = initial.publication, current.publication

    def binding(operation: PublicationOperationSnapshot) -> tuple[object, ...]:
        return (operation.action, operation.target, operation.preimage,
                operation.postimage, operation.postimage_bytes)

    if (original.marker != observed.marker
            or tuple(map(binding, original.operations)) != tuple(map(binding, observed.operations))):
        raise PublicationError("target_drift")
    actual = snapshot_source_manifest(trees=current.trees, files=current.files)
    prefix = observed.promoted_prefix
    if actual == _transform_selected_sources(initial, prefix):
        return

    # No-op postimages do not grant membership. Only the next unfinished write
    # can have created parents before replacing its target.
    next_operation = next((op for op in observed.operations[prefix:]
                           if op.current != op.postimage), None)
    if next_operation is not None and next_operation.action == "write":
        parts = Path(next_operation.target).parts
        chain = tuple(Path(*parts[:length]).as_posix()
                      for length in range(1, len(parts)))
        # Trying successive ancestor prefixes preserves original directory modes
        # and requires exact full-manifest equality, including absent trees.
        for length in range(1, len(chain) + 1):
            if actual == _transform_selected_sources(
                initial, prefix, new_directories=chain[:length],
            ):
                return
    raise PublicationError("target_drift")
