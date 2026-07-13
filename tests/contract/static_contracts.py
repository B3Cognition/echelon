from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PatternCheck:
    label: str
    path: Path
    pattern: str
    flags: int = 0
    should_match: bool = True


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _has(path: Path, pattern: str, flags: int = 0) -> bool:
    return re.search(pattern, _text(path), flags) is not None


def _run_checks(checks: list[PatternCheck]) -> list[str]:
    failures: list[str] = []
    for check in checks:
        matched = _has(check.path, check.pattern, check.flags)
        if matched != check.should_match:
            expectation = "match" if check.should_match else "not match"
            failures.append(
                f"{check.label}: expected {expectation} {check.pattern!r} "
                f"in {check.path}"
            )
    return failures


def _section_between(text: str, start: str, end: str) -> str:
    start_match = re.search(start, text, re.MULTILINE)
    if not start_match:
        return ""
    end_match = re.search(end, text[start_match.end() :], re.MULTILINE)
    if not end_match:
        return text[start_match.end() :]
    return text[start_match.end() : start_match.end() + end_match.start()]


def validate_commander_loading_contract(root: Path) -> list[str]:
    run = root / "extension/commands/echelon.run.md"
    build = root / "extension/commands/echelon.build.md"
    commander = root / "extension/agents/control/commander.md"
    finalize = root / "extension/workflow/phases/build-8-finalize.md"
    why2 = root / "extension/workflow/phases/phase1-why2.md"
    return _run_checks(
        [
            PatternCheck("run delegates to Python squad harness", run, r"squad.py|squad harness"),
            PatternCheck("build avoids commander.md", build, r"commander\.md", should_match=False),
            PatternCheck("commander contains Evidence Hierarchy", commander, r"Evidence Hierarchy"),
            PatternCheck("commander contains EVOI", commander, r"EVOI"),
            PatternCheck("commander contains Toulmin", commander, r"Toulmin"),
            PatternCheck("finalize contains Convergence Rules", finalize, r"Convergence Rules"),
            PatternCheck("commander contains Meta-Cognition", commander, r"Meta-Cognition"),
            PatternCheck("why2 contains token budget stop condition", why2, r"token_budget_k|token_budget_exhausted"),
            PatternCheck("run mentions COMMANDER judgment role", run, r"COMMANDER"),
            PatternCheck(
                "build avoids workflow definition routing",
                build,
                r"workflow/definition\.yaml",
                should_match=False,
            ),
            PatternCheck("commander has no SCIENTIST references", commander, r"SCIENTIST", should_match=False),
            PatternCheck("commander uses INVESTIGATOR", commander, r"INVESTIGATOR"),
        ]
    )


def validate_commander_routing_mandate_contract(root: Path) -> list[str]:
    commander = root / "extension/agents/control/commander.md"
    journal_types = root / "extension/workflow/journal-entry-types.yaml"
    why2 = root / "extension/workflow/phases/phase1-why2.md"
    accessors = root / "src/kernel/accessors.py"
    flags = re.IGNORECASE
    return _run_checks(
        [
            PatternCheck("routing_decision entry", journal_types, r"routing_decision", flags),
            PatternCheck("from_phase in journal type", journal_types, r"from_phase", flags),
            PatternCheck("evoi_score in journal type", journal_types, r"evoi_score", flags),
            PatternCheck("from_phase required field", journal_types, r"required_data_fields.*from_phase|from_phase.*to_phase", flags),
            PatternCheck("to_phase required field", journal_types, r"required_data_fields.*to_phase|from_phase.*to_phase", flags),
            PatternCheck("reason required field", journal_types, r"required_data_fields.*reason|from_phase.*reason", flags),
            PatternCheck("evoi_score required field", journal_types, r"required_data_fields.*evoi_score|reason.*evoi_score", flags),
            PatternCheck("quality_scores NEVER rule", commander, r"NEVER write.*quality_scores", flags),
            PatternCheck("understanding validation reference", why2, r"understanding\.validate|understanding-validate", flags),
            PatternCheck("pass_counter normalization", accessors, r"pass_counter", flags),
        ]
    )


def validate_guardian_always_on_contract(root: Path) -> list[str]:
    commander = root / "extension/agents/control/commander.md"
    guardian = root / "extension/agents/specialists/guardian.md"
    phase = root / "extension/workflow/phases/phase3-specialists.md"
    return _run_checks(
        [
            PatternCheck("commander references guardian mode", commander, r"specialists\.guardian_mode"),
            PatternCheck("phase defines always_on", phase, r"always_on"),
            PatternCheck("phase defines on_demand", phase, r"on_demand"),
            PatternCheck("phase has security dispatch section", phase, r"SECURITY Dispatch"),
            PatternCheck("phase references security checklist", phase, r"Minimum Security Checklist"),
            PatternCheck("phase references specialists.guardian_mode", phase, r"specialists\.guardian_mode"),
            PatternCheck("guardian references always_on", guardian, r"always_on"),
            PatternCheck("guardian has security checklist", guardian, r"Minimum Security Checklist"),
            PatternCheck("guardian references specialists.guardian_mode", guardian, r"specialists\.guardian_mode"),
            PatternCheck("guardian handles non-security domains", guardian, r"non-security domain"),
            PatternCheck("phase references GUARDIAN", phase, r"GUARDIAN"),
        ]
    )


