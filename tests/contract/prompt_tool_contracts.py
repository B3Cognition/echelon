from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from harness.prompt_markdown import parse_prompt_markdown


PROMPT_GLOBS = (
    "prosaic/subagents/*.md",
    "prosaic/commands/appendices/*.md",
    "prosaic/commands/echelon.*.md",
    "runtime/workflow/phases/**/*.md",
)

BUILD_SUBAGENT_NAMES = (
    "echelon.code-reviewer.md",
    "echelon.docs-verifier.md",
    "echelon.implementer.md",
    "echelon.integrator.md",
    "echelon.progress-tracker.md",
    "echelon.spec-guard.md",
    "echelon.tech-writer.md",
    "echelon.test-guardian.md",
)

PHASE_A_PHASE_GLOBS = (
    "phase1-*.md",
    "phase2-*.md",
    "phase3-*.md",
    "phase4-*.md",
    "phase-exp-*.md",
)

PROVIDER_NATIVE_TOOL_LANGUAGE_RE = re.compile(
    r"\b(?:WebSearch|WebFetch|ToolSearch|Bash)\b|"
    r"(?i:\b(?:agent|read|write|edit|glob|grep)\s+"
    r"(?:tools?|interfaces?|calls?)\b)|"
    r"\b(?:Agent|Read|Write|Edit|Glob|Grep)\(|"
    r"\b(?:Use|Call|Invoke)\s+(?:the\s+)?"
    r"(?:Agent|Read|Write|Edit|Glob|Grep)\b|"
    r"(?i:\b(?:via|with|through|invokes?|dispatch(?:es|ed|ing)?|"
    r"delegat(?:e|es|ed|ing))\s+(?:the\s+)?)"
    r"(?:Agent|Read|Write|Edit|Glob|Grep)\b|"
    r"\b(?:Read|Write|Edit|Glob|Grep)"
    r"(?:\s*/\s*"
    r"(?:Read|Write|Edit|Glob|Grep)){1,}\b|"
    r"`(?:Read|Write|Edit|Bash|Agent|Glob|Grep|WebSearch|WebFetch|ToolSearch)`|"
    r"\b(?:old_string|new_string|replace_all)\b"
)

EXECUTABLE_REFERENCE_RE = re.compile(
    r"\b(?:run|re-run|invoke|call|execute|use|validate|generate)\b"
    r".{0,120}\b(?:Skill tool|CLI|validator|command|script|"
    r"WebSearch|ToolSearch|Bash|Understanding|Lexicon|"
    r"speckit\.echelon|/speckit\.echelon|codegen CLI)\b",
    re.IGNORECASE,
)

EXACT_INVOCATION_RE = re.compile(
    r"`[^`\n]*(?:"
    r"speckit\.[\w.-]+|"
    r"echelon\.[\w.-]+|"
    r"understanding(?:\s+scan|\s+diagram|\s+\"\$|\s+\$|\s+<|\s+[\w{/])|"
    r"lexicon\s+validate|"
    r"echelon\s+[\w.-]+|"
    r"codegen\s+[\w.-]+|"
    r"bash\s+[\w./${}\"'-]+|"
    r"python\s+-m\s+[\w.]+(?:\s+[\w.-]+)?|"
    r"python\s+[\w./${}\"'-]+|"
    r"node\s+[\w./${}\"'-]+|"
    r"[\w./-]+\.sh\b|"
    r"sandbox-exec\.sh\b|"
    r"ls\s+[-\w./${}\"']+|"
    r"grep\s+[-\w./${}\"'|\\[\]()]+|"
    r"jq\s+[-'\"]|"
    r"pytest\s+[\w./:${}\"'-]+|"
    r"WebSearch|WebFetch|ToolSearch|Bash|Read|Glob|Grep|Write|Edit"
    r")[^`\n]*`",
    re.IGNORECASE,
)

PLAIN_EXACT_INVOCATION_RE = re.compile(
    r"(?:"
    r"/speckit\.echelon\.[\w.-]+|"
    r"\bspeckit\.echelon\.[\w.-]+|"
    r"\b[\w./-]+\.sh\b|"
    r"\bsandbox-exec\.sh\b|"
    r"\bWebSearch\b|\bWebFetch\b|\bToolSearch\b|\bBash\b"
    r")"
)

