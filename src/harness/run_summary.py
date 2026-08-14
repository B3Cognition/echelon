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
    if not summary:
        return _fallback_summary(context)
    narrative_lines = summary.splitlines()
    if context.quality_debt_status == "accepted_with_debt":
        narrative_lines = _safe_debt_narrative_clauses(summary)
        if not narrative_lines:
            return _fallback_summary(context)
    return _compose_summary(narrative_lines, context)


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


def _asserts_specification_quality_success(clause: str) -> bool:
    """Fail closed on one specification-quality verdict clause.

    This deliberately classifies semantic subjects and predicates instead of
    enumerating complete forbidden phrases. A model may narrate work, but it
    may not issue its own clean specification-quality verdict.
    """
    domain = re.search(
        r"\b(?:spec(?:ification)?|requirements?|quality|gates?|checks?|"
        r"standards?|criteria|criterion|assessment|review)\b",
        clause,
        flags=re.IGNORECASE,
    )
    positive_verdict = re.search(
        r"\b(?:pass(?:ed|es|ing)?|succeed(?:ed|s|ing)?|"
        r"certif(?:y|ied|ies|ication)|satisf(?:y|ied|ies|action)|"
        r"meet(?:s|ing)?|met|clear(?:ed|s)?|conform(?:s|ed|ant)?|"
        r"validat(?:e|ed|es|ion)|approv(?:e|ed|al)|flawless|perfect|"
        r"exceed(?:ed|s|ing)?|surpass(?:ed|es|ing)?|achiev(?:e|ed|es|ing)|"
        r"fulfill(?:ed|s|ing)?|resolv(?:e|ed|es|ing)|compli(?:ant|ance)|"
        r"clean|green|good|great|healthy|strong|solid|acceptable|"
        r"sound|excellent|unconditional|ready)\b",
        clause,
        flags=re.IGNORECASE,
    )
    generic_success = re.search(
        r"\bsuccess(?:ful(?:ly)?)?\b",
        clause,
        flags=re.IGNORECASE,
    )
    action_narration = _is_work_action_clause(clause)
    positive_verdict = bool(
        positive_verdict or (generic_success and not action_narration)
    )
    clean_bill = re.search(
        r"(?:\b(?:no|without)\s+(?:remaining\s+|outstanding\s+|unresolved\s+)?"
        r"(?:issues?|defects?|deficiencies|concerns?|failures?|findings?|"
        r"problems?|gaps?|debt)\b|\bfree\s+of\s+(?:issues?|defects?|"
        r"deficiencies|concerns?|failures?|findings?|problems?|gaps?|debt)\b|"
        r"\b(?:issues?|defects?|deficiencies|concerns?|failures?|findings?|"
        r"problems?|gaps?|debt)\b.{0,24}\b(?:absent|none)\b|"
        r"\black(?:s|ing)?\b.{0,36}\b(?:issues?|defects?|deficiencies|"
        r"concerns?|failures?|findings?|problems?|gaps?|debt)\b|"
        r"\bzero\b.{0,36}\b(?:issues?|defects?|deficiencies|concerns?|"
        r"failures?|findings?|problems?|gaps?|debt)\b|"
        r"\babsence\s+of\s+(?:issues?|defects?|deficiencies|concerns?|"
        r"failures?|findings?|problems?|gaps?|debt)\b|"
        r"\b(?:issue|defect|deficiency|concern|failure|finding|problem|gap|"
        r"debt)[- ]free\b)",
        clause,
        flags=re.IGNORECASE,
    )
    exhaustive = re.search(
        r"\b(?:all|every)\b.{0,80}\b(?:pass|succeed|satisf|meet|met|clear)",
        clause,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return bool(domain and (positive_verdict or clean_bill or exhaustive))


def _is_work_action_clause(clause: str) -> bool:
    return bool(
        re.search(
            r"\b(?:implemented|added|fixed|updated|wired|surfaced|preserved|tested)\b",
            clause,
            flags=re.IGNORECASE,
        )
    )


def _independent_claim_segments(sentence: str) -> list[str]:
    return [
        segment.strip()
        for segment in re.split(
            r"\s*,\s*(?=(?:while|but|although)\b)|"
            r"\s+and\s+(?=(?:(?:the\s+)?spec(?:ification)?(?:\s+quality)?|"
            r"quality|(?:all|every|no)\s+(?:spec(?:ification)?|quality|gates?|"
            r"checks?))\b)",
            sentence,
            flags=re.IGNORECASE,
        )
        if segment.strip()
    ]


def _safe_debt_narrative_clauses(summary: str) -> list[str]:
    """Drop only contradictory debt-mode clauses and retain safe narration."""
    safe: list[str] = []
    for line in summary.splitlines():
        sentences = re.split(r"(?<=[.!?;])\s+", line.strip())
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            claims = _independent_claim_segments(sentence)
            accepted = [
                claim
                for claim in claims
                if not _asserts_specification_quality_success(claim)
            ]
            if len(accepted) == len(claims):
                safe.append(sentence)
                continue
            for claim in accepted:
                cleaned = re.sub(
                    r"^(?:while|but|although|and)\s+",
                    "",
                    claim.rstrip(", "),
                    flags=re.IGNORECASE,
                )
                if cleaned:
                    safe.append(cleaned)
    return safe


def _normalized_truth_content(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _duplicates_required_truth(line: str, context: RunSummaryContext) -> bool:
    if _is_work_action_clause(line):
        return False
    lowered = line.casefold()
    if context.quality_debt_status == "accepted_with_debt":
        accepted_outcome = re.search(
            r"(?:\b(?:the\s+)?spec(?:ification)?(?:\s+quality)?\b.{0,100}"
            r"\baccepted\s+with\s+(?:quality\s+)?debt\b|"
            r"^accepted\s+with\s+(?:quality\s+)?debt\b|accepted_with_debt)",
            lowered,
        )
        residual_truth = re.search(r"\bresidual\s+gates?\b", lowered)
        artifact = _normalized_truth_content(context.quality_debt_artifact)
        artifact_truth = bool(
            artifact and artifact in _normalized_truth_content(line)
        )
        if accepted_outcome or residual_truth or artifact_truth:
            return True
    provider_message = context.provider_limit_message.strip()
    if provider_message:
        normalized_line = _normalized_truth_content(line)
        normalized_provider = _normalized_truth_content(provider_message)
        same_provider_fact = bool(
            normalized_provider
            and (
                normalized_provider in normalized_line
                or normalized_line in normalized_provider
            )
        )
        semantic_limit_line = bool(
            re.search(
                r"\b(?:hit|reached|exceeded)\b.{0,50}"
                r"\b(?:provider|session|rate|usage)\s+limit\b|"
                r"\b(?:provider|session|rate|usage)\s+limit\b.{0,50}"
                r"\b(?:reached|reset|resets)\b",
                lowered,
            )
        )
        if same_provider_fact or semantic_limit_line:
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