def validate_guardian_mode_config_naming_contract(root: Path) -> list[str]:
    public_sources = [
        root / "README.md",
        root / "extension/workflow/phases/phase3-specialists.md",
        root / "extension/agents/specialists/guardian.md",
        root / "extension/agents/control/commander.md",
    ]
    failures = _run_checks(
        [
            *[
                PatternCheck(
                    f"{path.name} uses canonical specialists.guardian_mode",
                    path,
                    r"specialists\.guardian_mode",
                )
                for path in public_sources
            ],
            *[
                PatternCheck(
                    f"{path.name} avoids deprecated guardian.mode",
                    path,
                    r"guardian\.mode",
                    should_match=False,
                )
                for path in public_sources
            ],
            PatternCheck(
                "config template keeps nested guardian_mode",
                root / "extension/config-template.yml",
                r"specialists:[\s\S]*guardian_mode:\s*always_on",
            ),
            PatternCheck(
                "extension config keeps nested guardian_mode",
                root / "extension/echelon-config.yml",
                r"specialists:[\s\S]*guardian_mode:\s*always_on",
            ),
        ]
    )
    return failures


def validate_lexicon_derived_spec_contract(root: Path) -> list[str]:
    """Lexicon must not replace the canonical rich spec.md artifact."""

    config = root / "extension/echelon-config.yml"
    config_template = root / "extension/config-template.yml"
    cartographer = root / "extension/agents/exploration/cartographer.md"
    phase1_what = root / "extension/workflow/phases/phase1-what.md"
    orchestrator = root / "extension/agents/solution/orchestrator.md"
    pipeline_matrix = root / "docs/pipeline-matrix.md"
    flags = re.IGNORECASE

    checks = [
        PatternCheck(
            "extension config routes Lexicon spec to derived artifact",
            config,
            r"requirements\.lexicon\.md",
        ),
        PatternCheck(
            "config template documents derived Lexicon artifact",
            config_template,
            r"requirements\.lexicon\.md",
        ),
        PatternCheck(
            "CARTOGRAPHER preserves rich spec.md",
            cartographer,
            r"spec\.md.*rich|rich.*spec\.md",
            flags,
        ),
        PatternCheck(
            "CARTOGRAPHER authors derived Lexicon artifact",
            cartographer,
            r"requirements\.lexicon\.md",
        ),
        PatternCheck(
            "CARTOGRAPHER validates derived Lexicon artifact against source_ref",
            cartographer,
            r"--source-ref\s+\"\{spec_dir\}/\{source_ref\}\"",
        ),
        PatternCheck(
            "CARTOGRAPHER requires source hash metadata",
            cartographer,
            r"SOURCE_SHA256",
        ),
        PatternCheck(
            "CARTOGRAPHER no longer says Lexicon authors spec.md",
            cartographer,
            r"Author `spec\.md` as an `ARTIFACT: SPEC`",
            should_match=False,
        ),
        PatternCheck(
            "phase1 what names derived Lexicon artifact",
            phase1_what,
            r"requirements\.lexicon\.md",
        ),
        PatternCheck(
            "phase1 what no longer instructs emitting spec.md in Lexicon grammar",
            phase1_what,
            r"Emit\s+the\s+spec\s+in\s+the\s+Lexicon\s+grammar",
            flags,
            should_match=False,
        ),
        PatternCheck(
            "ORCHESTRATOR validates tasks against configured spec_ref",
            orchestrator,
            r"--spec-ref\s+\"\{spec_dir\}/\$\{?spec_ref\}?",
        ),
        PatternCheck(
            "ORCHESTRATOR does not hardcode tasks gate spec_ref to spec.md",
            orchestrator,
            r"--spec-ref\s+\"\{spec_dir\}/spec\.md\"",
            should_match=False,
        ),
        PatternCheck(
            "phase3 plan prose includes canonical spec context",
            root / "extension/workflow/phases/phase3-plan.md",
            r"spec\.md",
        ),
        PatternCheck(
            "pipeline matrix documents rich spec as canonical",
            pipeline_matrix,
            r"`spec\.md`.*canonical|canonical.*`spec\.md`",
            flags,
        ),
    ]
    return _run_checks(checks)


def validate_cartographer_tool_usage_contract(root: Path) -> list[str]:
    """CARTOGRAPHER must know the deterministic validation command surfaces."""

    cartographer = root / "extension/agents/exploration/cartographer.md"
    phase1_what = root / "extension/workflow/phases/phase1-what.md"
    flags = re.IGNORECASE

    return _run_checks(
        [
            PatternCheck(
                "CARTOGRAPHER documents Understanding scan command",
                cartographer,
                r"understanding scan .*--enhanced .*--per-req .*--json .*--output",
            ),
            PatternCheck(
                "CARTOGRAPHER forbids understanding validate subcommand guesses",
                cartographer,
                r"NEVER run `understanding validate`",
            ),
            PatternCheck(
                "CARTOGRAPHER documents JSON output discipline",
                cartographer,
                r"--output /tmp/.*\.json",
            ),
            PatternCheck(
                "CARTOGRAPHER documents Lexicon source-ref command",
                cartographer,
                r"lexicon validate .*--source-ref",
            ),
            PatternCheck(
                "phase1 what passes validation tool contract",
                phase1_what,
                r"Validation Tool Contract",
                flags,
            ),
            PatternCheck(
                "phase1 what names understanding scan",
                phase1_what,
                r"understanding scan",
            ),
        ]
    )


