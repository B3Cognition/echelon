from pathlib import Path

from tests.contract.prompt_tool_contracts import (
    BUILD_GIT_STATE_DISCOVERY_COMMANDS,
    BUILD_GIT_STATE_DISCOVERY_VERBS,
    BUILD_SPEC_ARTIFACT_DISCOVERY_VERBS,
    BUILD_SPEC_ARTIFACT_DISCOVERY_TARGETS,
    BUILD_WORKFLOW_DEFINITION_ROUTING_TARGETS,
    BUILD_WORKFLOW_DEFINITION_ROUTING_VERBS,
    DELIVERY_COMMAND_RUNTIME_DISCOVERY_TARGETS,
    DELIVERY_COMMAND_RUNTIME_DISCOVERY_VERBS,
    DISCOVERY_NEGATIVE_BOUNDARY_VERBS,
    HARNESS_INTERNAL_DISCOVERY_TARGETS,
    HARNESS_INTERNAL_DISCOVERY_VERBS,
    VERIFY_SPEC_DIR_DISCOVERY_TARGETS,
    VERIFY_SPEC_DIR_DISCOVERY_VERBS,
    VERIFY_SPEC_RUN_DISCOVERY_TARGETS,
    VERIFY_SPEC_RUN_DISCOVERY_VERBS,
    _default_prompt_paths,
    scan_prompt_tool_contracts,
)


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


def test_harness_internal_discovery_targets_are_named_category() -> None:
    assert HARNESS_INTERNAL_DISCOVERY_TARGETS == (
        r"harness (?:source|code|files?|internals?|scripts?|functions?|(?:verify|verification|fulfillment|delivery)\s+scripts?)",
        "Ralph code",
        "src/harness",
        "ralph.py",
        "fulfillment_runner.py",
        "fulfillment_report_is_current",
        "latest_fulfillment_report",
        "read_fulfillment_metadata",
        "stamp_fulfillment_report",
    )


def test_harness_internal_discovery_verbs_are_named_category() -> None:
    assert HARNESS_INTERNAL_DISCOVERY_VERBS == (
        "find",
        "locate",
        "discover",
        "search",
        "scan",
        "browse",
        "consult",
        "study",
        "parse",
        "read",
        "inspect",
        "open",
        "view",
        "show",
        "display",
        "print",
        "dump",
        "grep",
        "list",
        "check",
        "look at",
        "review",
        "examine",
        "cat",
        "sed",
        "less",
        "more",
        "tail",
        "head",
    )


def test_discovery_negative_boundary_verbs_are_named_category() -> None:
    assert DISCOVERY_NEGATIVE_BOUNDARY_VERBS == (
        "find",
        "locate",
        "discover",
        "search",
        "read",
        "inspect",
        "open",
        "grep",
        "list",
        "glob",
        "run",
        "use",
        "scan",
        "view",
        "show",
        "display",
        "print",
        "dump",
        "review",
        "examine",
        "check",
        "look at",
        "parse",
        "cat",
        "sed",
        "less",
        "more",
        "tail",
        "head",
    )


