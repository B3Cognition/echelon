"""Quality preparation reads sealed review bytes without publishing them early."""
from dataclasses import replace
import hashlib
import json

import pytest

from harness import proportional_quality as quality
from harness.phase1_quality import AuthoritativeQualityAssessment, build_phase1_quality_certificate, has_current_phase1_quality_certificate
from harness.squad_publication import SquadPublicationTransaction
from tests.unit.test_phase1_quality import _quality_state, _write_passing_sage_issues
from tests.unit.test_proportional_quality import _repair_state


@pytest.fixture
def review(tmp_path):
    state, spec, report = _quality_state(tmp_path)
    payload = json.loads(report.read_text())
    payload.update(thresholds={"overall": 0.8}, scores={"overall": 0.9},
                   gates={"overall": {"score": 0.9, "threshold": 0.8, "pass": True,
                           "numeric_pass": True, "pass_basis": "numeric_threshold"}})
    report.write_text(json.dumps(payload))
    digest = hashlib.sha256(report.read_bytes()).hexdigest()
    state["understanding_evidence"]["digest"] = digest
    state["quality_scores"][0]["evidence_digest"] = digest
    issues = _write_passing_sage_issues(spec)
    passing = issues.read_bytes()
    issues.write_bytes(b"Stale canonical review must not be used.\n")
    (spec.parent / "requirements-overview.md").write_text("# Requirements\n")
    run = tmp_path / "runs/run-1"
    transaction = SquadPublicationTransaction.begin(tmp_path, run, "1" * 32)
    for name, content in (("issues.md", passing), ("quality-gates.md", b"## Verdict: PASS\n")):
        staged = transaction.build_path(name)
        staged.write_bytes(content)
        target = (spec.parent / name).relative_to(tmp_path)
        transaction.add_write(target, staged, owned_paths={target})
    publication = transaction.seal()
    with publication.inspect_sources(tree_paths=(state["spec_dir"],),
                                     file_paths=(report.relative_to(tmp_path).as_posix(),)) as sources:
        pass
    return tmp_path, state, spec, report, publication, sources, passing


def captured(review):
    root, _, spec, _, _, sources, _ = review
    return quality.project_authoritative_sage_evidence_snapshot(
        sources, spec.parent / "issues.md", project_root=root)


@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("mode", ["proportional", "perfectionist"])
def test_what_repair_progress_uses_staged_spec_without_early_publication(tmp_path, changed, mode):
    from tests.integration.test_squad_controller import _start_proportional_quality_loop
    from harness.squad import SquadAgentResult
    controller, store = _start_proportional_quality_loop(tmp_path)
    state = store.load()
    spec = tmp_path / state["spec_dir"] / "spec.md"
    spec.parent.mkdir(parents=True)
    original = b"# Original requirement\n"
    spec.write_bytes(original)
    state.update(phase="phase1-what", why_fail_count=2, why2_metric_stagnation_count=1,
        why_failure_baseline={"recorded_at": "2020-01-01T00:00:00+00:00"},
        quality_gate_remediation=dict(kind="proportional_quality",
            baseline_spec_sha256=hashlib.sha256(original).hexdigest()))
    if mode == "perfectionist":
        state.update(spec_authoring_mode=mode, phase1_quality_repair=None)
        state.pop("quality_gate_remediation")
    store.save(state)
    transaction = SquadPublicationTransaction.begin(tmp_path, controller._squad_dir, "3" * 32)
    staged = transaction.build_path("spec.md")
    staged.write_bytes(b"# Repaired requirement\n" if changed else original)
    target = spec.relative_to(tmp_path)
    transaction.add_write(target, staged, owned_paths={target})
    publication = transaction.seal()
    with publication.inspect_sources(tree_paths=(state["spec_dir"],)) as sources:
        pass
    snapshot = store.capture_routing_snapshot(expected_phase="phase1-what")
    node = controller._graph.get("phase1-what")
    result = SquadAgentResult(0, {"verdict": "DONE", "state_updates": {
        "evidence_resolution_status": "not_required", "spec_status": "planned"}}, "", 0, False)
    prepared = controller._prepare_phase_result(node, result, snapshot, publication_sources=sources)
    updates = controller._coordinate_what_repair_cycle_updates(node, prepared, snapshot, publication_sources=sources)
    if mode == "proportional":
        assert updates["proportional_quality_candidate_evidence"]["last_repair_outcome"] == (
            "consumed" if changed else "no_artifact_progress")
        assert updates["phase1_quality_repair"]["automatic_consumed"] == (1 if changed else 0)
    assert updates.get("why_fail_count", 2) == (0 if changed else 2)
    assert updates.get("why2_metric_stagnation_count", 1) == (0 if changed else 1)
    assert spec.read_bytes() == original and store.load() == snapshot.state