def validate_sage_understanding_followup_contract(root: Path) -> list[str]:
    """SAGE must use the documented Understanding JSON shape for handoff extraction."""

    sage = root / "extension/agents/exploration/sage.md"
    appendix = root / "extension/agents/exploration/appendices/sage-understanding-followup-reference.md"

    return _run_checks(
        [
            PatternCheck(
                "SAGE appendix documents indexed behavioral transition path",
                appendix,
                r"\.\[0\]\.behavioral_analysis\.transitions",
            ),
            PatternCheck(
                "SAGE appendix uses empty-list transition fallback",
                appendix,
                r"behavioral_analysis\.transitions\s*//\s*\[\]",
            ),
            PatternCheck(
                "SAGE appendix uses null-safe transition cell fallback",
                appendix,
                r"//\s*\"-\"",
            ),
            PatternCheck(
                "SAGE prompt references indexed behavioral transition path",
                sage,
                r"\.\[0\]\.behavioral_analysis\.transitions",
            ),
            PatternCheck(
                "SAGE prompt forbids top-level behavioral_analysis reads",
                sage,
                r"NEVER read `behavioral_analysis` as a top-level object",
            ),
        ]
    )


def validate_code_reviewer_confidence_filter_contract(root: Path) -> list[str]:
    target = root / "extension/agents/build/code-reviewer.md"
    flags = re.IGNORECASE | re.MULTILINE
    return _run_checks(
        [
            PatternCheck("80% threshold", target, r">80%|80.*confidence|confidence.*80", flags),
            PatternCheck("confidence_threshold config key", target, r"confidence_threshold", flags),
            PatternCheck("default 80", target, r"default.*80|default:.*80", flags),
            PatternCheck("consolidation section", target, r"consolidation rules", flags),
            PatternCheck("group similar issues", target, r"group similar issues", flags),
            PatternCheck("consolidated example", target, r"5 functions missing error handling", flags),
            PatternCheck("consolidation criteria", target, r"same category.*same severity|same severity.*same root cause", flags),
            PatternCheck("approved verdict condition", target, r"no critical.*high.*approved|approved.*no critical", flags),
            PatternCheck("changes requested condition", target, r"high.*changes_requested|changes_requested.*high", flags),
            PatternCheck("blocked condition", target, r"critical.*blocked|blocked.*critical", flags),
            PatternCheck("blocked trigger security", target, r"security", flags),
            PatternCheck("blocked trigger data loss", target, r"data loss", flags),
            PatternCheck("blocked trigger spec violation", target, r"spec violation", flags),
            PatternCheck("stylistic suppression", target, r"suppress stylistic preferences", flags),
            PatternCheck("ADR exception", target, r"violate.*adr|adr.*violat", flags),
            PatternCheck("confidence field", target, r"confidence.*percentage|confidence.*0.*100", flags),
            PatternCheck("severity field", target, r"critical.*high.*medium", flags),
            PatternCheck("file_line field", target, r"file_line|file.*line.*number", flags),
            PatternCheck("suggested_fix field", target, r"suggested_fix", flags),
            PatternCheck("summary table section", target, r"summary table", flags),
            PatternCheck("summary table columns", target, r"severity.*count.*status", flags),
        ]
    )


def validate_commander_token_tracking_contract(root: Path) -> list[str]:
    observable = root / "src/hormone_calc/observable.py"
    progress = root / "extension/agents/build/progress-tracker.md"
    token_logger = root / "extension/scripts/token-logger.py"
    config = root / "extension/config-template.yml"
    cli = root / "src/echelon/cli.py"
    journal_types = root / "extension/workflow/journal-entry-types.yaml"
    commander = root / "extension/agents/control/commander.md"
    return _run_checks(
        [
            PatternCheck("token_ledger in observable", observable, r"token_ledger"),
            PatternCheck("dispatch_id in observable", observable, r"dispatch_id"),
            PatternCheck("total_estimated_tokens in observable", observable, r"total_estimated_tokens"),
            PatternCheck("agent_codename in token logger", token_logger, r"agent_codename"),
            PatternCheck("estimated_tokens in progress tracker", progress, r"estimated_tokens"),
            PatternCheck("per_agent in token logger", token_logger, r"per_agent"),
            PatternCheck("per_phase in config template", config, r"per_phase"),
            PatternCheck("token_budget_k config key", cli, r"analysis\.token_budget_k|token_budget_k"),
            PatternCheck("commander avoids old budget key", commander, r"budget\.total_tokens", should_match=False),
            PatternCheck("budget_exhausted journal signal", journal_types, r"budget_exhausted"),
        ]
    )


def validate_implementer_eval_protocol_contract(root: Path) -> list[str]:
    implementer = root / "extension/agents/build/implementer.md"
    return _run_checks(
        [
            PatternCheck("capability eval", implementer, r"capability eval", re.IGNORECASE),
            PatternCheck("regression eval", implementer, r"regression eval", re.IGNORECASE),
            PatternCheck("pass@1", implementer, r"pass@1", re.IGNORECASE),
            PatternCheck("pass@3", implementer, r"pass@3", re.IGNORECASE),
            PatternCheck("unstable implementation", implementer, r"unstable implementation", re.IGNORECASE),
        ]
    )


def validate_sentinel_flakiness_contract(root: Path) -> list[str]:
    sentinel = root / "extension/agents/solution/sentinel.md"
    return _run_checks(
        [
            PatternCheck("Flakiness Management heading", sentinel, r"Flakiness Management"),
            PatternCheck("Detection Protocol", sentinel, r"Detection Protocol"),
            PatternCheck("Quarantine Process", sentinel, r"Quarantine Process"),
            PatternCheck("Root Cause Taxonomy", sentinel, r"Root Cause Taxonomy"),
            PatternCheck("Stability Targets", sentinel, r"Stability Targets"),
            PatternCheck("Review Cadence", sentinel, r"Review Cadence"),
        ]
    )


