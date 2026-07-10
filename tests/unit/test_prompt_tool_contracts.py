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


def test_flags_verify_spec_prompt_side_spec_dir_discovery(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "workflow" / "phases" / "verify-spec-1-init.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "When `spec_dir=` is absent, locate `specs/{spec_id}-*/` from the current root.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "verify_spec_dir_discovery"


def test_flags_verify_spec_prompt_side_latest_run_discovery(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "workflow" / "phases" / "verify-spec-1-init.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "List and sort `runs/` to infer the latest verification run directory.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "verify_spec_run_discovery"


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


def test_flags_build_prompt_spec_artifact_discovery(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "workflow" / "phases" / "build-1-init.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Search for state.json, runs/, tasks.md, spec.md, or specs/ before build init.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "build_spec_artifact_discovery"


def test_build_phase_prompts_use_ralph_owned_context_packs() -> None:
    root = Path(__file__).resolve().parents[2]
    phase_files = [
        root / "extension" / "workflow" / "phases" / name
        for name in (
            "build-2-implement.md",
            "build-3-spec-guard.md",
            "build-4-code-review.md",
            "build-5-test-guard.md",
            "build-6-progress.md",
            "build-7-integration.md",
            "build-8-documentation.md",
            "build-8-finalize.md",
            "build-8-verify-docs.md",
        )
    ]

    for phase_file in phase_files:
        text = phase_file.read_text(encoding="utf-8")
        assert "Compile context pack:" not in text
        assert "Ralph-owned context pack" in text
        assert "build_slice_context_index_file" in text


def test_current_agent_and_phase_prompts_have_contracted_tool_references() -> None:
    root = Path(__file__).resolve().parents[2]

    assert scan_prompt_tool_contracts(root) == []
