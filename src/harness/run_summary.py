"""One optional human-readable narrative at the end of an Echelon run."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
import io
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping


@dataclass(frozen=True)
class RunSummaryContext:
    project_root: Path
    command: str
    task: str
    status: str
    facts: tuple[str, ...] = ()
    next_step: str = ""
    inspect_paths: tuple[Path, ...] = ()
    quality_debt_status: str = ""
    quality_debt_artifact: str = ""
    quality_debt_failed_gates: tuple[str, ...] = ()
    quality_debt_resolved_by: str = ""
    provider_limit_message: str = ""


@dataclass(frozen=True)
class SummaryAgent:
    prompt: str
    metadata: Mapping[str, object]


def summarize_run(
    context: RunSummaryContext,
    *,
    provider: Any,
    agent: SummaryAgent,
) -> str:
    prompt = _summary_prompt(context, agent.prompt)
    try:
        with tempfile.TemporaryDirectory(prefix="echelon-summary-") as work_dir:
            metadata = {
                **agent.metadata,
                "quiet": True,
            }
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = provider.run_agent_result(
                    work_dir,
                    prompt,
                    timeout_ms=30_000,
                    request_metadata={
                        "allow_non_git_cwd": True,
                        "prompt_metadata": metadata,
                    },
                )
    except Exception:
        return _fallback_summary(context)

    if result.exit_code != 0 or result.timed_out:
        return _fallback_summary(context)
    summary = _clean_summary(result.stdout)
    if (
        context.quality_debt_status == "accepted_with_debt"
        and _asserts_specification_quality_success(summary)
    ):
        return _fallback_summary(context)
    if not summary:
        return _fallback_summary(context)
    return _compose_summary(summary.splitlines(), context)


def summarize_run_for_cli(context: RunSummaryContext) -> str:
    """Generate a summary with the workspace's configured provider."""
    try:
        from harness.config import load_config
        from harness.llm_provider import AICodingCliProvider
        from harness.prosaic_prompt_loader import ProsaicPromptLoader

        artifact = ProsaicPromptLoader(context.project_root).load_subagent(
            "echelon.summarizer"
        )
        if artifact is None:
            return _fallback_summary(context)
        provider = AICodingCliProvider(
            load_config(context.project_root, squad_only=True)
        )
        return summarize_run(
            context,
            provider=provider,
            agent=SummaryAgent(
                prompt=artifact.body,
                metadata=artifact.frontmatter,
            ),
        )
    except Exception:
        return _fallback_summary(context)


