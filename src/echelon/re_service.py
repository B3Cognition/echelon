from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReRunRequest:
    depth: str | None = None
    re_policy: str = "changed"
    re_max_inner: int | None = None
    profile: str | None = None
    re_token_limit: int | None = None
    re_time_limit_minutes: int | None = None
    reset: bool = False
    no_reuse: bool = False
    engine: str | None = None
    shadow: bool = False
    goals: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReRefreshRequest:
    sources: tuple[str, ...] = ()
    depth: str | None = None
    re_token_limit: int | None = None
    re_time_limit_minutes: int | None = None


@dataclass(frozen=True)
class ReDeepenRequest:
    target_layer: str
    all_sources: bool = False
    sources: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    from_run: str | None = None
    token_limit: int | None = None
    active_ms_limit: int | None = None
    semantic_token_limit: int | None = None
    semantic_active_ms_limit: int | None = None
    new_audit_epoch: bool = False
    shadow: bool = False


@dataclass(frozen=True)
class ReStatusRequest:
    run_id: str | None = None
    as_json: bool = False


@dataclass(frozen=True)
class ReContinueRequest:
    run_id: str | None = None
    re_max_inner: int | None = None
    re_token_limit: int | None = None
    re_time_limit_minutes: int | None = None
    re_semantic_token_limit: int | None = None
    re_semantic_time_limit_minutes: int | None = None


@dataclass(frozen=True)
class ReResumeRequest:
    answer: str | None = None
    recommended: bool = False
    banzai: bool = False
    re_max_inner: int | None = None
    re_token_limit: int | None = None
    re_time_limit_minutes: int | None = None
    re_semantic_token_limit: int | None = None
    re_semantic_time_limit_minutes: int | None = None


@dataclass(frozen=True)
class RePublishRequest:
    run_id: str
    allow_partial: bool = False
    commit: bool = False


@dataclass(frozen=True)
class ReFinalizeRequest:
    run_id: str | None = None
    allow_partial: bool = False


@dataclass(frozen=True)
class ReSynthesizeRequest:
    run_id: str | None = None
    allow_partial: bool = False
    re_token_limit: int | None = None
    re_time_limit_minutes: int | None = None
    from_run: str | None = None
    accept_partial: tuple[str, ...] = ()
    token_limit: int | None = None
    active_ms_limit: int | None = None


def _legacy_kernel():
    from echelon import cli

    return cli


def _append_option(args: list[str], name: str, value: object | None) -> None:
    if value is not None:
        args.extend((name, str(value)))


def run_re(request: ReRunRequest) -> None:
    legacy = bool(
        request.engine is not None
        or request.shadow
        or request.goals
        or request.re_max_inner is not None
        or request.profile is not None
        or request.reset
        or request.no_reuse
        or request.re_policy != "changed"
    )
    if not legacy:
        args: list[str] = []
        _append_option(args, "--depth", request.depth)
        _append_option(args, "--re-token-limit", request.re_token_limit)
        _append_option(
            args,
            "--re-time-limit-minutes",
            request.re_time_limit_minutes,
        )
        _legacy_kernel()._cmd_re_knowledge_run(args)
        return

    args = ["--re-policy", request.re_policy]
    _append_option(args, "--profile", request.profile)
    _append_option(args, "--re-max-inner", request.re_max_inner)
    _append_option(args, "--re-token-limit", request.re_token_limit)
    _append_option(
        args,
        "--re-time-limit-minutes",
        request.re_time_limit_minutes,
    )
    if request.reset:
        args.append("--reset")
    if request.no_reuse:
        args.append("--no-reuse")
    _append_option(args, "--engine", request.engine)
    if request.goals:
        args.extend(("--goal", request.goals[0]))
    if request.shadow:
        args.append("--shadow")
    _legacy_kernel()._cmd_re_run(args)


def refresh_re(request: ReRefreshRequest) -> None:
    args: list[str] = []
    for source_id in request.sources:
        args.extend(("--source", source_id))
    _append_option(args, "--depth", request.depth)
    _append_option(args, "--re-token-limit", request.re_token_limit)
    _append_option(
        args,
        "--re-time-limit-minutes",
        request.re_time_limit_minutes,
    )
    _legacy_kernel()._cmd_re_knowledge_refresh(args)