def test_what_progress_rejects_review_owned_writes(review):
    from harness.discovery_spec import projected_requirement_sha256
    root, state, spec, _, _, sources, _ = review
    original = spec.read_bytes()
    with pytest.raises(ValueError, match="WHAT ownership"):
        projected_requirement_sha256(sources, root=root, spec_dir=state["spec_dir"])
    assert spec.read_bytes() == original


def test_projected_review_is_distinct_from_physical_evidence_and_keeps_canonical_untouched(review):
    root, _, spec, _, _, _, passing = review
    snapshot = captured(review)
    assert snapshot.verdict == "PASS" and snapshot.issues == ()
    assert snapshot.content == passing
    assert snapshot.sha256 == hashlib.sha256(passing).hexdigest()
    assert not isinstance(snapshot, quality.AuthoritativeSageEvidenceSnapshot)
    assert (spec.parent / "issues.md").read_bytes() == b"Stale canonical review must not be used.\n"
    with pytest.raises(quality.QualityCandidateIntegrityError):
        quality.require_current_authoritative_sage_evidence_snapshot(snapshot, spec.parent / "issues.md", project_root=root)


def test_certificate_binds_projected_review_but_is_not_current_before_publication(review):
    root, state, spec, _, publication, _, passing = review
    assessment = AuthoritativeQualityAssessment(True, "PASS", "PASS", (), (), True, False, (), captured(review))
    certificate = build_phase1_quality_certificate(state, project_root=root, authoritative_sage_assessment=assessment)
    assert certificate is not None
    assert certificate["sage_evidence_sha256"] == hashlib.sha256(passing).hexdigest()
    state["spec_quality_certificate"] = certificate
    assert not has_current_phase1_quality_certificate(state, project_root=root)
    publication.publish()
    assert has_current_phase1_quality_certificate(state, project_root=root)


def test_candidate_preparation_uses_the_same_projected_artifact_set(review):
    root, _, spec, report, _, _, passing = review
    repair = _repair_state()
    candidate = quality.prepare_quality_candidate(
        project_root=root, spec_dir=spec.parent, run_artifact_root=root / "runs/run-1",
        run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
        understanding_evidence=report, normalized_gates={"overall": {"score": 0.9, "threshold": 0.8, "pass": True}},
        sage_finding_routes=(), formal_statement_count=1, repair_number=0, assessment_index=0,
        eligibility_reasons=(), repair_state=repair, authoritative_sage_evidence=captured(review))
    assert dict(candidate.owned_artifact_digests)["issues.md"] == hashlib.sha256(passing).hexdigest()
    assert dict(candidate.owned_artifact_digests)["quality-gates.md"] == hashlib.sha256(b"## Verdict: PASS\n").hexdigest()
    assert candidate.failed_gate_count == 0
    assert not (spec.parent / "quality-gates.md").exists()


