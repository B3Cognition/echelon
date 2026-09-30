"""Capability readiness is static, target-owned, and independent of product files."""
import json
from pathlib import Path

import pytest
import yaml

from harness import phase_a_readiness as readiness
from harness.stacks import preflight
from harness.verification_stack_runtime import resolve_verification_stacks


def select(root, ids):
    path = root / ".echelon/config.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"stacks": {"selected": ids}}))


def custom_stack(root, name="custom", types=("unit",), *, browser=False, required=True):
    path = root / ".echelon/stacks" / name
    path.mkdir(parents=True, exist_ok=True)
    raw = {
        "schema_version": "1.4",
        "stack": {"id": name, "name": name, "version": "1", "kind": "capability"},
        "applies_to": {"archetypes": ["custom"]},
        "provides": {"x.test.observer": name}, "context": {"files": ["context.md"]},
        "runnability": {"classification": "non_runnable", "policy": "not_applicable"},
        "coverage_observers": [{"id": name, "test_types": list(types),
            "command": 'npm test -- --reporter=json --outputFile="$ECHELON_COVERAGE_REPORT"', "report_path": ".echelon/report.json",
            "adapter": "vitest-json", "mode": "isolated", "required": required}],
    }
    if browser:
        raw["runnability"] = {"classification": "user_facing", "policy": "required",
            "runner": "linux_container", "capabilities": ["install", "start", "readiness", "primary_journey", "stop"],
            "required_observations": ["browser_dom"]}
        raw["coverage_observers"][0]["adapter"] = "playwright-json"
    (path / "stack.yml").write_text(yaml.safe_dump(raw))
    (path / "context.md").write_text("# Custom verification\n")
    return raw, path / "stack.yml"


def spec(root, *, targets=(), types=("unit",), owners=True, shared=False, visual=False):
    directory = root / "specs/001-demo"
    directory.mkdir(parents=True)
    for name in readiness.REQUIRED_PHASE_A_BUILD_INPUTS:
        (directory / name).write_text(f"# {name}\n")
    (directory / "plan-conformance.json").write_text(json.dumps({
        "status": "pass", "findings": [], "sources": ["spec.md", "tasks.md"]}))
    (directory / "spec.md").write_text("\n".join(f"- **FR-{i:03}**: Requirement {i}." for i in range(1, len(types)+1)))
    if targets:
        (directory / "targets.yml").write_text(yaml.safe_dump({"targets": list(targets)}))
    lines = ["| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |",
             "|---|---|---|---|---|---|---|"]
    lines += [f"| FR-{i:03} | TC-{i:03} | {kind} | planned | planned | tests | implement |" for i, kind in enumerate(types, 1)]
    if visual:
        lines += ["", "## Browser App Gates", "", "| Gate | Required | Coverage Evidence |",
                  "|---|---|---|", "| Visual validation task | yes | T-001 |"]
    (directory / "coverage-map.md").write_text("\n".join(lines) + "\n")
    tasks = []
    for i in range(1, max(len(types), len(targets))+1):
        target = f" target={targets[i-1]}" if targets and owners else ""
        case = 1 if shared else i
        tasks += [f"- [ ] T-{i:03} complexity=standard phase=build req=FR-{case:03} depends=none{target}",
                  f"  **Named Test Ownership:** TC-{case:03}"]
    (directory / "tasks.md").write_text("\n".join(tasks) + "\n")
    return directory


def check(root, directory, visual=True):
    return readiness.validate_phase_a_build_readiness(
        {"status": "done"}, [directory], project_root=root,
        visual_execution_available=visual)


@pytest.mark.parametrize("selected,code", [([], "stack_selection_required"), (["generic"], "stack_capabilities_unresolved")])
def test_empty_or_generic_cannot_be_build_ready_even_without_obligations(tmp_path, selected, code):
    select(tmp_path, selected)
    resolved = resolve_verification_stacks(tmp_path, tmp_path)
    findings = preflight.verification_capability_findings(resolved, coverage_test_types=(),
        browser_required=False, semantic_visual_required=False, visual_execution_available=False)
    assert code in {finding.code for finding in findings}


def test_explicit_non_runnable_disposition_is_retained(tmp_path):
    custom_stack(tmp_path)
    select(tmp_path, ["custom"])
    assert resolve_verification_stacks(tmp_path, tmp_path).runnability.sources == ("custom",)


@pytest.mark.parametrize("generic", [False, True])
def test_custom_capabilities_admit_readiness_before_code_exists(tmp_path, generic):
    custom_stack(tmp_path)
    select(tmp_path, ["generic", "custom"] if generic else ["custom"])
    result = check(tmp_path, spec(tmp_path))
    assert result.ready, result.blockers
    assert not (tmp_path / "package.json").exists()


