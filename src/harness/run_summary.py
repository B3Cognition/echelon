"""One optional human-readable narrative at the end of an Echelon run."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
import io
import json
from pathlib import Path
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
    return summary or _fallback_summary(context)


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
    }
    return (
        f"{agent_prompt.strip()}\n\n"
        "Use the following run context as your starting point. You may inspect the "
        "listed workspace paths when useful. Return only the final human-readable "
        "summary as three to seven short plain-text lines. Do not use bullets, a "
        "heading, JSON, or Markdown fences. Do not claim verification you did not "
        "observe.\n\n"
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
        verification_results = {
            fact[fact.lower().index("verify:") + 7 :].strip().rstrip(".")
            for fact in verification_facts
            if "verify:" in fact.lower()
        }
        if len(verification_results) > 1:
            lines.append(
                "Verification differed across strategies; see the delivery details above."
            )
        elif verification_results:
            lines.append(f"Verification: {next(iter(verification_results))}.")
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
    return "\n".join(lines)
