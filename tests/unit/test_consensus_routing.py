"""Post-consensus deterministic Tasks Lexicon routing (definition.yaml).

Regression guard for the 002-echelon-control-fe non-convergence loop: the
consensus gate routed EVERY WHY3 FAIL to phase3-how (ARCHITECT). A WHY3 FAIL is
a spec-quality failure (Structure gate / glossary / atomicity / ambiguity) owned
by CARTOGRAPHER — ARCHITECT cannot amend spec.md, so the gate reproduced the
identical FAIL every cycle until the iteration-10 force-kill. The phase spec
(phase3-consensus.md §Consensus Gate Check) already documents the correct
ownership routing; definition.yaml must match it:

    WHY3 CRITICAL spec issues   -> WHAT (phase1-what / CARTOGRAPHER)
    ASSESS2 CRITICAL feasibility -> HOW  (phase3-how / ARCHITECT)

This mirrors the proven phase1-why2 -> phase1-what spec-quality re-dispatch (same
agent, SAGE; same failure class).
"""
import pathlib
from unittest.mock import MagicMock

import pytest
import yaml

from harness.phase_graph import PhaseGraph
from harness.squad import SquadController
from harness.squad_executors import StagedParallelExecutor
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore


ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "runtime/workflow/definition.yaml"
PROSAIC_SUBAGENTS = ROOT / "prosaic/subagents"


def _targeted_why3_report(*issues: tuple[str, str, str, str]) -> str:
    """Build a complete authoritative WHY3 report for routing tests."""
    counts = {
        "CRITICAL": 0,
        "HIGH": 0,
        "MEDIUM": 0,
        "LOW": 0,
    }
    blocks = []
    for issue_id, severity, artifact, owner in issues:
        counts[severity] += 1
        blocks.append(
            f"""### {issue_id}: Mechanical mismatch
- **Severity:** {severity}
- **Type:** inconsistency
- **Description:** A bounded artifact reference is stale.
- **Affected artifact:** {artifact}
- **Affected section:** Existing reference
- **Evidence:** The current artifacts contain a contradictory reference.
- **Recommendation:** Align the existing reference.
- **Responsible agent:** {owner}
- **Action Required:** Amend the affected artifact.

### Resolution Guidance
- **Decision required:** No user decision — agent repair
- **Suggested option:** Align the existing reference with current evidence.
- **Evidence basis:** Current accepted artifacts.
- **Values not inferable:** None
- **Banzai eligible:** yes
"""
        )
    issue_blocks = "\n".join(blocks)
    return f"""# Issues — WHY3

## Summary
- **CRITICAL:** {counts['CRITICAL']}
- **HIGH:** {counts['HIGH']}
- **MEDIUM:** {counts['MEDIUM']}
- **LOW:** {counts['LOW']}
- **Verdict:** FAIL

## Issues

{issue_blocks}
"""


def _consensus_node():
    d = yaml.safe_load(DEFINITION.read_text())
    return next(
        n
        for n in d["phases"]
        if n["id"] == "phase3-consensus-tasks-lexicon"
    )


def _runtime_route(tmp_path, state_updates, *, iteration=0):
    config_path = tmp_path / ".echelon" / "config.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("lexicon_gate:\n  enabled: false\n", encoding="utf-8")
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    store = SquadStateStore(tmp_path / "squad" / "run-test")
    store.initialize("r", "semi", "msg", 0, "phase3-consensus", max_iterations=5)
    state = store.load()
    state["iteration"] = iteration
    state["quality_scores"] = [{"pass": True, "source": "harness:understanding"}]
    state.update(state_updates)
    store.save(state)

    ctrl = SquadController(
        provider=MagicMock(),
        state_store=store,
        phase_graph=graph,
        ext_dir=ROOT / "runtime",
        project_root=tmp_path,
        token_budget=0,
        squad_dir=store.squad_dir,
    )
    consensus_result = SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": "PASS", "state_updates": {}},
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    consensus = graph.get("phase3-consensus")
    snapshot = store.capture_routing_snapshot(
        expected_phase="phase3-consensus",
    )
    consensus_prepared = ctrl._prepare_phase_result(
        consensus,
        consensus_result,
        snapshot,
    )
    assert (
        ctrl._evaluate_transitions(consensus, consensus_prepared, snapshot)
        == "phase3-consensus-tasks-lexicon"
    )
    gate = graph.get("phase3-consensus-tasks-lexicon")
    gate_result = ctrl._executors["deterministic_lexicon"].execute(gate, store)
    gate_prepared = ctrl._prepare_phase_result(gate, gate_result.result, snapshot)
    return ctrl._evaluate_transitions(gate, gate_prepared, snapshot)


