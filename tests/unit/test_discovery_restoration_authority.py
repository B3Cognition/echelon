"""Native restore plans must name the exact sealed managed quality effect."""
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from tests.unit.test_proportional_quality import _candidate_repo, _git, _repair_state


@pytest.fixture
def authority(tmp_path):
    from harness.proportional_quality import (prepare_quality_candidate, materialize_quality_candidate, load_quality_candidate_snapshot,
        preflight_quality_candidate_restore, quality_candidate_effect_payload)
    from harness.proportional_quality_effects import _build_git_first_plan, _quality_completion_id
    root, spec, run, report = _candidate_repo(tmp_path)
    destination = root / "specs/001-demo"
    destination.parent.mkdir()
    spec.rename(destination)
    spec = destination
    evidence = json.loads(report.read_text())
    evidence["spec"]["path"] = "specs/001-demo/spec.md"
    report.write_text(json.dumps(evidence) + "\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "canonical managed spec fixture")
    repair = _repair_state()
    snapshots = []
    for index in range(2):
        content = f"# Candidate {index}\n"
        (spec / "spec.md").write_text(content)
        evidence["spec"]["sha256"] = hashlib.sha256(content.encode()).hexdigest()
        evidence["iteration"] = index
        current_report = report.with_name(f"assessment-{index}.json")
        current_report.write_text(json.dumps(evidence) + "\n")
        draft = prepare_quality_candidate(project_root=root, spec_dir=spec, run_artifact_root=run,
            run_id="run-1", spec_id="001-demo", candidate_id=f"quality-candidate-{index}",
            understanding_evidence=current_report,
            normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": False}},
            sage_finding_routes=(), formal_statement_count=2, repair_number=index,
            assessment_index=index, eligibility_reasons=(), repair_state=repair)
        _, candidate_receipt = materialize_quality_candidate(project_root=root, spec_dir=spec, candidate=draft,
            run_id="run-1", spec_id="001-demo", completion_id=_quality_completion_id(("b" if index == 0 else "c") * 32, "candidate"),
            next_phase="terminal-blocked", checkpoint_prestate={"kind": "git_head", "head": _git(root, "rev-parse", "HEAD")})
        snapshots.append(load_quality_candidate_snapshot(run / "quality-candidates" / f"quality-candidate-{index}.json"))
        repair["automatic_consumed"] += 1
    selected = preflight_quality_candidate_restore(project_root=root, spec_dir=spec,
        manifest_path=run / "quality-candidates/quality-candidate-0.json",
        expected_candidate_id="quality-candidate-0", expected_manifest_sha256=snapshots[0].sha256)
    completion_id = "c" * 32
    plan = _build_git_first_plan(project_root=root, spec_dir=spec, selected_restore=selected,
        completion_id=_quality_completion_id(completion_id, "restore"),
        base_commit=snapshots[1].manifest.checkpoint_commit, run_id="run-1", spec_id="001-demo", next_phase="terminal-blocked")
    effect = dict(kind="proportional_quality", operation="candidate", spec_dir="specs/001-demo", run_id="run-1", spec_id="001-demo",
        candidate=quality_candidate_effect_payload(replace(snapshots[1].manifest, checkpoint_commit="0" * 40)),
        checkpoint_prestate={"kind": "git_head", "head": snapshots[0].manifest.checkpoint_commit},
        restore_candidate_id="quality-candidate-0", restore_candidate_manifest_sha256=snapshots[0].sha256,
        restore_artifact_preimage_digests=dict(snapshots[1].manifest.owned_artifact_digests))
    completion = SimpleNamespace(marker=SimpleNamespace(completion_id=completion_id),
        intent=SimpleNamespace(quality_effect=effect, route={"to_phase": "terminal-blocked"}),
        receipts={"effects": {}}, fixture_candidate_receipt=candidate_receipt)
    return root, run, completion, plan, selected


def test_native_plan_matches_current_and_selected_candidate_authority(authority):
    from harness.discovery_restoration_completion import _validate_native_authority
    root, run, completion, plan, selected = authority
    before = _git(root, "rev-parse", "HEAD"), (root / "specs/001-demo/spec.md").read_bytes()
    assert _validate_native_authority(root, run, completion, plan, selected) == selected
    assert (_git(root, "rev-parse", "HEAD"), (root / "specs/001-demo/spec.md").read_bytes()) == before


@pytest.mark.parametrize("damage", ["current", "selected", "digest", "preimages", "completion", "phase", "run", "spec", "entries"])
def test_native_plan_cannot_be_rebound_to_another_effect(authority, damage):
    from harness.discovery_restoration_completion import _validate_native_authority
    root, run, completion, plan, selected = authority
    effect = completion.intent.quality_effect
    if damage == "current": effect["candidate"]["assessment_index"] += 1
    elif damage == "selected": effect["restore_candidate_id"] = "quality-candidate-1"
    elif damage == "digest": effect["restore_candidate_manifest_sha256"] = "a" * 64
    elif damage == "preimages": effect["restore_artifact_preimage_digests"]["spec.md"] = "b" * 64
    elif damage == "completion": completion.marker.completion_id = "d" * 32
    elif damage == "phase": completion.intent.route["to_phase"] = "phase1-what"
    elif damage == "run": effect["run_id"] = "other"
    elif damage == "spec": effect["spec_id"] = "other"
    else: selected = replace(selected, entries=selected.entries[:-1])
    with pytest.raises(ValueError):
        _validate_native_authority(root, run, completion, plan, selected)


def completed(authority):
    from harness.proportional_quality import materialize_quality_candidate_restore
    root, run, completion, plan, selected = authority
    receipt = materialize_quality_candidate_restore(project_root=root, spec_dir=root / "specs/001-demo",
        candidate=selected.snapshot.manifest, run_id=plan.run_id, spec_id=plan.spec_id,
        completion_id=plan.completion_id, next_phase=plan.next_phase,
        checkpoint_prestate={"kind": "git_head", "head": plan.base_commit},
        artifact_preimage_digests=completion.intent.quality_effect["restore_artifact_preimage_digests"],
        preflighted_restore=selected, restore_plan=plan)
    completion.receipts["effects"]["quality"] = dict(schema_version=1, operation="candidate",
        candidate=completion.fixture_candidate_receipt, restore=receipt)
    return completion.receipts["effects"]["quality"]


def test_native_authority_accepts_exact_completed_restore_receipt(authority):
    from harness.discovery_restoration_completion import _validate_native_authority
    root, run, completion, plan, selected = authority
    completed(authority)
    assert _validate_native_authority(root, run, completion, plan, selected) == selected


@pytest.mark.parametrize("damage", ["candidate_completion", "restore_completion", "restore_candidate", "preimages", "postimages", "run", "phase"])
def test_native_authority_rejects_another_validly_shaped_receipt(authority, damage):
    from harness.discovery_restoration_completion import _validate_native_authority
    root, run, completion, plan, selected = authority
    receipt = completed(authority)
    if damage == "candidate_completion": receipt["candidate"]["checkpoint"]["completion_id"] = "a" * 32
    elif damage == "restore_completion": receipt["restore"]["checkpoint"]["completion_id"] = "b" * 32
    elif damage == "restore_candidate": receipt["restore"]["candidate_id"] = "quality-candidate-9"
    elif damage in {"preimages", "postimages"}: receipt["restore"]["artifact_" + damage[:-1] + "_digests"]["spec.md"] = "c" * 64
    elif damage == "run": receipt["restore"]["checkpoint"]["run_id"] = "other-run"
    else: receipt["restore"]["checkpoint"]["next_phase"] = "phase1-what"
    with pytest.raises(ValueError):
        _validate_native_authority(root, run, completion, plan, selected)
