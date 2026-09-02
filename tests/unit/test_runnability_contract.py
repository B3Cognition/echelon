from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from harness.product_inventory import product_evidence_fingerprint
from harness.runnability_contract import (
    RunnabilityContractError,
    load_runnability_contract,
    runnability_contract_sha256,
)


BROWSER_CONTRACT = """\
schema_version: 1
enabled: true
install_commands:
  - pnpm install --frozen-lockfile
bootstrap_commands:
  - pnpm migrate
start_commands:
  - pnpm start:local
readiness:
  url: http://127.0.0.1:${ECHELON_PORT}/health
  timeout_ms: 120000
identity:
  command: pnpm dev:issue-session -- --player ${ECHELON_MARKER}
  stdout_json:
    token: ECHELON_SESSION_TOKEN
primary_journey:
  kind: browser
  url: ${ECHELON_BASE_URL}
  requirements: [FR-001]
  real_services_required: [web, api, postgres]
  session_storage:
    session-token: ${ECHELON_SESSION_TOKEN}
  steps:
    - action: goto
      path: /
    - action: expect
      selector: canvas
      state: visible
    - action: press
      key: ArrowUp
      repeat: 20
  observations:
    - id: checkpoint-visible
      kind: browser_dom
      selector: '[data-checkpoint-state="owned"]'
      expectation: present
    - id: checkpoint-persisted
      kind: postgres_query
      statement: SELECT player_id FROM checkpoints WHERE player_id = $1
      parameters: ['${ECHELON_MARKER}']
      expectation: one_row_exact
persistence_probe:
  restart_commands:
    - pnpm restart:local
  observations:
    - checkpoint-visible
    - checkpoint-persisted
stop_commands:
  - pnpm stop:local
"""


LOCAL_JOURNEY = """\
local_journey:
  prerequisites:
    - Docker with Compose v2
    - pnpm 9
  provision_commands:
    - docker compose up -d postgres
  readiness_commands:
    - docker compose exec -T postgres pg_isready -U game -d browser_3d_game
  prepare_commands:
    - docker compose exec -T postgres createdb -U game browser_3d_game_test
  verify_commands:
    - TEST_DATABASE_URL=postgresql://game:local-development-only@127.0.0.1:5432/browser_3d_game_test pnpm verify
  start_commands:
    - pnpm start
  open_urls:
    - http://127.0.0.1:3000
  stop_commands:
    - pnpm stop
  cleanup_commands:
    - docker compose down -v
"""


def _write_contract(root: Path, text: str) -> Path:
    path = root / ".echelon" / "runnability.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return root


@pytest.mark.unit
def test_loads_candidate_owned_browser_contract(tmp_path: Path) -> None:
    contract = load_runnability_contract(_write_contract(tmp_path, BROWSER_CONTRACT))

    assert contract is not None
    assert contract.primary_journey.kind == "browser"
    assert contract.primary_journey.steps[0].action == "goto"
    assert [item.kind for item in contract.primary_journey.observations] == [
        "browser_dom",
        "postgres_query",
    ]
    assert contract.persistence_probe.observation_ids == (
        "checkpoint-visible",
        "checkpoint-persisted",
    )
    assert contract.local_journey is None


@pytest.mark.unit
def test_loads_complete_local_user_journey_as_immutable_contract(
    tmp_path: Path,
) -> None:
    contract = load_runnability_contract(
        _write_contract(tmp_path, BROWSER_CONTRACT + LOCAL_JOURNEY)
    )

    assert contract is not None
    assert contract.local_journey is not None
    assert contract.local_journey.prerequisites == (
        "Docker with Compose v2",
        "pnpm 9",
    )
    assert contract.local_journey.provision_commands == (
        "docker compose up -d postgres",
    )
    assert contract.local_journey.readiness_commands == (
        "docker compose exec -T postgres pg_isready -U game -d browser_3d_game",
    )
    assert contract.local_journey.prepare_commands == (
        "docker compose exec -T postgres createdb -U game browser_3d_game_test",
    )
    assert contract.local_journey.verify_commands == (
        "TEST_DATABASE_URL=postgresql://game:local-development-only@127.0.0.1:5432/browser_3d_game_test pnpm verify",
    )
    assert contract.local_journey.start_commands == ("pnpm start",)
    assert contract.local_journey.open_urls == ("http://127.0.0.1:3000",)
    assert contract.local_journey.stop_commands == ("pnpm stop",)
    assert contract.local_journey.cleanup_commands == ("docker compose down -v",)


@pytest.mark.unit
def test_local_user_journey_rejects_unknown_fields(tmp_path: Path) -> None:
    text = BROWSER_CONTRACT + LOCAL_JOURNEY.replace(
        "  cleanup_commands:\n",
        "  host_execution: true\n  cleanup_commands:\n",
    )

    with pytest.raises(
        RunnabilityContractError,
        match="unknown local_journey key: host_execution",
    ):
        load_runnability_contract(_write_contract(tmp_path, text))