@pytest.mark.unit
def test_why3_fail_routes_to_the_controller_owned_repair_phase():
    node = _consensus_node()
    why3 = [
        t for t in node["transitions"]
        if "why3-verdict = FAIL" in t.get("condition", "")
    ]
    assert why3, "no transition keyed on 'why3-verdict = FAIL'"
    targets = {t["to"] for t in why3}
    assert {"phase1-discover", "phase1-what", "phase3-how"}.issubset(
        targets
    ), targets
    owned = [t for t in why3 if "why3_repair_phase" in t["condition"]]
    assert len(owned) == 5
    fallback = [t for t in why3 if "why3_repair_phase" not in t["condition"]]
    assert [t["to"] for t in fallback] == ["phase1-what"]
    # Bounded re-dispatch: increment + cap, like every other re-dispatch edge.
    assert all(t.get("action") == "increment_iteration" for t in why3)
    assert all("iteration < max_iterations" in t.get("condition", "") for t in why3)


@pytest.mark.unit
def test_assess2_rejected_still_routes_to_how():
    node = _consensus_node()
    assess2 = [
        t for t in node["transitions"]
        if "assess2-verdict = REJECTED" in t.get("condition", "")
    ]
    assert assess2, "no transition keyed on 'assess2-verdict = REJECTED'"
    assert all(t["to"] == "phase3-how" for t in assess2), (
        "ASSESS2 REJECTED (feasibility) must route to phase3-how (ARCHITECT)"
    )


@pytest.mark.unit
def test_why3_task_repair_routes_to_how_only_when_explicitly_owned():
    node = _consensus_node()
    for t in node["transitions"]:
        if t["to"] == "phase3-how":
            condition = t.get("condition", "")
            if "why3-verdict = FAIL" in condition:
                assert "why3_repair_phase = phase3-how" in condition


@pytest.mark.unit
def test_why3_discovery_owner_routes_to_discovery_phase():
    issues = """### ISS-001: Stale discovery evidence
- **Responsible agent:** DISCOVER
- **Action Required:** Amend assumptions.md.
"""

    assert (
        StagedParallelExecutor._why3_repair_phase_from_issues(issues)
        == "phase1-discover"
    )


@pytest.mark.unit
def test_why3_affected_task_routes_to_plan_when_role_label_conflicts():
    issues = """### ISS-004: Task contradicts the normative contract
- **Affected artifact:** tasks.md
- **Responsible agent:** HOW
- **Action Required:** The existing planning owner must amend T-005.
"""

    assert (
        StagedParallelExecutor._why3_repair_phase_from_issues(issues)
        == "phase3-plan"
    )


@pytest.mark.unit
def test_why3_affected_contract_routes_to_how_when_role_label_conflicts():
    issues = """### ISS-005: Contract is incomplete
- **Affected artifact:** contracts/internal-interfaces.md
- **Responsible agent:** ORCHESTRATOR
- **Action Required:** Repair the contract before planning.
"""

    assert (
        StagedParallelExecutor._why3_repair_phase_from_issues(issues)
        == "phase3-how"
    )