def deepen_re(request: ReDeepenRequest) -> None:
    args = ["--to", request.target_layer]
    if request.all_sources:
        args.append("--all")
    for source_id in request.sources:
        args.extend(("--source", source_id))
    for domain_id in request.domains:
        args.extend(("--domain", domain_id))
    _append_option(args, "--from-run", request.from_run)
    _append_option(args, "--token-limit", request.token_limit)
    _append_option(args, "--active-ms-limit", request.active_ms_limit)
    _append_option(args, "--semantic-token-limit", request.semantic_token_limit)
    _append_option(
        args,
        "--semantic-active-ms-limit",
        request.semantic_active_ms_limit,
    )
    if request.new_audit_epoch:
        args.append("--new-audit-epoch")
    if request.shadow:
        args.append("--shadow")
    _legacy_kernel()._cmd_re_deepen(args)


def show_re_status(request: ReStatusRequest) -> None:
    args = [request.run_id] if request.run_id else []
    if request.as_json:
        args.append("--json")
    _legacy_kernel()._cmd_re_status(args)


def continue_re(request: ReContinueRequest) -> None:
    args = [request.run_id] if request.run_id else []
    _append_option(args, "--re-max-inner", request.re_max_inner)
    _append_option(args, "--re-token-limit", request.re_token_limit)
    _append_option(
        args,
        "--re-time-limit-minutes",
        request.re_time_limit_minutes,
    )
    _append_option(
        args,
        "--re-semantic-token-limit",
        request.re_semantic_token_limit,
    )
    _append_option(
        args,
        "--re-semantic-time-limit-minutes",
        request.re_semantic_time_limit_minutes,
    )
    _legacy_kernel()._cmd_re_continue(args)


def resume_re(request: ReResumeRequest) -> None:
    args = [request.answer] if request.answer is not None else []
    if request.recommended:
        args.append("--recommended")
    if request.banzai:
        args.append("--banzai")
    _append_option(args, "--re-max-inner", request.re_max_inner)
    _append_option(args, "--re-token-limit", request.re_token_limit)
    _append_option(
        args,
        "--re-time-limit-minutes",
        request.re_time_limit_minutes,
    )
    _append_option(
        args,
        "--re-semantic-token-limit",
        request.re_semantic_token_limit,
    )
    _append_option(
        args,
        "--re-semantic-time-limit-minutes",
        request.re_semantic_time_limit_minutes,
    )
    _legacy_kernel()._cmd_re_resume(args)


def publish_re(request: RePublishRequest) -> None:
    args = [request.run_id]
    if request.allow_partial:
        args.append("--allow-partial")
    if request.commit:
        args.append("--commit")
    _legacy_kernel()._cmd_re_publish(args)


def finalize_re(request: ReFinalizeRequest) -> None:
    args = [request.run_id] if request.run_id else []
    if request.allow_partial:
        args.append("--allow-partial")
    _legacy_kernel()._cmd_re_finalize(args)


def synthesize_re(request: ReSynthesizeRequest) -> None:
    args: list[str] = []
    if request.from_run is not None:
        args.extend(("--from-run", request.from_run))
        for source_id in request.accept_partial:
            args.extend(("--accept-partial", source_id))
        _append_option(args, "--token-limit", request.token_limit)
        _append_option(args, "--active-ms-limit", request.active_ms_limit)
        _legacy_kernel()._cmd_re_synthesize(args)
        return
    if request.run_id:
        args.append(request.run_id)
    if request.allow_partial:
        args.append("--allow-partial")
    _append_option(args, "--re-token-limit", request.re_token_limit)
    _append_option(
        args,
        "--re-time-limit-minutes",
        request.re_time_limit_minutes,
    )
    _legacy_kernel()._cmd_re_synthesize(args)


def execute_re_run(*, run_id: str) -> None:
    _legacy_kernel()._cmd_re_execute_run([run_id])


def check_re_domain(*, run_id: str, source_id: str, domain_id: str) -> None:
    _legacy_kernel()._cmd_re_check_domain([run_id, source_id, domain_id])
