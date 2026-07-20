from __future__ import annotations

import pytest

from harness.re_repair_packet import ReRepairFinding, ReRepairPacket
from harness.re_controller import ReExtractionController


pytestmark = pytest.mark.unit


def test_repair_packet_round_trip_preserves_exact_scope() -> None:
    packet = ReRepairPacket(
        source_id="api",
        domain_id="001-api",
        spec_fingerprint="abc",
        attempt=1,
        findings=(
            ReRepairFinding(
                finding_id="ref-123",
                category="error-recovery",
                text="Missing retry exhaustion",
                source_evidence=("`src/a.ts:9`",),
            ),
        ),
    )

    assert ReRepairPacket.from_json_dict(packet.to_json_dict()) == packet


def test_repeated_finding_ids_are_recorded_per_domain() -> None:
    finding = ReRepairFinding(
        finding_id="ref-repeat",
        category="error-recovery",
        text="Missing retry exhaustion",
        source_evidence=("`src/a.ts:9`",),
    )
    state: dict[str, object] = {}
    first = ReRepairPacket("api", "001-api", "abc", 1, (finding,))
    second = ReRepairPacket("api", "001-api", "def", 2, (finding,))

    ReExtractionController._record_repeated_findings(state, first)
    ReExtractionController._record_repeated_findings(state, second)

    assert state["re_repeated_finding_ids"] == {
        "api/001-api": ["ref-repeat"]
    }
