"""Installed implementation authority for protocol 2.2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import ClassVar, Mapping

from harness.re_v2.canonical import content_digest

from .schema import Protocol22SchemaError, digest_value, safe_id


class Protocol22AuthorityError(Protocol22SchemaError):
    """Raised when an installed authority registration is invalid."""


_REGISTRY_FIELDS = (
    "executor_implementations",
    "renderer_implementations",
    "tokenizer_implementations",
    "calculator_implementations",
    "normalizer_implementations",
    "verifier_implementations",
    "partitioner_implementations",
    "ownership_implementations",
    "agent_contracts",
    "response_schemas",
)

_KIND_TO_FIELD = {
    "executor": "executor_implementations",
    "renderer": "renderer_implementations",
    "tokenizer": "tokenizer_implementations",
    "calculator": "calculator_implementations",
    "normalizer": "normalizer_implementations",
    "verifier": "verifier_implementations",
    "partitioner": "partitioner_implementations",
    "ownership": "ownership_implementations",
    "agent_contract": "agent_contracts",
    "response_schema": "response_schemas",
}


def implementation_closure_digest(files: Mapping[str, bytes]) -> str:
    """Hash a logical implementation closure independent of install location."""
    if not isinstance(files, Mapping) or not files:
        raise Protocol22AuthorityError(
            "implementation closure must contain at least one logical file"
        )
    rows: list[dict[str, str]] = []
    for logical_path, payload in files.items():
        path = _logical_path(logical_path)
        if not isinstance(payload, bytes):
            raise Protocol22AuthorityError(
                f"implementation closure payload must be bytes: {path}"
            )
        rows.append(
            {
                "content_hash": content_digest(payload),
                "logical_path": path,
            }
        )
    rows.sort(key=lambda row: row["logical_path"].encode("utf-8"))
    return content_digest(
        {
            "closure_schema": "implementation-closure-v1",
            "files": rows,
        }
    )


def _logical_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise Protocol22AuthorityError(
            "implementation closure logical path must be a normalized relative path"
        )
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise Protocol22AuthorityError(
            "implementation closure logical path contains invalid Unicode"
        ) from exc
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise Protocol22AuthorityError(
            "implementation closure logical path must be a normalized relative path"
        )
    return value


@dataclass(frozen=True, slots=True)
class InstalledAuthorityRegistry:
    executor_implementations: Mapping[str, str]
    renderer_implementations: Mapping[str, str]
    tokenizer_implementations: Mapping[str, str]
    calculator_implementations: Mapping[str, str]
    normalizer_implementations: Mapping[str, str]
    verifier_implementations: Mapping[str, str]
    partitioner_implementations: Mapping[str, str]
    ownership_implementations: Mapping[str, str]
    agent_contracts: Mapping[str, str]
    response_schemas: Mapping[str, str]

    FIELDS: ClassVar[tuple[str, ...]] = _REGISTRY_FIELDS

    def __post_init__(self) -> None:
        for field in self.FIELDS:
            value = getattr(self, field)
            if not isinstance(value, Mapping):
                raise Protocol22AuthorityError(
                    f"InstalledAuthorityRegistry.{field} must be a mapping"
                )
            copied: dict[str, str] = {}
            for authority_id, implementation_digest in value.items():
                try:
                    safe_id(
                        authority_id,
                        f"InstalledAuthorityRegistry.{field} authority ID",
                    )
                    digest_value(
                        implementation_digest,
                        f"InstalledAuthorityRegistry.{field} digest",
                    )
                except Protocol22SchemaError as exc:
                    raise Protocol22AuthorityError(str(exc)) from exc
                copied[authority_id] = implementation_digest
            object.__setattr__(
                self,
                field,
                MappingProxyType(dict(sorted(copied.items()))),
            )

    def digest_for(self, authority_kind: str, authority_id: str) -> str | None:
        field = _KIND_TO_FIELD.get(authority_kind)
        if field is None:
            raise Protocol22AuthorityError(
                f"unknown installed authority kind: {authority_kind!r}"
            )
        return getattr(self, field).get(authority_id)

    def require(self, authority_kind: str, authority_id: str) -> str:
        installed = self.digest_for(authority_kind, authority_id)
        if installed is None:
            raise Protocol22AuthorityError(
                f"missing installed {authority_kind} authority {authority_id!r}"
            )
        return installed


@dataclass(frozen=True, slots=True)
class AuthorityMismatch:
    authority_kind: str
    authority_id: str
    expected_digest: str
    installed_digest: str | None

    def __post_init__(self) -> None:
        if self.authority_kind not in _KIND_TO_FIELD:
            raise Protocol22AuthorityError(
                f"unknown authority mismatch kind: {self.authority_kind!r}"
            )
        try:
            safe_id(self.authority_id, "AuthorityMismatch.authority_id")
            digest_value(self.expected_digest, "AuthorityMismatch.expected_digest")
            if self.installed_digest is not None:
                digest_value(
                    self.installed_digest,
                    "AuthorityMismatch.installed_digest",
                )
        except Protocol22SchemaError as exc:
            raise Protocol22AuthorityError(str(exc)) from exc


def validate_installed_authorities(
    catalog: object,
    registry: InstalledAuthorityRegistry,
) -> tuple[AuthorityMismatch, ...]:
    """Return every installed digest mismatch without mutating run state."""
    if not isinstance(registry, InstalledAuthorityRegistry):
        raise Protocol22AuthorityError(
            "validate_installed_authorities requires InstalledAuthorityRegistry"
        )
    entries = getattr(catalog, "entries", None)
    if not isinstance(entries, (list, tuple)):
        raise Protocol22AuthorityError("executor catalog has no closed entries")

    expected: dict[tuple[str, str], str] = {}

    def add(kind: str, authority_id: str, authority_digest: str) -> None:
        key = (kind, authority_id)
        previous = expected.get(key)
        if previous is not None and previous != authority_digest:
            raise Protocol22AuthorityError(
                f"executor catalog gives conflicting digests for {kind} {authority_id!r}"
            )
        expected[key] = authority_digest

    for entry in entries:
        try:
            add(
                "executor",
                entry.adapter_id,
                entry.executor_implementation_digest,
            )
            calculator = entry.reservation_calculator
            add(
                "calculator",
                calculator.calculator_id,
                calculator.implementation_digest,
            )
            accounting = entry.token_accounting
            add(
                "normalizer",
                accounting.normalization_id,
                accounting.implementation_digest,
            )
            verifier = entry.verifier
            add(
                "verifier",
                verifier.verifier_id,
                verifier.implementation_digest,
            )
            renderer = entry.request_renderer
            if renderer is not None:
                add(
                    "renderer",
                    renderer.renderer_id,
                    renderer.implementation_digest,
                )
                add(
                    "agent_contract",
                    _agent_contract_id(entry.producer_family),
                    renderer.agent_contract_hash,
                )
                for schema in renderer.response_schemas:
                    add(
                        "response_schema",
                        schema.artifact_kind,
                        schema.schema_hash,
                    )
            tokenizer = entry.request_tokenizer
            if tokenizer is not None:
                add(
                    "tokenizer",
                    tokenizer.tokenizer_id,
                    tokenizer.implementation_digest,
                )
        except AttributeError as exc:
            raise Protocol22AuthorityError(
                "executor catalog entry is not a closed authority value"
            ) from exc

    mismatches: list[AuthorityMismatch] = []
    for (kind, authority_id), expected_digest in sorted(expected.items()):
        installed = registry.digest_for(kind, authority_id)
        if installed != expected_digest:
            mismatches.append(
                AuthorityMismatch(
                    authority_kind=kind,
                    authority_id=authority_id,
                    expected_digest=expected_digest,
                    installed_digest=installed,
                )
            )
    return tuple(mismatches)


def _agent_contract_id(producer_family: str) -> str:
    role_by_family = {
        "closure-recheck": "echelon.re-validator",
        "compact-baseline": "echelon.re-baseliner",
        "compact-deepening": "echelon.re-deepener",
        "semantic-audit": "echelon.re-validator",
        "semantic-resolution": "echelon.re-resolver",
        "source-composition-guard": "echelon.re-validator",
    }
    role = role_by_family.get(producer_family)
    if role is not None:
        return role
    raise Protocol22AuthorityError(
        f"provider-backed producer has no agent authority: {producer_family}"
    )


__all__ = (
    "AuthorityMismatch",
    "InstalledAuthorityRegistry",
    "Protocol22AuthorityError",
    "implementation_closure_digest",
    "validate_installed_authorities",
)