@pytest.mark.parametrize("damage", [None, "missing", "duplicate", "digest"])
def test_restoration_preimages_use_assessed_candidate_before_publication(review, damage):
    root, _, spec, report, _, _, passing = review
    current = quality.prepare_quality_candidate(
        project_root=root, spec_dir=spec.parent, run_artifact_root=root / "runs/run-1",
        run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-1",
        understanding_evidence=report, normalized_gates={"overall": {"score": 0.9, "threshold": 0.8, "pass": True}},
        sage_finding_routes=(), formal_statement_count=1, repair_number=1, assessment_index=1,
        eligibility_reasons=(), repair_state=_repair_state(automatic_consumed=1,
            candidate_ids=["quality-candidate-0"], baseline_candidate_id="quality-candidate-0"),
        authoritative_sage_evidence=captured(review))
    selected = replace(current, candidate_id="quality-candidate-0",
        owned_artifact_digests=tuple((name, "a" * 64) for name, _ in current.owned_artifact_digests))
    before = (spec.parent / "issues.md").read_bytes()
    if damage is not None:
        images = current.owned_artifact_digests
        if damage == "missing": images = images[:-1]
        if damage == "duplicate": images = (*images, images[0])
        if damage == "digest": images = ((images[0][0], "bad"), *images[1:])
        current = replace(current, owned_artifact_digests=images)
        with pytest.raises(quality.QualityCandidateIntegrityError):
            quality.candidate_artifact_preimage_digests(spec.parent, selected, current_candidate=current)
        return
    preimages = quality.candidate_artifact_preimage_digests(spec.parent, selected, current_candidate=current)
    assert preimages == dict(current.owned_artifact_digests)
    assert preimages["issues.md"] == hashlib.sha256(passing).hexdigest()
    assert (spec.parent / "issues.md").read_bytes() == before
    assert not (spec.parent / "quality-gates.md").exists()


@pytest.mark.parametrize("damage", [None, "spec", "report", "artifact", "gates", "route", "repair_number", "eligibility_reasons"])
def test_managed_quality_effect_is_bound_to_same_captured_candidate(review, damage):
    from types import SimpleNamespace
    from harness.discovery_quality import validate_why2_quality_effect
    root, state, spec, report, _, sources, _ = review
    repair = _repair_state()
    candidate = quality.prepare_quality_candidate(project_root=root, spec_dir=spec.parent,
        run_artifact_root=root / "runs/run-1", run_id="run-1", spec_id="001-demo",
        candidate_id="quality-candidate-0", understanding_evidence=report,
        normalized_gates={"overall": {"score": 0.9, "threshold": 0.8, "pass": True}},
        sage_finding_routes=(), formal_statement_count=1, repair_number=0, assessment_index=0,
        eligibility_reasons=(), repair_state=repair, authoritative_sage_evidence=captured(review))
    binding = SimpleNamespace(producer="why2", spec_id="001-demo", sources=sources,
        source={"authority": {"managed_identity": {"spec_path": state["spec_dir"]}},
            "quality_policy": dict(authoring_mode="proportional", repair=_repair_state(), product_input_mapping_repair=False)},
        recovery={"operation": {"binding": {"run_id": "run-1"}}},
        candidate={"routing": {"state_updates": {"finding_routes": {"findings": []}}}})
    prestate = {"kind": "git_head", "head": "a" * 40}
    effect = dict(kind="proportional_quality", operation="candidate", spec_dir=state["spec_dir"],
        run_id="run-1", spec_id="001-demo", candidate=quality.quality_candidate_effect_payload(candidate),
        checkpoint_prestate=prestate, restore_candidate_id=None, restore_candidate_manifest_sha256=None,
        restore_artifact_preimage_digests=None)
    if damage == "spec": effect["spec_dir"] = "specs/other"
    elif damage == "report": effect["candidate"]["understanding_evidence_digest"] = "0" * 64
    elif damage == "artifact": effect["candidate"]["owned_artifact_digests"]["spec.md"] = "0" * 64
    elif damage == "gates": effect["candidate"]["normalized_gates"][0]["score"] = 0.95
    elif damage == "route": effect["candidate"]["sage_finding_routes"] = [{"issue_id": "ISS-000001", "route": "spec_repair"}]
    elif damage == "repair_number": effect["candidate"]["repair_number"] = 999
    elif damage == "eligibility_reasons": effect["candidate"]["eligibility_reasons"] = ["critical_sage_issue"]
    if damage is None:
        validate_why2_quality_effect(binding, effect, root=root, run=root / "runs/run-1", checkpoint_prestate=prestate)
    else:
        with pytest.raises((ValueError, quality.QualityCandidateIntegrityError)):
            validate_why2_quality_effect(binding, effect, root=root, run=root / "runs/run-1", checkpoint_prestate=prestate)


