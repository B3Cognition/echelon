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
            PatternCheck("build references commander.md", build, r"commander\.md"),
            PatternCheck("commander contains Evidence Hierarchy", commander, r"Evidence Hierarchy"),
            PatternCheck("commander contains EVOI", commander, r"EVOI"),
            PatternCheck("commander contains Toulmin", commander, r"Toulmin"),
            PatternCheck("finalize contains Convergence Rules", finalize, r"Convergence Rules"),
            PatternCheck("commander contains Meta-Cognition", commander, r"Meta-Cognition"),
            PatternCheck("why2 contains token budget stop condition", why2, r"token_budget_k|token_budget_exhausted"),
            PatternCheck("run mentions COMMANDER judgment role", run, r"COMMANDER"),
            PatternCheck("build references commander path", build, r"agents/control/commander\.md"),
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
            PatternCheck("commander references guardian mode", commander, r"guardian.mode"),
            PatternCheck("phase defines always_on", phase, r"always_on"),
            PatternCheck("phase defines on_demand", phase, r"on_demand"),
            PatternCheck("phase has security dispatch section", phase, r"SECURITY Dispatch"),
            PatternCheck("phase references security checklist", phase, r"Minimum Security Checklist"),
            PatternCheck("phase references guardian.mode", phase, r"guardian\.mode"),
            PatternCheck("guardian references always_on", guardian, r"always_on"),
            PatternCheck("guardian has security checklist", guardian, r"Minimum Security Checklist"),
            PatternCheck("guardian references guardian.mode", guardian, r"guardian\.mode"),
            PatternCheck("guardian handles non-security domains", guardian, r"non-security domain"),
            PatternCheck("phase references GUARDIAN", phase, r"GUARDIAN"),
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