def validate_sage_contradiction_types_contract(root: Path) -> list[str]:
    appendix = root / "extension/agents/exploration/appendices/sage-contradiction-detection-reference.md"
    sage = root / "extension/agents/exploration/sage.md"
    flags = re.IGNORECASE | re.MULTILINE
    return _run_checks(
        [
            PatternCheck("requirement_conflict", appendix, r"requirement_conflict", flags),
            PatternCheck("assumption_requirement_misalignment", appendix, r"assumption_requirement_misalignment", flags),
            PatternCheck("boundary_violation", appendix, r"boundary_violation", flags),
            PatternCheck("priority_inversion", appendix, r"priority_inversion", flags),
            PatternCheck("acceptance_criteria_conflict", appendix, r"acceptance_criteria_conflict", flags),
            PatternCheck("contradiction_type field", appendix, r"contradiction_type", flags),
            PatternCheck("artifact_a field", appendix, r"artifact_a", flags),
            PatternCheck("artifact_b field", appendix, r"artifact_b", flags),
            PatternCheck("description field", appendix, r"description", flags),
            PatternCheck("severity field", appendix, r"severity", flags),
            PatternCheck("suggested_resolution field", appendix, r"suggested_resolution", flags),
            PatternCheck("BLOCKING severity", appendix, r"BLOCKING", flags),
            PatternCheck("WARNING severity", appendix, r"WARNING", flags),
            PatternCheck("zero contradiction message", appendix, r"No contradictions detected across", flags),
            PatternCheck("logging requirement", appendix, r"log.*contradiction check was performed|Always log that the contradiction check", flags),
            PatternCheck("sage section header", sage, r"Systematic Contradiction Detection", flags),
            PatternCheck("appendix title", appendix, r"SAGE Contradiction Detection Reference|Contradiction Detection", flags),
        ]
    )


def validate_sage_decisions_schema_contract(root: Path) -> list[str]:
    path = root / "knowledge-base/sage-decisions.yaml"
    if not path.exists():
        return [f"sage decisions file missing: {path}"]
    text = _text(path)
    failures = _run_checks(
        [
            PatternCheck("schema_version is 2", path, r"^schema_version:\s*2\s*$", re.MULTILINE),
            PatternCheck("append_only is true", path, r"^append_only:\s*true\s*$", re.MULTILINE),
            PatternCheck("max_entries is 100", path, r"^max_entries:\s*100\s*$", re.MULTILINE),
            PatternCheck("entries key exists", path, r"^entries:", re.MULTILINE),
        ]
    )
    entries_line = next((line for line in text.splitlines() if line.startswith("entries:")), "")
    if "[]" not in entries_line and not re.search(r"^entries:\n(?:\s*\n)*\s*-", text, re.MULTILINE):
        failures.append("entries must be an array ([] or list of - items)")

    expected_keys = {"schema_version", "append_only", "max_entries", "entries"}
    for line in text.splitlines():
        if not line or line.startswith("#") or line[0].isspace() or line.startswith("-"):
            continue
        key = line.split(":", 1)[0]
        if key not in expected_keys:
            failures.append(f"unexpected top-level key: {key}")
    return failures


def validate_veteran_project_scoping_contract(root: Path) -> list[str]:
    kb = root / "knowledge-base"
    schema = kb / "kb-schema.md"
    patterns = kb / "patterns.yaml"
    pitfalls = kb / "pitfalls.yaml"
    veteran = root / "extension/agents/learning/veteran.md"
    mirror = root / "extension/agents/learning/mirror.md"
    failures = _run_checks(
        [
            PatternCheck("schema documents project_fingerprint", schema, r"project_fingerprint"),
            PatternCheck("schema documents scope enum", schema, r"local_only", 0),
            PatternCheck("schema documents global scope", schema, r"global", 0),
            PatternCheck("schema documents SHA-256", schema, r"SHA-256"),
            PatternCheck("schema documents 12 char truncation", schema, r"12"),
            PatternCheck("veteran prompt exists", veteran, r".*"),
            PatternCheck("mirror references project_fingerprint", mirror, r"project_fingerprint"),
            PatternCheck("mirror computes with shasum", mirror, r"shasum -a 256"),
        ]
    )
    if not veteran.exists():
        failures.append(f"veteran.md missing: {veteran}")

    schema_text = _text(schema)
    patterns_section = _section_between(schema_text, r"^## patterns\.yaml", r"^## pitfalls\.yaml")
    pitfalls_section = _section_between(schema_text, r"^## pitfalls\.yaml", r"^## agent-scores\.yaml")
    if "project_fingerprint" not in patterns_section or "project_fingerprint" not in pitfalls_section:
        failures.append("project_fingerprint not documented in both patterns and pitfalls sections")

    pattern_text = _text(patterns)
    pitfall_text = _text(pitfalls)
    pattern_entries = re.findall(r"^\s*-\s+id:\s*PAT-", pattern_text, re.MULTILINE)
    pitfall_entries = re.findall(r"^\s*-\s+id:\s*PIT-", pitfall_text, re.MULTILINE)
    pattern_fingerprints = re.findall(r"project_fingerprint:", pattern_text)
    pitfall_fingerprints = re.findall(r"project_fingerprint:", pitfall_text)
    pattern_scopes = re.findall(r"scope:", pattern_text)
    pitfall_scopes = re.findall(r"scope:", pitfall_text)
    if not pattern_entries or len(pattern_fingerprints) < len(pattern_entries):
        failures.append(f"patterns.yaml fingerprints: {len(pattern_fingerprints)} for {len(pattern_entries)} entries")
    if not pattern_entries or len(pattern_scopes) < len(pattern_entries):
        failures.append(f"patterns.yaml scopes: {len(pattern_scopes)} for {len(pattern_entries)} entries")
    if not pitfall_entries or len(pitfall_fingerprints) < len(pitfall_entries):
        failures.append(f"pitfalls.yaml fingerprints: {len(pitfall_fingerprints)} for {len(pitfall_entries)} entries")
    if not pitfall_entries or len(pitfall_scopes) < len(pitfall_entries):
        failures.append(f"pitfalls.yaml scopes: {len(pitfall_scopes)} for {len(pitfall_entries)} entries")
    invalid_scope_lines = [
        line
        for line in (pattern_text + "\n" + pitfall_text).splitlines()
        if "scope:" in line and "local_only" not in line and "global" not in line
    ]
    if invalid_scope_lines:
        failures.append(f"invalid scope values: {invalid_scope_lines}")
    return failures