@pytest.mark.parametrize("damage", [None, "undeclared", "declaration", "candidate", "preimages", "digest"])
def test_managed_restoration_requires_exact_declared_retained_candidate(review, damage):
    from copy import deepcopy
    from types import SimpleNamespace
    from harness.discovery_quality import validate_why2_quality_effect
    from tests.unit.test_proportional_quality import _git
    root, state, spec, report, publication, sources, passing = review
    run = root / "runs/run-1"
    original_issues = (spec.parent / "issues.md").read_bytes()
    original_gates = (spec.parent / "quality-gates.md").read_bytes() if (spec.parent / "quality-gates.md").exists() else None
    (spec.parent / "issues.md").write_bytes(passing)
    (spec.parent / "quality-gates.md").write_bytes(b"## Verdict: PASS\n")
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Test User")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "candidate fixture")
    repair = _repair_state()
    arguments = dict(project_root=root, spec_dir=spec.parent, run_artifact_root=run, run_id="run-1", spec_id="001-demo",
        understanding_evidence=report, normalized_gates={"overall": {"score": 0.9, "threshold": 0.8, "pass": True}},
        sage_finding_routes=(), formal_statement_count=1, repair_number=0, eligibility_reasons=(), repair_state=repair)
    old = quality.capture_quality_candidate(**arguments, candidate_id="quality-candidate-0", assessment_index=0)
    policy = dict(authoring_mode="proportional", repair=deepcopy(repair), product_input_mapping_repair=False)
    (spec.parent / "issues.md").write_bytes(original_issues)
    if original_gates is None:
        (spec.parent / "quality-gates.md").unlink()
    else:
        (spec.parent / "quality-gates.md").write_bytes(original_gates)
    current = quality.prepare_quality_candidate(**arguments, candidate_id="quality-candidate-1", assessment_index=1,
        authoritative_sage_evidence=captured(review))
    prestate = {"kind": "git_head", "head": old.checkpoint_commit}
    binding = SimpleNamespace(producer="why2", spec_id="001-demo", sources=sources,
        request=SimpleNamespace(continuation_id="discovery-restore-" + "a" * 32),
        source={"authority": {"managed_identity": {"spec_path": state["spec_dir"]}}, "quality_policy": policy},
        recovery={"operation": {"binding": {"run_id": "run-1"}}, "completion_id": "a" * 32},
        candidate={"routing": {"state_updates": {"finding_routes": {"findings": []}}}})
    old_snapshot = quality.load_quality_candidate_snapshot(run / "quality-candidates/quality-candidate-0.json")
    effect = dict(kind="proportional_quality", operation="candidate", spec_dir=state["spec_dir"], run_id="run-1", spec_id="001-demo",
        candidate=quality.quality_candidate_effect_payload(current), checkpoint_prestate=prestate,
        restore_candidate_id=old.candidate_id, restore_candidate_manifest_sha256=old_snapshot.sha256,
        restore_artifact_preimage_digests=dict(current.owned_artifact_digests))
    if damage == "undeclared": binding.request.continuation_id = None
    elif damage == "declaration": binding.request.continuation_id = "discovery-restore-" + "b" * 32
    elif damage == "candidate": effect["restore_candidate_id"] = current.candidate_id
    elif damage == "preimages": effect["restore_artifact_preimage_digests"]["issues.md"] = "c" * 64
    elif damage == "digest": effect["restore_candidate_manifest_sha256"] = "d" * 64
    if damage is None:
        result = validate_why2_quality_effect(binding, effect, root=root, run=run, checkpoint_prestate=prestate)
        assert quality.quality_candidate_effect_payload(result) == effect["candidate"]
    else:
        with pytest.raises((ValueError, quality.QualityCandidateIntegrityError)):
            validate_why2_quality_effect(binding, effect, root=root, run=run, checkpoint_prestate=prestate)


