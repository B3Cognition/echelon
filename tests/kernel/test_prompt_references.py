from pathlib import Path
import re

from harness.journal_prompt_validator import validate_prompt_journal_examples
from harness.verdict_contract_validator import validate_verdict_contracts


REPO_ROOT = Path(__file__).resolve().parents[2]
EXTENSION_ROOT = REPO_ROOT / "extension"
PROMPT_ROOTS = [
    EXTENSION_ROOT / "agents",
    EXTENSION_ROOT / "commands",
    EXTENSION_ROOT / "workflow" / "phases",
]

REFERENCE_RE = re.compile(
    r"`((?:agents/(?:[^`]+/(?:templates|appendices)/[^`]+))|"
    r"(?:commands/appendices/[^`]+)|"
    r"(?:workflow/phases/appendices/[^`]+))`"
)

PROMPT_REFERENCE_RE = re.compile(
    r"(?:`|\(|\s|^)"
    r"("
    r"(?:\.specify/extensions/echelon/)?"
    r"(?:agents/|commands/|workflow/phases/|templates/|docs/)"
    r"[^`)\s,*]+"
    r"\.(?:md|yaml|yml)"
    r")"
)


def _resolve_prompt_reference(ref: str, prompt: Path) -> Path:
    if ref.startswith(".specify/extensions/echelon/"):
        return EXTENSION_ROOT / ref.removeprefix(".specify/extensions/echelon/")
    if (
        ref.startswith("agents/")
        or ref.startswith("commands/")
        or ref.startswith("workflow/phases/")
    ):
        return EXTENSION_ROOT / ref
    if ref.startswith("docs/"):
        return REPO_ROOT / ref
    if ref.startswith("templates/"):
        local = prompt.parent / ref
        if local.exists():
            return local
        return EXTENSION_ROOT / ref
    return prompt.parent / ref


def test_prompt_template_and_appendix_references_exist():
    missing = []

    for root in PROMPT_ROOTS:
        for prompt in root.rglob("*.md"):
            text = prompt.read_text()
            for match in REFERENCE_RE.finditer(text):
                rel_path = match.group(1)
                target = EXTENSION_ROOT / rel_path
                if not target.exists():
                    missing.append(
                        f"{prompt.relative_to(REPO_ROOT)} references missing {rel_path}"
                    )

    assert not missing, "\n".join(missing)


def test_prompt_template_docs_and_appendix_references_exist():
    missing = []

    for root in PROMPT_ROOTS:
        for prompt in root.rglob("*.md"):
            text = prompt.read_text()
            for match in PROMPT_REFERENCE_RE.finditer(text):
                rel_path = match.group(1)
                target = _resolve_prompt_reference(rel_path, prompt)
                if not target.exists():
                    missing.append(
                        f"{prompt.relative_to(REPO_ROOT)} references missing {rel_path}"
                    )

    assert not missing, "\n".join(missing)


def test_prompt_journal_entry_examples_match_canonical_schema():
    prompt_files = []
    for root in PROMPT_ROOTS:
        prompt_files.extend(root.rglob("*.md"))
    prompt_files.extend((EXTENSION_ROOT / "templates").rglob("*.yaml"))

    findings = validate_prompt_journal_examples(prompt_files)

    assert not findings, "\n".join(
        f"{finding.path.relative_to(REPO_ROOT)}:{finding.line}: "
        f"{finding.entry_type}: {finding.reason}: {finding.details}"
        for finding in findings
    )


def test_prompt_verdict_contracts_match_canonical_sources():
    findings = validate_verdict_contracts(REPO_ROOT)

    assert not findings, "\n".join(
        f"{finding.path.relative_to(REPO_ROOT)}:{finding.line}: "
        f"{finding.phase_id}: {finding.reason}: {finding.details}"
        for finding in findings
    )


def test_build_finalize_uses_appendices_for_large_reference_sections():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "build-8-finalize.md"
    text = prompt.read_text()

    assert "workflow/phases/appendices/build-8-verify-gates.md" in text
    assert "workflow/phases/appendices/build-8-summary-reference.md" in text
    assert "workflow/phases/appendices/build-8-feedback-reference.md" in text


