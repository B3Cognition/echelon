"""Pure assembly of captured physical source bytes into typed candidates."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from harness.element_artifacts import _validate_input
from harness.element_identity_candidate import (
    CandidateArtifact,
    CandidateDiagnostic,
    IDENTITY_SUPPORTED_ROLES,
)
from harness.squad_source_baseline_codec import encode_initial_publication_sources
from harness.squad_source_snapshot import PublicationSourcesSnapshot, _source_path


_INVALID_INPUT = "invalid captured candidate source request"
_INVALID_BASELINE = "typed source baseline must contain valid UTF-8 text without NUL"


@dataclass(frozen=True, slots=True)
class CandidateSourceBinding:
    source_path: str
    artifact_path: str
    role: str


@dataclass(frozen=True, slots=True)
class CapturedCandidateSources:
    artifacts: tuple[CandidateArtifact, ...]
    diagnostics: tuple[CandidateDiagnostic, ...]


def _sequence(value: object) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError
    return tuple(value)


def _parts(path: str) -> tuple[str, ...]:
    return PurePosixPath(path).parts


def _at_or_below(path: str, root: str) -> bool:
    path_parts, root_parts = _parts(path), _parts(root)
    return path_parts[:len(root_parts)] == root_parts


def _ancestors(path: str) -> set[str]:
    parts = _parts(path)
    return {PurePosixPath(*parts[:length]).as_posix() for length in range(1, len(parts))}


def _decode_typed(value: bytes, artifact_path: str) -> str:
    try:
        text = value.decode("utf-8")
        _validate_input(path=artifact_path, role="references", text=text)
        return text
    except (AttributeError, RecursionError, TypeError, UnicodeError, ValueError):
        raise ValueError(_INVALID_BASELINE) from None


def _normalize(
    bindings: object, writable_paths: object, opaque_write_paths: object,
) -> tuple[tuple[CandidateSourceBinding, ...], tuple[str, ...], tuple[str, ...]]:
    try:
        binding_values = _sequence(bindings)
        writable_values = _sequence(writable_paths)
        opaque_values = _sequence(opaque_write_paths)

        for binding in binding_values:
            if type(binding) is not CandidateSourceBinding:
                raise ValueError
            _source_path(binding.source_path)
            _validate_input(path=binding.artifact_path, role="references", text="")
            binding.artifact_path.encode("utf-8")
            if type(binding.role) is not str or binding.role not in IDENTITY_SUPPORTED_ROLES:
                raise ValueError
            binding.role.encode("utf-8")
        for path in (*writable_values, *opaque_values):
            _source_path(path)

        source_paths = tuple(binding.source_path for binding in binding_values)
        artifact_paths = tuple(binding.artifact_path for binding in binding_values)
        if len(set(source_paths)) != len(source_paths):
            raise ValueError
        if len(set(artifact_paths)) != len(artifact_paths):
            raise ValueError
        if len(set(writable_values)) != len(writable_values):
            raise ValueError
        if len(set(opaque_values)) != len(opaque_values):
            raise ValueError
        if not set(opaque_values) <= set(writable_values):
            raise ValueError
        if set(opaque_values) & set(source_paths):
            raise ValueError
        return binding_values, writable_values, opaque_values
    except Exception:
        raise ValueError(_INVALID_INPUT) from None


def assemble_candidate_sources(
    snapshot: PublicationSourcesSnapshot,
    bindings: Sequence[CandidateSourceBinding],
    *,
    writable_paths: Sequence[str],
    opaque_write_paths: Sequence[str] = (),
) -> CapturedCandidateSources:
    """Join an authenticated initial capture using only explicit caller mappings."""
    encode_initial_publication_sources(snapshot)
    bindings, writable_paths, opaque_write_paths = _normalize(
        bindings, writable_paths, opaque_write_paths,
    )

    operations = {operation.target: operation for operation in snapshot.publication.operations}
    observations = {item.path: item.content for item in snapshot.files}
    tree_roots = tuple(tree.path for tree in snapshot.trees)
    directories: set[str] = set()
    known_files: set[str] = set()
    for tree in snapshot.trees:
        for directory in tree.directories:
            directories.add(directory.path)
            directories.update(_ancestors(directory.path))
        for item in tree.files:
            observations[item.path] = item.content
            known_files.add(item.path)
            directories.update(_ancestors(item.path))
    for item in snapshot.files:
        if item.content is not None:
            known_files.add(item.path)
            directories.update(_ancestors(item.path))
    for operation in snapshot.publication.operations:
        if operation.current_bytes is not None:
            known_files.add(operation.target)
            directories.update(_ancestors(operation.target))

    diagnostics: list[CandidateDiagnostic] = []
    bound_sources = {binding.source_path for binding in bindings}
    writable = set(writable_paths)
    opaque = set(opaque_write_paths)
    for operation in snapshot.publication.operations:
        if operation.target not in writable:
            diagnostics.append(CandidateDiagnostic(
                "artifact_out_of_scope", operation.target, None,
                "sealed operation target is not explicitly writable",
            ))
        if operation.target not in bound_sources and operation.target not in opaque:
            diagnostics.append(CandidateDiagnostic(
                "publication_target_unbound", operation.target, None,
                "sealed operation target has no explicit typed or opaque binding",
            ))

    artifacts: list[CandidateArtifact] = []
    for binding in bindings:
        source_path = binding.source_path
        if source_path in directories or any(
            _at_or_below(source_path, path) and source_path != path for path in known_files
        ):
            raise ValueError(_INVALID_INPUT) from None
        operation = operations.get(source_path)
        captured = (
            operation is not None
            or source_path in observations
            or any(_at_or_below(source_path, root) for root in tree_roots)
        )
        if not captured:
            raise ValueError(_INVALID_INPUT) from None
        before = operation.current_bytes if operation is not None else observations.get(source_path)
        after = operation.postimage_bytes if operation is not None else before
        if before is None and after is None:
            continue
        before_text = None if before is None else _decode_typed(before, binding.artifact_path)
        if after is None:
            after_text = None
        else:
            try:
                after_text = _decode_typed(after, binding.artifact_path)
            except ValueError:
                diagnostics.append(CandidateDiagnostic(
                    "candidate_source_not_text", source_path, None,
                    "typed proposed source must contain valid UTF-8 text without NUL",
                ))
                continue
        artifacts.append(CandidateArtifact(
            binding.artifact_path, binding.role, before_text, after_text,
        ))

    return CapturedCandidateSources(
        tuple(sorted(artifacts, key=lambda item: item.path)),
        tuple(sorted(set(diagnostics), key=lambda row: (
            row.path or "", row.element_id or "", row.code, row.detail,
        ))),
    )


__all__ = ["CandidateSourceBinding", "CapturedCandidateSources", "assemble_candidate_sources"]
