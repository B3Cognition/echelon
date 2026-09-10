from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.config import HarnessConfig


@pytest.mark.unit
def test_target_owned_config_selects_authoritative_verification_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness.verification_stack_runtime import resolve_verification_stacks

    workspace = tmp_path / "workspace"
    target = workspace / "sources" / "game"
    (workspace / ".echelon").mkdir(parents=True)
    (target / ".echelon").mkdir(parents=True)
    (target / ".echelon" / "config.yml").write_text(
        "stacks:\n  selected: [browser-3d-game]\n",
        encoding="utf-8",
    )
    configs = {
        workspace.resolve(): {"stacks": {"selected": ["workspace-stack"]}},
        target.resolve(): {
            "stacks": {
                "selected": ["browser-3d-game"],
                "target_archetypes": ["browser-3d-game"],
            }
        },
    }
    monkeypatch.setattr(
        "harness.verification_stack_runtime.get_full_resolved_config",
        lambda root: configs[Path(root).resolve()],
    )
    resolved = object()
    resolver = MagicMock(return_value=resolved)
    monkeypatch.setattr(
        "harness.verification_stack_runtime.load_stack_definitions",
        lambda **_kwargs: {"browser-3d-game": object()},
    )
    monkeypatch.setattr(
        "harness.verification_stack_runtime.find_stack_extension_root",
        lambda _root: workspace / ".echelon" / "runtime" / "stacks",
    )
    monkeypatch.setattr(
        "harness.verification_stack_runtime.resolve_stacks", resolver
    )

    result = resolve_verification_stacks(workspace, target)

    assert result is resolved
    assert resolver.call_args.args[0] == ["browser-3d-game"]
    assert resolver.call_args.kwargs["target_archetypes"] == {
        "browser-3d-game"
    }


@pytest.mark.unit
def test_build_verification_sandbox_spec_preserves_delivery_isolation(
    tmp_path: Path,
) -> None:
    from harness.verification_stack_runtime import build_verification_sandbox_spec

    config = HarnessConfig(
        target_repo=str(tmp_path),
        target_default_branch="main",
        provider="docker",
    )

    spec = build_verification_sandbox_spec(
        config,
        worktree=tmp_path,
        spec_id="001-demo",
        strategy_id="standalone",
        run_id="verify-1",
    )

    assert spec.worktree_mount == str(tmp_path)
    assert spec.container_mount == "/workspace"
    assert spec.env["ECHELON_HARNESS_RUN"] == "1"
    assert spec.env["NODE_OPTIONS"] == "--use-env-proxy"
    assert spec.ephemeral_volumes == ["node_modules"]
