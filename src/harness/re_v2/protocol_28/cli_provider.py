"""Shared CLI rendering for protocol-2.8 producer and verifier roles."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import stat
import tempfile
from typing import Callable

from harness.echelon_result_schema import EchelonResultContract
from harness.re_v2.protocol_22.provider import (
    DispatchReservationV1,
    decode_prosaic_agent_bytes,
    normalize_shared_provider_usage,
)
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.protocol_28.executors import RoleV1
from harness.re_v2.protocol_28.lifecycle import L4DispatchResultV1
from harness.squad_provider import SquadCliProvider


_RESULT_CONTRACT = EchelonResultContract(
    allowed_state_update_keys=frozenset(),
    allowed_verdicts=frozenset({"DONE"}),
    unexpected_state_updates="reject",
)
_SLICE_FILE_BY_ROLE = {
    "producer": "exhaustive-evidence-slice.json",
    "verifier": "exhaustive-verification.json",
}
_RECONCILIATION_FILE_BY_ROLE = {
    "producer": "knowledge-reconciliation-candidate.json",
    "verifier": "knowledge-reconciliation-review.json",
}


class Protocol28CliProviderError(RuntimeError):
    """Raised when the shared CLI cannot enforce an L4 execution contract."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SquadCliProtocol28Backend:
    """Execute isolated L4 role calls through one shared provider instance."""

    def __init__(self, provider_factory: Callable[[], SquadCliProvider]) -> None:
        if not callable(provider_factory):
            raise Protocol28CliProviderError("L4 CLI backend requires a provider factory")
        self._provider_factory = provider_factory
        self._provider: SquadCliProvider | None = None

    def execute(
        self,
        role: RoleV1,
        agent_bytes: bytes,
        context_bytes: bytes,
        response_schema_bytes: bytes,
        reservation: DispatchReservationV1,
    ) -> L4DispatchResultV1:
        if role not in _SLICE_FILE_BY_ROLE:
            raise Protocol28CliProviderError(f"unknown L4 role: {role!r}")
        artifact = decode_prosaic_agent_bytes(agent_bytes)
        try:
            context = load_canonical_object(context_bytes, lambda value: value)
            load_canonical_object(response_schema_bytes, lambda value: value)
        except ValueError as exc:
            raise Protocol28CliProviderError(
                "L4 CLI context or response schema is not canonical"
            ) from exc
        filename = _result_filename(role, context)
        prompt = _render_prompt(
            artifact.body,
            role,
            context_bytes.decode("utf-8"),
            response_schema_bytes.decode("utf-8"),
            filename,
        )
        if len(prompt.encode("utf-8")) > reservation.initial_input_tokens:
            raise Protocol28CliProviderError(
                "L4 CLI prompt exceeds its conservative input reservation"
            )
        started_at = _now()
        with tempfile.TemporaryDirectory(prefix=f"echelon-l4-{role}-") as temporary:
            root = Path(temporary)
            result = self._shared_provider().exec_agent(
                str(root),
                prompt,
                # The reservation includes process shutdown and boundary checks,
                # not just time spent inside the provider. Keep actual usage exact.
                timeout_ms=max(1, reservation.active_ms - min(5_000, reservation.active_ms // 10)),
                result_contract=_RESULT_CONTRACT,
                prompt_metadata=dict(artifact.frontmatter),
                allow_result_repair=False,
                strict_result_envelope=True,
                isolated_workspace=True,
            )
            payload = _read_exact_result(root, filename)
        ended_at = _now()
        usage = normalize_shared_provider_usage(
            result.token_usage, result.token_usage_details
        )
        valid_envelope = (
            not result.echelon_result_validation_reason
            and result.verdict == "DONE"
            and not result.state_updates
        )
        successful = (
            result.exit_code == 0
            and not result.timed_out
            and valid_envelope
            and payload is not None
        )
        return L4DispatchResultV1(
            raw_result=payload or b"",
            provider_name=result.provider_name.strip() or "shared-cli",
            model_revision=result.model_name.strip() or None,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=max(0, int(result.duration_ms)),
            result_kind=("provider_timeout" if result.timed_out else
                         "provider_result" if successful else "provider_failure"),
            token_status=usage.status,
            billable_tokens=usage.billable_tokens,
            active_status="trusted_exact",
            active_ms=max(0, int(result.duration_ms)),
        )

    def _shared_provider(self) -> SquadCliProvider:
        if self._provider is None:
            self._provider = self._provider_factory()
        return self._provider


def _result_filename(role: RoleV1, context: object) -> str:
    files = (
        _RECONCILIATION_FILE_BY_ROLE
        if isinstance(context, dict)
        and context.get("kind") == "knowledge-reconciliation"
        else _SLICE_FILE_BY_ROLE
    )
    return files[role]


def _read_exact_result(root: Path, filename: str) -> bytes | None:
    try:
        entries = tuple(root.iterdir())
        metadata = entries[0].lstat() if len(entries) == 1 else None
    except OSError:
        return None
    if (
        metadata is None
        or entries[0].name != filename
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size <= 0
    ):
        return None
    try:
        return entries[0].read_bytes()
    except OSError:
        return None


def _render_prompt(
    body: str, role: RoleV1, context: str, schema: str, filename: str
) -> str:
    return (
        body
        + ("" if body.endswith("\n") else "\n")
        + f"\nWrite exactly `{filename}` and complete the transport as instructed below.\n"
        + "Do not read any live workspace path; the canonical context below is complete.\n"
        + "## Frozen slice context (canonical JSON)\n"
        + context
        + "\n## Exact response schema authority (canonical JSON)\n"
        + schema
        + "\n## Transport completion\n"
        + f"Write the JSON result only to `{filename}`; do not print it in the assistant response.\n"
        + "After writing the file, return only this bare YAML transport envelope, "
        + "with no prose or Markdown fences:\n"
        + "echelon_result:\n"
        + "  verdict: DONE\n"
        + "  state_updates: {}\n"
    )


__all__ = (
    "Protocol28CliProviderError",
    "SquadCliProtocol28Backend",
)
