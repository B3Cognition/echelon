"""Runtime input admission is exercised through the real composed operation."""
import json

import pytest

from tests.unit.test_discovery_operation import (
    case, enrolled, turn_prepared, prepared, execute, DiscoveryExecutor,
)


def test_runtime_context_reaches_all_turns_but_raw_config_does_not(prepared):
    root, state, _, _ = prepared
    (root / ".echelon/constitution.md").write_text("# Constitution\nLocal-first game.\n")
    kb = root / "knowledge-base"
    kb.mkdir()
    (kb / "calibration-profile.yaml").write_text("confidence: conservative\n")
    (state.squad_dir / "evolution-report.md").write_text("Keep the camera steady.\n")
    with (root / ".echelon/config.yml").open("a") as stream:
        stream.write("\nprivate_test_secret: NEVER_SEND_THIS_CONFIG_VALUE\n")
    executor = DiscoveryExecutor()
    result = execute(prepared, executor, create=True)
    assert result.status == "reviewed", result.reason
    for call in executor.calls:
        context = call["context"]
        assert context["runtime"]["user_message"] == "Create an isometric game"
        assert context["runtime"]["mode"] == "greenfield"
        assert context["evidence"][".echelon/constitution.md"] == "# Constitution\nLocal-first game.\n"
        assert context["evidence"]["knowledge-base/calibration-profile.yaml"] == "confidence: conservative\n"
        assert context["evidence"]["runs/first/evolution-report.md"] == "Keep the camera steady.\n"
        assert "runs/first/context/prior-spec-context.md" in context["evidence"]
        assert "NEVER_SEND_THIS_CONFIG_VALUE" not in json.dumps(call)
    dependency = next(item for item in result.candidate.artifacts if item.path == ".echelon/constitution.md")
    assert dependency.role == "references" and dependency.before_text == dependency.after_text
    assert ".echelon/constitution.md" in executor.calls[-1]["context"]["source_citations"]


@pytest.mark.parametrize("content", [
    "mempalace:\n  wing: game\n",
    "mempalace:\n  wing: game\n  enabled: false\n",
    "mempalace:\n  wing: game\nmempalace: {}\n",
    "mempalace:\n  wing: game\n  wing: ''\n",
    "mempalace: null\n", "mempalace: []\n", "mempalace:\n  wing: false\n",
    "[]\n", "not: [valid\n", "", "null\n",
])
def test_unadmitted_configuration_blocks_before_attempt_or_reservation(prepared, content):
    root, state, store, _ = prepared
    (root / ".echelon/config.yml").write_text(content)
    before = state.load()
    history = store.identity_history(spec_id="game")
    executor = DiscoveryExecutor()
    result = execute(prepared, executor, create=True)
    assert result.status == "blocked"
    assert result.token_usage == 0 and result.dispatch_count == 0
    assert executor.calls == [] and state.load() == before
    assert store.identity_history(spec_id="game") == history
    assert store.reserve(spec_id="game", kind="U", operation_id="prove-unused", count=1) == ("U-000001",)


@pytest.mark.parametrize("field,value", [
    ("mode", "brownfield"), ("implementation_targets", ["engine"]),
    ("requested_re_sources", ["engine"]), ("ignore_re", True),
    ("published_re_context", {"status": "attached", "artifacts": {}}),
    ("published_re_context", {"status": "absent", "generation": 1, "artifacts": {}}),
    ("product_inputs", {"inputs_dir": "other"}),
    ("retarget", {"memory_excluded": True}),
    ("context_dir", "outside/context"),
])
def test_unsupported_run_selection_is_not_silently_ignored(prepared, field, value):
    state = prepared[1]
    # Admission must validate actual persisted inputs, including malformed state
    # that bypassed a generic writer, without trusting absence-shaped labels.
    raw = state.load()
    raw[field] = value
    (state.squad_dir / "state.json").write_text(json.dumps(raw))
    executor = DiscoveryExecutor()
    result = execute(prepared, executor, create=True)
    assert result.status == "blocked"
    assert executor.calls == []
    assert "managed_discovery_operation" not in state.load()


@pytest.mark.parametrize("target", [".echelon/config.yml", "runs/first/context/prior-spec-context.md",
    "runs/first/context/feature-registry.snapshot.json", "runs/first/context/mempalace-reconciliation.json"])
def test_required_runtime_input_missing_blocks(prepared, target):
    (prepared[0] / target).unlink()
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "blocked"
    assert executor.calls == []


@pytest.mark.parametrize("relative", ["re/index.json", "re/sources/unregistered/data.md",
    "runs/first/context/published-re/brief.md"])
def test_actual_re_files_cannot_be_hidden_by_absent_state(prepared, relative):
    root, state, _, _ = prepared
    raw = state.load()
    raw["published_re_context"] = {"status": "absent", "generation": 0, "artifacts": {}}
    state.save(raw)
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("unregistered RE")
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "blocked"
    assert executor.calls == []


