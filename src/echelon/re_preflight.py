"""One local request estimate and explicit aggregate-budget authorization."""

import shlex
import sys

from harness.re_v2.knowledge_preflight import KnowledgeRequestEstimate


def authorize_knowledge_preflight(
    estimate: KnowledgeRequestEstimate,
    *,
    token_limit: int,
    active_ms_limit: int,
    explicit_token_limit: bool,
    command: tuple[str, ...],
) -> int:
    """Return an authorized absolute ceiling, never raise it silently."""
    print(
        f"[re] whole-request preflight · local heuristic · "
        f"{estimate.source_count} source(s) to analyze · "
        f"{estimate.file_count} text files / {estimate.line_count:,} lines / "
        f"{estimate.domain_count} provisional domains", flush=True,
    )
    print(
        f"[re] planning range {estimate.lower_tokens:,}–{estimate.upper_tokens:,} tokens · "
        f"recommended absolute ceiling {estimate.recommended_tokens:,} · "
        f"configured/explicit ceiling {token_limit:,}", flush=True,
    )
    print(
        "[re] includes discovery, source analysis, review/repair and workspace synthesis; "
        "tool/cache context replay varies by provider. Not a guarantee. "
        f"Active-time ceiling unchanged: {active_ms_limit // 60_000} minutes.", flush=True,
    )
    recommended = estimate.recommended_tokens
    if recommended <= token_limit or explicit_token_limit:
        if recommended > token_limit:
            print("[re] explicit ceiling is below the planning recommendation; "
                  "honoring it without an increase.", flush=True)
        print(f"[re] effective absolute token ceiling {token_limit:,}", flush=True)
        return token_limit
    retry = shlex.join((*command, "--re-token-limit", str(recommended)))
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ValueError(
            "preflight recommends more tokens than configured; no provider work started. "
            f"Authorize explicitly by rerunning: {retry}"
        )
    try:
        answer = input(f"Authorize an absolute {recommended:,}-token ceiling for this "
                       "whole request? [y/N] ").strip().lower()
    except EOFError:
        answer = ""
    if answer not in {"y", "yes"}:
        raise ValueError(f"larger preflight ceiling not authorized; no provider work started. "
                         f"To authorize explicitly: {retry}")
    print(f"[re] effective absolute token ceiling {recommended:,} (approved)", flush=True)
    return recommended