def validate_re_source_ownership_contract(root: Path) -> list[str]:
    """RE extraction stages source-owned artifacts and workspace synthesis."""
    specifier = root / "extension/agents/re/specifier.md"
    verifier = root / "extension/agents/re/verifier.md"
    expander = root / "extension/agents/re/expander.md"
    validator = root / "extension/agents/re/validator.md"
    checklister = root / "extension/agents/re/checklister.md"
    constituter = root / "extension/agents/re/constituter.md"
    golddigger = root / "extension/agents/exploration/golddigger.md"
    preflight = root / "extension/workflow/phases/re-extract-0-preflight.md"
    finalize = root / "extension/scripts/bash/finalize-run.sh"
    planner = root / "extension/agents/re/planner.md"
    tasker = root / "extension/agents/re/tasker.md"
    retarget = root / "extension/workflow/phases/re-retarget-1-input.md"
    checks = [
        PatternCheck("specifier source overview", specifier, r"\$RE_OUTPUT_DIR/sources/\{source-id\}/overview\.md"),
        PatternCheck("specifier source spec", specifier, r"\$RE_OUTPUT_DIR/sources/\{source-id\}/specs/\{domain-id\}/spec\.md"),
        PatternCheck("specifier workspace contracts", specifier, r"\$RE_OUTPUT_DIR/workspace/contracts\.md"),
        PatternCheck("verifier source quality", verifier, r"\$RE_OUTPUT_DIR/quality/\{source-id\}/coverage-report\.md"),
        PatternCheck("expander source ownership", expander, r"\$RE_OUTPUT_DIR/sources/\{source-id\}/specs/\{domain-id\}/spec\.md"),
        PatternCheck("validator semantic quality", validator, r"semantic_quality_review"),
        PatternCheck("checklister source checklist", checklister, r"\$RE_OUTPUT_DIR/sources/\{source-id\}/specs/\{domain-id\}/checklist\.md"),
        PatternCheck("checklister workspace checklist", checklister, r"\$RE_OUTPUT_DIR/workspace/checklist\.md"),
        PatternCheck("constituter workspace strategy", constituter, r"\$RE_OUTPUT_DIR/workspace/strategy/constitution\.md"),
        PatternCheck("golddigger workspace mode", golddigger, r"Mode 1 - Workspace Reverse Engineering"),
        PatternCheck("golddigger no project-root overview", golddigger, r"specs/000-re-overview", should_match=False),
        PatternCheck("preflight initializes workspace mode", preflight, r"'mode': 'workspace'"),
        PatternCheck("preflight does not initialize single mode", preflight, r"'mode': 'single'", should_match=False),
        PatternCheck("preflight allows empty workspace", preflight, r"empty declared workspace is valid"),
        PatternCheck("finalize stages RE index", finalize, r"re/index\.json"),
        PatternCheck("finalize stages RE sources", finalize, r"re/sources"),
        PatternCheck("finalize stages RE workspace", finalize, r"re/workspace"),
        PatternCheck("finalize rejects RE runtime paths", finalize, r"cache\|staging\|locks"),
        PatternCheck("planner writes source-owned plan", planner, r"re/sources/\{source-id\}/specs/\{domain-id\}/plan\.md"),
        PatternCheck("tasker writes source-owned tasks", tasker, r"re/sources/\{source-id\}/specs/\{domain-id\}/tasks\.md"),
        PatternCheck("retarget edits workspace strategy", retarget, r"re/workspace/strategy/constitution\.md"),
        PatternCheck("planner avoids old overview", planner, r"specs/000-re-overview", should_match=False),
        PatternCheck("tasker avoids old overview", tasker, r"specs/000-re-overview", should_match=False),
    ]
    return _run_checks(checks)