@pytest.mark.unit
def test_safe_why3_repairs_keep_each_local_owner_in_dependency_order():
    issues = _targeted_why3_report(
        ("ISS-001", "MEDIUM", "spec.md", "WHAT"),
        ("ISS-002", "MEDIUM", "unknowns.md", "DISCOVER"),
        (
            "ISS-003",
            "MEDIUM",
            "test-strategy.md; coverage-map.md",
            "SENTINEL",
        ),
    )

    assert StagedParallelExecutor._why3_targeted_repair_phases_from_issues(
        issues
    ) == (
        "phase1-discover",
        "phase1-what",
        "phase3-sentinel",
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "unsafe_line",
    [
        "- **Severity:** HIGH",
        "- **Decision required:** Product owner decision",
        (
            "- **Decision required:** No user decision yet; ask the product "
            "owner to choose the value."
        ),
        "- **Values not inferable:** Browser policy",
        "- **Banzai eligible:** no",
    ],
)
def test_targeted_why3_repair_queue_rejects_non_mechanical_findings(
    unsafe_line,
):
    fields = {
        "severity": "- **Severity:** MEDIUM",
        "decision": "- **Decision required:** No user decision — agent repair",
        "values": "- **Values not inferable:** None",
        "eligible": "- **Banzai eligible:** yes",
    }
    if "Severity" in unsafe_line:
        fields["severity"] = unsafe_line
    elif "Decision required" in unsafe_line:
        fields["decision"] = unsafe_line
    elif "Values not inferable" in unsafe_line:
        fields["values"] = unsafe_line
    else:
        fields["eligible"] = unsafe_line
    issues = _targeted_why3_report(
        ("ISS-001", "MEDIUM", "spec.md", "WHAT"),
    )
    original = {
        "severity": "- **Severity:** MEDIUM",
        "decision": "- **Decision required:** No user decision — agent repair",
        "values": "- **Values not inferable:** None",
        "eligible": "- **Banzai eligible:** yes",
    }
    changed = next(key for key in fields if fields[key] != original[key])
    issues = issues.replace(original[changed], fields[changed])

    assert (
        StagedParallelExecutor._why3_targeted_repair_phases_from_issues(
            issues
        )
        == ()
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "contradiction",
    [
        "- **Severity:** CRITICAL",
        "- **Decision required:** Product owner decision",
        "- **Values not inferable:** Browser policy",
        "- **Banzai eligible:** no",
    ],
)
def test_targeted_why3_repair_queue_rejects_duplicate_authority_fields(
    contradiction,
):
    issues = _targeted_why3_report(
        ("ISS-001", "MEDIUM", "spec.md", "WHAT"),
    )
    marker = {
        "Severity": "- **Severity:** MEDIUM",
        "Decision required": (
            "- **Decision required:** No user decision — agent repair"
        ),
        "Values not inferable": "- **Values not inferable:** None",
        "Banzai eligible": "- **Banzai eligible:** yes",
    }
    label = next(label for label in marker if label in contradiction)
    issues = issues.replace(marker[label], marker[label] + "\n" + contradiction)

    assert (
        StagedParallelExecutor._why3_targeted_repair_phases_from_issues(
            issues
        )
        == ()
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "corruption",
    [
        "\n### ISS-BROKEN Missing colon\n",
        "\n- **CRITICAL:** 1\n",
    ],
)
def test_targeted_why3_repair_queue_rejects_malformed_or_contradictory_report(
    corruption,
):
    issues = _targeted_why3_report(
        ("ISS-001", "MEDIUM", "spec.md", "WHAT"),
    ) + corruption

    assert (
        StagedParallelExecutor._why3_targeted_repair_phases_from_issues(
            issues
        )
        == ()
    )


@pytest.mark.unit
def test_targeted_why3_repair_owner_receives_issues_context():
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)

    for phase in (
        "phase1-discover",
        "phase1-what",
        "phase3-how",
        "phase3-sentinel",
        "phase3-plan",
    ):
        assert "issues.md" in graph.get(phase).context_pack


@pytest.mark.unit
def test_targeted_why3_queue_resets_only_its_owner_dispatch_counts(
    tmp_path,
):
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "issues.md").write_text(
        _targeted_why3_report(
            ("ISS-001", "MEDIUM", "unknowns.md", "DISCOVER"),
            ("ISS-002", "MEDIUM", "coverage-map.md", "SENTINEL"),
        ),
        encoding="utf-8",
    )
    state = {
        "why3_verdict": "FAIL",
        "spec_dir": str(spec_dir),
        "phase_dispatch_counts": {
            "phase1-discover": 6,
            "phase3-sentinel": 4,
            "phase3-plan": 3,
        },
    }
    executor = object.__new__(StagedParallelExecutor)
    executor._project_root = tmp_path

    updates = executor._why3_repair_updates(state)

    assert updates["why3_targeted_repair_queue"] == [
        "phase1-discover",
        "phase3-sentinel",
    ]
    assert updates["phase_dispatch_counts"] == {"phase3-plan": 3}


@pytest.mark.unit
def test_targeted_why3_repair_routes_only_the_queued_owners():
    prepared = MagicMock(verdict="DONE")
    state = {
        "why3_verdict": "FAIL",
        "why3_targeted_repair_queue": [
            "phase1-discover",
            "phase1-what",
            "phase3-sentinel",
        ],
    }

    route, updates = SquadController._phase3_targeted_repair_route(
        MagicMock(id="phase1-discover"),
        prepared,
        state,
    )

    assert route == "phase1-what"
    assert updates == {
        "why3_repair_phase": "phase1-what",
        "why3_targeted_repair_queue": [
            "phase1-what",
            "phase3-sentinel",
        ],
    }