def test_verify_spec_map_runs_deterministic_codegraph_evidence_map_first():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "verify-spec-4-map.md"
    text = prompt.read_text()

    assert "write-codegraph-evidence-map" in text
    assert "{verify_run_dir}/codegraph-evidence-map.json" in text
    assert "{verify_run_dir}/codegraph-evidence-map.md" in text
    assert "fallback_requirement_ids" in text
    assert "schema_version: 2" in text
    assert "Verified Implementation Evidence" in text
    assert "CodeGraph Candidates" in text
    assert "`Confidence` must be `high`, `medium`, `low`, or `none`" in text


def test_verify_spec_uses_python_owned_canonical_requirement_inventory():
    audit_phase = (EXTENSION_ROOT / "workflow" / "phases" / "verify-spec-3-audit.md").read_text()
    map_phase = (EXTENSION_ROOT / "workflow" / "phases" / "verify-spec-4-map.md").read_text()
    judge_phase = (EXTENSION_ROOT / "workflow" / "phases" / "verify-spec-5-judge.md").read_text()
    workflow = (EXTENSION_ROOT / "workflow" / "definition.yaml").read_text()
    auditor = (EXTENSION_ROOT / "agents" / "build" / "spec-fulfillment-auditor.md").read_text()
    mapper = (EXTENSION_ROOT / "agents" / "build" / "implementation-mapper.md").read_text()
    guard = (EXTENSION_ROOT / "agents" / "build" / "spec-guard.md").read_text()

    assert "write-canonical-requirements" in audit_phase
    assert "write-requirement-audit" in audit_phase
    assert "Do not dispatch SPEC-FULFILLMENT-AUDITOR" in audit_phase
    assert "id: verify-spec-3-audit" in workflow
    assert "type: commander_internal" in workflow
    for text in (audit_phase, map_phase, judge_phase, auditor, mapper, guard):
        assert "canonical-requirements.json" in text
    for text in (map_phase, judge_phase, mapper, guard):
        assert "unmapped_candidate" in text


def test_verify_spec_judge_requires_artifact_row_set_validation():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "verify-spec-5-judge.md"
    text = prompt.read_text()

    assert "requirement-audit.md" in text
    assert "fulfillment-report.md" in text
    assert "row-set integrity" in text
    assert "validate-fulfillment-artifacts" in text
    assert "Do not validate row sets by\nhand" in text
    assert "hard stop" in text.lower()
    assert "Do not render summary counts as a markdown table" in text
    assert "status labels in the first column" in text


def test_verify_spec_judge_documents_scoped_report_contract():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "verify-spec-5-judge.md"
    text = prompt.read_text()

    assert "When `verify_scope=scoped`" in text
    assert "judge only IDs listed in `scoped_ids`" in text
    assert "preserve unaffected rows" in text
    assert "base_full_verify_commit" in text


def test_build_command_forbids_hand_editing_verify_spec_reports():
    prompt = EXTENSION_ROOT / "commands" / "echelon.build.md"
    text = prompt.read_text()

    assert "fulfillment-report.md" in text
    assert "fulfillment-gaps.md" in text
    assert "NEVER hand-edit" in text
    assert "verify-spec-owned" in text


def test_implementation_mapper_respects_deterministic_codegraph_boundary():
    prompt = EXTENSION_ROOT / "agents" / "build" / "implementation-mapper.md"
    text = prompt.read_text()
    lowered = " ".join(text.lower().split())

    assert "{verify_run_dir}/codegraph-evidence-map.json" in text
    assert "preserve `codegraph_candidates`" in text
    assert "candidate leads with a disposition" in lowered
    assert "fallback_requirement_ids" in text
    assert "low`, `none`, or `ambiguous`" in text
    assert "never treat codegraph candidates as verified implementation or test evidence" in lowered


def test_sage_uses_appendix_for_decision_calibration_reference():
    prompt = EXTENSION_ROOT / "agents" / "exploration" / "sage.md"
    text = prompt.read_text()

    assert "agents/exploration/appendices/sage-decision-calibration-reference.md" in text