FENCED_COMMAND_RE = re.compile(
    r"```(?:bash|sh|text|console)?\n"
    r"(?:(?!```).)*(?:"
    r"speckit\.[\w.-]+|"
    r"understanding(?:\s+scan|\s+diagram|\s+\"\$|\s+\$|\s+<|\s+[\w{/])|"
    r"lexicon\s+validate|"
    r"echelon\s+[\w.-]+|"
    r"codegen\s+[\w.-]+|"
    r"bash\s+[\w./${}\"'-]+|"
    r"python\s+-m\s+[\w.]+(?:\s+[\w.-]+)?|"
    r"python\s+[\w./${}\"'-]+|"
    r"node\s+[\w./${}\"'-]+|"
    r"[\w./-]+\.sh\b|"
    r"sandbox-exec\.sh\b|"
    r"ls\s+[-\w./${}\"']+|"
    r"grep\s+[-\w./${}\"'|\\[\]()]+|"
    r"jq\s+[-'\"]|"
    r"pytest\s+[\w./:${}\"'-]+"
    r")(?:(?!```).)*```",
    re.IGNORECASE | re.DOTALL,
)

HARNESS_INTERNAL_DISCOVERY_TARGETS = (
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

HARNESS_INTERNAL_DISCOVERY_TARGET_RE = "|".join(
    target if "\\" in target else re.escape(target)
    for target in HARNESS_INTERNAL_DISCOVERY_TARGETS
)

HARNESS_INTERNAL_DISCOVERY_VERBS = (
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

HARNESS_INTERNAL_DISCOVERY_VERB_RE = "|".join(
    re.escape(verb) for verb in HARNESS_INTERNAL_DISCOVERY_VERBS
)

HARNESS_INTERNAL_DISCOVERY_RE = re.compile(
    rf"\b(?:{HARNESS_INTERNAL_DISCOVERY_VERB_RE})\b"
    rf".{{0,160}}\b(?:{HARNESS_INTERNAL_DISCOVERY_TARGET_RE})\b",
    re.IGNORECASE,
)

BUILD_GIT_STATE_DISCOVERY_COMMANDS = (
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

BUILD_GIT_STATE_DISCOVERY_COMMAND_RE = "|".join(
    re.escape(command) for command in BUILD_GIT_STATE_DISCOVERY_COMMANDS
)

BUILD_GIT_STATE_DISCOVERY_VERBS = (
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

BUILD_GIT_STATE_DISCOVERY_VERB_RE = "|".join(
    re.escape(verb) for verb in BUILD_GIT_STATE_DISCOVERY_VERBS
)

BUILD_GIT_STATE_DISCOVERY_RE = re.compile(
    rf"\b(?:{BUILD_GIT_STATE_DISCOVERY_VERB_RE})\b"
    rf".{{0,120}}\b(?:git\s+(?:{BUILD_GIT_STATE_DISCOVERY_COMMAND_RE})|rev-parse)\b",
    re.IGNORECASE,
)

BUILD_SPEC_ARTIFACT_DISCOVERY_TARGETS = (
    "state.json",
    "runs/",
    "tasks.md",
    "spec.md",
    "specs/",
    "progress-report.md",
    "run-history.json",
)

BUILD_SPEC_ARTIFACT_DISCOVERY_TARGET_RE = "|".join(
    re.escape(target) for target in BUILD_SPEC_ARTIFACT_DISCOVERY_TARGETS
)

BUILD_SPEC_ARTIFACT_DISCOVERY_VERBS = (
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

BUILD_SPEC_ARTIFACT_DISCOVERY_VERB_RE = "|".join(
    re.escape(verb) for verb in BUILD_SPEC_ARTIFACT_DISCOVERY_VERBS
)

BUILD_SPEC_ARTIFACT_DISCOVERY_RE = re.compile(
    rf"\b(?:{BUILD_SPEC_ARTIFACT_DISCOVERY_VERB_RE})\b"
    rf".{{0,160}}\b(?:{BUILD_SPEC_ARTIFACT_DISCOVERY_TARGET_RE})\b",
    re.IGNORECASE,
)

VERIFY_SPEC_DIR_DISCOVERY_TARGETS = ("specs/",)

VERIFY_SPEC_DIR_DISCOVERY_TARGET_RE = "|".join(
    re.escape(target) for target in VERIFY_SPEC_DIR_DISCOVERY_TARGETS
)

VERIFY_SPEC_DIR_DISCOVERY_VERBS = (
    "find",
    "locate",
    "glob",
    "list",
    "search",
)

VERIFY_SPEC_DIR_DISCOVERY_VERB_RE = "|".join(
    re.escape(verb) for verb in VERIFY_SPEC_DIR_DISCOVERY_VERBS
)

VERIFY_SPEC_DIR_DISCOVERY_RE = re.compile(
    rf"\b(?:{VERIFY_SPEC_DIR_DISCOVERY_VERB_RE})\b"
    rf".{{0,120}}\b(?:{VERIFY_SPEC_DIR_DISCOVERY_TARGET_RE})",
    re.IGNORECASE,
)

VERIFY_SPEC_RUN_DISCOVERY_TARGETS = ("runs/",)

VERIFY_SPEC_RUN_DISCOVERY_TARGET_RE = "|".join(
    re.escape(target) for target in VERIFY_SPEC_RUN_DISCOVERY_TARGETS
)

VERIFY_SPEC_RUN_DISCOVERY_VERBS = (
    "find",
    "locate",
    "glob",
    "list",
    "search",
    "sort",
    "infer",
)

VERIFY_SPEC_RUN_DISCOVERY_VERB_RE = "|".join(
    re.escape(verb) for verb in VERIFY_SPEC_RUN_DISCOVERY_VERBS
)

VERIFY_SPEC_RUN_DISCOVERY_RE = re.compile(
    rf"\b(?:{VERIFY_SPEC_RUN_DISCOVERY_VERB_RE})\b"
    rf".{{0,120}}\b(?:{VERIFY_SPEC_RUN_DISCOVERY_TARGET_RE})",
    re.IGNORECASE,
)

DELIVERY_COMMAND_RUNTIME_DISCOVERY_TARGETS = (
    "subagents/echelon.commander.md",
    "workflow/definition.yaml",
)

DELIVERY_COMMAND_RUNTIME_DISCOVERY_TARGET_RE = "|".join(
    re.escape(target) for target in DELIVERY_COMMAND_RUNTIME_DISCOVERY_TARGETS
)

DELIVERY_COMMAND_RUNTIME_DISCOVERY_VERBS = (
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

DELIVERY_COMMAND_RUNTIME_DISCOVERY_VERB_RE = "|".join(
    re.escape(verb) for verb in DELIVERY_COMMAND_RUNTIME_DISCOVERY_VERBS
)

DELIVERY_COMMAND_RUNTIME_DISCOVERY_RE = re.compile(
    rf"\b(?:{DELIVERY_COMMAND_RUNTIME_DISCOVERY_VERB_RE})\b"
    rf".{{0,120}}\b(?:{DELIVERY_COMMAND_RUNTIME_DISCOVERY_TARGET_RE})\b",
    re.IGNORECASE,
)

BUILD_WORKFLOW_DEFINITION_ROUTING_TARGETS = ("workflow/definition.yaml",)

BUILD_WORKFLOW_DEFINITION_ROUTING_TARGET_RE = "|".join(
    re.escape(target) for target in BUILD_WORKFLOW_DEFINITION_ROUTING_TARGETS
)

BUILD_WORKFLOW_DEFINITION_ROUTING_VERBS = (
    "follow",
    "following",
    "use",
    "consult",
    "read",
    "inspect",
    "open",
    "check",
)

BUILD_WORKFLOW_DEFINITION_ROUTING_VERB_RE = "|".join(
    re.escape(verb) for verb in BUILD_WORKFLOW_DEFINITION_ROUTING_VERBS
)

BUILD_WORKFLOW_DEFINITION_ROUTING_RE = re.compile(
    rf"\b(?:{BUILD_WORKFLOW_DEFINITION_ROUTING_VERB_RE})\b"
    rf".{{0,260}}\b(?:{BUILD_WORKFLOW_DEFINITION_ROUTING_TARGET_RE})\b",
    re.IGNORECASE,
)

DISCOVERY_NEGATIVE_BOUNDARY_VERBS = (
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

DISCOVERY_NEGATIVE_BOUNDARY_VERB_RE = "|".join(
    re.escape(verb) for verb in DISCOVERY_NEGATIVE_BOUNDARY_VERBS
)


@dataclass(frozen=True)
class PromptToolContractFinding:
    path: Path
    line: int
    reason: str
    text: str


def _default_prompt_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for pattern in PROMPT_GLOBS:
        paths.extend(root.glob(pattern))
    return sorted(path for path in paths if path.is_file())


def _default_phase_a_prompt_paths(root: Path) -> list[Path]:
    paths = list((root / "prosaic" / "subagents").glob("*.md"))
    phase_dir = root / "runtime" / "workflow" / "phases"
    for pattern in PHASE_A_PHASE_GLOBS:
        paths.extend(phase_dir.glob(pattern))
    return sorted(path for path in paths if path.is_file())


def scan_phase_a_provider_native_language(
    root: Path,
    paths: list[Path] | None = None,
) -> list[PromptToolContractFinding]:
    """Find provider-native tool API language in canonical Phase A prompt bodies."""
    findings: list[PromptToolContractFinding] = []
    prompt_paths = paths if paths is not None else _default_phase_a_prompt_paths(root)
    for path in prompt_paths:
        content = path.read_text(encoding="utf-8")
        body = parse_prompt_markdown(content, source=path).body
        body_start = len(content) - len(body)
        line_offset = content[:body_start].count("\n")
        for index, line in enumerate(body.splitlines(), start=1):
            if not PROVIDER_NATIVE_TOOL_LANGUAGE_RE.search(line):
                continue
            findings.append(
                PromptToolContractFinding(
                    path=path,
                    line=line_offset + index,
                    reason="provider_native_tool_language",
                    text=line.strip(),
                )
            )
    return findings


def _window(lines: list[str], index: int, radius: int = 10) -> str:
    start = max(0, index - radius)
    end = min(len(lines), index + radius + 1)
    return "\n".join(lines[start:end])


def _has_exact_invocation(context: str) -> bool:
    return bool(
        EXACT_INVOCATION_RE.search(context)
        or PLAIN_EXACT_INVOCATION_RE.search(context)
        or FENCED_COMMAND_RE.search(context)
    )


def _is_non_executable_reference(line: str) -> bool:
    lowered = line.lower()
    if "do not run understanding" in lowered or "does not run understanding" in lowered:
        return True
    if "understanding is not required" in lowered:
        return True
    if "understanding output" in lowered and "skill tool" not in lowered:
        return True
    if "`build`:" in line and "`start`:" in line:
        return True
    if re.match(r"\d+\.\s+\*\*first (?:dry|real) run\*\*", lowered):
        return True
    return False


def _is_negative_boundary(line: str) -> bool:
    lowered = line.strip().lower()
    if re.search(
        r"\bif\b.{0,80}\b(?:absent|missing|not provided)\b.{0,120}\b"
        rf"(?:{DISCOVERY_NEGATIVE_BOUNDARY_VERB_RE})\b",
        lowered,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:do not|never|must not)\b.{0,120}\b"
            rf"(?:{DISCOVERY_NEGATIVE_BOUNDARY_VERB_RE})\b",
            lowered,
        )
    )


def _is_build_prompt(path: Path) -> bool:
    normalized = path.as_posix()
    return (
        (
            path.name in BUILD_SUBAGENT_NAMES
            and (
                "/prosaic/subagents/" in normalized
                or normalized.startswith("prosaic/subagents/")
            )
        )
        or "/runtime/workflow/phases/build-" in normalized
        or normalized.startswith("runtime/workflow/phases/build-")
    )


def _is_verify_spec_phase(path: Path) -> bool:
    normalized = path.as_posix()
    return (
        "/runtime/workflow/phases/verify-spec-" in normalized
        or normalized.startswith("runtime/workflow/phases/verify-spec-")
    )


def _is_echelon_command_wrapper(path: Path) -> bool:
    normalized = path.as_posix()
    return (
        "/prosaic/commands/echelon." in normalized
        or normalized.startswith("prosaic/commands/echelon.")
    ) and path.name.endswith(".md")


def _is_command_appendix(path: Path) -> bool:
    normalized = path.as_posix()
    return "/prosaic/commands/appendices/" in normalized or normalized.startswith(
        "prosaic/commands/appendices/"
    )


def _is_harness_run_command(path: Path) -> bool:
    normalized = path.as_posix()
    return normalized.endswith("prosaic/commands/echelon.harness-run.md")


def scan_prompt_tool_contracts(
    root: Path,
    paths: list[Path] | None = None,
) -> list[PromptToolContractFinding]:
    """Find executable tool references that do not carry a concrete invocation.

    The scanner is intentionally conservative. It only flags lines that combine
    an action verb with an executable-tool noun, then accepts the reference when
    a nearby inline or fenced exact command/tool identifier makes the operational
    contract concrete.
    """

    findings: list[PromptToolContractFinding] = []
    prompt_paths = paths if paths is not None else _default_prompt_paths(root)

    for path in prompt_paths:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if HARNESS_INTERNAL_DISCOVERY_RE.search(stripped):
                if _is_negative_boundary(stripped):
                    continue
                findings.append(
                    PromptToolContractFinding(
                        path=path,
                        line=index + 1,
                        reason="harness_internal_discovery",
                        text=stripped,
                    )
                )
                continue
            if (
                _is_verify_spec_phase(path)
                and VERIFY_SPEC_DIR_DISCOVERY_RE.search(stripped)
            ):
                if _is_negative_boundary(stripped):
                    continue
                findings.append(
                    PromptToolContractFinding(
                        path=path,
                        line=index + 1,
                        reason="verify_spec_dir_discovery",
                        text=stripped,
                    )
                )
                continue
            if (
                _is_harness_run_command(path)
                and VERIFY_SPEC_DIR_DISCOVERY_RE.search(stripped)
            ):
                if _is_negative_boundary(stripped):
                    continue
                findings.append(
                    PromptToolContractFinding(
                        path=path,
                        line=index + 1,
                        reason="harness_spec_dir_discovery",
                        text=stripped,
                    )
                )
                continue
            if (
                _is_verify_spec_phase(path)
                and VERIFY_SPEC_RUN_DISCOVERY_RE.search(stripped)
            ):
                if _is_negative_boundary(stripped):
                    continue
                findings.append(
                    PromptToolContractFinding(
                        path=path,
                        line=index + 1,
                        reason="verify_spec_run_discovery",
                        text=stripped,
                    )
                )
                continue
            if _is_build_prompt(path) and BUILD_GIT_STATE_DISCOVERY_RE.search(stripped):
                if _is_negative_boundary(stripped):
                    continue
                findings.append(
                    PromptToolContractFinding(
                        path=path,
                        line=index + 1,
                        reason="build_git_state_discovery",
                        text=stripped,
                    )
                )
                continue
            if (
                _is_build_prompt(path)
                and BUILD_SPEC_ARTIFACT_DISCOVERY_RE.search(stripped)
            ):
                if _is_negative_boundary(stripped):
                    continue
                findings.append(
                    PromptToolContractFinding(
                        path=path,
                        line=index + 1,
                        reason="build_spec_artifact_discovery",
                        text=stripped,
                    )
                )
                continue
            if (
                _is_build_prompt(path)
                and BUILD_WORKFLOW_DEFINITION_ROUTING_RE.search(stripped)
            ):
                if _is_negative_boundary(stripped):
                    continue
                findings.append(
                    PromptToolContractFinding(
                        path=path,
                        line=index + 1,
                        reason="build_workflow_definition_routing",
                        text=stripped,
                    )
                )
                continue
            if (
                (
                    _is_echelon_command_wrapper(path)
                    or _is_command_appendix(path)
                )
                and DELIVERY_COMMAND_RUNTIME_DISCOVERY_RE.search(stripped)
            ):
                if _is_negative_boundary(stripped):
                    continue
                findings.append(
                    PromptToolContractFinding(
                        path=path,
                        line=index + 1,
                        reason="command_runtime_discovery",
                        text=stripped,
                    )
                )
                continue
            if not EXECUTABLE_REFERENCE_RE.search(stripped):
                continue
            if _is_non_executable_reference(stripped):
                continue
            context = _window(lines, index)
            if _has_exact_invocation(context):
                continue
            findings.append(
                PromptToolContractFinding(
                    path=path,
                    line=index + 1,
                    reason="missing_exact_invocation",
                    text=stripped,
                )
            )
    return findings