@pytest.mark.parametrize("field,value", [("verdict", "FAIL"), ("content", b"different"),
                                        ("sha256", "0" * 64), ("project_relative_path", "other/issues.md")])
def test_projected_review_revalidates_its_full_source_binding(review, field, value):
    root, state, _, _, _, _, _ = review
    snapshot = replace(captured(review), **{field: value})
    assessment = AuthoritativeQualityAssessment(True, "PASS", "PASS", (), (), True, False, (), snapshot)
    assert build_phase1_quality_certificate(state, project_root=root, authoritative_sage_assessment=assessment) is None


def test_malformed_source_envelope_is_a_bounded_quality_rejection(review):
    root, state, _, _, _, _, _ = review
    snapshot = replace(captured(review), sources_payload='{"version":999}')
    assessment = AuthoritativeQualityAssessment(True, "PASS", "PASS", (), (), True, False, (), snapshot)
    assert build_phase1_quality_certificate(state, project_root=root, authoritative_sage_assessment=assessment) is None


def test_projected_review_cannot_borrow_evidence_for_a_different_spec_image(review):
    root, state, spec, _, publication, _, _ = review
    original = spec.read_bytes()
    try:
        spec.write_bytes(original + b"\nA different reviewed specification.\n")
        with publication.inspect_sources(tree_paths=(state["spec_dir"],)) as sources:
            pass
    finally:
        spec.write_bytes(original)
    staged = quality.project_authoritative_sage_evidence_snapshot(sources, spec.parent / "issues.md", project_root=root)
    assessment = AuthoritativeQualityAssessment(True, "PASS", "PASS", (), (), True, False, (), staged)
    assert build_phase1_quality_certificate(state, project_root=root, authoritative_sage_assessment=assessment) is None


@pytest.mark.parametrize("unexpected", ["spec.md", "requirements-overview.md"])
def test_review_projection_cannot_also_rewrite_requirement_artifacts(review, unexpected):
    root, state, spec, _, _, _, passing = review
    transaction = SquadPublicationTransaction.begin(root, root / "runs/run-1", "3" * 32)
    for name, content in (("issues.md", passing), ("quality-gates.md", b"## Verdict: PASS\n"),
                          (unexpected, b"Unauthorized requirement rewrite.\n")):
        staged = transaction.build_path(name)
        staged.write_bytes(content)
        target = (spec.parent / name).relative_to(root)
        transaction.add_write(target, staged, owned_paths={target})
    with transaction.seal().inspect_sources(tree_paths=(state["spec_dir"],)) as sources:
        pass
    with pytest.raises(quality.QualityCandidateIntegrityError):
        quality.project_authoritative_sage_evidence_snapshot(sources, spec.parent / "issues.md", project_root=root)


