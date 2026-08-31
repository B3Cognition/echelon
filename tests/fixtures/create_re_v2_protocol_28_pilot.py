#!/usr/bin/env python3
"""Create a disposable clean protocol-2.8 installed-provider pilot workspace."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.re_v2.canonical import content_digest  # noqa: E402
from harness.re_v2.protocol_28.executors import build_l4_executor_catalog  # noqa: E402
from harness.re_v2.protocol_28.lifecycle import (  # noqa: E402
    create_or_reuse_protocol_28_child,
)
from harness.re_v2.protocol_28.policies import (  # noqa: E402
    build_initial_exhaustive_policy,
)
from harness.re_v2.protocol_28.preparation import (  # noqa: E402
    load_protocol_28_role_bytes,
    prepare_protocol_28_request,
)
from tests.unit.test_re_v2_protocol_28_preparation import (  # noqa: E402
    _preparation_fixture,
)


def create_pilot(parent: Path) -> tuple[Path, str]:
    parent = parent.resolve()
    if parent.exists() and any(parent.iterdir()):
        raise ValueError(f"pilot parent must be empty: {parent}")
    parent.mkdir(parents=True, exist_ok=True)
    workspace, intent, eligible_l3, options = _preparation_fixture(parent)
    config = workspace / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "workspace:\n"
        "  git_role: orchestration\n"
        "  sources:\n"
        "    - id: api\n"
        "      path: sources/api\n"
        "harness:\n"
        "  provider: docker\n"
        "  llm:\n"
        "    cli: codex\n"
        "    model: gpt-5.4\n"
        "    timeout_ms: 300000\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["echelon", "workspace", "migrate-to-prosaic"],
        cwd=workspace,
        check=True,
    )
    producer, verifier = load_protocol_28_role_bytes(workspace)
    policy = build_initial_exhaustive_policy(
        producer_contract_hash=content_digest(producer),
        verifier_contract_hash=content_digest(verifier),
    )
    executors = build_l4_executor_catalog(
        inherited_executor_contract_hash=content_digest(
            options.inherited_executor_contract_bytes
        ),
        producer_agent_contract_hash=content_digest(producer),
        verifier_agent_contract_hash=content_digest(verifier),
    )
    intent = replace(
        intent,
        exhaustive_policy_catalog_id=policy.identity,
        executor_catalog_id=executors.identity,
    )
    options = replace(
        options,
        token_limit=100_000_000,
        active_ms_limit=600_000_000,
        producer_agent_bytes=producer,
        verifier_agent_bytes=verifier,
    )
    inputs = prepare_protocol_28_request(workspace, intent, eligible_l3, options)
    run_dir = create_or_reuse_protocol_28_child(workspace, inputs)
    metadata = {
        "workspace": str(workspace),
        "run_id": run_dir.name,
        "provider": "codex",
        "producer_model_tier": "strong",
        "producer_effort": "high",
        "verifier_model_tier": "strong",
        "verifier_effort": "high",
        "planned_slices": sum(
            len(target.entries) for target in inputs.exhaustive_plan.target_plans
        ),
    }
    (workspace / "pilot-metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace / "sources" / "api",
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status:
        raise RuntimeError("pilot source is dirty after creation")
    return workspace, run_dir.name


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: create_re_v2_protocol_28_pilot.py <empty-pilot-parent>",
            file=sys.stderr,
        )
        return 2
    workspace, run_id = create_pilot(Path(argv[1]))
    print(json.dumps({"workspace": str(workspace), "run_id": run_id}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