def test_required_runnability_needs_one_task_to_declare_candidate_contract(tmp_path):
    custom_stack(tmp_path, browser=True, types=("e2e",))
    select(tmp_path, ["custom"])
    directory = spec(tmp_path, types=("e2e",))

    missing = check(tmp_path, directory)
    assert not missing.ready
    assert "runnability_contract_owner_required" in "\n".join(missing.blockers)

    tasks = directory / "tasks.md"
    tasks.write_text(tasks.read_text() +
        "  **Files:**\n  - `.echelon/runnability.yml` - local journey\n")
    owned = check(tmp_path, directory)
    assert owned.ready, owned.blockers
    assert not (tmp_path / ".echelon/runnability.yml").exists()


def test_required_runnability_rejects_two_declared_owners(tmp_path):
    custom_stack(tmp_path, browser=True, types=("e2e",))
    select(tmp_path, ["custom"])
    directory = spec(tmp_path, types=("e2e",))
    tasks = directory / "tasks.md"
    tasks.write_text(tasks.read_text() +
        "  **Files:**\n  - `.echelon/runnability.yml` - local journey\n"
        "- [ ] T-002 complexity=standard phase=build req=INFRA depends=T-001\n"
        "  **Files:**\n  - `.echelon/runnability.yml` - duplicate owner\n")

    result = check(tmp_path, directory)
    assert not result.ready
    assert "runnability_contract_owner_ambiguous" in "\n".join(result.blockers)


def test_required_runnability_owner_must_belong_to_its_target(tmp_path):
    custom_stack(tmp_path, "front", ("e2e",), browser=True)
    custom_stack(tmp_path, "back", ("unit",))
    select(tmp_path / "sources/front", ["front"])
    select(tmp_path / "sources/back", ["back"])
    directory = spec(tmp_path, targets=("sources/front", "sources/back"), types=("e2e", "unit"))
    tasks = directory / "tasks.md"
    tasks.write_text(tasks.read_text() +
        "  **Files:**\n  - `sources/back/.echelon/runnability.yml` - other target\n")

    result = check(tmp_path, directory)
    assert not result.ready
    assert any("sources/front: runnability_contract_owner_required" in item for item in result.blockers)


def test_owner_deferred_runnability_does_not_require_current_task_owner(tmp_path):
    from harness.runnability_disposition import defer_runnability, plan_runnability
    from tests.unit.test_runnability_disposition import _report

    custom_stack(tmp_path, browser=True, types=("e2e",))
    select(tmp_path / "sources/game", ["custom"])
    directory = spec(tmp_path, targets=("sources/game",), types=("e2e",))
    defer_runnability(spec_dir=directory, target="sources/game",
                       reason="Owner approved separate work.", evidence_report=_report(tmp_path))
    deferred = check(tmp_path, directory)
    assert deferred.ready, deferred.blockers

    plan_runnability(directory)
    planned = check(tmp_path, directory)
    assert not planned.ready
    assert "runnability_contract_owner_required" in "\n".join(planned.blockers)


def test_native_basename_deferral_exempts_its_unique_target(tmp_path):
    from harness.runnability_disposition import defer_runnability
    from tests.unit.test_runnability_disposition import _report

    custom_stack(tmp_path, browser=True, types=("e2e",))
    select(tmp_path / "sources/game", ["custom"])
    directory = spec(tmp_path, targets=("sources/game",), types=("e2e",))
    defer_runnability(spec_dir=directory, target="game", reason="Owner approved follow-up.",
                       evidence_report=_report(tmp_path, target_id="game"))
    result = check(tmp_path, directory)
    assert result.ready, result.blockers


def test_basename_deferral_does_not_exempt_ambiguous_sibling_targets(tmp_path):
    from harness.runnability_disposition import defer_runnability
    from tests.unit.test_runnability_disposition import _report

    custom_stack(tmp_path, browser=True, types=("e2e",))
    select(tmp_path / "sources/game", ["custom"])
    select(tmp_path / "examples/game", ["custom"])
    directory = spec(tmp_path, targets=("sources/game", "examples/game"), types=("e2e", "e2e"))
    defer_runnability(spec_dir=directory, target="game", reason="Owner approved follow-up.",
                       evidence_report=_report(tmp_path, target_id="game"))

    result = check(tmp_path, directory)
    assert not result.ready
    assert sum("runnability_contract_owner_required" in item for item in result.blockers) == 2


def test_valid_spike_task_can_own_required_runnability(tmp_path):
    custom_stack(tmp_path, browser=True, types=("e2e",))
    select(tmp_path, ["custom"])
    directory = spec(tmp_path, types=("e2e",))
    tasks = directory / "tasks.md"
    tasks.write_text(tasks.read_text() +
        "- [ ] T-S01 complexity=standard phase=build req=INFRA depends=T-001\n"
        "  **Files:**\n  - `.echelon/runnability.yml` - local journey\n")
    result = check(tmp_path, directory)
    assert result.ready, result.blockers


