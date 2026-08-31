from __future__ import annotations

from pathlib import Path

import pytest

from harness.prosaic_prompt_loader import ProsaicCommandArtifact
from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.protocol_22.provider import (
    DispatchReservationV1,
    canonical_prosaic_agent_bytes,
)
from harness.re_v2.protocol_28.cli_provider import SquadCliProtocol28Backend
from harness.squad_provider import SquadAgentResult


class _FileWritingProvider:
    def __init__(self, *, extra: bool = False) -> None:
        self.extra = extra
        self.calls = 0

    def exec_agent(self, project_root: str, prompt: str, **_kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        filename = (
            "exhaustive-verification.json"
            if "exhaustive-verification.json" in prompt
            else "exhaustive-evidence-slice.json"
        )
        Path(project_root, filename).write_bytes(canonical_json_bytes({"schema_version": 1}))
        if self.extra:
            Path(project_root, "extra.txt").write_text("forbidden", encoding="utf-8")
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=10,
            timed_out=False,
            token_usage=7,
            token_usage_details={
                "input_tokens": 4,
                "cached_input_tokens": 0,
                "reasoning_output_tokens": 1,
                "visible_output_tokens": 2,
            },
            provider_name="fake-cli",
            model_name="fake-model",
        )


def _agent() -> bytes:
    return canonical_prosaic_agent_bytes(
        ProsaicCommandArtifact(
            frontmatter={"model_tier": "strong", "effort": "high"},
            body="Produce the exact result.",
        )
    )


@pytest.mark.integration
def test_shared_cli_backend_captures_exact_role_file_and_reuses_provider() -> None:
    provider = _FileWritingProvider()
    backend = SquadCliProtocol28Backend(lambda: provider)  # type: ignore[arg-type]
    reservation = DispatchReservationV1(10_000, 10_000, 1_000)

    producer = backend.execute(
        "producer", _agent(), b'{"role":"producer"}\n', b'{"type":"object"}\n', reservation
    )
    verifier = backend.execute(
        "verifier", _agent(), b'{"role":"verifier"}\n', b'{"type":"object"}\n', reservation
    )

    assert producer.result_kind == verifier.result_kind == "provider_result"
    assert producer.provider_name == "fake-cli"
    assert provider.calls == 2


@pytest.mark.integration
def test_shared_cli_backend_rejects_extra_candidate_file() -> None:
    backend = SquadCliProtocol28Backend(
        lambda: _FileWritingProvider(extra=True)  # type: ignore[arg-type]
    )

    result = backend.execute(
        "producer",
        _agent(),
        b'{"role":"producer"}\n',
        b'{"type":"object"}\n',
        DispatchReservationV1(10_000, 10_000, 1_000),
    )

    assert result.result_kind == "provider_failure"
    assert result.raw_result == b""
