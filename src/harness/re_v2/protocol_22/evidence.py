"""Provider-neutral bounded evidence selection for protocol 2.2."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path, PurePosixPath
import stat
from types import MappingProxyType
from typing import ClassVar, Literal, Mapping, Protocol

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.snapshot import (
    CapturedSnapshot,
    ReV2SnapshotError,
    load_snapshot_manifest,
    validate_source_snapshot,
)

from .artifacts import (
    DepthDebtV1,
    DeterministicAssessmentInputV2,
    EvidenceExcerptV1,
    EvidencePackV1,
    OmittedEvidenceDescriptorV1,
)
from .inventory import InventoryArtifactV1, InventoryFileV1
from .model import WorkItemV2
from .partition import FileRecordV1, WorkspacePartitionCatalogV1
from .policies import (
    ArtifactPolicyEntryV1,
    DomainEvidencePackPolicyParametersV1,
    EvidencePackPolicyParametersV1,
    PathClassifierV1,
    Protocol22PolicyError,
    SourceEvidencePackPolicyParametersV1,
    layer_policy_hash,
)
from .schema import (
    Protocol22SchemaError,
    exact_object,
    load_canonical_object,
    one_of,
    optional_digest,
    safe_id,
    safe_relative_path,
)


class Protocol22EvidenceError(Protocol22SchemaError):
    """Raised when pinned evidence cannot be selected or reconstructed safely."""


class SnapshotReaderV1(Protocol):
    def read_file(
        self,
        source_id: str,
        source_relative_path: str,
        expected: FileRecordV1,
    ) -> bytes:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class EvidenceAuthorityDescriptorV1:
    source_id: str
    source_relative_path: str
    authority_kind: Literal["direct", "domain_projection"]
    origin_domain_key: str | None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "source_id",
        "source_relative_path",
        "authority_kind",
        "origin_domain_key",
    )

    def __post_init__(self) -> None:
        try:
            safe_id(self.source_id, "EvidenceAuthorityDescriptorV1.source_id")
            safe_relative_path(
                self.source_relative_path,
                "EvidenceAuthorityDescriptorV1.source_relative_path",
            )
            one_of(
                self.authority_kind,
                frozenset({"direct", "domain_projection"}),
                "EvidenceAuthorityDescriptorV1.authority_kind",
            )
            optional_digest(
                self.origin_domain_key,
                "EvidenceAuthorityDescriptorV1.origin_domain_key",
            )
        except Protocol22SchemaError as exc:
            raise Protocol22EvidenceError(str(exc)) from exc
        if self.authority_kind == "domain_projection" and self.origin_domain_key is None:
            raise Protocol22EvidenceError(
                "domain_projection authority requires origin_domain_key"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "EvidenceAuthorityDescriptorV1":
        try:
            raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
            return cls(**{field: raw[field] for field in cls.FIELDS})
        except Protocol22EvidenceError:
            raise
        except Protocol22SchemaError as exc:
            raise Protocol22EvidenceError(str(exc)) from exc


def evidence_authority_id(descriptor: EvidenceAuthorityDescriptorV1) -> str:
    if not isinstance(descriptor, EvidenceAuthorityDescriptorV1):
        raise Protocol22EvidenceError(
            "evidence authority hashing requires EvidenceAuthorityDescriptorV1"
        )
    return content_digest(descriptor.to_json_dict())


@dataclass(frozen=True, slots=True)
class PinnedSnapshotReaderV1:
    """Read only catalog-authorized regular files from one immutable snapshot."""

    snapshot: CapturedSnapshot
    partition: WorkspacePartitionCatalogV1
    _roots: Mapping[str, Path] = field(init=False, repr=False, compare=False)
    _records: Mapping[str, Mapping[str, FileRecordV1]] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, CapturedSnapshot):
            raise Protocol22EvidenceError(
                "PinnedSnapshotReaderV1 requires a CapturedSnapshot"
            )
        if not isinstance(self.partition, WorkspacePartitionCatalogV1):
            raise Protocol22EvidenceError(
                "PinnedSnapshotReaderV1 requires a workspace partition catalog"
            )
        if self.snapshot.snapshot_id != self.partition.snapshot_id:
            raise Protocol22EvidenceError(
                "snapshot identity does not match workspace partition catalog"
            )
        try:
            validate_source_snapshot(self.snapshot)
            manifest = load_snapshot_manifest(self.snapshot)
        except ReV2SnapshotError as exc:
            raise Protocol22EvidenceError(f"invalid pinned snapshot: {exc}") from exc
        if manifest.components is None:
            raise Protocol22EvidenceError(
                "pinned evidence requires a composite workspace snapshot"
            )
        components = {component.source_id: component for component in manifest.components}
        declared = {source.source_id: source for source in self.partition.sources}
        if set(components) != set(declared):
            raise Protocol22EvidenceError(
                "snapshot components do not match partition catalog sources"
            )
        roots: dict[str, Path] = {}
        records: dict[str, Mapping[str, FileRecordV1]] = {}
        for source_id, source in declared.items():
            component = components[source_id]
            if component.workspace_path != source.workspace_relative_path:
                raise Protocol22EvidenceError(
                    "snapshot component path does not match partition catalog"
                )
            root = (
                self.snapshot.read_root
                if component.workspace_path == "."
                else self.snapshot.read_root.joinpath(
                    *component.workspace_path.split("/")
                )
            )
            roots[source_id] = root
            records[source_id] = MappingProxyType(
                {record.source_relative_path: record for record in source.files}
            )
        object.__setattr__(self, "_roots", MappingProxyType(roots))
        object.__setattr__(self, "_records", MappingProxyType(records))

    def read_file(
        self,
        source_id: str,
        source_relative_path: str,
        expected: FileRecordV1,
    ) -> bytes:
        if not isinstance(expected, FileRecordV1):
            raise Protocol22EvidenceError(
                "pinned read requires a catalog FileRecordV1"
            )
        try:
            safe_id(source_id, "PinnedSnapshotReaderV1.source_id")
            safe_relative_path(
                source_relative_path,
                "PinnedSnapshotReaderV1.source_relative_path",
            )
        except Protocol22SchemaError as exc:
            raise Protocol22EvidenceError(str(exc)) from exc
        records = self._records.get(source_id)
        if records is None:
            raise Protocol22EvidenceError(
                f"source is absent from pinned catalog: {source_id}"
            )
        catalog_record = records.get(source_relative_path)
        if catalog_record is None or catalog_record != expected:
            raise Protocol22EvidenceError(
                "expected file record does not byte-match catalog authority"
            )
        if expected.object_kind != "regular":
            raise Protocol22EvidenceError("pinned evidence file is not regular")
        payload, mode = _read_no_follow(
            self._roots[source_id],
            source_relative_path,
        )
        actual = _record_for_payload(source_relative_path, mode, payload)
        if actual != expected:
            raise Protocol22EvidenceError(
                "pinned snapshot bytes do not match catalog authority"
            )
        return payload


@dataclass(frozen=True, slots=True)
class _Candidate:
    row: InventoryFileV1
    record: FileRecordV1
    payload: bytes
    lines: tuple[bytes, ...]
    role_index: int
    origin_domain_key: str | None

    @property
    def key(self) -> tuple[bytes, str]:
        return self.row.sort_key

    @property
    def priority_key(self) -> tuple[object, ...]:
        return self.role_index, *self.row.sort_key


@dataclass(frozen=True, slots=True)
class _SelectionContext:
    work_item: WorkItemV2
    inventory: InventoryArtifactV1
    inventory_hash: str
    policy: ArtifactPolicyEntryV1
    candidates: tuple[_Candidate, ...]
    ineligible: tuple[OmittedEvidenceDescriptorV1, ...]


def build_evidence_pack(
    work_item: WorkItemV2,
    inventory_bytes: bytes,
    snapshot_reader: SnapshotReaderV1,
    policy: ArtifactPolicyEntryV1,
) -> bytes:
    """Select complete original-line prefixes under provider-neutral byte caps."""
    context = _selection_context(
        work_item,
        inventory_bytes,
        snapshot_reader,
        policy,
    )
    selections = {candidate.key: 0 for candidate in context.candidates}
    rejection_reasons: dict[tuple[bytes, str], str] = {}

    # Stage 2: retain one whole line from each candidate in pinned priority order.
    for candidate in sorted(context.candidates, key=lambda item: item.priority_key):
        if not candidate.lines:
            continue
        proposal = dict(selections)
        proposal[candidate.key] = 1
        if _selection_fits(context, proposal, rejection_reasons):
            selections = proposal
            continue
        isolated = {item.key: 0 for item in context.candidates}
        isolated[candidate.key] = 1
        reason = (
            "capacity_exhausted"
            if _selection_fits(context, isolated, {})
            else "line_too_large"
        )
        rejection_reasons[candidate.key] = reason

    retained = tuple(
        sorted(
            (
                candidate
                for candidate in context.candidates
                if selections[candidate.key] > 0
            ),
            key=lambda item: item.key,
        )
    )

    # Stage 3: divide remaining serialized capacity equally across retained files.
    if retained:
        current_size = _selection_size(context, selections, rejection_reasons)
        remaining = max(0, _effective_cap(policy) - current_size)
        share = remaining // len(retained)
        for candidate in retained:
            starting_size = _selection_size(
                context,
                selections,
                rejection_reasons,
            )
            while selections[candidate.key] < len(candidate.lines):
                proposal = dict(selections)
                proposal[candidate.key] += 1
                proposal_size = _selection_size(
                    context,
                    proposal,
                    rejection_reasons,
                )
                if (
                    proposal_size - starting_size > share
                    or proposal_size > _effective_cap(context.policy)
                ):
                    break
                selections = proposal

    # Stage 4: redistribute unused capacity in normalized-path round-robin passes.
    while retained:
        progressed = False
        for candidate in retained:
            if selections[candidate.key] >= len(candidate.lines):
                continue
            proposal = dict(selections)
            proposal[candidate.key] += 1
            if _selection_fits(context, proposal, rejection_reasons):
                selections = proposal
                progressed = True
        if not progressed:
            break

    value = _pack_value(context, selections, rejection_reasons)
    payload = canonical_json_bytes(value)
    if not _fits(policy, payload):
        raise Protocol22EvidenceError(
            "evidence policy cannot encode its mandatory depth debt"
        )
    try:
        pack = EvidencePackV1.from_json_dict(value)
    except Protocol22SchemaError as exc:
        raise Protocol22EvidenceError(str(exc)) from exc
    return canonical_json_bytes(pack.to_json_dict())


def validate_evidence_pack(
    work_item: WorkItemV2,
    payload: bytes,
    inventory_bytes: bytes,
    snapshot_reader: SnapshotReaderV1,
    policy: ArtifactPolicyEntryV1,
) -> DeterministicAssessmentInputV2:
    """Reconstruct an evidence pack exactly; never repair candidate bytes."""
    if not isinstance(payload, bytes):
        raise Protocol22EvidenceError("evidence payload must be bytes")
    diagnostics: set[str] = set()
    decoded: EvidencePackV1 | None = None
    try:
        decoded = load_canonical_object(payload, EvidencePackV1.from_json_dict)
    except Protocol22SchemaError:
        diagnostics.add("canonical_schema_invalid")

    inventory_hash = content_digest(inventory_bytes) if isinstance(inventory_bytes, bytes) else None
    dependency_valid = (
        inventory_hash is not None
        and inventory_hash in work_item.required_artifact_hashes
    )
    if not dependency_valid:
        diagnostics.add("dependency_closure_invalid")

    policy_valid = False
    if decoded is not None:
        try:
            expected = build_evidence_pack(
                work_item,
                inventory_bytes,
                snapshot_reader,
                policy,
            )
        except (Protocol22EvidenceError, Protocol22SchemaError):
            expected = None
        policy_valid = expected is not None and payload == expected
        if not policy_valid:
            diagnostics.add("evidence_reconstruction_mismatch")

    return DeterministicAssessmentInputV2(
        canonical_schema_valid=decoded is not None,
        dependency_closure_valid=dependency_valid,
        policy_conformance_valid=policy_valid,
        depth_debt=None if decoded is None else decoded.depth_debt,
        normalized_diagnostics=tuple(sorted(diagnostics)),
    )


def _selection_context(
    work_item: WorkItemV2,
    inventory_bytes: bytes,
    snapshot_reader: SnapshotReaderV1,
    policy: ArtifactPolicyEntryV1,
) -> _SelectionContext:
    inventory, inventory_hash, parameters = _validate_invocation(
        work_item,
        inventory_bytes,
        snapshot_reader,
        policy,
    )
    role_index = {role: index for index, role in enumerate(parameters.role_priority)}
    candidates: list[_Candidate] = []
    ineligible: list[OmittedEvidenceDescriptorV1] = []
    origin = inventory.scope.domain_key
    for row in inventory.files:
        if row.object_kind != "regular" or row.text_status != "eligible_utf8":
            ineligible.append(_file_omission(row, origin, "non_text"))
            continue
        role = _classify_path(row.source_relative_path, parameters.path_classifiers)
        if role is None:
            ineligible.append(_file_omission(row, origin, "policy_ineligible"))
            continue
        record = _inventory_record(row)
        try:
            payload = snapshot_reader.read_file(
                inventory.scope.source_id,
                row.source_relative_path,
                record,
            )
        except Protocol22EvidenceError:
            raise
        except Exception as exc:
            raise Protocol22EvidenceError(
                f"pinned snapshot read failed: {row.source_relative_path}: {exc}"
            ) from exc
        _verify_payload(record, payload)
        candidates.append(
            _Candidate(
                row=row,
                record=record,
                payload=payload,
                lines=_raw_lines(payload),
                role_index=role_index[role],
                origin_domain_key=origin,
            )
        )
    return _SelectionContext(
        work_item=work_item,
        inventory=inventory,
        inventory_hash=inventory_hash,
        policy=policy,
        candidates=tuple(candidates),
        ineligible=tuple(sorted(ineligible, key=_omission_sort_key)),
    )


def _validate_invocation(
    work_item: WorkItemV2,
    inventory_bytes: bytes,
    snapshot_reader: SnapshotReaderV1,
    policy: ArtifactPolicyEntryV1,
) -> tuple[
    InventoryArtifactV1,
    str,
    EvidencePackPolicyParametersV1,
]:
    if not isinstance(work_item, WorkItemV2):
        raise Protocol22EvidenceError(
            "evidence producer requires schema-2 WorkItemV2"
        )
    if not isinstance(inventory_bytes, bytes):
        raise Protocol22EvidenceError("inventory payload must be bytes")
    if not callable(getattr(snapshot_reader, "read_file", None)):
        raise Protocol22EvidenceError(
            "snapshot reader must implement the pinned read contract"
        )
    if not isinstance(policy, ArtifactPolicyEntryV1):
        raise Protocol22EvidenceError(
            "evidence producer requires a closed artifact policy"
        )
    kind = work_item.output_key.artifact_kind
    if kind not in {"source-evidence-pack", "domain-evidence-pack"}:
        raise Protocol22EvidenceError("work item is not an evidence-pack artifact")
    expected_inventory_kind = (
        "domain-inventory" if kind == "domain-evidence-pack" else "source-inventory"
    )
    try:
        inventory = load_canonical_object(
            inventory_bytes,
            InventoryArtifactV1.from_json_dict,
        )
    except Protocol22SchemaError as exc:
        raise Protocol22EvidenceError(f"invalid canonical inventory: {exc}") from exc
    if inventory.artifact_kind != expected_inventory_kind:
        raise Protocol22EvidenceError(
            "inventory artifact kind does not match evidence scope"
        )
    if inventory.scope != work_item.output_key.scope:
        raise Protocol22EvidenceError(
            "inventory scope does not match evidence work item scope"
        )
    if kind == "domain-evidence-pack":
        if inventory.partition_id != work_item.output_key.partition_id:
            raise Protocol22EvidenceError(
                "inventory partition does not match evidence work item"
            )
    elif inventory.partition_id is not None:
        raise Protocol22EvidenceError(
            "source inventory must have null partition identity"
        )
    inventory_hash = content_digest(inventory_bytes)
    expected_dependency_count = 1 if kind == "domain-evidence-pack" else 2
    if (
        inventory_hash not in work_item.required_artifact_hashes
        or len(work_item.required_artifact_hashes) != expected_dependency_count
    ):
        raise Protocol22EvidenceError(
            "inventory hash does not match evidence dependency closure"
        )
    if policy.artifact_kind != kind or policy.layer != "L0":
        raise Protocol22EvidenceError(
            "evidence policy does not match work item artifact kind"
        )
    try:
        policy_hash = layer_policy_hash(policy)
    except Protocol22PolicyError as exc:
        raise Protocol22EvidenceError(str(exc)) from exc
    expected_contract = {
        "producer_id": "evidence-pack-producer-v1",
        "producer_family": "evidence-pack",
        "producer_protocol_version": policy.producer_protocol_version,
        "result_contract_id": policy.result_contract_id,
    }
    for field_name, expected in expected_contract.items():
        if getattr(work_item, field_name) != expected:
            raise Protocol22EvidenceError(
                f"work item {field_name} does not match evidence policy"
            )
    if work_item.output_key.layer_policy_hash != policy_hash:
        raise Protocol22EvidenceError(
            "work item layer policy hash does not match evidence policy"
        )
    if (
        work_item.output_key.producer_protocol_version
        != policy.producer_protocol_version
    ):
        raise Protocol22EvidenceError(
            "output key producer protocol does not match evidence policy"
        )
    if work_item.output_key.layer != "L0":
        raise Protocol22EvidenceError("evidence work item must use layer L0")
    parameters = policy.policy_parameters
    expected_parameter_type = (
        DomainEvidencePackPolicyParametersV1
        if kind == "domain-evidence-pack"
        else SourceEvidencePackPolicyParametersV1
    )
    if not isinstance(parameters, expected_parameter_type):
        raise Protocol22EvidenceError(
            "evidence policy parameters do not match work item scope"
        )
    if policy.max_conservative_input_tokens is None:
        raise Protocol22EvidenceError(
            "evidence policy requires a conservative input-token cap"
        )
    if policy.byte_estimator_id != "utf8-byte-upper-bound-v1":
        raise Protocol22EvidenceError("unsupported evidence byte estimator")
    return inventory, inventory_hash, parameters


def _inventory_record(row: InventoryFileV1) -> FileRecordV1:
    return FileRecordV1(
        **{field: getattr(row, field) for field in FileRecordV1.FIELDS}
    )


def _classify_path(
    path: str,
    classifiers: tuple[PathClassifierV1, ...],
) -> str | None:
    candidate = PurePosixPath(path)
    for classifier in classifiers:
        for pattern in classifier.patterns:
            if candidate.match(pattern) or (
                pattern.startswith("**/") and candidate.match(pattern[3:])
            ):
                return classifier.role
    return None


def _raw_lines(payload: bytes) -> tuple[bytes, ...]:
    if not payload:
        return ()
    lines: list[bytes] = []
    start = 0
    while True:
        delimiter = payload.find(b"\n", start)
        if delimiter < 0:
            if start < len(payload):
                lines.append(payload[start:])
            break
        lines.append(payload[start : delimiter + 1])
        start = delimiter + 1
        if start == len(payload):
            break
    return tuple(lines)


def _verify_payload(expected: FileRecordV1, payload: object) -> None:
    if not isinstance(payload, bytes):
        raise Protocol22EvidenceError("pinned snapshot reader returned non-bytes")
    try:
        decoded = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise Protocol22EvidenceError(
            "eligible snapshot payload is not strict UTF-8"
        ) from exc
    if b"\x00" in payload:
        raise Protocol22EvidenceError("eligible snapshot payload contains NUL")
    if (
        expected.object_kind != "regular"
        or expected.text_status != "eligible_utf8"
        or content_digest(payload) != expected.content_hash
        or len(payload) != expected.byte_count
        or len(_raw_lines(payload)) != expected.line_count
    ):
        raise Protocol22EvidenceError(
            "pinned snapshot payload does not match inventory record"
        )
    if decoded.encode("utf-8") != payload:
        raise Protocol22EvidenceError("snapshot UTF-8 round trip changed bytes")


def _file_omission(
    row: InventoryFileV1,
    origin_domain_key: str | None,
    reason: str,
) -> OmittedEvidenceDescriptorV1:
    return OmittedEvidenceDescriptorV1(
        descriptor_kind="file",
        source_relative_path=row.source_relative_path,
        ownership=row.ownership,
        origin_domain_key=origin_domain_key,
        start_line=None,
        end_line=None,
        reason_code=reason,
    )


def _range_omission(
    candidate: _Candidate,
    first_omitted_line: int,
) -> OmittedEvidenceDescriptorV1:
    return OmittedEvidenceDescriptorV1(
        descriptor_kind="line_range",
        source_relative_path=candidate.row.source_relative_path,
        ownership=candidate.row.ownership,
        origin_domain_key=candidate.origin_domain_key,
        start_line=first_omitted_line,
        end_line=len(candidate.lines),
        reason_code="capacity_exhausted",
    )


def _omission_sort_key(value: OmittedEvidenceDescriptorV1) -> tuple[object, ...]:
    return (
        value.source_relative_path.encode("utf-8"),
        value.ownership,
        "" if value.origin_domain_key is None else value.origin_domain_key,
        value.descriptor_kind,
        0 if value.start_line is None else value.start_line,
        0 if value.end_line is None else value.end_line,
        value.reason_code,
    )


def _pack_value(
    context: _SelectionContext,
    selections: Mapping[tuple[bytes, str], int],
    rejection_reasons: Mapping[tuple[bytes, str], str],
) -> dict[str, object]:
    excerpts: list[EvidenceExcerptV1] = []
    omissions = list(context.ineligible)
    fully_selected = 0
    partially_selected = 0
    omitted_files = len(context.ineligible)
    omitted_ranges = 0
    for candidate in context.candidates:
        selected_count = selections[candidate.key]
        total = len(candidate.lines)
        if total == 0:
            fully_selected += 1
            continue
        if selected_count == 0:
            omitted_files += 1
            omissions.append(
                _file_omission(
                    candidate.row,
                    candidate.origin_domain_key,
                    rejection_reasons.get(candidate.key, "capacity_exhausted"),
                )
            )
            continue
        raw = b"".join(candidate.lines[:selected_count])
        descriptor = EvidenceAuthorityDescriptorV1(
            source_id=context.inventory.scope.source_id,
            source_relative_path=candidate.row.source_relative_path,
            authority_kind="direct",
            origin_domain_key=candidate.origin_domain_key,
        )
        excerpts.append(
            EvidenceExcerptV1(
                evidence_authority_id=evidence_authority_id(descriptor),
                source_relative_path=candidate.row.source_relative_path,
                ownership=candidate.row.ownership,
                origin_domain_key=candidate.origin_domain_key,
                mode=candidate.row.mode,
                source_blob_hash=candidate.row.content_hash,
                start_line=1,
                end_line=selected_count,
                raw_excerpt_hash=content_digest(raw),
                text_lf=raw.decode("utf-8", errors="strict").replace("\r\n", "\n"),
                complete_file=selected_count == total,
            )
        )
        if selected_count == total:
            fully_selected += 1
        else:
            partially_selected += 1
            omitted_ranges += 1
            omissions.append(_range_omission(candidate, selected_count + 1))
    omissions = sorted(omissions, key=_omission_sort_key)
    omission_hash = (
        None
        if not omissions
        else content_digest([item.to_json_dict() for item in omissions])
    )
    debt = DepthDebtV1(
        inventory_file_count=len(context.inventory.files),
        fully_selected_file_count=fully_selected,
        partially_selected_file_count=partially_selected,
        omitted_file_count=omitted_files,
        omitted_range_count=omitted_ranges,
        omitted_descriptor_hash=omission_hash,
        domain_depth_debt_rollup=None,
        omitted_domain_summary_count=0,
        omitted_domain_descriptor_hash=None,
        retained_projected_claim_count=0,
        omitted_projected_claim_count=0,
        omitted_projected_claim_descriptor_hash=None,
    )
    policy = context.policy
    return {
        "schema_version": 1,
        "artifact_kind": context.work_item.output_key.artifact_kind,
        "scope": context.work_item.output_key.scope.to_json_dict(),
        "layer_policy_hash": context.work_item.output_key.layer_policy_hash,
        "inventory_artifact_hash": context.inventory_hash,
        "byte_estimator_id": policy.byte_estimator_id,
        "max_canonical_json_bytes": policy.max_canonical_json_bytes,
        "max_conservative_input_tokens": policy.max_conservative_input_tokens,
        "excerpts": [
            item.to_json_dict() for item in sorted(excerpts, key=lambda item: item.sort_key)
        ],
        "depth_debt": debt.to_json_dict(),
    }


def _effective_cap(policy: ArtifactPolicyEntryV1) -> int:
    token_cap = policy.max_conservative_input_tokens
    if token_cap is None:
        raise Protocol22EvidenceError(
            "evidence policy requires max_conservative_input_tokens"
        )
    return min(policy.max_canonical_json_bytes, token_cap)


def _fits(policy: ArtifactPolicyEntryV1, payload: bytes) -> bool:
    return len(payload) <= _effective_cap(policy)


def _selection_size(
    context: _SelectionContext,
    selections: Mapping[tuple[bytes, str], int],
    rejection_reasons: Mapping[tuple[bytes, str], str],
) -> int:
    return len(canonical_json_bytes(_pack_value(context, selections, rejection_reasons)))


def _selection_fits(
    context: _SelectionContext,
    selections: Mapping[tuple[bytes, str], int],
    rejection_reasons: Mapping[tuple[bytes, str], str],
) -> bool:
    return _fits(
        context.policy,
        canonical_json_bytes(_pack_value(context, selections, rejection_reasons)),
    )


def _read_no_follow(root: Path, source_relative_path: str) -> tuple[bytes, str]:
    parts = PurePosixPath(source_relative_path).parts
    if not parts:
        raise Protocol22EvidenceError("snapshot file path is empty")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        raise Protocol22EvidenceError(
            "platform cannot provide required no-follow snapshot reads"
        )
    descriptors: list[int] = []
    try:
        current = os.open(root, directory_flags | nofollow)
        descriptors.append(current)
        if not stat.S_ISDIR(os.fstat(current).st_mode):
            raise Protocol22EvidenceError("snapshot component root is not a directory")
        for part in parts[:-1]:
            current = os.open(part, directory_flags | nofollow, dir_fd=current)
            descriptors.append(current)
            if not stat.S_ISDIR(os.fstat(current).st_mode):
                raise Protocol22EvidenceError(
                    f"snapshot evidence parent is not a directory: {source_relative_path}"
                )
        file_descriptor = os.open(
            parts[-1],
            os.O_RDONLY | nofollow,
            dir_fd=current,
        )
        descriptors.append(file_descriptor)
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise Protocol22EvidenceError(
                f"snapshot evidence entry is not regular: {source_relative_path}"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(file_descriptor)
    except Protocol22EvidenceError:
        raise
    except OSError as exc:
        raise Protocol22EvidenceError(
            f"snapshot evidence entry cannot be read safely: {source_relative_path}: {exc}"
        ) from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mode,
        before.st_mtime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mode,
        after.st_mtime_ns,
    )
    if before_identity != after_identity:
        raise Protocol22EvidenceError(
            f"snapshot evidence entry changed while read: {source_relative_path}"
        )
    executable = bool(stat.S_IMODE(after.st_mode) & 0o111)
    return b"".join(chunks), "100755" if executable else "100644"


def _record_for_payload(path: str, mode: str, payload: bytes) -> FileRecordV1:
    if b"\x00" in payload:
        text_status = "contains_nul"
    else:
        try:
            payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            text_status = "invalid_utf8"
        else:
            text_status = "eligible_utf8"
    return FileRecordV1(
        source_relative_path=path,
        mode=mode,
        object_kind="regular",
        content_hash=content_digest(payload),
        byte_count=len(payload),
        line_count=len(_raw_lines(payload)),
        text_status=text_status,
    )


__all__ = (
    "EvidenceAuthorityDescriptorV1",
    "PinnedSnapshotReaderV1",
    "Protocol22EvidenceError",
    "SnapshotReaderV1",
    "build_evidence_pack",
    "evidence_authority_id",
    "validate_evidence_pack",
)