@pytest.mark.parametrize("mode", ["proportional", "perfectionist"])
def test_controller_pass_preparation_uses_projected_review_without_publishing(review, mode):
    from tests.integration.test_squad_controller import _controller
    from harness.squad_provider import SquadAgentResult
    root, state, spec, _, _, sources, passing = review
    controller, store = _controller(root, squad_dir=root / "runs/run-1")
    store.initialize("run-test", "greenfield", "game", 0, "phase1-why2")
    saved = store.load()
    saved.update(state, phase="phase1-why2", spec_authoring_mode=mode,
                 phase1_quality_repair=_repair_state() if mode == "proportional" else None)
    store.save(saved)
    baseline = store.load()
    snapshot = store.capture_routing_snapshot(expected_phase="phase1-why2")
    node = controller._graph.get("phase1-why2")
    result = SquadAgentResult(0, {"verdict": "PASS", "state_updates": {
        "evidence_resolution_status": "not_required", "finding_routes": {"findings": []}}}, "", 0, False)
    prepared = controller._prepare_phase_result(node, result, snapshot, publication_sources=sources)
    _, updates, request = controller._coordinate_why_transition_state(node, prepared, snapshot, publication_sources=sources)
    assert request is None
    assert updates["spec_quality_certificate"]["sage_evidence_sha256"] == hashlib.sha256(passing).hexdigest()
    if mode == "proportional":
        effect = updates["_proportional_quality_effect"]
        assert dict(effect["candidate"]["owned_artifact_digests"])["issues.md"] == hashlib.sha256(passing).hexdigest()
    else:
        assert "_proportional_quality_effect" not in updates
    assert store.load() == baseline
    assert (spec.parent / "issues.md").read_bytes().startswith(b"Stale canonical")


def failing_review(tmp_path, *, discovery=False, banzai=False, finding="incompleteness"):
    from tests.integration.test_squad_controller import (
        _start_proportional_quality_loop, _proportional_assessment_fixture,
    )
    controller, store = _start_proportional_quality_loop(tmp_path)
    updates, result = _proportional_assessment_fixture(controller, store, 0)
    state = store.load()
    state.update(updates, autonomy_mode="banzai" if banzai else "semi")
    store.save(state)
    spec = tmp_path / state["spec_dir"]
    content = (spec / "issues.md").read_text().replace("ISS-QUALITY-0", "ISS-000001")
    result.echelon_result["state_updates"]["finding_routes"]["findings"][0]["issue_id"] = "ISS-000001"
    if discovery:
        content = content.replace("**Affected artifact:** spec.md", "**Affected artifact:** assumptions.md").replace(
            "**Responsible agent:** WHAT", "**Responsible agent:** DISCOVER")
    if banzai:
        content = content.replace("**Banzai eligible:** no", "**Banzai eligible:** yes")
    if finding == "critical":
        content = content.replace("**Severity:** LOW", "**Severity:** CRITICAL").replace(
            "**CRITICAL:** 0", "**CRITICAL:** 1").replace("**LOW:** 1", "**LOW:** 0")
    elif finding == "contradiction":
        content = content.replace("**Type:** incompleteness", "**Type:** contradiction")
    _write_passing_sage_issues(spec / "spec.md")
    transaction = SquadPublicationTransaction.begin(tmp_path, controller._squad_dir, "2" * 32)
    for name, payload in (("issues.md", content.encode()), ("quality-gates.md", b"## Verdict: FAIL\n")):
        staged = transaction.build_path(name)
        staged.write_bytes(payload)
        target = (spec / name).relative_to(tmp_path)
        transaction.add_write(target, staged, owned_paths={target})
    publication = transaction.seal()
    with publication.inspect_sources(tree_paths=(state["spec_dir"],)) as sources:
        pass
    return controller, store, result, sources


def test_banzai_options_use_full_staged_resolution_guidance(tmp_path):
    controller, store, result, sources = failing_review(tmp_path, banzai=True)
    snapshot = store.capture_routing_snapshot(expected_phase="phase1-why2")
    assessment = controller._authoritative_quality_assessment(
        provider_verdict="FAIL", eval_state=snapshot.state,
        routes=tuple(result.echelon_result["state_updates"]["finding_routes"]["findings"]),
        spec_dir=tmp_path / snapshot.state["spec_dir"], publication_sources=sources)
    request = controller._prepare_banzai_quality_issue_resolution(snapshot, assessment)
    assert request is not None
    assert request.options[0].id == "ISS-000001"
    assert request.options[0].next_phase == "phase1-what"
    candidates = controller._banzai_issue_resolution_candidates(dict(snapshot.state), sage_evidence=assessment.sage_evidence)
    assert candidates[0]["suggested_option"] == "Repair the certified failing dimension."
    assert store.load() == snapshot.state


