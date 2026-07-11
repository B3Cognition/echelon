from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


PROMPT_GLOBS = (
    "extension/agents/**/*.md",
    "extension/commands/appendices/*.md",
    "extension/commands/echelon.bugfix.md",
    "extension/commands/echelon.build.md",
    "extension/commands/echelon.harness-run.md",
    "extension/commands/echelon.re-extract.md",
    "extension/commands/echelon.re-plan-all.md",
    "extension/commands/echelon.re-retarget.md",
    "extension/commands/echelon.reopen.md",
    "extension/commands/echelon.verify-spec.md",
    "extension/workflow/phases/**/*.md",
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

HARNESS_INTERNAL_DISCOVERY_RE = re.compile(
    r"\b(?:find|locate|discover|search|scan|browse|read|inspect|open|view|show|display|print|dump|grep|list|check|look at|review|examine|cat|sed|less|more|tail|head)\b"
    r".{0,160}\b(?:"
    r"harness (?:source|code|files?|internals?|scripts?|functions?|(?:verify|verification|fulfillment|delivery)\s+scripts?)|"
    r"Ralph code|"
    r"src/harness|"
    r"ralph\.py|"
    r"fulfillment_runner\.py|"
    r"fulfillment_report_is_current|"
    r"latest_fulfillment_report|"
    r"read_fulfillment_metadata|"
    r"stamp_fulfillment_report"
    r")\b",
    re.IGNORECASE,
)

BUILD_GIT_STATE_DISCOVERY_RE = re.compile(
    r"\b(?:check|get|query|inspect|read|run|use)\b"
    r".{0,120}\b(?:git\s+status|git\s+log|git\s+rev-parse|rev-parse)\b",
    re.IGNORECASE,
)

BUILD_SPEC_ARTIFACT_DISCOVERY_RE = re.compile(
    r"\b(?:find|get|query|read|locate|glob|list|search|scan)\b"
    r".{0,160}\b(?:state\.json|runs/|tasks\.md|spec\.md|specs/)\b",
    re.IGNORECASE,
)

VERIFY_SPEC_DIR_DISCOVERY_RE = re.compile(
    r"\b(?:find|locate|glob|list|search)\b.{0,120}\bspecs/",
    re.IGNORECASE,
)

VERIFY_SPEC_RUN_DISCOVERY_RE = re.compile(
    r"\b(?:find|locate|glob|list|search|sort|infer)\b.{0,120}\bruns/",
    re.IGNORECASE,
)

DELIVERY_COMMAND_RUNTIME_DISCOVERY_RE = re.compile(
    r"\b(?:read|inspect|open|locate|discover|search)\b"
    r".{0,120}\b(?:agents/control/commander\.md|workflow/definition\.yaml)\b",
    re.IGNORECASE,
)

BUILD_WORKFLOW_DEFINITION_ROUTING_RE = re.compile(
    r"\b(?:follow|following|use|consult|read|inspect|open|check)\b"
    r".{0,260}\bworkflow/definition\.yaml\b",
    re.IGNORECASE,
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
        r"(?:find|locate|discover|search|read|inspect|open|grep|list|glob)\b",
        lowered,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:do not|never|must not)\b.{0,120}\b"
            r"(?:find|locate|discover|search|read|inspect|open|grep|list)\b",
            lowered,
        )
    )


def _is_build_prompt(path: Path) -> bool:
    normalized = path.as_posix()
    return (
        "/extension/agents/build/" in normalized
        or normalized.startswith("extension/agents/build/")
        or "/extension/workflow/phases/build-" in normalized
        or normalized.startswith("extension/workflow/phases/build-")
    )


def _is_verify_spec_phase(path: Path) -> bool:
    normalized = path.as_posix()
    return (
        "/extension/workflow/phases/verify-spec-" in normalized
        or normalized.startswith("extension/workflow/phases/verify-spec-")
    )


def _is_delivery_command(path: Path) -> bool:
    normalized = path.as_posix()
    return normalized.endswith(
        ("extension/commands/echelon.build.md", "extension/commands/echelon.verify-spec.md")
    )


def _is_command_appendix(path: Path) -> bool:
    normalized = path.as_posix()
    return "/extension/commands/appendices/" in normalized or normalized.startswith(
        "extension/commands/appendices/"
    )


def _is_re_extract_command(path: Path) -> bool:
    normalized = path.as_posix()
    return normalized.endswith(
        (
            "extension/commands/echelon.re-extract.md",
            "extension/commands/echelon.re-plan-all.md",
            "extension/commands/echelon.re-retarget.md",
            "extension/commands/echelon.reopen.md",
            "extension/commands/echelon.bugfix.md",
        )
    )


def _is_harness_run_command(path: Path) -> bool:
    normalized = path.as_posix()
    return normalized.endswith("extension/commands/echelon.harness-run.md")


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
                    _is_delivery_command(path)
                    or _is_command_appendix(path)
                    or _is_re_extract_command(path)
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
