from pathlib import Path

from tests.contract.prompt_tool_contracts import scan_prompt_tool_contracts


def test_flags_vague_validator_reference(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text("Run the validator and repair until clean.\n", encoding="utf-8")

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "missing_exact_invocation"


def test_accepts_exact_cli_reference_with_output_discipline(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        'Run `lexicon validate "{spec_dir}/requirements.lexicon.md" --type spec --json` '
        "and treat stdout as the verdict.\n",
        encoding="utf-8",
    )

    assert scan_prompt_tool_contracts(tmp_path, [prompt]) == []


def test_flags_vague_skill_tool_reference(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text("Use the Skill tool to invoke Understanding validation.\n", encoding="utf-8")

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "missing_exact_invocation"


def test_accepts_exact_skill_tool_reference(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "Use the Skill tool: `speckit.echelon.understanding-validate <spec.md>`.\n",
        encoding="utf-8",
    )

    assert scan_prompt_tool_contracts(tmp_path, [prompt]) == []


def test_accepts_nearby_fenced_command_contract(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "Invoke the validator with the exact command below:\n\n"
        "```bash\n"
        "understanding scan \"$SPEC_PATH\" --enhanced --per-req --json --output /tmp/u.json\n"
        "```\n",
        encoding="utf-8",
    )

    assert scan_prompt_tool_contracts(tmp_path, [prompt]) == []


def test_accepts_documentation_checklist_command_requirements(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "4. **First dry run** - the safest preview command, what it checks, "
        "and what output or exit behavior to expect.\n"
        "5. **First real run** - the command that performs the primary workflow "
        "locally and the expected output, generated files, state changes, or service URL.\n",
        encoding="utf-8",
    )

    assert scan_prompt_tool_contracts(tmp_path, [prompt]) == []


def test_flags_harness_internal_discovery_instruction(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "Find harness files that reference fulfillment-report verified-at.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "harness_internal_discovery"


def test_flags_direct_harness_source_read_instruction(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "Read src/harness/fulfillment_runner.py to discover the provenance format.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "harness_internal_discovery"


def test_accepts_negative_harness_source_boundary(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "Do not inspect, read, or search for harness source, Ralph code, "
        "ralph.py, fulfillment_runner.py, or Echelon implementation internals.\n",
        encoding="utf-8",
    )

    assert scan_prompt_tool_contracts(tmp_path, [prompt]) == []


def test_flags_build_prompt_git_state_discovery(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "agents" / "build" / "implementer.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Check git status and git log in the worktree before implementing.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "build_git_state_discovery"


def test_current_agent_and_phase_prompts_have_contracted_tool_references() -> None:
    root = Path(__file__).resolve().parents[2]

    assert scan_prompt_tool_contracts(root) == []