def test_sage_uses_appendix_for_understanding_followup_reference():
    prompt = EXTENSION_ROOT / "agents" / "exploration" / "sage.md"
    text = prompt.read_text()

    assert "agents/exploration/appendices/sage-understanding-followup-reference.md" in text


def test_sage_uses_appendix_for_contradiction_detection_reference():
    prompt = EXTENSION_ROOT / "agents" / "exploration" / "sage.md"
    text = prompt.read_text()

    assert "agents/exploration/appendices/sage-contradiction-detection-reference.md" in text


def test_cartographer_does_not_request_reverse_engineering_deep_dives():
    prompt = EXTENSION_ROOT / "agents" / "exploration" / "cartographer.md"
    text = prompt.read_text()

    assert "cartographer-golddigger-deep-dive-reference.md" not in text
    assert "Mode 2 Deep Dive Requests" not in text


def test_commands_use_jsonl_reasoning_journal_name():
    stale = []

    for prompt in (EXTENSION_ROOT / "commands").rglob("*.md"):
        for lineno, line in enumerate(prompt.read_text().splitlines(), start=1):
            if "reasoning-journal.json" in line and "reasoning-journal.jsonl" not in line:
                stale.append(f"{prompt.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")

    assert not stale, "\n".join(stale)


def test_spec_glob_fallbacks_are_guarded_by_authoritative_spec_dir_contract():
    """Prompts may locate specs only as a documented fallback."""
    violations = []
    roots = [
        EXTENSION_ROOT / "commands",
        EXTENSION_ROOT / "workflow" / "phases",
    ]
    guarded_patterns = (
        "spec_dir` is present",
        "state.json.spec_dir` is present",
        "spec_dir=` is present",
        "spec_dir` is provided",
    )
    fallback_patterns = (
        "spec_dir` is absent",
        "state.json.spec_dir` is absent",
        "spec_dir=` is absent",
    )
    positive_fallback_patterns = (
        "Only fall back to `specs/{spec_id}-*/`",
        "fall back to `specs/{spec_id}-*/`",
        "locate `specs/{spec_id}-*/`",
        "locate or glob `specs/{spec_id}-*/`",
        "locate the spec directory",
    )

    for root in roots:
        for prompt in root.rglob("*.md"):
            text = prompt.read_text()
            if "specs/{spec_id}-*/" not in text:
                continue
            if not any(pattern in text for pattern in positive_fallback_patterns):
                continue
            if not any(pattern in text for pattern in guarded_patterns):
                violations.append(
                    f"{prompt.relative_to(REPO_ROOT)}: specs/{{spec_id}}-* fallback lacks authoritative spec_dir guard"
                )
            if not any(pattern in text for pattern in fallback_patterns):
                violations.append(
                    f"{prompt.relative_to(REPO_ROOT)}: specs/{{spec_id}}-* fallback lacks explicit spec_dir-absent condition"
                )

    assert not violations, "\n".join(violations)


def test_re_single_phase_commands_use_shared_contract():
    commands = [
        "echelon.re-analyze.md",
        "echelon.re-specify.md",
        "echelon.re-verify.md",
        "echelon.re-expand.md",
        "echelon.re-validate.md",
        "echelon.re-checklist.md",
        "echelon.re-constitute.md",
        "echelon.re-plan.md",
        "echelon.re-tasks.md",
    ]

    for command_name in commands:
        text = (EXTENSION_ROOT / "commands" / command_name).read_text()
        assert "commands/appendices/re-single-phase-command.md" in text
        assert "then stop. Always execute only this phase" not in text
        assert "Use `workflow/definition.yaml`" not in text
        assert "Do not read `workflow/definition.yaml` to rediscover\nrouting." in text


def test_re_extract_command_uses_declared_phase_sequence():
    text = (EXTENSION_ROOT / "commands" / "echelon.re-extract.md").read_text()

    assert "Use this command's declared `re_extraction` phase sequence" in text
    assert "Do not read `agents/control/commander.md` or\n`workflow/definition.yaml`" in text
    assert "`re-extract-0-preflight`" in text
    assert "`re-extract-7-constitute`" in text
    assert "Then read `workflow/definition.yaml`" not in text


