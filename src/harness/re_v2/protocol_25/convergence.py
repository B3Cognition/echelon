"""Bounded, recoverable one-successor Banzai convergence for L3."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Mapping

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.schema import load_canonical_object

from .debt import finalize_protocol_25_debt
from .guidance import GuidanceDirectiveV1


class BanzaiConvergenceError(RuntimeError):
    """Raised when bounded autonomous convergence cannot advance safely."""


@dataclass(frozen=True, slots=True)
class BanzaiResultV1:
    run_id: str
    semantic_status: str
    public_status: Literal["complete", "complete_with_debt"]
    successor_created: bool
    provider_call_count: int
    debt_manifest_hash: str | None
    guidance_directive_hash: str
    unresolved_start: int
    unresolved_end: int

    def to_json_dict(self) -> dict[str, object]:
        return {
            "automatic_successor_count": 1,
            "automatic_successor_limit": 1,
            "debt_manifest_hash": self.debt_manifest_hash,
            "guidance_directive_hash": self.guidance_directive_hash,
            "guidance_kind": "banzai",
            "provider_call_count": self.provider_call_count,
            "public_status": self.public_status,
            "run_id": self.run_id,
            "semantic_status": self.semantic_status,
            "successor_created": self.successor_created,
            "unresolved_end": self.unresolved_end,
            "unresolved_start": self.unresolved_start,
            "zero_call_reuse": self.provider_call_count == 0,
        }


def run_banzai_resume(
    *,
    project_root: Path,
    blocked_run_dir: Path,
    create_or_reuse_successor: Callable[[Path], tuple[Path, bool]],
    execute_successor: Callable[[Path], object],
) -> BanzaiResultV1:
    """Run at most one paid successor, then close or accept its exact debt."""
    coordinator = BanzaiCoordinator(
        project_root=Path(project_root),
        blocked_run_dir=Path(blocked_run_dir),
        create_or_reuse_successor=create_or_reuse_successor,
        execute_successor=execute_successor,
    )
    return coordinator.run()


@dataclass(slots=True)
class BanzaiCoordinator:
    project_root: Path
    blocked_run_dir: Path
    create_or_reuse_successor: Callable[[Path], tuple[Path, bool]]
    execute_successor: Callable[[Path], object]

    def run(self) -> BanzaiResultV1:
        starting_dir = self.blocked_run_dir.resolve()
        starting_authority = _load_authority(starting_dir)
        starting_status = _load_status(starting_dir)
        directive = _guidance_directive(starting_authority)

        if directive is not None and directive.kind == "banzai":
            _validate_banzai_directive(directive)
            return self._finish_child(
                starting_dir,
                starting_status,
                successor_created=False,
                directive=directive,
                unresolved_start=_unresolved_count(starting_status),
            )

        if starting_status.get("status") != "blocked_plateau":
            raise BanzaiConvergenceError(
                "Banzai requires an authenticated semantic plateau"
            )
        guidance = starting_status.get("guidance")
        if not isinstance(guidance, Mapping) or guidance.get("banzai_eligible") is not True:
            raise BanzaiConvergenceError(
                "Banzai requires complete audit, epoch, closure-root, and source-root authority"
            )

        child_dir, created = self.create_or_reuse_successor(starting_dir)
        child_dir = Path(child_dir).resolve()
        child_authority = _load_authority(child_dir)
        child_directive = _guidance_directive(child_authority)
        if child_directive is None:
            raise BanzaiConvergenceError("Banzai successor has no immutable guidance")
        _validate_banzai_directive(
            child_directive,
            expected_root=starting_authority.manifest.run_manifest_id,
        )
        return self._finish_child(
            child_dir,
            _load_status(child_dir),
            successor_created=created,
            directive=child_directive,
            unresolved_start=_unresolved_count(starting_status),
        )

    def _finish_child(
        self,
        child_dir: Path,
        before: Mapping[str, object],
        *,
        successor_created: bool,
        directive: GuidanceDirectiveV1,
        unresolved_start: int,
    ) -> BanzaiResultV1:
        status = str(before.get("status"))
        if status == "complete":
            return _result(
                child_dir, "complete", successor_created, 0, None,
                directive, unresolved_start, 0,
            )
        if status == "complete_with_debt":
            debt_hash = _debt_hash(before)
            return _result(
                child_dir,
                "complete_with_debt",
                successor_created,
                0,
                debt_hash,
                directive,
                unresolved_start,
                _unresolved_count(before),
            )
        if status == "blocked_plateau":
            acceptance = _finalize_debt(self.project_root, child_dir)
            after = _load_status(child_dir)
            if after.get("status") != "complete_with_debt":
                raise BanzaiConvergenceError(
                    "validated residual debt did not produce a terminal public status"
                )
            debt_hash = _debt_hash(after)
            if debt_hash != acceptance.identity:
                raise BanzaiConvergenceError(
                    "finalized residual debt differs from replayed public status"
                )
            return _result(
                child_dir,
                "complete_with_debt",
                successor_created,
                0,
                debt_hash,
                directive,
                unresolved_start,
                _unresolved_count(after),
            )
        if status not in {"in_progress", "paused"}:
            raise BanzaiConvergenceError(
                "Banzai successor stopped outside semantic convergence"
            )

        before_calls = _provider_calls(before)
        self.execute_successor(child_dir)
        after = _load_status(child_dir)
        provider_calls = max(0, _provider_calls(after) - before_calls)
        final_status = str(after.get("status"))
        if final_status == "complete":
            return _result(
                child_dir,
                "complete",
                successor_created,
                provider_calls,
                None,
                directive,
                unresolved_start,
                0,
            )
        if final_status == "complete_with_debt":
            return _result(
                child_dir,
                "complete_with_debt",
                successor_created,
                provider_calls,
                _debt_hash(after),
                directive,
                unresolved_start,
                _unresolved_count(after),
            )
        if final_status == "blocked_plateau":
            acceptance = _finalize_debt(self.project_root, child_dir)
            finalized = _load_status(child_dir)
            if finalized.get("status") != "complete_with_debt":
                raise BanzaiConvergenceError(
                    "validated residual debt did not produce a terminal public status"
                )
            debt_hash = _debt_hash(finalized)
            if debt_hash != acceptance.identity:
                raise BanzaiConvergenceError(
                    "finalized residual debt differs from replayed public status"
                )
            return _result(
                child_dir,
                "complete_with_debt",
                successor_created,
                provider_calls,
                debt_hash,
                directive,
                unresolved_start,
                _unresolved_count(finalized),
            )
        raise BanzaiConvergenceError(
            "Banzai successor did not reach complete or complete-with-debt; "
            f"fixed status={final_status}"
        )


def _load_authority(run_dir: Path) -> object:
    from .status import _authority

    return _authority(run_dir, None)


def _load_status(run_dir: Path) -> dict[str, object]:
    from .status import protocol_25_status_document

    return protocol_25_status_document(run_dir)


def _finalize_debt(project_root: Path, run_dir: Path) -> object:
    return finalize_protocol_25_debt(
        project_root=project_root,
        run_dir=run_dir,
        require_banzai=True,
    )


def _guidance_directive(authority: object) -> GuidanceDirectiveV1 | None:
    payload = authority.inputs.human_guidance
    reference = authority.manifest.human_guidance
    if payload is None and reference is None:
        return None
    if payload is None or reference is None:
        raise BanzaiConvergenceError("immutable guidance authority is incomplete")
    if content_digest(payload) != reference.object_hash:
        raise BanzaiConvergenceError("immutable guidance authority hash mismatch")
    try:
        return load_canonical_object(payload, GuidanceDirectiveV1.from_json_dict)
    except Exception as exc:
        raise BanzaiConvergenceError(f"invalid Banzai guidance: {exc}") from exc


def _validate_banzai_directive(
    directive: GuidanceDirectiveV1,
    *,
    expected_root: str | None = None,
) -> None:
    if (
        directive.kind != "banzai"
        or not directive.accept_residual_debt
        or directive.automatic_successor_limit != 1
        or directive.successor_index != 1
    ):
        raise BanzaiConvergenceError(
            "Banzai permits exactly successor index 1 with automatic limit 1"
        )
    root = directive.automation_root_manifest_hash
    if root is None or root != directive.parent_manifest_hash:
        raise BanzaiConvergenceError("Banzai successor has invalid automation root authority")
    if expected_root is not None and root != expected_root:
        raise BanzaiConvergenceError("Banzai successor belongs to a different automation root")


def _provider_calls(document: Mapping[str, object]) -> int:
    telemetry = document.get("telemetry")
    calls = telemetry.get("calls_by_operation") if isinstance(telemetry, Mapping) else None
    if not isinstance(calls, Mapping):
        return 0
    return sum(value for value in calls.values() if isinstance(value, int) and value >= 0)


def _unresolved_count(document: Mapping[str, object]) -> int:
    semantic = document.get("semantic")
    value = semantic.get("unresolved_findings") if isinstance(semantic, Mapping) else None
    return value if isinstance(value, int) and value >= 0 else 0


def _debt_hash(document: Mapping[str, object]) -> str:
    value = document.get("debt_manifest_hash")
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise BanzaiConvergenceError("complete-with-debt status has no debt manifest")
    return value


def _result(
    run_dir: Path,
    status: Literal["complete", "complete_with_debt"],
    successor_created: bool,
    provider_calls: int,
    debt_hash: str | None,
    directive: GuidanceDirectiveV1,
    unresolved_start: int,
    unresolved_end: int,
) -> BanzaiResultV1:
    return BanzaiResultV1(
        run_id=run_dir.name,
        semantic_status="blocked_plateau" if status == "complete_with_debt" else "complete",
        public_status=status,
        successor_created=successor_created,
        provider_call_count=provider_calls,
        debt_manifest_hash=debt_hash,
        guidance_directive_hash=directive.identity,
        unresolved_start=unresolved_start,
        unresolved_end=unresolved_end,
    )


__all__ = (
    "BanzaiConvergenceError",
    "BanzaiCoordinator",
    "BanzaiResultV1",
    "run_banzai_resume",
)