def _summary_prompt(context: RunSummaryContext, agent_prompt: str) -> str:
    payload = {
        "command": context.command[:160],
        "task": context.task[:1_000],
        "status": context.status[:80],
        "facts": [fact[:500] for fact in context.facts[:20]],
        "next_step": context.next_step[:500],
        "workspace": str(context.project_root),
        "inspect_paths": [str(path) for path in context.inspect_paths[:8]],
        "quality_debt_status": context.quality_debt_status[:80],
        "quality_debt_artifact": context.quality_debt_artifact[:500],
        "quality_debt_failed_gates": [
            gate[:160] for gate in context.quality_debt_failed_gates[:8]
        ],
        "quality_debt_resolved_by": context.quality_debt_resolved_by[:40],
        "provider_limit_message": context.provider_limit_message[:500],
    }
    return (
        f"{agent_prompt.strip()}\n\n"
        "Use the following run context as your starting point. You may inspect the "
        "listed workspace paths when useful. Return only the final human-readable "
        "summary as three to seven short plain-text lines. Do not use bullets, a "
        "heading, JSON, or Markdown fences. Do not claim verification you did not "
        "observe. If quality_debt_status is accepted_with_debt, say accepted with "
        "quality debt, name the resolver and most important residual gates, and "
        "never call specification quality passed or fully certified. Keep any "
        "provider-limit fact independently visible.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _clean_summary(raw: object) -> str:
    raw_text = str(raw or "").strip()
    if raw_text.startswith(("{", "[")):
        return ""
    lines: list[str] = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```"):
            continue
        if line.startswith(("- ", "* ", "• ")):
            line = line[2:].strip()
        if line:
            lines.append(line[:280])
        if len(lines) == 7:
            break
    text = "\n".join(lines)
    return text[:1_200].rstrip()


def _asserts_specification_quality_success(summary: str) -> bool:
    """Fail closed on positive certification claims while debt is accepted.

    This deliberately classifies semantic subjects and predicates instead of
    enumerating complete forbidden phrases. A model may narrate work, but it
    may not issue its own clean specification-quality verdict.
    """
    domain = re.search(
        r"\b(?:spec(?:ification)?|requirements?|quality|gates?|checks?|"
        r"standards?|criteria|criterion|assessment|review|defects?)\b",
        summary,
        flags=re.IGNORECASE,
    )
    positive_verdict = re.search(
        r"\b(?:pass(?:ed|es|ing)?|succeed(?:ed|s|ing)?|success(?:ful(?:ly)?)?|"
        r"certif(?:y|ied|ies|ication)|satisf(?:y|ied|ies|action)|"
        r"meet(?:s|ing)?|met|clear(?:ed|s)?|conform(?:s|ed|ant)?|"
        r"validat(?:e|ed|es|ion)|approv(?:e|ed|al)|flawless|perfect|"
        r"exceed(?:ed|s|ing)?|surpass(?:ed|es|ing)?|achiev(?:e|ed|es|ing)|"
        r"fulfill(?:ed|s|ing)?|resolv(?:e|ed|es|ing)|compli(?:ant|ance)|"
        r"clean|green|sound|excellent|unconditional|ready)\b",
        summary,
        flags=re.IGNORECASE,
    )
    clean_bill = re.search(
        r"\b(?:no|without)\s+(?:remaining\s+|outstanding\s+|unresolved\s+)?"
        r"(?:issues?|defects?|failures?|gaps?|debt)\b",
        summary,
        flags=re.IGNORECASE,
    )
    exhaustive = re.search(
        r"\b(?:all|every)\b.{0,80}\b(?:pass|succeed|satisf|meet|met|clear)",
        summary,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return bool((domain and positive_verdict) or clean_bill or exhaustive)


def _duplicates_required_truth(line: str, context: RunSummaryContext) -> bool:
    lowered = line.casefold()
    if context.quality_debt_status == "accepted_with_debt" and re.search(
        r"(?:accepted_with_debt|quality[- ]debt|residual gates?|quality-debt\.json)",
        lowered,
    ):
        return True
    if context.provider_limit_message and re.search(
        r"(?:provider|rate|usage)\s+limit|quota",
        lowered,
    ):
        return True
    return False


def _compose_summary(
    narrative_lines: list[str],
    context: RunSummaryContext,
) -> str:
    """Retain authoritative truths inside the final seven-line/1,200-char cap."""
    required = _required_outcome_truth_lines(context)
    selected: list[str] = []
    line_limit = max(0, 7 - len(required))
    required_text = "\n".join(required)
    for raw_line in narrative_lines:
        line = raw_line.strip()
        if not line or _duplicates_required_truth(line, context):
            continue
        if len(selected) >= line_limit:
            break
        separators = len(selected) + len(required)
        remaining = 1_200 - len(required_text) - separators - sum(
            len(item) for item in selected
        )
        if remaining <= 0:
            break
        selected.append(line[:remaining].rstrip())
    return "\n".join((*selected, *required))


def _required_outcome_truth_lines(context: RunSummaryContext) -> list[str]:
    lines: list[str] = []
    if context.quality_debt_status == "accepted_with_debt":
        detail = "Specification quality: accepted with quality debt"
        resolver = context.quality_debt_resolved_by.strip()[:40]
        if resolver:
            detail += f" by {resolver}"
        gates = [
            gate.strip()[:60]
            for gate in context.quality_debt_failed_gates[:8]
            if gate.strip()
        ]
        if gates:
            detail += "; residual gates: " + ", ".join(gates)
        artifact = context.quality_debt_artifact.strip()[:220]
        if artifact:
            detail += f"; evidence: {artifact}"
        lines.append(detail + ".")
    provider = context.provider_limit_message.strip()[:240]
    if provider:
        provider = provider.rstrip(".")
        if re.match(r"provider\s+limit\b", provider, flags=re.IGNORECASE):
            lines.append(provider + ".")
        else:
            lines.append(f"Provider limit: {provider}.")
    return lines


def _fallback_summary(context: RunSummaryContext) -> str:
    delivery = "delivery" in context.command.lower()
    work = "delivery" if delivery else "specification work"
    if context.status == "done":
        lines = [f"Echelon completed the requested {work}."]
    elif context.status == "returned":
        lines = [f"Echelon finished dispatching the requested {work}."]
    else:
        lines = [f"Echelon worked on the requested {work}, but it is not complete."]

    facts = [fact.strip() for fact in context.facts if fact.strip()]
    outcome = next(
        (fact for fact in facts if fact.startswith(("Delivery result:", "Result:"))),
        "",
    )
    published = next(
        (fact for fact in facts if fact.lower().startswith("published")),
        "",
    )
    verification_facts = [fact for fact in facts if "verify:" in fact.lower()]
    if not verification_facts:
        verification_facts = [
            fact for fact in facts if "verification" in fact.lower()
        ]
    stopped = next(
        (fact for fact in facts if "stopped:" in fact.lower()),
        "",
    )

    if outcome:
        lines.append(outcome)
    elif published:
        lines.append(published)
    if len(verification_facts) > 1:
        verification_results = [
            fact[fact.lower().index("verify:") + 7 :].strip().rstrip(".")
            for fact in verification_facts
            if "verify:" in fact.lower()
        ]
        verdicts = {
            verdict
            for result in verification_results
            for verdict in ("failed", "passed", "deferred", "skipped")
            if verdict in result.lower()
        }
        if len(verdicts) > 1 or (not verdicts and len(set(verification_results)) > 1):
            lines.append(
                "Verification differed across strategies; see the delivery details above."
            )
        elif verdicts:
            lines.append(f"Verification: {next(iter(verdicts))} across strategies.")
        elif verification_results:
            lines.append(f"Verification: {verification_results[0]}.")
    elif verification_facts:
        verification = verification_facts[0]
        if "verify:" in verification.lower():
            verification = verification[verification.lower().index("verify:") + 7 :]
            verification = f"Verification: {verification.strip().rstrip('.')}."
        lines.append(verification)
    if stopped:
        stopped = stopped[stopped.lower().index("stopped:") + 8 :]
        lines.append(f"Stopped: {stopped.strip().rstrip('.')}.")
    if context.next_step.strip():
        lines.append(f"Next: {context.next_step.strip()}")
    return _compose_summary(lines, context)