@pytest.mark.unit
def test_last_targeted_why3_repair_starts_bounded_recertification():
    route, updates = SquadController._phase3_targeted_repair_route(
        MagicMock(id="phase3-sentinel"),
        MagicMock(verdict="DONE"),
        {
            "why3_verdict": "FAIL",
            "why3_targeted_repair_queue": ["phase3-sentinel"],
        },
    )

    assert route == "phase1-understanding"
    assert updates == {
        "why3_repair_phase": None,
        "why3_targeted_repair_queue": [],
        "why3_targeted_repair_recertification": True,
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("phase", "verdict", "expected"),
    [
        ("phase1-why2", "PASS", "phase1-lexicon-derive"),
        ("phase1-lexicon", "PASS", "phase3-understanding"),
    ],
)
def test_targeted_why3_recertification_skips_completed_product_phases(
    phase,
    verdict,
    expected,
):
    route, updates = SquadController._phase3_targeted_repair_route(
        MagicMock(id=phase),
        MagicMock(
            verdict=verdict,
            state_updates=(
                {"spec_quality_certificate": {"source_sha256": "a" * 64}}
                if phase == "phase1-why2"
                else {
                    "lexicon_evaluation": "passed",
                    "lexicon_pass": True,
                }
            ),
        ),
        {
            "why3_verdict": "FAIL",
            "why3_targeted_repair_queue": [],
            "why3_targeted_repair_recertification": True,
        },
    )

    assert route == expected
    assert updates == (
        {"why3_targeted_repair_recertification": None}
        if phase == "phase1-lexicon"
        else {}
    )


@pytest.mark.unit
def test_targeted_recertification_never_bypasses_missing_quality_certificate():
    route, updates = SquadController._phase3_targeted_repair_route(
        MagicMock(id="phase1-why2"),
        MagicMock(verdict="PASS", state_updates={}),
        {
            "why3_verdict": "FAIL",
            "why3_targeted_repair_queue": [],
            "why3_targeted_repair_recertification": True,
        },
    )

    assert route is None
    assert updates == {}


@pytest.mark.unit
@pytest.mark.parametrize(
    "state_updates",
    [
        {},
        {"lexicon_evaluation": "failed", "lexicon_pass": False},
        {"lexicon_evaluation": "pending", "lexicon_pass": False},
        {"lexicon_evaluation": "passed", "lexicon_pass": False},
    ],
)
def test_targeted_recertification_never_bypasses_failed_lexicon(
    state_updates,
):
    route, updates = SquadController._phase3_targeted_repair_route(
        MagicMock(id="phase1-lexicon"),
        MagicMock(verdict="DONE", state_updates=state_updates),
        {
            "why3_verdict": "FAIL",
            "why3_targeted_repair_queue": [],
            "why3_targeted_repair_recertification": True,
        },
    )

    assert route is None
    assert updates == {}


@pytest.mark.unit
def test_targeted_recertification_skips_explicitly_disabled_lexicon_gate():
    route, updates = SquadController._phase3_targeted_repair_route(
        MagicMock(id="phase1-lexicon"),
        MagicMock(
            verdict="DONE",
            state_updates={"lexicon_evaluation": "pending"},
        ),
        {
            "why3_verdict": "FAIL",
            "why3_targeted_repair_queue": [],
            "why3_targeted_repair_recertification": True,
        },
        spec_lexicon_gate_enabled=False,
    )

    assert route == "phase3-understanding"
    assert updates == {"why3_targeted_repair_recertification": None}