def test_flags_harness_function_implementation_discovery(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "Find fulfillment_report_is_current implementation.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "harness_internal_discovery"


def test_flags_harness_function_discovery_synonyms(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "Locate fulfillment_report_is_current provenance handling.\n"
        "Discover latest_fulfillment_report implementation.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert [finding.reason for finding in findings] == [
        "harness_internal_discovery",
        "harness_internal_discovery",
    ]


def test_flags_harness_script_and_function_discovery_phrasing(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "Check the harness verify script to understand stale report handling.\n"
        "Inspect harness functions before deciding how to update fulfillment state.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert [finding.reason for finding in findings] == [
        "harness_internal_discovery",
        "harness_internal_discovery",
    ]


def test_flags_soft_harness_source_discovery_phrasing(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "Check harness code to understand stale fulfillment handling.\n"
        "Look at src/harness/fulfillment_runner.py for the exact format.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert [finding.reason for finding in findings] == [
        "harness_internal_discovery",
        "harness_internal_discovery",
    ]


def test_flags_review_harness_source_discovery_phrasing(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "Review harness internals before deciding how to update fulfillment state.\n"
        "Examine src/harness/ralph.py to understand the resume flow.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert [finding.reason for finding in findings] == [
        "harness_internal_discovery",
        "harness_internal_discovery",
    ]


def test_flags_view_harness_source_discovery_phrasing(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "View src/harness/ralph.py before deciding how delivery resume works.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "harness_internal_discovery"


def test_flags_show_display_harness_source_discovery_phrasing(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "Show src/harness/ralph.py before deciding how delivery resume works.\n"
        "Display harness internals before updating fulfillment state.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert [finding.reason for finding in findings] == [
        "harness_internal_discovery",
        "harness_internal_discovery",
    ]


def test_flags_print_dump_harness_source_discovery_phrasing(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "Print src/harness/ralph.py before deciding how delivery resume works.\n"
        "Dump harness internals before updating fulfillment state.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert [finding.reason for finding in findings] == [
        "harness_internal_discovery",
        "harness_internal_discovery",
    ]


def test_flags_scan_browse_harness_source_discovery_phrasing(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "Scan src/harness/ralph.py before deciding how delivery resume works.\n"
        "Browse harness internals before updating fulfillment state.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert [finding.reason for finding in findings] == [
        "harness_internal_discovery",
        "harness_internal_discovery",
    ]


def test_flags_consult_study_parse_harness_source_discovery_phrasing(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "Consult src/harness/ralph.py before deciding how delivery resume works.\n"
        "Study harness internals before updating fulfillment state.\n"
        "Parse fulfillment_runner.py to learn the fulfillment metadata format.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert [finding.reason for finding in findings] == [
        "harness_internal_discovery",
        "harness_internal_discovery",
        "harness_internal_discovery",
    ]


def test_flags_shell_harness_source_read_phrasing(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "Run `cat src/harness/ralph.py` to inspect the resume flow.\n"
        "Use `sed -n '1,80p' src/harness/fulfillment_runner.py` for the format.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert [finding.reason for finding in findings] == [
        "harness_internal_discovery",
        "harness_internal_discovery",
    ]


def test_accepts_negative_harness_source_boundary(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        "Do not locate, discover, inspect, read, or search for harness source, Ralph code, "
        "ralph.py, fulfillment_runner.py, fulfillment_report_is_current, "
        "or Echelon implementation internals.\n",
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


def test_verify_spec_dir_discovery_targets_are_named_category() -> None:
    assert VERIFY_SPEC_DIR_DISCOVERY_TARGETS == ("specs/",)


def test_verify_spec_dir_discovery_verbs_are_named_category() -> None:
    assert VERIFY_SPEC_DIR_DISCOVERY_VERBS == (
        "find",
        "locate",
        "glob",
        "list",
        "search",
    )


def test_flags_harness_run_prompt_side_spec_dir_discovery(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "commands" / "echelon.harness-run.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "If `spec_dir` is absent, locate the spec directory: find `specs/{spec_id}-*/`.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "harness_spec_dir_discovery"


def test_flags_harness_run_mixed_negative_and_positive_spec_discovery(
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "extension" / "commands" / "echelon.harness-run.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "When `spec_dir` is provided, do not locate `specs/{spec_id}-*/`. "
        "If `spec_dir` is absent, locate `specs/{spec_id}-*/`.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "harness_spec_dir_discovery"


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


def test_verify_spec_run_discovery_targets_are_named_category() -> None:
    assert VERIFY_SPEC_RUN_DISCOVERY_TARGETS == ("runs/",)


def test_verify_spec_run_discovery_verbs_are_named_category() -> None:
    assert VERIFY_SPEC_RUN_DISCOVERY_VERBS == (
        "find",
        "locate",
        "glob",
        "list",
        "search",
        "sort",
        "infer",
    )


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


def test_build_git_state_discovery_commands_are_named_category() -> None:
    assert BUILD_GIT_STATE_DISCOVERY_COMMANDS == (
        "status",
        "log",
        "rev-parse",
        "diff",
        "branch",
        "show",
        "ls-files",
        "ls-tree",
        "cat-file",
        "grep",
    )


def test_build_git_state_discovery_verbs_are_named_category() -> None:
    assert BUILD_GIT_STATE_DISCOVERY_VERBS == (
        "check",
        "get",
        "query",
        "inspect",
        "read",
        "run",
        "use",
        "review",
        "examine",
        "look at",
        "parse",
        "view",
        "show",
        "display",
        "print",
        "dump",
    )


def test_flags_build_prompt_git_state_discovery_synonyms(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "agents" / "build" / "implementer.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Get git status and rev-parse before implementing.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "build_git_state_discovery"


def test_flags_build_prompt_git_diff_branch_show_discovery(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "agents" / "build" / "implementer.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Inspect git diff, git branch, and git show before implementing.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "build_git_state_discovery"


def test_flags_build_prompt_git_ls_files_discovery(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "agents" / "build" / "implementer.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Run git ls-files before implementing.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "build_git_state_discovery"


def test_flags_build_prompt_git_ls_tree_discovery(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "agents" / "build" / "implementer.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Run git ls-tree to inspect repository files before implementing.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "build_git_state_discovery"


def test_flags_build_prompt_git_cat_file_discovery(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "agents" / "build" / "implementer.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Use git cat-file to inspect repository objects before implementing.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "build_git_state_discovery"


def test_flags_build_prompt_git_grep_discovery(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "agents" / "build" / "implementer.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Use git grep to locate relevant requirements before implementing.\n",
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


def test_build_spec_artifact_discovery_targets_are_named_category() -> None:
    assert BUILD_SPEC_ARTIFACT_DISCOVERY_TARGETS == (
        "state.json",
        "runs/",
        "tasks.md",
        "spec.md",
        "specs/",
        "progress-report.md",
        "run-history.json",
    )


def test_build_spec_artifact_discovery_verbs_are_named_category() -> None:
    assert BUILD_SPEC_ARTIFACT_DISCOVERY_VERBS == (
        "find",
        "get",
        "query",
        "read",
        "locate",
        "glob",
        "list",
        "search",
        "scan",
        "inspect",
        "open",
        "view",
        "show",
        "display",
        "print",
        "dump",
        "review",
        "examine",
        "check",
        "look at",
        "parse",
        "cat",
        "sed",
        "less",
        "more",
        "tail",
        "head",
    )


def test_flags_build_prompt_spec_artifact_discovery_synonyms(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "workflow" / "phases" / "build-1-init.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Get state.json and task progress before build init.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "build_spec_artifact_discovery"


def test_flags_build_prompt_progress_artifact_discovery(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "workflow" / "phases" / "build-1-init.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Read progress-report.md and run-history.json before build init.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "build_spec_artifact_discovery"


def test_flags_soft_build_prompt_artifact_discovery_verbs(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "workflow" / "phases" / "build-1-init.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Inspect tasks.md and review progress-report.md before build init.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "build_spec_artifact_discovery"


def test_flags_delivery_command_runtime_discovery(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "commands" / "echelon.build.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Read `agents/control/commander.md` and `workflow/definition.yaml` before build.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "command_runtime_discovery"


def test_delivery_command_runtime_discovery_targets_are_named_category() -> None:
    assert DELIVERY_COMMAND_RUNTIME_DISCOVERY_TARGETS == (
        "agents/control/commander.md",
        "workflow/definition.yaml",
    )


def test_delivery_command_runtime_discovery_verbs_are_named_category() -> None:
    assert DELIVERY_COMMAND_RUNTIME_DISCOVERY_VERBS == (
        "read",
        "inspect",
        "open",
        "locate",
        "discover",
        "search",
        "list",
        "check",
        "review",
        "examine",
        "look at",
        "view",
        "show",
        "display",
        "print",
        "dump",
        "run",
        "use",
        "grep",
        "rg",
        "cat",
        "sed",
        "less",
        "more",
        "tail",
        "head",
        "find",
        "glob",
    )


def test_flags_delivery_command_runtime_discovery_synonyms(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "commands" / "echelon.build.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Inspect `workflow/definition.yaml` before build.\n"
        "Open `agents/control/commander.md` before build.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert [finding.reason for finding in findings] == [
        "command_runtime_discovery",
        "command_runtime_discovery",
    ]


def test_flags_delivery_command_runtime_discovery_soft_verbs(
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "extension" / "commands" / "echelon.build.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Check `workflow/definition.yaml` before build.\n"
        "Review `agents/control/commander.md` before build.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert [finding.reason for finding in findings] == [
        "command_runtime_discovery",
        "command_runtime_discovery",
    ]


def test_flags_delivery_command_runtime_discovery_shell_readers(
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "extension" / "commands" / "echelon.build.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Run `cat workflow/definition.yaml` before build.\n"
        "Use `sed -n '1,80p' agents/control/commander.md` before build.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert [finding.reason for finding in findings] == [
        "command_runtime_discovery",
        "command_runtime_discovery",
    ]


def test_flags_delivery_command_runtime_discovery_search_readers(
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "extension" / "commands" / "echelon.build.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Run `grep -n re_extraction workflow/definition.yaml` before build.\n"
        "List `agents/control/commander.md` before build.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert [finding.reason for finding in findings] == [
        "command_runtime_discovery",
        "command_runtime_discovery",
    ]


def test_flags_delivery_command_runtime_discovery_direct_search_commands(
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "extension" / "commands" / "echelon.build.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Grep `workflow/definition.yaml` before build.\n"
        "rg `agents/control/commander.md` before build.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert [finding.reason for finding in findings] == [
        "command_runtime_discovery",
        "command_runtime_discovery",
    ]


def test_flags_delivery_command_runtime_discovery_locator_commands(
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "extension" / "commands" / "echelon.build.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Find `workflow/definition.yaml` before build.\n"
        "Glob `agents/control/commander.md` before build.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert [finding.reason for finding in findings] == [
        "command_runtime_discovery",
        "command_runtime_discovery",
    ]


def test_flags_build_phase_workflow_definition_routing(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "workflow" / "phases" / "build-2-implement.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Follow `workflow/definition.yaml` transitions after each quality gate.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "build_workflow_definition_routing"


def test_build_workflow_definition_routing_targets_are_named_category() -> None:
    assert BUILD_WORKFLOW_DEFINITION_ROUTING_TARGETS == ("workflow/definition.yaml",)


def test_build_workflow_definition_routing_verbs_are_named_category() -> None:
    assert BUILD_WORKFLOW_DEFINITION_ROUTING_VERBS == (
        "follow",
        "following",
        "use",
        "consult",
        "read",
        "inspect",
        "open",
        "check",
    )


def test_flags_command_appendix_runtime_discovery(tmp_path: Path) -> None:
    prompt = (
        tmp_path
        / "extension"
        / "commands"
        / "appendices"
        / "re-single-phase-command.md"
    )
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "ALWAYS read `agents/control/commander.md` first.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "command_runtime_discovery"


def test_flags_any_echelon_command_runtime_discovery(tmp_path: Path) -> None:
    prompt = tmp_path / "extension" / "commands" / "echelon.re-verify.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "Read `workflow/definition.yaml` before running the phase.\n",
        encoding="utf-8",
    )

    findings = scan_prompt_tool_contracts(tmp_path, [prompt])

    assert len(findings) == 1
    assert findings[0].reason == "command_runtime_discovery"


def test_default_prompt_paths_include_all_echelon_command_wrappers() -> None:
    root = Path(__file__).resolve().parents[2]
    expected = set((root / "extension" / "commands").glob("echelon.*.md"))
    actual = set(_default_prompt_paths(root))

    assert expected <= actual


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