def test_re_constituter_contract_is_controller_owned_and_rerunnable():
    phase = (
        EXTENSION_ROOT / "workflow/phases/re-extract-7-constitute.md"
    ).read_text()
    agent = (EXTENSION_ROOT / "agents/re/constituter.md").read_text()

    assert "state_updates: {}" in phase
    assert "state_updates: {}" in agent
    assert not re.search(r"state_updates:\n\s+status:\s+done", phase)
    assert not re.search(r"state_updates:\n\s+status:\s+done", agent)
    assert "read an existing strategy output before updating it" in agent
    assert "read it before updating it" in phase
    assert "shell redirection" in agent
    assert "backup, temporary, alternate" in phase


def test_gatekeeper_contract_is_rerunnable_for_existing_assessment_files():
    phase = (EXTENSION_ROOT / "workflow/phases/phase2-decide.md").read_text()
    agent = (EXTENSION_ROOT / "agents/feasibility/gatekeeper.md").read_text()

    assert "read existing assessment outputs before updating them" in agent
    assert "read it before updating it" in phase
    assert "shell redirection" in agent
    assert "shell-written files" in phase
    assert "Return the first-pass gate decision as the top-level `verdict` only" in agent
    assert "do not return `gate_decision` or `phase_recommendation`" in phase


def test_re_plan_all_command_uses_declared_phase_sequence():
    text = (EXTENSION_ROOT / "commands" / "echelon.re-plan-all.md").read_text()

    assert "Use this command's declared `re_planning` phase sequence" in text
    assert "Do not read `agents/control/commander.md` or\n`workflow/definition.yaml`" in text
    assert "`re-planning-0-preflight`" in text
    assert "`re-planning-2-tasks`" in text
    assert "Then read `workflow/definition.yaml`" not in text


def test_re_retarget_command_uses_declared_phase_sequence():
    text = (EXTENSION_ROOT / "commands" / "echelon.re-retarget.md").read_text()

    assert "Use this command's declared `re_retarget` phase sequence" in text
    assert "Do not read `agents/control/commander.md` or\n`workflow/definition.yaml`" in text
    assert "`re-retarget-0-preflight`" in text
    assert "`re-retarget-1-input`" in text
    assert "Then read `workflow/definition.yaml`" not in text


def test_reopen_command_uses_declared_phase_sequence():
    text = (EXTENSION_ROOT / "commands" / "echelon.reopen.md").read_text()

    assert "Use this command's declared `reopen` phase sequence" in text
    assert "Do not read `agents/control/commander.md` or `workflow/definition.yaml`" in text
    assert "`reopen-1-apply-gaps`" in text
    assert "`workflow/phases/reopen-1-apply-gaps.md`" in text
    assert "Then read `workflow/definition.yaml`" not in text


def test_bugfix_command_uses_declared_phase_sequence():
    text = (EXTENSION_ROOT / "commands" / "echelon.bugfix.md").read_text()

    assert "Use this command's declared bugfix phase sequence" in text
    assert "Do not read `agents/control/commander.md` or `workflow/definition.yaml`" in text
    assert "`bugfix-1-init`" in text
    assert "`bugfix-5-finalize`" in text
    assert "`bugfix-done`" in text
    assert "Then read `workflow/definition.yaml`" not in text


def test_primary_agent_prompts_have_paired_always_never_rules():
    violations = []

    for prompt in (EXTENSION_ROOT / "agents").rglob("*.md"):
        rel = prompt.relative_to(REPO_ROOT)
        if "appendices" in prompt.parts or "templates" in prompt.parts:
            continue

        lines = prompt.read_text().splitlines()
        if "## ALWAYS / NEVER Rules" not in lines:
            violations.append(f"{rel}: missing ALWAYS / NEVER Rules section")
            continue

        start = lines.index("## ALWAYS / NEVER Rules")
        end = next(
            (
                index
                for index in range(start + 1, len(lines))
                if lines[index].startswith("## ")
            ),
            len(lines),
        )
        rule_lines = [
            line
            for line in lines[start + 1 : end]
            if line.startswith("ALWAYS") or line.startswith("NEVER")
        ]

        if len(rule_lines) % 2 != 0:
            violations.append(f"{rel}: unpaired ALWAYS / NEVER rule")
            continue

        for first, second in zip(rule_lines[0::2], rule_lines[1::2]):
            if not first.startswith("ALWAYS") or not second.startswith("NEVER"):
                violations.append(
                    f"{rel}: rules must be ordered ALWAYS then NEVER"
                )
                break

    assert not violations, "\n".join(violations)