@pytest.mark.unit
def test_proportional_recertification_routes_after_certificate_is_derived(
    tmp_path,
):
    config_path = tmp_path / ".echelon" / "config.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("lexicon_gate:\n  enabled: false\n", encoding="utf-8")
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    store = SquadStateStore(tmp_path / "runs" / "run-test")
    store.initialize(
        "r",
        "semi",
        "msg",
        0,
        "phase1-why2",
        spec_authoring_mode="proportional",
    )
    state = store.load()
    state.update(
        {
            "why3_verdict": "FAIL",
            "why3_targeted_repair_queue": [],
            "why3_targeted_repair_recertification": True,
        }
    )
    store.save(state)
    ctrl = SquadController(
        provider=MagicMock(),
        state_store=store,
        phase_graph=graph,
        ext_dir=ROOT / "runtime",
        project_root=tmp_path,
        token_budget=0,
        squad_dir=store.squad_dir,
    )
    node = graph.get("phase1-why2")
    snapshot = store.capture_routing_snapshot(expected_phase=node.id)
    prepared = ctrl._prepare_phase_result(
        node,
        SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "PASS",
                "state_updates": {
                    "evidence_resolution_status": "not_required",
                    "finding_routes": {"findings": []},
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        ),
        snapshot,
    )
    certificate = {"source_sha256": "a" * 64}
    ctrl._coordinate_why_transition_state = MagicMock(
        return_value=(
            None,
            {
                "why_fail_count": 0,
                "spec_quality_certificate": certificate,
            },
            None,
        )
    )

    decision = ctrl._coordinate_transition_routing(
        node,
        prepared,
        snapshot,
    )

    assert decision.to_phase == "phase1-lexicon-derive"
    assert decision.queued_state_updates["spec_quality_certificate"] == (
        certificate
    )
    ctrl._coordinate_why_transition_state.assert_called_once()


@pytest.mark.unit
def test_stale_spec_certificates_do_not_preempt_the_active_local_owner(
    tmp_path,
):
    config_path = tmp_path / ".echelon" / "config.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "lexicon_gate:\n  enabled: true\n",
        encoding="utf-8",
    )
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    store = SquadStateStore(tmp_path / "runs" / "run-test")
    store.initialize("r", "semi", "msg", 0, "phase3-sentinel")
    state = store.load()
    state.update(
        {
            "why3_verdict": "FAIL",
            "why3_repair_phase": "phase3-sentinel",
            "why3_targeted_repair_queue": ["phase3-sentinel"],
        }
    )
    store.save(state)
    ctrl = SquadController(
        provider=MagicMock(),
        state_store=store,
        phase_graph=graph,
        ext_dir=ROOT / "runtime",
        project_root=tmp_path,
        token_budget=0,
        squad_dir=store.squad_dir,
    )

    assert ctrl._guard_spec_lexicon_evidence("phase3-sentinel") == (
        "phase3-sentinel"
    )
    assert store.current_phase() == "phase3-sentinel"


@pytest.mark.unit
@pytest.mark.parametrize(
    "queue",
    [
        ["phase4-document"],
        ["phase3-sentinel", "phase1-what"],
        ["phase3-sentinel", "phase3-sentinel"],
    ],
)
def test_corrupt_targeted_queue_cannot_bypass_spec_lexicon_guard(
    tmp_path,
    queue,
):
    config_path = tmp_path / ".echelon" / "config.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("lexicon_gate:\n  enabled: true\n", encoding="utf-8")
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    store = SquadStateStore(tmp_path / "runs" / "run-test")
    store.initialize("r", "semi", "msg", 0, queue[0])
    state = store.load()
    state.update(
        {
            "why3_verdict": "FAIL",
            "why3_repair_phase": queue[0],
            "why3_targeted_repair_queue": queue,
        }
    )
    store.save(state)
    ctrl = SquadController(
        provider=MagicMock(),
        state_store=store,
        phase_graph=graph,
        ext_dir=ROOT / "runtime",
        project_root=tmp_path,
        token_budget=0,
        squad_dir=store.squad_dir,
    )

    assert ctrl._guard_spec_lexicon_evidence(queue[0]) == (
        "phase1-lexicon-derive"
    )
    assert store.current_phase() == "phase1-lexicon-derive"


@pytest.mark.unit
def test_why2_failure_prepares_controller_owned_discovery_route(tmp_path):
    config_path = tmp_path / ".echelon" / "config.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("lexicon_gate:\n  enabled: false\n", encoding="utf-8")
    spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "issues.md").write_text(
        """### ISS-001: Stale discovery evidence
- **Responsible agent:** DISCOVER
- **Action Required:** Amend assumptions.md.
""",
        encoding="utf-8",
    )
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    store = SquadStateStore(tmp_path / "runs" / "run-test")
    store.initialize("r", "banzai", "msg", 0, "phase1-why2")
    state = store.load()
    state["spec_dir"] = str(spec_dir)
    store.save(state)
    ctrl = SquadController(
        provider=MagicMock(),
        state_store=store,
        phase_graph=graph,
        ext_dir=ROOT / "runtime",
        project_root=tmp_path,
        token_budget=0,
        squad_dir=store.squad_dir,
    )
    node = graph.get("phase1-why2")
    result = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "FAIL",
            "state_updates": {
                "evidence_resolution_status": "not_required",
                "finding_routes": {
                    "findings": [
                        {
                            "issue_id": "ISS-001",
                            "route": "spec_repair",
                            "rationale": "Discovery evidence is stale.",
                        }
                    ]
                },
            },
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    snapshot = store.capture_routing_snapshot(expected_phase="phase1-why2")

    prepared = ctrl._prepare_phase_result(node, result, snapshot)

    assert prepared.state_updates["why2_repair_phase"] == "phase1-discover"