@pytest.mark.parametrize("suffix", [
    "- [ ] T-002 implement runtime\n  **Files:**\n"
    "  - `.echelon/runnability.yml` - malformed task\n",
    "  **Files:**\n  ```markdown\n"
    "  - `.echelon/runnability.yml` - example only\n  ```\n",
    "~~~markdown\n"
    "- [ ] T-002 complexity=standard phase=build req=INFRA depends=T-001\n"
    "  **Files:**\n  - `.echelon/runnability.yml` - fenced task example\n~~~\n",
])
def test_noncanonical_or_fenced_example_cannot_claim_runnability_owner(tmp_path, suffix):
    custom_stack(tmp_path, browser=True, types=("e2e",))
    select(tmp_path, ["custom"])
    directory = spec(tmp_path, types=("e2e",))
    tasks = directory / "tasks.md"
    tasks.write_text(tasks.read_text() + suffix)
    result = check(tmp_path, directory)
    assert not result.ready
    assert "runnability_contract_owner_required" in "\n".join(result.blockers)


def test_explicit_root_target_cannot_borrow_other_targets_task(tmp_path):
    custom_stack(tmp_path, "front", ("e2e",), browser=True)
    custom_stack(tmp_path, "back", ("unit",))
    select(tmp_path, ["front"])
    select(tmp_path / "sources/back", ["back"])
    directory = spec(tmp_path, targets=(".", "sources/back"), types=("e2e", "unit"))
    tasks = directory / "tasks.md"
    tasks.write_text(tasks.read_text() +
        "  **Files:**\n  - `.echelon/runnability.yml` - wrong target owner\n")
    result = check(tmp_path, directory)
    assert not result.ready
    assert any(".: runnability_contract_owner_required" in item for item in result.blockers)


def test_workspace_deferral_alias_cannot_exempt_root_and_named_sibling(tmp_path):
    from harness.runnability_disposition import defer_runnability
    from tests.unit.test_runnability_disposition import _report

    custom_stack(tmp_path, browser=True, types=("e2e",))
    select(tmp_path, ["custom"])
    select(tmp_path / "sources/workspace", ["custom"])
    directory = spec(tmp_path, targets=(".", "sources/workspace"), types=("e2e", "e2e"))
    defer_runnability(spec_dir=directory, target="workspace",
                       reason="Owner approved follow-up.",
                       evidence_report=_report(tmp_path, target_id="workspace"))
    result = check(tmp_path, directory)
    assert not result.ready
    assert sum("runnability_contract_owner_required" in item for item in result.blockers) == 2


def test_invalid_runnability_disposition_is_not_reported_as_stack_failure(tmp_path):
    custom_stack(tmp_path, browser=True, types=("e2e",))
    select(tmp_path, ["custom"])
    directory = spec(tmp_path, types=("e2e",))
    (directory / "runnability-disposition.json").write_text("{")

    result = check(tmp_path, directory)
    assert not result.ready
    assert "runnability_disposition_invalid" in "\n".join(result.blockers)
    assert "verification_stack_invalid" not in "\n".join(result.blockers)


def test_optional_observer_does_not_satisfy_required_coverage(tmp_path):
    custom_stack(tmp_path, required=False)
    select(tmp_path, ["custom"])
    result = check(tmp_path, spec(tmp_path))
    assert not result.ready
    assert "coverage_observer_unavailable" in "\n".join(result.blockers)


def test_targets_only_need_their_owned_coverage_types(tmp_path):
    custom_stack(tmp_path, "front", ("e2e",), browser=True)
    custom_stack(tmp_path, "back", ("unit",))
    select(tmp_path / "sources/front", ["front"])
    select(tmp_path / "sources/back", ["back"])
    directory = spec(tmp_path, targets=("sources/front", "sources/back"), types=("e2e", "unit"), visual=True)
    tasks = directory / "tasks.md"
    tasks.write_text(tasks.read_text().replace(
        "  **Named Test Ownership:** TC-001",
        "  **Named Test Ownership:** TC-001\n  **Files:**\n"
        "  - `sources/front/.echelon/runnability.yml` - composed browser journey",
    ))
    result = check(tmp_path, directory)
    assert result.ready, result.blockers


def test_multi_target_unowned_tasks_block(tmp_path):
    select(tmp_path, ["browser-3d-game"])
    result = check(tmp_path, spec(tmp_path, targets=("sources/front", "sources/back"), types=("unit", "unit"), owners=False))
    assert not result.ready
    assert "ownership" in "\n".join(result.blockers)