def test_re_agent_prompts_use_standard_output_block_heading():
    violations = []

    for prompt in (EXTENSION_ROOT / "agents" / "re").glob("*.md"):
        text = prompt.read_text()
        if "## echelon_result format" in text:
            violations.append(
                f"{prompt.relative_to(REPO_ROOT)}: uses stale output heading"
            )
        if "## Output Block" not in text:
            violations.append(
                f"{prompt.relative_to(REPO_ROOT)}: missing Output Block heading"
            )

    assert not violations, "\n".join(violations)


def test_verify_spec_command_and_phases_exist():
    assert (EXTENSION_ROOT / "commands" / "echelon.verify-spec.md").exists()
    extension_text = (EXTENSION_ROOT / "extension.yml").read_text()
    assert 'name: "speckit.echelon.verify-spec"' in extension_text
    assert 'file: "commands/echelon.verify-spec.md"' in extension_text
    for phase in [
        "verify-spec-1-init.md",
        "verify-spec-2-codegraph.md",
        "verify-spec-3-audit.md",
        "verify-spec-4-map.md",
        "verify-spec-5-judge.md",
    ]:
        assert (EXTENSION_ROOT / "workflow" / "phases" / phase).exists()


def test_verify_spec_agents_are_registered():
    text = (EXTENSION_ROOT / "extension.yml").read_text()

    expected = {
        "speckit.echelon.spec-fulfillment-auditor": "agents/build/spec-fulfillment-auditor.md",
        "speckit.echelon.implementation-mapper": "agents/build/implementation-mapper.md",
    }
    for name, rel_path in expected.items():
        assert f'name: "{name}"' in text
        assert f'file: "{rel_path}"' in text
        assert (EXTENSION_ROOT / rel_path).exists()


def test_reopen_command_and_phase_exist():
    assert (EXTENSION_ROOT / "commands" / "echelon.reopen.md").exists()
    assert (EXTENSION_ROOT / "workflow" / "phases" / "reopen-1-apply-gaps.md").exists()

    extension_text = (EXTENSION_ROOT / "extension.yml").read_text()
    assert 'name: "speckit.echelon.reopen"' in extension_text
    assert 'file: "commands/echelon.reopen.md"' in extension_text


def test_harness_run_reads_fulfillment_gaps():
    text = (EXTENSION_ROOT / "commands" / "echelon.harness-run.md").read_text()
    assert "fulfillment-gaps.md" in text
    assert "mandatory implementation context" in text


