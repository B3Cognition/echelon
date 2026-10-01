"""Durable documentation convergence through the actual controller boundary."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from harness.ai_cli_backend import CliRunResult
from tests.unit.test_delivery_slice_runner import slice_project


IMPACT = """---
schema_version: 2
docs_required: false
readme_updated: false
changelog_updated: false
changelog_format: not_required
not_applicable_reason: Internal greeting test maintenance.
delivery_change_ids: [T-001]
documented_changes:
  - change_id: T-001
    disposition: not_applicable
    reason: Internal test maintenance.
    evidence_paths: [app.py]
---
# Documentation Impact Report
Internal greeting test maintenance; app.py is the evidence.
"""


def review_report(fail=False):
    metadata = dict(schema_version=2, reviewed_change_ids=["T-001"], uncovered_change_ids=[],
                    unsupported_claims=["app.py: explain greeting"] if fail else [],
                    verdict="FAIL" if fail else "PASS", readme_first_run_manual=not fail,
                    changelog_valid=True, impact_report_valid=True, project_evidence_checked=True,
                    evidence_items_checked=4, blocking_findings=int(fail),
                    runnability_evidence_sha256="", runnability_commands_current=False)
    return "---\n" + yaml.safe_dump(metadata) + "---\n# Docs Verification Report\n" + metadata["verdict"]


class DocumentationExecutor:
    supports_read_only_review = True

    def __init__(self, spec, script=None, reject_first=False, always_reject=False):
        self.spec, self.script = spec, script
        self.reject_first, self.always_reject = reject_first, always_reject
        self.calls, self.snapshots = [], []

    @property
    def steps(self):
        return [call[0]["step"] for call in self.calls]

    def run_agent_result(self, cwd, prompt, *, request_metadata, **kwargs):
        assignment = request_metadata["delivery_assignment"]
        self.calls.append((assignment, request_metadata["prompt_metadata"], prompt))
        report = self.spec / "docs-verification-report.md"
        self.snapshots.append(report.read_text() if report.exists() else None)
        writer = assignment["step"] == "tech_writer"
        fail = not writer and (self.always_reject or self.reject_first and len(self.calls) == 2)
        if writer:
            Path(cwd, "README.md").write_text("# Greeting\nInternal test fixture.\n")
        payload = {**assignment, "verdict": "DONE" if writer else "FAIL" if fail else "PASS",
                   "summary": "Inspected app.py", "findings": ["app.py: explain greeting"] if fail else [],
                   "report_markdown": IMPACT if writer else review_report(fail)}
        if self.script:
            response = self.script(assignment, payload, Path(cwd))
            if response is not None:
                return response
        return CliRunResult(0, json.dumps(payload), "", token_usage=7)


@pytest.fixture
def documentation_project(slice_project):
    project, spec, evidence = slice_project
    def factory(**kwargs):
        from harness.delivery_documentation import DeliveryDocumentationRunner
        source = Path(__file__).resolve().parents[2] / "prosaic/subagents"
        for role in ("tech-writer", "docs-verifier"):
            name = f"echelon.delivery-{role}.md"
            shutil.copyfile(source / name, project / ".echelon/prosaic/subagents" / name)
        executor = DocumentationExecutor(spec, **kwargs)
        return DeliveryDocumentationRunner(executor, project), executor, dict(
            worktree=project, spec_dir=spec, evidence_root=evidence, allowed_task_ids={"T-001"}, changed_files=["app.py"])
    return factory


def test_rejected_docs_are_repaired_before_publication(documentation_project):
    runner, provider, paths = documentation_project(reject_first=True)
    result = runner.run(**paths)
    assert result.succeeded and result.task_ids == [], result.reason
    assert provider.steps == ["tech_writer", "docs_verifier"] * 2
    assert provider.snapshots == [None] * 4
    assert result.token_usage == 28
    assert (paths["spec_dir"] / "docs-verification-report.md").read_text() == review_report()
    assert "app.py: explain greeting" in provider.calls[2][2]
    replay = runner.run(**paths, journal_required=True)
    assert replay.succeeded and replay.token_usage == 28
    assert len(provider.calls) == 4


def test_controlled_documentation_journal_binds_operation_before_replay(documentation_project):
    runner, provider, paths = documentation_project()
    identity = dict(build_id="build-a", delivery_run_id="run-a",
                    spec_id="001-slice", operation_id="docs-op")
    result = runner.run(**paths, operation_id="docs-op", operation_binding=identity)
    assert result.succeeded, result.reason
    journal = next(paths["evidence_root"].rglob("journal.json"))
    data = json.loads(journal.read_text())
    assert data["schema_version"] == 5
    assert data["operation_binding"] == identity
    assert runner.run(**paths, operation_id="docs-op", operation_binding=identity,
                      journal_required=True).succeeded
    assert provider.steps == ["tech_writer", "docs_verifier"]

    for field in identity:
        wrong = {**identity, field: identity[field] + "-other"}
        blocked = runner.run(**paths, operation_id="docs-op", operation_binding=wrong,
                             journal_required=True)
        assert not blocked.succeeded
        assert "documentation operation binding changed" in blocked.reason
    unbound = runner.run(**paths, operation_id="docs-op", journal_required=True)
    assert not unbound.succeeded
    assert "documentation operation binding" in unbound.reason
    assert provider.steps == ["tech_writer", "docs_verifier"]


def test_legacy_documentation_journal_cannot_become_controlled(documentation_project):
    runner, provider, paths = documentation_project()
    assert runner.run(**paths, operation_id="docs-op").succeeded
    identity = dict(build_id="build-a", delivery_run_id="run-a",
                    spec_id="001-slice", operation_id="docs-op")
    blocked = runner.run(**paths, operation_id="docs-op", operation_binding=identity,
                         journal_required=True)
    assert not blocked.succeeded
    assert "documentation operation binding changed" in blocked.reason
    assert provider.steps == ["tech_writer", "docs_verifier"]


def test_docs_reviewer_is_told_the_strict_findings_shape(documentation_project):
    runner, provider, paths = documentation_project(reject_first=True)
    result = runner.run(**paths)
    assert result.succeeded, result.reason
    reviewer_prompt = next(prompt for assignment, _, prompt in provider.calls
                           if assignment["step"] == "docs_verifier")
    assert "findings must be a JSON array of non-empty strings" in reviewer_prompt
    assert "not objects or a Markdown table" in reviewer_prompt


def test_historical_missing_report_feedback_does_not_block_staged_review(documentation_project):
    historical = "documentation-impact-report-missing: prior canonical report absent"
    provider = None

    def script(assignment, payload, _root):
        prompt = provider.calls[-1][2]
        repair_text = prompt.split("## Repair feedback\n", 1)[1]
        try:
            repair = json.loads(repair_text)
        except ValueError:
            repair = {}
        if assignment["step"] == "tech_writer" and repair.get("historical_verification_feedback") != historical:
            payload.update(verdict="NEEDS_CONTEXT", summary="canonical report is absent",
                           findings=["Need publication-order context"])
        if assignment["step"] == "docs_verifier":
            context = json.loads(prompt.split("## Independent review inputs\n", 1)[1].split("\n## Repair feedback", 1)[0])
            if context.get("publication_status") != "staged_not_published":
                payload.update(verdict="FAIL", summary="canonical report is absent",
                               findings=["Create canonical report before review"],
                               report_markdown=review_report(True))
        return CliRunResult(0, json.dumps(payload), "", token_usage=7)

    runner, provider, paths = documentation_project(script=script)
    result = runner.run(**paths, feedback=historical)
    assert result.succeeded, result.reason
    assert provider.steps == ["tech_writer", "docs_verifier"]
    assert provider.snapshots == [None, None]
    reviewer_prompt = provider.calls[1][2]
    assert '"impact_report_source": "writer_result.report_markdown"' in reviewer_prompt
    assert '"publication_status": "staged_not_published"' in reviewer_prompt
    assert (paths["spec_dir"] / "documentation-impact-report.md").read_text() == IMPACT


def test_completed_malformed_review_retries_without_rewriting_candidate(documentation_project):
    reviews = 0
    def script(assignment, payload, root):
        nonlocal reviews
        if assignment["step"] == "docs_verifier":
            reviews += 1
            if reviews == 1:
                payload.update(verdict="FAIL", findings=[{"id": "DOCS-001", "issue": "README omission"}],
                               report_markdown=review_report(True))
        return CliRunResult(0, json.dumps(payload), "", token_usage=7)

    runner, provider, paths = documentation_project(script=script)
    blocked = runner.run(**paths)
    assert blocked.reason == "invalid documentation findings"
    initial = json.loads(next(paths["evidence_root"].rglob("journal.json")).read_text())
    assert initial["records"][-1]["token_usage"] == 7
    (paths["spec_dir"] / "harness-run-history.json").write_text('{"runs": [{"status": "blocked"}]}')

    recovered = type(runner)(provider, runner._project_dir).run(**paths, journal_required=True)
    assert recovered.succeeded, recovered.reason
    assert recovered.token_usage == 21
    assert provider.steps == ["tech_writer", "docs_verifier", "docs_verifier"]
    journal = json.loads(next(paths["evidence_root"].rglob("journal.json")).read_text())
    assert journal["rejected_reviews"] == [initial["records"][-1]]
    assert journal["records"][0] == initial["records"][0]
    assert journal["records"][1]["assignment"]["dispatch_id"] != initial["records"][1]["assignment"]["dispatch_id"]
    assert journal["records"][1]["assignment"]["candidate_fingerprint"] == initial["records"][1]["assignment"]["candidate_fingerprint"]


@pytest.mark.parametrize("obstacle", ["changed_candidate", "exhausted_budget", "second_malformed"])
def test_malformed_review_retry_is_bounded_and_preserves_safety(documentation_project, obstacle):
    def script(assignment, payload, root):
        if assignment["step"] == "docs_verifier":
            payload.update(verdict="FAIL", findings=[{"id": "DOCS-001", "issue": "README omission"}],
                           report_markdown=review_report(True))
        return CliRunResult(0, json.dumps(payload), "", token_usage=7)

    runner, provider, paths = documentation_project(script=script)
    assert runner.run(**paths, token_budget=14 if obstacle == "exhausted_budget" else None).reason == "invalid documentation findings"
    if obstacle == "changed_candidate":
        (paths["worktree"] / "README.md").write_text("changed after review")
    resumed = type(runner)(provider, runner._project_dir).run(**paths, journal_required=True)
    assert resumed.status == "blocked"
    if obstacle == "changed_candidate":
        assert "candidate changed" in resumed.reason
    elif obstacle == "exhausted_budget":
        assert resumed.reason == "delivery_documentation_budget_exhausted"
    else:
        assert resumed.reason == "invalid documentation findings"
    assert len(provider.calls) == (3 if obstacle == "second_malformed" else 2)
    if obstacle == "second_malformed":
        again = type(runner)(provider, runner._project_dir).run(**paths, journal_required=True)
        assert again.reason == "invalid documentation findings"
        assert len(provider.calls) == 3


def test_documentation_source_binding_ignores_controller_run_history(documentation_project):
    from harness.delivery_documentation import _source_fingerprint
    _, _, paths = documentation_project()
    before = _source_fingerprint(paths["worktree"], paths["spec_dir"])
    (paths["spec_dir"] / "harness-run-history.json").write_text('{"runs": [{"status": "blocked"}]}')
    assert _source_fingerprint(paths["worktree"], paths["spec_dir"]) == before


def test_repeated_rejection_survives_reconstruction(documentation_project):
    runner, provider, paths = documentation_project(always_reject=True)
    first = runner.run(**paths)
    assert first.reason == "delivery_documentation_repair_limit"
    second = type(runner)(provider, runner._project_dir).run(**paths, journal_required=True)
    assert second.reason == first.reason
    assert provider.steps == ["tech_writer", "docs_verifier"] * 3


def test_explicit_budget_extension_replays_documentation_author_receipt(documentation_project):
    runner, provider, paths = documentation_project()
    blocked = runner.run(**paths, token_budget=7)
    assert not blocked.succeeded and "budget_exhausted" in blocked.reason
    assert provider.steps == ["tech_writer"]

    resumed = type(runner)(provider, runner._project_dir).run(
        **paths, journal_required=True, token_budget=100,
        budget_extension_limit=100,
    )

    assert resumed.succeeded, resumed.reason
    assert provider.steps == ["tech_writer", "docs_verifier"]
    journal = json.loads(next(paths["evidence_root"].rglob("journal.json")).read_text())
    assert journal["budget_limit"] == 100


@pytest.mark.parametrize("fault", ["identity", "fields", "legacy", "report_verdict", "passing_findings", "object_findings", "source", "spec", "control", "reviewer", "report_write"])
def test_invalid_dispatch_cannot_publish(documentation_project, fault):
    def script(assignment, payload, root):
        if assignment["step"] != "docs_verifier":
            return
        if fault == "identity": payload["task_ids"] = ["T-002"]
        if fault == "fields": payload["extra"] = True
        if fault == "legacy": return CliRunResult(0, "ALL DOCS PASS", "", token_usage=7)
        if fault == "report_verdict": payload["report_markdown"] = review_report(True)
        if fault == "passing_findings": payload["findings"] = ["unresolved"]
        if fault == "object_findings": payload.update(
            verdict="FAIL", findings=[{"id": "DOCS-001", "issue": "README omission"}],
            report_markdown=review_report(True),
        )
        if fault == "source": (root / "app.py").write_text("changed")
        if fault == "spec": (root / "specs/001-slice/spec.md").write_text("changed")
        if fault == "control": (root / ".echelon/config.yml").write_text("changed")
        if fault == "reviewer": (root / "README.md").write_text("changed")
        if fault == "report_write": (root / "specs/001-slice/docs-verification-report.md").write_text("intruder")
    runner, provider, paths = documentation_project(script=script)
    result = runner.run(**paths)
    assert result.status == "blocked", result.reason
    assert len(provider.calls) == 2
    assert not (paths["spec_dir"] / "documentation-impact-report.md").exists()


def test_native_scopes_and_original_reports_are_guarded(documentation_project):
    runner, provider, paths = documentation_project()
    (paths["spec_dir"] / "docs-verification-report.md").write_text("old report")
    result = runner.run(**paths)
    assert result.succeeded, result.reason
    assert provider.snapshots == ["old report"] * 2
    for assignment, metadata, prompt in provider.calls:
        assert assignment["task_ids"] == ["T-001"]
        assert metadata["tool_write_scope_exclusive"] is True
        expected = [str(paths["worktree"] / name) for name in ("README.md", "CHANGELOG.md")] if assignment["step"] == "tech_writer" else []
        assert metadata["tool_write_paths"] == expected
        assert str(paths["spec_dir"]) in metadata["tool_forbidden_roots"]
        assert str(paths["evidence_root"]) in metadata["tool_forbidden_roots"]


@pytest.mark.parametrize("options", [{"stop_requested": lambda: True}, {"token_budget": 0}, {"allowed_task_ids": set()}, {"runnability_required": True}, {"journal_required": True}])
def test_preflight_refuses_without_provider(documentation_project, options):
    runner, provider, paths = documentation_project()
    result = runner.run(**{**paths, **options})
    assert result.status == "blocked"
    assert provider.calls == []


class ProcessLost(BaseException):
    pass


@pytest.mark.parametrize("point", ["intent", "completion", "publication"])
def test_crash_recovery(documentation_project, monkeypatch, point):
    from harness.delivery_slice_journal import DeliverySliceJournal
    from harness import delivery_documentation as module
    runner, provider, paths = documentation_project()
    original_save = DeliverySliceJournal.save
    original_write = module.write_text_atomic
    fired = False
    def save(self, data):
        nonlocal fired
        original_save(self, data)
        records = data["records"]
        if not fired and len(records) == 1 and ((point == "intent" and records[0]["result"] is None) or (point == "completion" and records[0]["result"] is not None)):
            fired = True
            raise ProcessLost()
    def write(path, text, **kwargs):
        nonlocal fired
        original_write(path, text, **kwargs)
        if point == "publication" and Path(path) == paths["spec_dir"] / "documentation-impact-report.md" and not fired:
            fired = True
            raise ProcessLost()
    monkeypatch.setattr(DeliverySliceJournal, "save", save)
    monkeypatch.setattr(module, "write_text_atomic", write)
    with pytest.raises(ProcessLost): runner.run(**paths)
    result = type(runner)(provider, runner._project_dir).run(**paths, journal_required=True)
    if point == "intent":
        assert result.status == "blocked" and "unknown" in result.reason
        assert provider.calls == []
    else:
        assert result.succeeded, result.reason
        assert provider.steps == ["tech_writer", "docs_verifier"]
        assert result.token_usage == 14


@pytest.mark.parametrize("fault", ["source", "ignored", "build_marker", "symlink", "report"])
def test_writer_can_change_only_document_paths(documentation_project, fault):
    def script(assignment, payload, root):
        if fault == "source": (root / "app.py").write_text("changed")
        if fault == "ignored":
            (root / ".pytest_cache").mkdir(exist_ok=True)
            (root / ".pytest_cache/changed").write_text("changed")
        if fault == "build_marker": (root / ".harness-build-status.json").write_text("changed")
        if fault == "symlink":
            (root / "README.md").unlink()
            (root / "README.md").symlink_to(root / "app.py")
        if fault == "report": (root / "specs/001-slice/documentation-impact-report.md").write_text("changed")
    runner, provider, paths = documentation_project(script=script)
    result = runner.run(**paths)
    assert result.status == "blocked", result.reason
    assert len(provider.calls) == 1


def test_deterministic_failure_cannot_be_overridden_by_model_pass(documentation_project):
    def script(assignment, payload, root):
        if assignment["step"] == "tech_writer":
            payload["report_markdown"] = IMPACT.replace("docs_required: false", "docs_required: true")
    runner, provider, paths = documentation_project(script=script)
    result = runner.run(**paths)
    assert result.reason == "delivery_documentation_repair_limit"
    assert len(provider.calls) == 6
    assert "deterministic_findings" in provider.calls[2][2]
    assert not (paths["spec_dir"] / "docs-verification-report.md").exists()


def test_no_impact_review_must_cover_exact_inventory(documentation_project):
    def script(assignment, payload, root):
        if assignment["step"] == "docs_verifier":
            payload["report_markdown"] = review_report().replace("T-001", "T-002")
    runner, provider, paths = documentation_project(script=script)
    result = runner.run(**paths)
    assert result.status == "blocked"
    assert not (paths["spec_dir"] / "docs-verification-report.md").exists()


@pytest.mark.parametrize("usage,budget", [(None, 100), (7, 7), (7, 14)])
def test_usage_limits_block_and_survive_restart(documentation_project, usage, budget):
    def script(assignment, payload, root):
        return CliRunResult(0, json.dumps(payload), "", token_usage=usage)
    runner, provider, paths = documentation_project(script=script)
    first = runner.run(**paths, token_budget=budget)
    assert first.status == "blocked"
    calls = len(provider.calls)
    second = runner.run(**paths, journal_required=True)
    assert second.status == "blocked" and len(provider.calls) == calls
    assert second.token_usage == first.token_usage


def test_unknown_provider_return_is_never_reexecuted(documentation_project):
    def script(*args): raise RuntimeError("provider connection lost")
    runner, provider, paths = documentation_project(script=script)
    assert runner.run(**paths).status == "blocked"
    resumed = runner.run(**paths, journal_required=True)
    assert "unknown" in resumed.reason and resumed.token_usage is None
    assert len(provider.calls) == 1


@pytest.mark.parametrize("change", ["source", "reports", "feedback", "missing", "corrupt", "roles"])
def test_completed_receipts_refuse_stale_inputs(documentation_project, change):
    runner, provider, paths = documentation_project()
    assert runner.run(**paths).succeeded
    if change == "source": (paths["worktree"] / "app.py").write_text("new source")
    if change == "reports": (paths["spec_dir"] / "docs-verification-report.md").write_text("independent edit")
    if change == "feedback": paths["feedback"] = "new request"
    if change == "missing": next(paths["evidence_root"].rglob("journal.json")).unlink()
    if change == "corrupt": next(paths["evidence_root"].rglob("journal.json")).write_text("{}")
    if change == "roles": (paths["worktree"] / ".echelon/prosaic/subagents/echelon.delivery-tech-writer.md").unlink()
    result = runner.run(**paths, journal_required=True)
    assert result.status == "blocked" and len(provider.calls) == 2


def test_external_spec_publication(documentation_project, tmp_path):
    runner, provider, paths = documentation_project()
    external = tmp_path / "external-spec"
    shutil.move(paths["spec_dir"], external)
    paths["spec_dir"] = provider.spec = external
    result = runner.run(**paths)
    assert result.succeeded, result.reason
    assert (external / "docs-verification-report.md").is_file()


def test_publication_refuses_report_changed_at_write_boundary(documentation_project, monkeypatch):
    from harness import delivery_documentation as module
    runner, provider, paths = documentation_project()
    original = module.write_text_atomic
    def race(path, text, **kwargs):
        if path == paths["spec_dir"] / "documentation-impact-report.md":
            path.write_text("another writer")
        return original(path, text, **kwargs)
    monkeypatch.setattr(module, "write_text_atomic", race)
    result = runner.run(**paths)
    assert result.status == "blocked"
    assert (paths["spec_dir"] / "documentation-impact-report.md").read_text() == "another writer"


@pytest.mark.parametrize("change", ["source", "report", "latest"])
def test_current_runnability_content_is_bound(documentation_project, tmp_path, change):
    from harness.product_inventory import product_evidence_fingerprint
    from tests.unit.test_runnability_evidence import _write_report
    runner, provider, paths = documentation_project()
    ref = _write_report(tmp_path / "runnability", candidate_fingerprint=product_evidence_fingerprint(paths["worktree"]), contract_hash="")
    paths["runnability_report"] = ref
    def script(assignment, payload, root):
        assert "pnpm start:local" in provider.calls[-1][2]
        assert ref.evidence_sha256 in provider.calls[-1][2]
        if change == "source": (root / "app.py").write_text("stale source")
        if change == "report": ref.path.write_text(ref.path.read_text().replace("checkpoint", "altered"))
        if change == "latest": (ref.path.parent / "latest.json").write_text("{}")
    provider.script = script
    result = runner.run(**paths)
    assert result.status == "blocked", result.reason
    assert len(provider.calls) == 1


def test_verification_context_is_captured_without_provider_spec_access(documentation_project):
    runner, provider, paths = documentation_project()
    (paths["spec_dir"] / "verification-report.md").write_text("Smoke test: greeting returned correctly")
    assert runner.run(**paths).succeeded
    assert all("Smoke test: greeting returned correctly" in call[2] for call in provider.calls)


def test_provider_cannot_rewrite_own_evidence_journal(documentation_project):
    runner, provider, paths = documentation_project()
    def script(*args):
        next(paths["evidence_root"].rglob("journal.json")).write_text("{}")
    provider.script = script
    result = runner.run(**paths)
    assert result.status == "blocked" and len(provider.calls) == 1


def test_tightened_budget_cannot_widen_after_reconstruction(documentation_project, monkeypatch):
    from harness.delivery_slice_journal import DeliverySliceJournal
    runner, provider, paths = documentation_project()
    original = DeliverySliceJournal.save
    def save(self, data):
        original(self, data)
        if len(data["records"]) == 1 and data["records"][0]["result"] is not None:
            raise ProcessLost()
    monkeypatch.setattr(DeliverySliceJournal, "save", save)
    with pytest.raises(ProcessLost): runner.run(**paths, token_budget=100)
    monkeypatch.setattr(DeliverySliceJournal, "save", original)
    tightened = runner.run(**paths, token_budget=7, journal_required=True)
    assert tightened.status == "blocked"
    assert runner.run(**paths, token_budget=100, journal_required=True).status == "blocked"
    assert len(provider.calls) == 1


@pytest.mark.parametrize("fault", ["receipt_order", "duplicate_dispatch", "negative_usage", "publication", "extra", "report_schema"])
def test_corrupt_journal_cannot_publish_or_dispatch(documentation_project, fault):
    runner, provider, paths = documentation_project()
    assert runner.run(**paths).succeeded
    journal = next(paths["evidence_root"].rglob("journal.json"))
    data = json.loads(journal.read_text())
    if fault == "receipt_order": data["records"].reverse()
    if fault == "duplicate_dispatch": data["records"][1]["assignment"]["dispatch_id"] = data["records"][0]["assignment"]["dispatch_id"]
    if fault == "negative_usage": data["records"][0]["token_usage"] = -1
    if fault == "publication": data["publication"]["after"]["docs-verification-report.md"] = "forged"
    if fault == "extra": data["extra"] = "untrusted"
    if fault == "report_schema": data["records"][0]["result"]["report_markdown"] = IMPACT.replace("schema_version: 2", "schema_version: true")
    journal.write_text(json.dumps(data))
    assert runner.run(**paths, journal_required=True).status == "blocked"
    assert len(provider.calls) == 2


@pytest.mark.parametrize("fault", ["missing", "stale", "unsafe_output", "unsupported"])
def test_additional_preflight_blocks_without_dispatch(documentation_project, tmp_path, fault):
    from tests.unit.test_runnability_evidence import _write_report
    runner, provider, paths = documentation_project()
    if fault == "missing": (paths["worktree"] / ".echelon/prosaic/subagents/echelon.delivery-docs-verifier.md").unlink()
    if fault == "stale": paths["runnability_report"] = _write_report(tmp_path / "stale-runnability")
    if fault == "unsafe_output": (paths["spec_dir"] / "docs-verification-report.md").symlink_to(paths["worktree"] / "app.py")
    if fault == "unsupported": provider.supports_read_only_review = False
    result = runner.run(**paths)
    assert result.status == "blocked" and provider.calls == []


def test_lost_return_after_provider_entry_remains_unknown(documentation_project, monkeypatch):
    from harness.delivery_slice_journal import DeliverySliceJournal
    runner, provider, paths = documentation_project()
    original = DeliverySliceJournal.save
    def save(self, data):
        if data["records"] and data["records"][-1]["result"] is not None:
            raise ProcessLost()
        original(self, data)
    monkeypatch.setattr(DeliverySliceJournal, "save", save)
    with pytest.raises(ProcessLost): runner.run(**paths)
    result = runner.run(**paths, journal_required=True)
    assert result.status == "blocked" and "unknown" in result.reason
    assert len(provider.calls) == 1 and result.token_usage is None


def test_canonical_before_images_preserve_exact_line_endings(documentation_project):
    runner, provider, paths = documentation_project()
    (paths["spec_dir"] / "docs-verification-report.md").write_bytes(b"old report\r\n")
    result = runner.run(**paths)
    assert result.succeeded, result.reason
    journal = json.loads(next(paths["evidence_root"].rglob("journal.json")).read_text())
    assert journal["reports_before"]["docs-verification-report.md"] == "old report\r\n"


@pytest.mark.parametrize("fault", ["boolean_count", "string_flag", "duplicate_yaml", "no_evidence"])
def test_report_frontmatter_requires_exact_types(documentation_project, fault):
    def script(assignment, payload, root):
        if assignment["step"] != "docs_verifier": return
        text = review_report()
        if fault == "boolean_count": text = text.replace("evidence_items_checked: 4", "evidence_items_checked: true")
        if fault == "string_flag": text = text.replace("project_evidence_checked: true", 'project_evidence_checked: "true"')
        if fault == "duplicate_yaml": text = text.replace("verdict: PASS", "verdict: FAIL\nverdict: PASS")
        if fault == "no_evidence": text = text.replace("evidence_items_checked: 4", "evidence_items_checked: 0")
        payload["report_markdown"] = text
    runner, provider, paths = documentation_project(script=script)
    result = runner.run(**paths)
    assert result.status == "blocked" and len(provider.calls) == 2


@pytest.mark.parametrize("document", ["README.md", "CHANGELOG.md"])
def test_ignored_document_mutation_during_review_blocks(documentation_project, document):
    def script(assignment, payload, root):
        if assignment["step"] == "docs_verifier":
            (root / document).write_text("Unreviewed document mutation\n")
    runner, provider, paths = documentation_project(script=script)
    subprocess.run(["git", "init", "--quiet", str(paths["worktree"])], check=True)
    (paths["worktree"] / ".gitignore").write_text("README.md\nCHANGELOG.md\n")
    result = runner.run(**paths)
    assert result.status == "blocked", result.reason
    assert len(provider.calls) == 2
    assert not (paths["spec_dir"] / "docs-verification-report.md").exists()


@pytest.mark.parametrize("document", ["README.md", "CHANGELOG.md"])
def test_changed_ignored_document_cannot_reuse_completed_review(documentation_project, document):
    runner, provider, paths = documentation_project()
    subprocess.run(["git", "init", "--quiet", str(paths["worktree"])], check=True)
    (paths["worktree"] / ".gitignore").write_text("README.md\nCHANGELOG.md\n")
    assert runner.run(**paths).succeeded
    (paths["worktree"] / document).write_text("Changed after accepted review\n")
    result = type(runner)(provider, runner._project_dir).run(**paths, journal_required=True)
    assert result.status == "blocked", result.reason
    assert "candidate changed" in result.reason
    assert len(provider.calls) == 2 and result.token_usage == 14


def test_scope_exceeding_fifty_tasks_is_documented_and_replayed(documentation_project):
    task_ids = [f"T-{number:03d}" for number in range(1, 52)]
    def script(assignment, payload, root):
        metadata = yaml.safe_load(payload["report_markdown"].split("---", 2)[1])
        if assignment["step"] == "tech_writer":
            metadata["delivery_change_ids"] = task_ids
            entry = metadata["documented_changes"][0]
            metadata["documented_changes"] = [{**entry, "change_id": task_id} for task_id in task_ids]
        else:
            metadata["reviewed_change_ids"] = task_ids
        payload["report_markdown"] = "---\n" + yaml.safe_dump(metadata) + "---\n# Documentation report\n"
    runner, provider, paths = documentation_project(script=script)
    (paths["spec_dir"] / "tasks.md").write_text("".join(
        f"- [ ] {task_id} complexity=standard phase=build req=FR-1 depends=none\n" for task_id in task_ids))
    paths["allowed_task_ids"] = set(task_ids)
    result = runner.run(**paths)
    assert result.succeeded, result.reason
    assert result.task_ids == [] and result.token_usage == 14
    assert all(assignment["task_ids"] == task_ids for assignment, _, _ in provider.calls)
    replay = type(runner)(provider, runner._project_dir).run(**paths, journal_required=True)
    assert replay.succeeded and replay.token_usage == 14
    assert len(provider.calls) == 2