def test_shared_case_must_be_supported_by_both_targets(tmp_path):
    custom_stack(tmp_path, "unit", ("unit",))
    custom_stack(tmp_path, "contract", ("contract",))
    select(tmp_path / "sources/front", ["unit"])
    select(tmp_path / "sources/back", ["contract"])
    result = check(tmp_path, spec(tmp_path, targets=("sources/front", "sources/back"), shared=True))
    assert not result.ready
    assert any("sources/back" in item and "coverage_observer_unavailable" in item for item in result.blockers)


def test_visual_gate_requires_available_executor(tmp_path):
    custom_stack(tmp_path, types=("e2e",), browser=True)
    select(tmp_path, ["custom"])
    result = check(tmp_path, spec(tmp_path, types=("e2e",), visual=True), visual=False)
    assert not result.ready
    assert "semantic_visual_capability_unavailable" in "\n".join(result.blockers)


def test_unsupported_runtime_is_not_substituted(tmp_path):
    raw, path = custom_stack(tmp_path, browser=True)
    raw["runnability"]["runner"] = "macos_simulator"
    path.write_text(yaml.safe_dump(raw))
    select(tmp_path, ["custom"])
    result = check(tmp_path, spec(tmp_path))
    assert not result.ready
    assert "verification_runtime_unavailable" in "\n".join(result.blockers)


def test_browser_observer_needs_runtime_capabilities(tmp_path):
    raw, path = custom_stack(tmp_path, types=("e2e",), browser=True)
    raw["runnability"]["capabilities"].remove("readiness")
    path.write_text(yaml.safe_dump(raw))
    select(tmp_path, ["custom"])
    result = check(tmp_path, spec(tmp_path, types=("e2e",)))
    assert not result.ready
    assert "verification_runtime_unavailable" in "\n".join(result.blockers)


def test_generic_artifacts_cannot_publish_readiness(tmp_path):
    select(tmp_path, ["generic"])
    result = check(tmp_path, spec(tmp_path))
    assert not result.ready
    assert "stack_capabilities_unresolved" in "\n".join(result.blockers)


def test_gate_with_unresolved_multi_target_owner_blocks(tmp_path):
    select(tmp_path, ["browser-3d-game"])
    directory = spec(tmp_path, targets=("sources/a", "sources/b"), types=("unit", "unit"), visual=True)
    path = directory / "coverage-map.md"
    path.write_text(path.read_text().replace("| yes | T-001 |", "| yes | screenshot |"))
    result = check(tmp_path, directory)
    assert not result.ready
    assert "verification_ownership_unresolved" in "\n".join(result.blockers)


def test_target_tasks_without_canonical_targets_are_not_single_repo(tmp_path):
    custom_stack(tmp_path)
    select(tmp_path, ["custom"])
    directory = spec(tmp_path)
    path = directory / "tasks.md"
    path.write_text(path.read_text().replace("depends=none", "depends=none target=sources/a"))
    result = check(tmp_path, directory)
    assert not result.ready
    assert "verification_ownership_unresolved" in "\n".join(result.blockers)


def test_malformed_target_entry_cannot_disappear(tmp_path):
    custom_stack(tmp_path)
    select(tmp_path, ["custom"])
    directory = spec(tmp_path, targets=("sources/a",))
    (directory / "targets.yml").write_text("targets: [sources/a, {bad: missing-path}]\n")
    result = check(tmp_path, directory)
    assert not result.ready


def test_owner_deferral_removes_only_deferred_obligations(tmp_path):
    custom_stack(tmp_path)
    select(tmp_path, ["custom"])
    directory = spec(tmp_path, types=("unit", "contract"))
    (directory / "deferred-scope.json").write_text(json.dumps({"schema_version": 1, "entries": [{
        "entry_id": "owner-1", "status": "deferred", "selected_ids": ["FR-002"],
        "derived_task_ids": ["T-002"], "prior_task_statuses": {}, "reason": "Owner deferred",
        "deferred_at": "2026-09-30T00:00:00Z", "planned_at": None}]}))
    result = check(tmp_path, directory)
    assert result.ready, result.blockers


@pytest.mark.parametrize("map_text", ["# missing obligations\n", "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n|---|---|---|---|---|---|---|\n| FR-001 | TC-001/TC-002 | unit/e2e/contract | planned | planned | tests | implement |\n"])
def test_bad_coverage_still_blocks_before_capabilities(tmp_path, map_text):
    custom_stack(tmp_path)
    select(tmp_path, ["custom"])
    directory = spec(tmp_path)
    (directory / "coverage-map.md").write_text(map_text)
    result = check(tmp_path, directory)
    assert not result.ready
    assert "coverage-map.md invalid" in "\n".join(result.blockers)