def validate_auditor_internalizer_split_contract(root: Path) -> list[str]:
    auditor = root / "extension/agents/learning/auditor.md"
    internalizer = root / "extension/agents/learning/internalizer.md"
    extension_yml = root / "extension/extension.yml"
    endocrine = root / "extension/scripts/bash/endocrine.sh"
    phase4 = root / "extension/workflow/phases/phase4-document.md"
    failures: list[str] = []
    for path in [auditor, internalizer]:
        if not path.exists():
            failures.append(f"missing file: {path}")

    negative_keywords = [
        "I-01 requirement_coverage_rate",
        "I-05 numeric_contradiction_rate",
        "I-09 confidence_accuracy",
        "I-13 first_pass_acceptance",
        "Absorption Metrics",
        "int-Accuracy Metrics",
        "int-Calibration Metrics",
        "int-Transfer Metrics",
        "Int-Gate Evaluation",
        "Cold-Start Check",
        "Cross-Validation.*Goodhart",
        "Per-Agent Internalization Scoring",
        "internalization-log.yaml entries",
    ]
    for keyword in negative_keywords:
        if _has(auditor, keyword):
            failures.append(f"auditor.md still contains internalizer keyword: {keyword}")

    checks = [
        *[
            PatternCheck(f"auditor contains {keyword}", auditor, keyword)
            for keyword in [
                "Domain Accuracy",
                "Correction Factors",
                "Confidence Data",
                "calibration-profile.yaml",
                "Evolution Signal",
                "Calibration Dashboard",
            ]
        ],
        *[
            PatternCheck(f"internalizer contains {keyword}", internalizer, keyword)
            for keyword in [
                "I-01 requirement_coverage_rate",
                "I-05 numeric_contradiction_rate",
                "I-09 confidence_accuracy",
                "I-13 first_pass_acceptance",
                "Absorption Metrics",
                "int-Accuracy Metrics",
                "int-Calibration Metrics",
                "int-Transfer Metrics",
                "Int-Gate Evaluation",
                "Cold-Start Check",
                "Cross-Validation",
                "Per-Agent Internalization Scoring",
                "internalization-log.yaml",
            ]
        ],
        PatternCheck("internalizer never modifies calibration profile", internalizer, r"NEVER modify .?calibration-profile\.yaml"),
        PatternCheck("internalizer never modifies agent prompts", internalizer, r"NEVER modify agent prompts"),
        PatternCheck("internalizer registered", extension_yml, r"speckit\.echelon\.internalizer"),
        PatternCheck("internalizer in endocrine", endocrine, r"INTERNALIZER"),
        PatternCheck("phase4 references internalizer", phase4, r"INTERNALIZER"),
        PatternCheck("phase4 finalizes internalizer", phase4, r"INTERNALIZER.*FINALIZE|FINALIZE.*INTERNALIZER", re.DOTALL),
    ]
    failures.extend(_run_checks(checks))
    endocrine_text = _text(endocrine)
    if not re.search(r"MIRROR\|ADAPTIVE\|AUDITOR\|INTERNALIZER\|REALIST[\s\S]{0,120}learning", endocrine_text):
        failures.append("INTERNALIZER not mapped to learning archetype")
    return failures


def validate_auditor_internalization_contract(root: Path) -> list[str]:
    target = root / "extension/agents/learning/internalizer.md"
    appendix = root / "extension/agents/learning/appendices/internalizer-output-formats.md"
    flags = re.IGNORECASE | re.MULTILINE
    return _run_checks(
        [
            PatternCheck("internalization scoring section", target, r"^## Per-Agent Internalization Scoring", flags),
            PatternCheck("absorption category", target, r"Absorption.*I-01.*I-04|Absorption.*requirement_coverage.*dependency_awareness", flags),
            PatternCheck("accuracy category", target, r"Accuracy.*I-05.*I-08|Accuracy.*numeric_contradiction.*keyword_scope", flags),
            PatternCheck("calibration category", target, r"Calibration.*I-09.*I-12|Calibration.*confidence_accuracy.*escalation_precision", flags),
            PatternCheck("transfer category", target, r"Transfer.*I-13.*I-16|Transfer.*first_pass_acceptance.*priority_alignment", flags),
            PatternCheck("composite score", target, r"composite.score|composite_score", flags),
            PatternCheck("category weights", target, r"weight.*0\.(20|30)|Absorption weight.*0\.30", flags),
            PatternCheck("trend improving", target, r"improving.*composite.*mean", flags),
            PatternCheck("trend declining", target, r"declining.*composite.*mean", flags),
            PatternCheck("trend stable", target, r"stable.*within", flags),
            PatternCheck("insufficient data", target, r"insufficient_data|insufficient.data", flags),
            PatternCheck("agent-scores storage", target, r"agent-scores\.yaml", flags),
            PatternCheck("internalization output block", appendix, r"internalization:", flags),
            PatternCheck("category_scores block", appendix, r"category_scores:", flags),
            PatternCheck("metric_values block", appendix, r"metric_values:", flags),
            PatternCheck("history block", appendix, r"history:", flags),
            PatternCheck("null vs zero rule", target, r"null.*not.*0\.0|null.*not 0", flags),
            PatternCheck("history cap", target, r"capped at 20|oldest removed", flags),
            PatternCheck("KB write protocol", target, r"kb-write\.sh", flags),
        ]
    )