@pytest.mark.unit
@pytest.mark.parametrize(
    "field",
    [
        "prerequisites",
        "provision_commands",
        "readiness_commands",
        "prepare_commands",
        "verify_commands",
        "start_commands",
        "open_urls",
        "stop_commands",
        "cleanup_commands",
    ],
)
def test_local_user_journey_requires_every_lifecycle_field(
    tmp_path: Path,
    field: str,
) -> None:
    lines = LOCAL_JOURNEY.splitlines()
    start = lines.index(f"  {field}:")
    end = start + 1
    while end < len(lines) and lines[end].startswith("    "):
        end += 1
    del lines[start:end]
    text = BROWSER_CONTRACT + "\n".join(lines) + "\n"

    with pytest.raises(
        RunnabilityContractError,
        match=rf"local_journey\.{field} must not be empty",
    ):
        load_runnability_contract(_write_contract(tmp_path, text))


@pytest.mark.unit
def test_missing_candidate_contract_is_explicitly_absent(tmp_path: Path) -> None:
    assert load_runnability_contract(tmp_path) is None


@pytest.mark.unit
def test_contract_rejects_product_policy_override(tmp_path: Path) -> None:
    text = BROWSER_CONTRACT + "scope: follow_up\n"

    with pytest.raises(RunnabilityContractError, match="unknown root key: scope"):
        load_runnability_contract(_write_contract(tmp_path, text))


@pytest.mark.unit
def test_contract_reports_all_unknown_root_keys_and_allowed_schema(
    tmp_path: Path,
) -> None:
    text = """\
version: 1
runtime: linux_container
provision:
  command: pnpm install
"""

    with pytest.raises(RunnabilityContractError) as raised:
        load_runnability_contract(_write_contract(tmp_path, text))

    message = str(raised.value)
    assert "unknown root keys: version, runtime, provision" in message
    assert "allowed root keys:" in message
    assert "schema_version" in message
    assert "install_commands" in message


@pytest.mark.unit
def test_contract_requires_harness_observation_beyond_exit_status(tmp_path: Path) -> None:
    text = """\
schema_version: 1
enabled: true
install_commands: [make install]
start_commands: [make start]
readiness:
  url: http://127.0.0.1:${ECHELON_PORT}/health
  timeout_ms: 30000
primary_journey:
  kind: exec
  requirements: [FR-001]
  real_services_required: []
  steps:
    - action: exec
      command: ./game-smoke
  observations: []
stop_commands: [make stop]
"""

    with pytest.raises(RunnabilityContractError, match="observable assertion"):
        load_runnability_contract(_write_contract(tmp_path, text))


@pytest.mark.unit
def test_contract_rejects_unsupported_variable(tmp_path: Path) -> None:
    text = BROWSER_CONTRACT.replace(
        "${ECHELON_BASE_URL}", "${HOME}/secret"
    )

    with pytest.raises(RunnabilityContractError, match="unsupported variable: HOME"):
        load_runnability_contract(_write_contract(tmp_path, text))


@pytest.mark.unit
def test_contract_rejects_duplicate_observation_ids(tmp_path: Path) -> None:
    duplicate = """\
    - id: checkpoint-visible
      kind: browser_dom
      selector: canvas
      expectation: present
"""
    text = BROWSER_CONTRACT.replace("persistence_probe:\n", duplicate + "persistence_probe:\n")

    with pytest.raises(RunnabilityContractError, match="duplicate observation id"):
        load_runnability_contract(_write_contract(tmp_path, text))


@pytest.mark.unit
def test_contract_digest_is_yaml_key_order_independent(tmp_path: Path) -> None:
    first = load_runnability_contract(_write_contract(tmp_path / "first", BROWSER_CONTRACT))
    reordered = BROWSER_CONTRACT.replace(
        "schema_version: 1\nenabled: true\n",
        "enabled: true\nschema_version: 1\n",
    )
    second = load_runnability_contract(_write_contract(tmp_path / "second", reordered))

    assert first is not None
    assert second is not None
    assert runnability_contract_sha256(first) == runnability_contract_sha256(second)


@pytest.mark.unit
def test_product_fingerprint_excludes_contract_but_contract_hash_changes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, capture_output=True)
    (project / "app.js").write_text("export const ready = true;\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.js"], cwd=project, check=True)
    _write_contract(project, BROWSER_CONTRACT)
    first = load_runnability_contract(project)
    assert first is not None
    first_product = product_evidence_fingerprint(project)
    first_contract = runnability_contract_sha256(first)

    changed = BROWSER_CONTRACT.replace(
        '[data-checkpoint-state="owned"]',
        '[data-checkpoint-state="saved"]',
    )
    _write_contract(project, changed)
    second = load_runnability_contract(project)

    assert second is not None
    assert product_evidence_fingerprint(project) == first_product
    assert runnability_contract_sha256(second) != first_contract