@pytest.mark.unit
def test_iteration_cap_fallback_preserved():
    # The force-convergence escape at the cap must remain.
    node = _consensus_node()
    fallback = [
        t for t in node["transitions"]
        if "iteration >= max_iterations" in t.get("condition", "")
    ]
    assert fallback and all(t.get("action") == "force_convergence_warning" for t in fallback)


@pytest.mark.unit
def test_certified_metric_failure_precedes_consensus_success_and_risk_acceptance():
    transitions = _consensus_node()["transitions"]
    quality_failure = next(
        index
        for index, transition in enumerate(transitions)
        if "quality_gates.fail" in transition.get("condition", "")
    )
    success = next(
        index
        for index, transition in enumerate(transitions)
        if "why3-verdict = PASS" in transition.get("condition", "")
    )
    accept_risk = next(
        index
        for index, transition in enumerate(transitions)
        if "accept_with_risk" in transition.get("condition", "")
    )
    qualitative_failure = next(
        index
        for index, transition in enumerate(transitions)
        if "why3-verdict = FAIL" in transition.get("condition", "")
    )

    assert qualitative_failure < quality_failure < success < accept_risk


@pytest.mark.unit
def test_legacy_consensus_resume_redirects_to_deterministic_gate(tmp_path):
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    store = SquadStateStore(tmp_path / "squad" / "run-test")
    store.initialize("r", "semi", "msg", 0, "phase3-consensus", max_iterations=5)
    ctrl = SquadController(
        provider=MagicMock(),
        state_store=store,
        phase_graph=graph,
        ext_dir=ROOT / "runtime",
        project_root=tmp_path,
        token_budget=0,
        squad_dir=store.squad_dir,
    )

    assert ctrl._guard_understanding_evidence("phase3-consensus") == "phase3-understanding"
    assert store.current_phase() == "phase3-understanding"


@pytest.mark.unit
def test_runtime_why3_fail_routes_to_what_before_cap(tmp_path):
    assert _runtime_route(
        tmp_path,
        {"why3_verdict": "FAIL", "assess2_verdict": "PASS"},
        iteration=4,
    ) == "phase1-what"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("repair_phase", "expected"),
    [
        ("phase1-discover", "phase1-discover"),
        ("phase1-what", "phase1-what"),
        ("phase3-how", "phase3-how"),
        ("phase3-sentinel", "phase3-sentinel"),
        ("phase3-plan", "phase3-plan"),
    ],
)
def test_runtime_why3_fail_honors_controller_owned_repair_phase(
    tmp_path,
    repair_phase,
    expected,
):
    assert _runtime_route(
        tmp_path,
        {
            "why3_verdict": "FAIL",
            "assess2_verdict": "PASS",
            "why3_repair_phase": repair_phase,
        },
        iteration=4,
    ) == expected


@pytest.mark.unit
def test_runtime_assess2_rejected_routes_to_how_before_cap(tmp_path):
    assert _runtime_route(
        tmp_path,
        {"why3_verdict": "PASS", "assess2_verdict": "REJECTED"},
        iteration=4,
    ) == "phase3-how"


@pytest.mark.unit
def test_runtime_certified_metric_failure_routes_to_spec_repair_before_success(
    tmp_path,
):
    assert _runtime_route(
        tmp_path,
        {
            "why3_verdict": "PASS",
            "assess2_verdict": "PASS",
            "quality_scores": [
                {"pass": False, "source": "harness:understanding"}
            ],
        },
        iteration=4,
    ) == "phase1-what"


@pytest.mark.unit
@pytest.mark.parametrize(
    "state_updates",
    [
        {"why3_verdict": "FAIL", "assess2_verdict": "PASS"},
        {"why3_verdict": "PASS", "assess2_verdict": "REJECTED"},
        {"why3_verdict": "FAIL", "assess2_verdict": "REJECTED"},
    ],
)
def test_runtime_consensus_failure_uses_fallback_at_iteration_cap(
    tmp_path,
    state_updates,
):
    assert _runtime_route(tmp_path, state_updates, iteration=5) == "checkpoint-plan"
