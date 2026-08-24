from __future__ import annotations

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.model import RunManifest
from harness.re_v2.protocol_22 import PROTOCOL_VERSION, RUN_MANIFEST_SCHEMA_VERSION
from tests.re_v2_protocol_22_fixtures import (
    artifact_key_v2,
    manifest_v2,
    work_template_v2,
)
from tests.unit.test_re_v2_model import (
    valid_artifact_key,
    valid_run_manifest_dict,
    valid_work_template,
)


@pytest.mark.parametrize(
    ("protocol", "snapshot_kind", "expected_manifest_digest"),
    (
        (
            "2.0",
            "git-worktree",
            "sha256:7ac95ce703b04cc139e51915d387b0ccaae74f26b0db0d6511a16557716d6f1b",
        ),
        (
            "2.1",
            "workspace-git-composite",
            "sha256:85ada60ab484c4d5c62c67e51ee06b16ef27291fafd2640f954dfed29ba54907",
        ),
    ),
)
def test_schema_1_manifest_bytes_remain_frozen(
    protocol: str,
    snapshot_kind: str,
    expected_manifest_digest: str,
) -> None:
    raw = valid_run_manifest_dict()
    raw["engine_protocol_version"] = protocol
    raw["source_snapshot_kind"] = snapshot_kind

    payload = canonical_json_bytes(RunManifest.from_json_dict(raw).to_json_dict())

    assert content_digest(payload) == expected_manifest_digest


def test_schema_1_work_identities_remain_frozen() -> None:
    assert valid_work_template().template_id == (
        "sha256:1409b831e2e5f56dfa1e7ca55129a7a571a759eb811f1e6263441eabdf1f51a2"
    )
    assert valid_artifact_key().identity == (
        "sha256:8dbebbaa987d4fcc2e78bb3e7754877adc45d313c7957e2ee2a426f772a30fac"
    )


def test_protocol_22_package_pins_its_manifest_identity() -> None:
    assert PROTOCOL_VERSION == "2.2"
    assert RUN_MANIFEST_SCHEMA_VERSION == 2


def test_schema_2_manifest_and_work_identities_remain_frozen() -> None:
    assert manifest_v2().run_manifest_id == (
        "sha256:f5b5d58af8f348d4b6fdeb2ae2fffdcd8087a49eccab810df2837d8dc1d5833c"
    )
    assert artifact_key_v2().identity == (
        "sha256:73d6ce8aa64c60d74a01c803ecbeca09691cf2028e2f8c62c6579fd1a79e95d1"
    )
    assert work_template_v2().identity == (
        "sha256:ac14a69b78a0b807a078fe7576c4271a130c62ab6336fa115af0fabd223a0d23"
    )
