from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SUBAGENTS = ROOT / "prosaic" / "subagents"
COMMANDS = ROOT / "prosaic" / "commands"


SUBAGENT_POLICY = {
    "echelon.adaptive.md": ("balanced", "medium"),
    "echelon.advocate.md": ("balanced", "medium"),
    "echelon.architect.md": ("strong", "high"),
    "echelon.auditor.md": ("balanced", "high"),
    "echelon.benchmark.md": ("balanced", "high"),
    "echelon.cartographer.md": ("strong", "high"),
    "echelon.change-controller.md": ("strong", "high"),
    "echelon.checkpoint.md": ("balanced", "medium"),
    "echelon.chief.md": ("strong", "high"),
    "echelon.code-reviewer.md": ("strong", "high"),
    "echelon.commander.md": ("strong", "medium"),
    "echelon.consolidator.md": ("strong", "high"),
    "echelon.debugger.md": ("strong", "high"),
    "echelon.docs-verifier.md": ("balanced", "medium"),
    "echelon.engineering-manager.md": ("strong", "medium"),
    "echelon.gatekeeper.md": ("strong", "high"),
    "echelon.golddigger.md": ("balanced", "medium"),
    "echelon.guardian.md": ("strong", "high"),
    "echelon.implementation-mapper.md": ("balanced", "medium"),
    "echelon.implementer.md": ("strong", "high"),
    "echelon.integrator.md": ("strong", "medium"),
    "echelon.internalizer.md": ("balanced", "medium"),
    "echelon.investigator.md": ("strong", "high"),
    "echelon.lexicon-deriver.md": ("balanced", "medium"),
    "echelon.maverick.md": ("balanced", "high"),
    "echelon.mirror.md": ("balanced", "medium"),
    "echelon.modeler.md": ("balanced", "medium"),
    "echelon.monitor.md": ("fast", "low"),
    "echelon.oracle.md": ("strong", "high"),
    "echelon.orchestrator.md": ("strong", "high"),
    "echelon.progress-tracker.md": ("fast", "low"),
    "echelon.re-analyzer.md": ("balanced", "medium"),
    "echelon.re-baseliner.md": ("strong", "high"),
    "echelon.re-deepener.md": ("strong", "high"),
    "echelon.re-checklister.md": ("fast", "low"),
    "echelon.re-constituter.md": ("strong", "high"),
    "echelon.re-expander.md": ("strong", "high"),
    "echelon.re-planner.md": ("strong", "high"),
    "echelon.re-specifier.md": ("strong", "high"),
    "echelon.re-tasker.md": ("strong", "high"),
    "echelon.re-validator.md": ("strong", "high"),
    "echelon.re-verifier.md": ("balanced", "medium"),
    "echelon.realist.md": ("strong", "high"),
    "echelon.sage.md": ("strong", "high"),
    "echelon.scorekeeper.md": ("fast", "low"),
    "echelon.scout.md": ("balanced", "medium"),
    "echelon.sentinel.md": ("strong", "medium"),
    "echelon.summarizer.md": ("fast", "low"),
    "echelon.spec-fulfillment-auditor.md": ("balanced", "medium"),
    "echelon.spec-guard.md": ("strong", "medium"),
    "echelon.strategist.md": ("strong", "high"),
    "echelon.synthesizer.md": ("strong", "high"),
    "echelon.tech-writer.md": ("balanced", "medium"),
    "echelon.test-guardian.md": ("strong", "medium"),
    "echelon.tracker.md": ("balanced", "medium"),
    "echelon.validator.md": ("balanced", "medium"),
    "echelon.verification.md": ("strong", "high"),
    "echelon.veteran.md": ("strong", "high"),
    "echelon.visual-validator.md": ("balanced", "high"),
}

COMMAND_POLICY = {
    "echelon.bugfix.md": ("strong", "medium"),
    "echelon.build.md": ("strong", "high"),
    "echelon.change.md": ("strong", "high"),
    "echelon.cicd.md": ("fast", "low"),
    "echelon.codegen.md": ("strong", "high"),
    "echelon.codegenlight.md": ("strong", "high"),
    "echelon.deploy.md": ("balanced", "medium"),
    "echelon.feedback.md": ("balanced", "medium"),
    "echelon.ground.md": ("fast", "low"),
    "echelon.harness-init.md": ("balanced", "medium"),
    "echelon.harness-resume.md": ("fast", "low"),
    "echelon.harness-run.md": ("fast", "low"),
    "echelon.harness-status.md": ("fast", "low"),
    "echelon.health.md": ("balanced", "medium"),
    "echelon.init.md": ("balanced", "medium"),
    "echelon.innovate.md": ("fast", "low"),
    "echelon.investigate.md": ("fast", "low"),
    "echelon.re-analyze.md": ("fast", "low"),
    "echelon.re-checklist.md": ("fast", "low"),
    "echelon.re-constitute.md": ("fast", "low"),
    "echelon.re-expand.md": ("fast", "low"),
    "echelon.re-extract.md": ("balanced", "medium"),
    "echelon.re-plan-all.md": ("balanced", "medium"),
    "echelon.re-plan.md": ("fast", "low"),
    "echelon.re-retarget.md": ("balanced", "medium"),
    "echelon.re-specify.md": ("fast", "low"),
    "echelon.re-tasks.md": ("fast", "low"),
    "echelon.re-validate.md": ("fast", "low"),
    "echelon.re-verify.md": ("fast", "low"),
    "echelon.reopen.md": ("balanced", "medium"),
    "echelon.resume.md": ("fast", "low"),
    "echelon.review.md": ("strong", "medium"),
    "echelon.run.md": ("fast", "low"),
    "echelon.status.md": ("fast", "low"),
    "echelon.understanding-batch.md": ("fast", "low"),
    "echelon.understanding-diagram.md": ("fast", "low"),
    "echelon.understanding-energy.md": ("fast", "low"),
    "echelon.understanding-scan.md": ("fast", "low"),
    "echelon.understanding-validate.md": ("fast", "low"),
    "echelon.verify-spec.md": ("balanced", "medium"),
    "echelon.verify.md": ("strong", "high"),
}


def _frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name} has no YAML frontmatter"
    _start, raw, _body = text.split("---", 2)
    data = yaml.safe_load(raw)
    assert isinstance(data, dict), f"{path.name} frontmatter is not a mapping"
    return data


def test_all_subagents_declare_approved_model_tier_and_effort() -> None:
    discovered = {path.name for path in SUBAGENTS.glob("*.md")}
    assert discovered == set(SUBAGENT_POLICY)

    for filename, expected in SUBAGENT_POLICY.items():
        metadata = _frontmatter(SUBAGENTS / filename)
        assert (metadata.get("model_tier"), metadata.get("effort")) == expected


def test_all_commands_declare_approved_model_tier_and_effort() -> None:
    discovered = {path.name for path in COMMANDS.glob("*.md")}
    assert discovered == set(COMMAND_POLICY)

    for filename, expected in COMMAND_POLICY.items():
        metadata = _frontmatter(COMMANDS / filename)
        assert (metadata.get("model_tier"), metadata.get("effort")) == expected