def validate_auditor_calibration_dashboard_contract(root: Path) -> list[str]:
    auditor = root / "extension/agents/learning/auditor.md"
    internalizer = root / "extension/agents/learning/internalizer.md"
    flags = re.IGNORECASE | re.MULTILINE
    failures = _run_checks(
        [
            PatternCheck("dashboard section", auditor, r"^## Calibration Dashboard Generation", flags),
            PatternCheck("domain overview", auditor, r"Domain Calibration Overview", flags),
            PatternCheck("agent internalization health", internalizer, r"Agent Internalization Health|internalization.*health|per-agent.*scoring", flags),
            PatternCheck("cross-validation flags", internalizer, r"Cross-Validation|CV-1|CV-2|CV-3", flags),
            PatternCheck("evolution signals", auditor, r"Evolution Signals", flags),
            PatternCheck("calibration health score", auditor, r"Calibration Health Score", flags),
            PatternCheck("health formula", auditor, r"calibration_health.*=.*domains_above_threshold|calibration_health", flags),
            PatternCheck("healthy threshold", auditor, r"HEALTHY.*0\.75|>= 0\.75", flags),
            PatternCheck("degraded threshold", auditor, r"DEGRADED.*0\.50|0\.50.*0\.74", flags),
            PatternCheck("critical threshold", auditor, r"CRITICAL.*< 0\.50|CRITICAL.*0\.50", flags),
            PatternCheck("generated during finalize", auditor, r"FINALIZE", flags),
            PatternCheck("commander dashboard request", auditor, r"COMMANDER.*request|COMMANDER.*dashboard", flags),
            PatternCheck("output path", auditor, r"calibration-dashboard\.md", flags),
            PatternCheck("high risk definition", auditor, r"HIGH.*accuracy.*< 0\.5|HIGH.*< 0\.5", flags),
            PatternCheck("medium risk definition", auditor, r"MEDIUM.*0\.5.*0\.75", flags),
            PatternCheck("low risk definition", auditor, r"LOW.*> 0\.75|LOW.*0\.75", flags),
        ]
    )
    return failures


def validate_state_schema_build_qa_split_contract(root: Path) -> list[str]:
    schema = root / "templates/state-schema.json"
    return _run_checks(
        [
            PatternCheck("build_done token", schema, r'"build_done"'),
            PatternCheck("build_init token", schema, r'"build_init"'),
            PatternCheck("build_loop token", schema, r'"build_loop"'),
            PatternCheck("BUILD_IN_PROGRESS token", schema, r'"BUILD_IN_PROGRESS"'),
            PatternCheck("QA_IN_PROGRESS token", schema, r'"QA_IN_PROGRESS"'),
            PatternCheck("QA_COMPLETE token", schema, r'"QA_COMPLETE"'),
            PatternCheck("CHANGE_PENDING token", schema, r'"CHANGE_PENDING"'),
        ]
    )


def validate_build_phase_constitution_preflight_contract(root: Path) -> list[str]:
    """Build prompts must consume only preflight-validated constitution snapshots."""

    build_init = root / "extension/workflow/phases/build-1-init.md"
    cli = root / "src/echelon/cli.py"
    flags = re.IGNORECASE | re.DOTALL

    return _run_checks(
        [
            PatternCheck(
                "build init forbids constitution copy recovery",
                build_init,
                r"Do not copy, synthesize, or repair `constitution\.md`",
            ),
            PatternCheck(
                "build init no longer copies constitution from memory",
                build_init,
                r"cp\s+.*\.specify/memory/constitution\.md",
                should_match=False,
            ),
            PatternCheck(
                "build init treats template constitution as hard stop",
                build_init,
                r"unresolved constitution template markers.*STOP",
                flags,
            ),
            PatternCheck(
                "harness run calls Phase A readiness preflight",
                cli,
                r"_block_if_harness_phase_a_not_ready",
            ),
            PatternCheck(
                "harness run preflight uses shared readiness validator",
                cli,
                r"validate_phase_a_readiness\(\{\"status\": \"done\"\}, \[spec_dir\]\)",
            ),
        ]
    )


def validate_constitution_source_of_truth_contract(root: Path) -> list[str]:
    """Constitution is canonical in spec-kit memory and published as read-only snapshots."""

    chief = root / "extension/agents/control/chief.md"
    phase1_what = root / "extension/workflow/phases/phase1-what.md"
    codegen_preamble = root / "extension/workflow/phases/codegen-A-preamble.md"
    phase3_how = root / "extension/workflow/phases/phase3-how.md"
    artifact_index = root / "src/echelon/artifact_index.py"
    finalize = root / "extension/scripts/bash/finalize-run.sh"
    journal_types = root / "extension/workflow/journal-entry-types.yaml"
    flags = re.IGNORECASE | re.DOTALL

    checks = [
        PatternCheck(
            "CHIEF forbids direct constitution edits",
            chief,
            r"NEVER write, edit, patch, or shell-substitute `constitution\.md` directly",
        ),
        PatternCheck(
            "CHIEF retries through speckit constitution",
            chief,
            r"Invoke `speckit\.constitution` again",
        ),
        PatternCheck(
            "CHIEF no longer uses sed fallback",
            chief,
            r"sed\s+-i.*constitution\.md",
            flags,
            should_match=False,
        ),
        PatternCheck(
            "CHIEF journal data uses skill retry",
            chief,
            r"skill_retry_used",
        ),
        PatternCheck(
            "CHIEF no longer emits placeholder_fix_applied",
            chief,
            r"placeholder_fix_applied",
            should_match=False,
        ),
        PatternCheck(
            "phase1 what routes placeholder constitution back to CHIEF",
            phase1_what,
            r"Return to `phase1-constitution`.*speckit-echelon-chief",
            flags,
        ),
        PatternCheck(
            "phase1 what forbids direct constitution edits",
            phase1_what,
            r"Do not edit, patch, or shell-substitute `\.specify/memory/constitution\.md`",
        ),
        PatternCheck(
            "phase1 what no longer records placeholder fix event",
            phase1_what,
            r"constitution_placeholder_fix|sed_fallback",
            should_match=False,
        ),
        PatternCheck(
            "codegen treats constitution as published snapshot",
            codegen_preamble,
            r"constitution\.md is a published Phase A snapshot",
        ),
        PatternCheck(
            "codegen no longer copies constitution from memory",
            codegen_preamble,
            r"cp\s+.*\.specify/memory/constitution\.md",
            flags,
            should_match=False,
        ),
        PatternCheck(
            "codegen rejects constitution template markers",
            codegen_preamble,
            r"constitution\.md contains unresolved template markers",
        ),
        PatternCheck(
            "phase3 how treats constitution as read-only",
            phase3_how,
            r"constitution\.md.*read-only published Phase A snapshot",
        ),
        PatternCheck(
            "phase3 how forbids constitution output",
            phase3_how,
            r"do not edit, rewrite, append to, or output `constitution\.md`",
        ),
        PatternCheck(
            "phase3 how uses amendment candidates",
            phase3_how,
            r"constitution-amendment-candidates\.md",
        ),
        PatternCheck(
            "phase3 how no longer lists constitution.md as output",
            phase3_how,
            r"\| `constitution\.md` \|",
            should_match=False,
        ),
        PatternCheck(
            "artifact index marks constitution owner as CHIEF",
            artifact_index,
            r'"constitution\.md",\s*"Constitution snapshot",\s*"Published read-only snapshot.*?"Phase A",\s*"CHIEF"',
            flags,
        ),
        PatternCheck(
            "finalize validates canonical constitution before publishing",
            finalize,
            r"grep -qE .*CONSTITUTION_VERSION.*CONSTITUTION_SRC",
            flags,
        ),
        PatternCheck(
            "finalize publishes snapshot from canonical memory",
            finalize,
            r"constitution\.md snapshot published from \.specify/memory",
        ),
        PatternCheck(
            "journal registry no longer allows COMMANDER placeholder fix",
            journal_types,
            r"constitution_placeholder_fix",
            should_match=False,
        ),
        PatternCheck(
            "journal registry uses skill retry field",
            journal_types,
            r"required_data_fields: \[mode, constitution_path, skill_retry_used\]",
        ),
    ]
    return _run_checks(checks)


