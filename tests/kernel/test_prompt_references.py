from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]
EXTENSION_ROOT = REPO_ROOT / "extension"
PROMPT_ROOTS = [
    EXTENSION_ROOT / "agents",
    EXTENSION_ROOT / "commands",
    EXTENSION_ROOT / "workflow" / "phases",
]

REFERENCE_RE = re.compile(
    r"`((?:agents/(?:[^`]+/(?:templates|appendices)/[^`]+))|"
    r"(?:workflow/phases/appendices/[^`]+))`"
)

PROMPT_REFERENCE_RE = re.compile(
    r"(?:`|\(|\s|^)"
    r"("
    r"(?:\.specify/extensions/echelon/)?"
    r"(?:agents/|workflow/phases/|templates/|docs/)"
    r"[^`)\s,*]+"
    r"\.(?:md|yaml|yml)"
    r")"
)


def _resolve_prompt_reference(ref: str, prompt: Path) -> Path:
    if ref.startswith(".specify/extensions/echelon/"):
        return EXTENSION_ROOT / ref.removeprefix(".specify/extensions/echelon/")
    if ref.startswith("agents/") or ref.startswith("workflow/phases/"):
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


def test_build_finalize_uses_appendices_for_large_reference_sections():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "build-8-finalize.md"
    text = prompt.read_text()

    assert "workflow/phases/appendices/build-8-verify-gates.md" in text
    assert "workflow/phases/appendices/build-8-summary-reference.md" in text


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


def test_cartographer_uses_appendix_for_brownfield_deep_dive_reference():
    prompt = EXTENSION_ROOT / "agents" / "exploration" / "cartographer.md"
    text = prompt.read_text()

    assert (
        "agents/exploration/appendices/cartographer-golddigger-deep-dive-reference.md"
        in text
    )


def test_commands_use_jsonl_reasoning_journal_name():
    stale = []

    for prompt in (EXTENSION_ROOT / "commands").rglob("*.md"):
        for lineno, line in enumerate(prompt.read_text().splitlines(), start=1):
            if "reasoning-journal.json" in line and "reasoning-journal.jsonl" not in line:
                stale.append(f"{prompt.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")

    assert not stale, "\n".join(stale)


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


def test_init_routes_post_creation_state_updates_through_echelon_result():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "init.md"
    text = prompt.read_text()

    assert 'Set `state.json.phase` to `"phase1-constitution"`' not in text
    assert 'Set `state.json.constitution_status` to `"exists"`' not in text
    assert 'Set `state.json.constitution_status` to `"pending"`' not in text
    assert "echelon_result.state_updates" in text
    assert "constitution_status: exists" in text
    assert "constitution_status: pending" in text


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