def test_agent_prompts_do_not_write_squad_state_directly():
    violations = []

    for prompt in (EXTENSION_ROOT / "agents").rglob("*.md"):
        for lineno, line in enumerate(prompt.read_text().splitlines(), start=1):
            if "${SQUAD_DIR}/state.json" in line and "with open" in line and "'w'" in line:
                violations.append(f"{prompt.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
            if re.search(r"\bset `state\.json\.[^`]+`", line, re.IGNORECASE):
                violations.append(f"{prompt.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
            if re.search(r"\bset `state\.json\.[^`]+=", line, re.IGNORECASE):
                violations.append(f"{prompt.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")

    assert not violations, "\n".join(violations)


def test_phase1_what_routes_state_and_journal_through_echelon_result():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "phase1-what.md"
    text = prompt.read_text()

    assert "journal-append.sh" not in text
    assert "`journal.json`" not in text
    assert "Update state.json" not in text
    assert "Set `state.json" not in text
    assert "echelon_result.state_updates" in text
    assert "echelon_result.journal_entries" in text


def test_phase1_what_treats_spec_dir_as_authoritative_path():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "phase1-what.md"
    text = prompt.read_text()

    assert "Treat `spec_dir` as authoritative" in text
    assert "NEVER prefix it with `${SQUAD_DIR}`" in text
    assert "specs/{spec_id}/spec.md" not in text
    assert "spec_dir: specs/{spec_id}" not in text
    assert "If `specs/{NNN}-{feature-name}/` is missing" not in text
    assert "{spec_dir}/spec.md" in text


def test_phase2_decide_routes_kill_status_through_echelon_result():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "phase2-decide.md"
    text = prompt.read_text()

    assert 'set state.json status to "killed"' not in text
    assert "echelon_result.state_updates" in text
    assert "status: killed" in text


def test_build_1_init_routes_build_state_through_echelon_result():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "build-1-init.md"
    text = prompt.read_text()

    assert "Set `state.json.spec_status`" not in text
    assert "set result as `state.json.build.total_tasks`" not in text
    assert "Set `state.json.build.completed_tasks`" not in text
    assert "Update `${SQUAD_DIR}/state.json`" not in text
    assert "echelon_result.state_updates" in text
    assert "tasks_completed_pct: 0" in text
    assert "`spec_dir` — authoritative spec artifact directory" in text
    assert "Do not search for `state.json`, `${SQUAD_DIR}`, `runs/`" in text
    assert "Do not use `find`, `ls`,\nglobbing, or parent-directory scans to discover spec artifacts" in text
    assert "Always use `${PROJECT_ROOT}/specs/{NNN}-{feature}`" not in text


def test_build_6_progress_routes_build_state_through_echelon_result():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "build-6-progress.md"
    text = prompt.read_text()

    assert "update `state.json.build.completed_tasks`" not in text
    assert "Record the task result in `state.json.build.task_results`" not in text
    assert "Recompute `state.json.build.tasks_completed_pct`" not in text
    assert "Write the new value to `state.json.build.tasks_completed_pct`" not in text
    assert "echelon_result.state_updates" in text
    assert "previous completed_tasks + 1" in text


def test_build_8_finalize_routes_completion_state_through_echelon_result():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "build-8-finalize.md"
    text = prompt.read_text()

    assert "Set `state.json.spec_status`" not in text
    assert "Log journal entry:" not in text
    assert "### 8.3 Update State" not in text
    assert "Set `state.json.requires_human_review`" not in text
    assert "Set `state.json.constitution_amendments_pending`" not in text
    assert "echelon_result.state_updates" in text
    assert "echelon_result.journal_entries" in text
    assert "status: build_done" in text


def test_manual_specialist_commands_route_state_and_journal_through_echelon_result():
    commands = [
        EXTENSION_ROOT / "commands" / "echelon.innovate.md",
        EXTENSION_ROOT / "commands" / "echelon.ground.md",
        EXTENSION_ROOT / "commands" / "echelon.investigate.md",
    ]

    for prompt in commands:
        text = prompt.read_text()
        assert f"{prompt.name}: Update `${{SQUAD_DIR}}/state.json`" not in text
        assert f"{prompt.name}: append a MANAGER entry" not in text
        assert "echelon_result:" in text
        assert "state_updates:" in text
        assert "journal_entries:" in text


def test_active_run_specialist_commands_require_state_spec_dir():
    for prompt in [
        EXTENSION_ROOT / "commands" / "echelon.innovate.md",
        EXTENSION_ROOT / "commands" / "echelon.ground.md",
    ]:
        text = prompt.read_text()

        assert "Treat `state.json.spec_dir` as authoritative" in text
        assert "Do not locate, glob, search, list, or infer `specs/{spec_id}-*/`" in text
        assert "Active squad state is missing spec_dir" in text
        assert "If `state.json.spec_dir` is absent, locate" not in text


def test_bugfix_and_reopen_phases_accept_authoritative_spec_dir():
    expected = {
        EXTENSION_ROOT / "workflow" / "phases" / "bugfix-1-init.md":
            "Optional. Authoritative spec artifact directory",
        EXTENSION_ROOT / "workflow" / "phases" / "reopen-1-apply-gaps.md":
            "optional `spec_dir=<absolute-or-repo-relative-path>`",
    }

    for prompt, marker in expected.items():
        text = prompt.read_text()

        assert marker in text
        assert "When `spec_dir` is present, treat it as authoritative" in text
        assert "do not locate or glob `specs/{spec_id}-*/`" in text


def test_bugfix_finalize_writes_to_authoritative_spec_dir():
    text = (
        EXTENSION_ROOT / "workflow" / "phases" / "bugfix-5-finalize.md"
    ).read_text()

    assert 'ls "{spec_dir}"/bugfix-*.md' in text
    assert "Write `{spec_dir}/bugfix-{n}.md`" in text
    assert "append the bugfix tasks to `{spec_dir}/tasks.md`" in text
    assert "specs/{spec_id}-{spec_name}/bugfix-{n}.md" not in text
    assert "specs/{spec_id}-{spec_name}/tasks.md" not in text


def test_init_routes_post_creation_state_updates_through_echelon_result():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "init.md"
    text = prompt.read_text()

    assert 'Set `state.json.phase` to `"phase1-constitution"`' not in text
    assert 'Set `state.json.constitution_status` to `"exists"`' not in text
    assert 'Set `state.json.constitution_status` to `"pending"`' not in text
    assert "echelon_result.state_updates" in text
    assert "constitution_status: exists" in text
    assert "constitution_status: pending" in text
    assert "sets `state.json.fallback_mode = true`" not in text
    assert "fallback_mode: true" in text
    assert "execution_mode: manual_specification" in text


def test_phase1_why2_routes_state_updates_through_echelon_result():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "phase1-why2.md"
    text = prompt.read_text()

    assert "Set `state.json.status`" not in text
    assert "Set `state.json.blocked_reason`" not in text
    assert "persist Understanding availability check result to state.json" not in text
    assert "append to `state.json.quality_scores[]`" not in text
    assert "State fields to write" not in text
    assert "echelon_result.state_updates" in text
    assert "status: blocked" in text
    assert "quality_scores:" in text


def test_sage_quality_scores_use_boolean_pass_and_separate_iteration_marker():
    import re

    prompt = EXTENSION_ROOT / "agents" / "exploration" / "sage.md"
    text = prompt.read_text()
    match = re.search(r"state_updates:\n(?P<block>.*?)(?:\n  journal_entries:)", text, re.S)
    assert match is not None
    state_update_block = match.group("block")

    assert "pass: <true|false>" in state_update_block
    assert 'pass_id: "WHY2-iter-{N}"' in state_update_block
    assert 'pass: "WHY2-iter-{N}"' not in state_update_block


def test_phase1_modeler_routes_last_dispatch_through_echelon_result():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "phase1-modeler.md"
    text = prompt.read_text()

    assert "Set `state.json.last_dispatch.agent`" not in text
    assert "echelon_result.state_updates" in text
    assert "last_dispatch:" in text
    assert 'agent: "speckit-echelon-modeler (MODELER)"' in text


def test_build_7_integration_routes_checkpoint_through_echelon_result():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "build-7-integration.md"
    text = prompt.read_text()

    assert "Append to `state.json.build.phase_checkpoints`" not in text
    assert "echelon_result.state_updates" in text
    assert "build:" in text
    assert "phase_checkpoints:" in text


def test_phase3_specialists_routes_active_specialists_through_echelon_result():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "phase3-specialists.md"
    text = prompt.read_text()

    assert "Update `state.json.active_specialists`" not in text
    assert "echelon_result.state_updates" in text
    assert "active_specialists:" in text


def test_phase4_document_routes_done_state_through_echelon_result():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "phase4-document.md"
    text = prompt.read_text()

    assert "Update `state.json`:" not in text
    assert 'setting `state.json.status = "done"`' not in text
    assert 'state.json.status = "done"' not in text
    assert "echelon_result.state_updates" in text
    assert "status: done" in text


def test_phase3_consensus_references_returned_done_state():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "phase3-consensus.md"
    text = prompt.read_text()

    assert 'state.json.status = "done"' not in text
    assert "BEFORE returning status: done" in text


def test_codegen_decompose_names_codegen_state_explicitly():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "codegen-2-decompose.md"
    text = prompt.read_text()

    assert "Update state.json:" not in text
    assert "Update `codegen-state.json`" in text