@pytest.mark.parametrize("discovery,expected", [(False, "phase1-what"), (True, "phase1-discover")])
def test_routing_preparation_uses_staged_repair_owner(tmp_path, discovery, expected):
    controller, store, result, sources = failing_review(tmp_path, discovery=discovery)
    snapshot = store.capture_routing_snapshot(expected_phase="phase1-why2")
    node = controller._graph.get("phase1-why2")
    prepared = controller._prepare_phase_result(node, result, snapshot, publication_sources=sources)
    decision = controller._coordinate_transition_routing(node, prepared, snapshot, publication_sources=sources)
    assert decision.to_phase == expected
    assert store.load() == snapshot.state


@pytest.mark.parametrize("mode", ["proportional", "perfectionist"])
def test_staged_provider_pass_cannot_override_failed_numeric_assessment(review, mode):
    from tests.integration.test_squad_controller import _controller
    from harness.squad_provider import SquadAgentResult
    root, state, _, report, publication, _, _ = review
    payload = json.loads(report.read_text())
    payload.update(scores={"overall": 0.6}, **{"pass": False})
    payload["gates"]["overall"].update(score=0.6, **{"pass": False, "numeric_pass": False})
    report.write_text(json.dumps(payload))
    digest = hashlib.sha256(report.read_bytes()).hexdigest()
    state["understanding_evidence"].update(digest=digest, **{"pass": False, "failing_gates": ["overall"]})
    state["quality_scores"][0].update(evidence_digest=digest, overall=0.6, **{"pass": False})
    with publication.inspect_sources(tree_paths=(state["spec_dir"],),
                                     file_paths=(report.relative_to(root).as_posix(),)) as sources:
        pass
    controller, store = _controller(root, squad_dir=root / "runs/run-1")
    store.initialize("run-test", "greenfield", "game", 0, "phase1-why2")
    saved = store.load()
    saved.update(state, phase="phase1-why2", spec_authoring_mode=mode,
                 phase1_quality_repair=_repair_state() if mode == "proportional" else None)
    store.save(saved)
    snapshot = store.capture_routing_snapshot(expected_phase="phase1-why2")
    node = controller._graph.get("phase1-why2")
    result = SquadAgentResult(0, {"verdict": "PASS", "state_updates": {
        "evidence_resolution_status": "not_required", "finding_routes": {"findings": []}}}, "", 0, False)
    prepared = controller._prepare_phase_result(node, result, snapshot, publication_sources=sources)
    route, updates, request = controller._coordinate_why_transition_state(node, prepared, snapshot, publication_sources=sources)
    assert route == "terminal-blocked"
    assert updates["status"] == "blocked"
    assert not updates.get("spec_quality_certificate")
    assert "_proportional_quality_effect" not in updates
    assert request is None
    assert store.load() == snapshot.state


@pytest.mark.parametrize("finding", ["critical", "contradiction"])
def test_perfectionist_staged_severe_findings_route_to_repair(tmp_path, finding):
    controller, store, result, sources = failing_review(tmp_path, finding=finding)
    state = store.load()
    state.update(spec_authoring_mode="perfectionist", phase1_quality_repair=None)
    store.save(state)
    snapshot = store.capture_routing_snapshot(expected_phase="phase1-why2")
    node = controller._graph.get("phase1-why2")
    prepared = controller._prepare_phase_result(node, result, snapshot, publication_sources=sources)
    decision = controller._coordinate_transition_routing(node, prepared, snapshot, publication_sources=sources)
    assert decision.to_phase == "phase1-what"
    assert store.load() == snapshot.state