@pytest.mark.parametrize("report", [
    {"accepted_count": 1, "rejected": []},
    {"accepted_count": 0, "rejected": [{"drawer_id": "old"}]},
    {"accepted_count": False, "rejected": []},
    {},
])
def test_retained_memory_context_requires_supported_empty_observation(prepared, report):
    (prepared[1].squad_dir / "context/mempalace-reconciliation.json").write_text(json.dumps(report))
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "blocked"
    assert executor.calls == []


@pytest.mark.parametrize("relative", [".echelon/config.yml", ".echelon/constitution.md",
    "runs/first/context/prior-spec-context.md", "knowledge-base/calibration-profile.yaml",
    "runs/first/evolution-report.md", "re/index.json"])
def test_runtime_input_change_blocks_replay_without_replenishing_usage(prepared, relative):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    path = prepared[0] / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    content = path.read_text() if path.exists() else ""
    path.write_text(content + "\n# changed\n")
    result = execute(prepared, executor)
    assert result.status == "blocked"
    assert (result.token_usage, result.dispatch_count, len(executor.calls)) == (21, 3, 3)


@pytest.mark.parametrize("field,value", [("user_message", "Different game"),
    ("stack_contract", {"stack": "different"}), ("autonomy_mode", "guided"),
    ("calibration_map", {"scout": "changed"})])
def test_runtime_state_change_blocks_replay(prepared, field, value):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    state = prepared[1]
    raw = state.load()
    raw[field] = value
    state.save(raw)
    result = execute(prepared, executor)
    assert result.status == "blocked"
    assert (result.token_usage, result.dispatch_count, len(executor.calls)) == (21, 3, 3)


@pytest.mark.parametrize("relative", [".echelon/constitution.md", "knowledge-base", "re"])
def test_runtime_source_symlink_is_not_followed(prepared, tmp_path, relative):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("Do not read")
    (prepared[0] / relative).symlink_to(outside)
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "blocked"
    assert executor.calls == []


@pytest.mark.parametrize("change", ["context", "config", "state"])
def test_input_change_during_provider_turn_blocks_before_allocation(prepared, change):
    class DriftingExecutor(DiscoveryExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            reply = super().run_inspection_turn(*args, **kwargs)
            if change == "context":
                (prepared[1].squad_dir / "context/prior-spec-context.md").write_text("Changed during turn\n")
            elif change == "config":
                (prepared[0] / ".echelon/config.yml").write_text("mempalace: {}\n")
            else:
                state = prepared[1].load()
                state["user_message"] = "Changed request"
                prepared[1].save(state)
            return reply
    executor = DriftingExecutor()
    result = execute(prepared, executor, create=True)
    assert result.status == "blocked"
    assert (result.token_usage, result.dispatch_count) == (7, 1)
    assert prepared[1].load()["managed_discovery_operation"]["attempts"] == [dict(number=1, result=None)]
    assert prepared[2].reserve(spec_id="game", kind="U", operation_id="prove-unused", count=1) == ("U-000001",)


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("mode", ["guided", "semi", "banzai"])
def test_supported_provider_and_autonomy_combinations_keep_input_guards(prepared, provider, mode):
    state = prepared[1]
    raw = state.load()
    raw["autonomy_mode"] = mode
    state.save(raw)
    executor = DiscoveryExecutor(provider)
    result = execute(prepared, executor, create=True)
    assert result.status == "reviewed", result.reason
    assert result.token_usage == 21 and result.dispatch_count == 3
    (prepared[0] / ".echelon/constitution.md").write_text("New policy\n")
    assert execute(prepared, executor).status == "blocked"
    assert len(executor.calls) == 3


@pytest.mark.parametrize("content", [
    '{"features":[{"feature_id":"other","requirements":[{"id":"U-000001"}]}],"wip_features":[],"user_request":"Create an isometric game"}',
    '{"features":[],"wip_features":[{"feature_id":"other"}],"user_request":"Create an isometric game"}',
    '{"features":[],"wip_features":[],"user_request":"Different request"}',
    '{"features":[],"features":[],"wip_features":[],"user_request":"Create an isometric game"}',
    '{}', 'not json',
])
def test_unadmitted_prior_feature_context_is_not_rebound_to_this_specs_ids(prepared, content):
    (prepared[1].squad_dir / "context/feature-registry.snapshot.json").write_text(content)
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "blocked"
    assert executor.calls == []


@pytest.mark.parametrize("relative", [
    "runs/first/context/prior-spec-context.md", "runs/first/context/current-feature-context.md",
    "runs/first/context/stale-memory-report.md", "knowledge-base/calibration-profile.yaml",
    ".echelon/constitution.md", "runs/first/evolution-report.md",
])
def test_ambiguous_runtime_reference_cannot_bind_to_new_same_spelled_id(prepared, relative):
    path = prepared[0] / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Foreign spec context\nRetained reference U-000001.\n")
    executor = DiscoveryExecutor()
    result = execute(prepared, executor, create=True)
    assert result.status == "blocked"
    assert (result.token_usage, result.dispatch_count) == (0, 0)
    assert executor.calls == []
    assert "managed_discovery_operation" not in prepared[1].load()