def validate_constitution_context_pack_contract(root: Path) -> list[str]:
    """Spec and planning agents that must honor governance receive read-only constitution context."""

    workflow = root / "extension/workflow/definition.yaml"
    phase1_what = root / "extension/workflow/phases/phase1-what.md"
    phase3_plan = root / "extension/workflow/phases/phase3-plan.md"
    phase3_consensus = root / "extension/workflow/phases/phase3-consensus.md"
    architect = root / "extension/agents/solution/architect.md"
    flags = re.IGNORECASE | re.DOTALL

    checks = [
        PatternCheck(
            "workflow phase1-what includes canonical constitution memory",
            workflow,
            r"id:\s+phase1-what[\s\S]*?context_pack:[\s\S]*?\.specify/memory/constitution\.md",
        ),
        PatternCheck(
            "workflow phase3-plan includes constitution snapshot",
            workflow,
            r"id:\s+phase3-plan[\s\S]*?context_pack:[\s\S]*?- constitution\.md",
        ),
        PatternCheck(
            "workflow WHY3 includes constitution snapshot",
            workflow,
            r"id:\s+speckit-echelon-sage[\s\S]*?mode:\s+WHY3[\s\S]*?context_pack:[\s\S]*?- constitution\.md",
        ),
        PatternCheck(
            "workflow PLAN2 includes constitution snapshot",
            workflow,
            r"id:\s+speckit-echelon-orchestrator[\s\S]*?mode:\s+PLAN2[\s\S]*?context_pack:[\s\S]*?- constitution\.md",
        ),
        PatternCheck(
            "phase1 what prompt includes read-only constitution",
            phase1_what,
            r"read-only \.specify/memory/constitution\.md",
        ),
        PatternCheck(
            "phase1 what prompt forbids CARTOGRAPHER constitution mutation",
            phase1_what,
            r"do not edit, patch, append to, or regenerate the constitution",
            flags,
        ),
        PatternCheck(
            "phase3 plan prompt includes read-only constitution",
            phase3_plan,
            r"read-only constitution\.md",
        ),
        PatternCheck(
            "phase3 plan forbids ORCHESTRATOR constitution output",
            phase3_plan,
            r"Do not edit, rewrite, append to, or output `constitution\.md`",
        ),
        PatternCheck(
            "phase3 consensus WHY3 includes constitution",
            phase3_consensus,
            r"including the read-only constitution snapshot",
        ),
        PatternCheck(
            "phase3 consensus PLAN2 includes read-only constitution",
            phase3_consensus,
            r"PLAN2 Context Pack[\s\S]*?`constitution\.md` \(read-only published Phase A governance snapshot\)",
            flags,
        ),
        PatternCheck(
            "phase3 consensus PLAN2 forbids constitution mutation",
            phase3_consensus,
            r"Treat `constitution\.md` as read-only governance context\. Do not edit, rewrite, append to, or output `constitution\.md`",
        ),
        PatternCheck(
            "ARCHITECT consumes published constitution snapshot",
            architect,
            r"read-only `constitution\.md` snapshot",
        ),
        PatternCheck(
            "ARCHITECT forbids speckit constitution invocation",
            architect,
            r"NEVER invoke `speckit\.constitution`",
        ),
        PatternCheck(
            "ARCHITECT stale fallback removed",
            architect,
            r"USE\*\* `speckit\.constitution` if one doesn't exist|If constitution doesn't exist",
            flags,
            should_match=False,
        ),
        PatternCheck(
            "ARCHITECT outputs amendment candidates only",
            architect,
            r"constitution-amendment-candidates\.md",
        ),
    ]
    return _run_checks(checks)
