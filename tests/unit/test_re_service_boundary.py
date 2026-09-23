import ast
import inspect

from typer.testing import CliRunner


ACTIVE_RE_CALLBACKS = {
    "re_run",
    "re_refresh",
    "re_deepen",
    "re_status",
    "re_continue",
    "re_resume",
    "re_publish",
    "re_finalize",
    "re_synthesize",
    "re_execute_run",
    "re_check_domain",
}


def test_active_re_callbacks_are_quarantined_from_legacy_cli():
    from echelon import cli_app

    forbidden = ("_legacy_cli(", "echelon import cli", "echelon.cli import")
    for callback_name in ACTIVE_RE_CALLBACKS:
        source = inspect.getsource(getattr(cli_app, callback_name))
        assert all(text not in source for text in forbidden), callback_name
    assert not hasattr(cli_app, "_legacy_cli")


def test_re_service_is_the_only_legacy_boundary_without_protocol_imports():
    from echelon import re_service

    source = inspect.getsource(re_service)
    kernel_source = inspect.getsource(re_service._legacy_kernel)
    legacy_import = "from echelon import cli"
    assert source.count(legacy_import) == 1
    assert legacy_import in kernel_source

    import_paths = [
        path
        for node in ast.walk(ast.parse(source))
        for path in (
            ([node.module] if isinstance(node, ast.ImportFrom) else [])
            + (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
        )
        if path is not None
    ]
    assert not any(path.startswith("harness.re_v2") for path in import_paths)


def test_re_run_routes_knowledge_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.re_service import ReRunRequest

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.run_re",
        lambda request: calls.append(request),
    )
    result = CliRunner().invoke(
        app,
        ["re", "run", "--depth", "deep", "--re-token-limit", "9000"],
    )
    assert result.exit_code == 0
    assert calls == [ReRunRequest(depth="deep", re_token_limit=9000)]


def test_re_run_routes_legacy_protocol_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.re_service import ReRunRequest

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.run_re",
        lambda request: calls.append(request),
    )
    result = CliRunner().invoke(
        app,
        [
            "re",
            "run",
            "--engine",
            "v2",
            "--goal",
            "inventory",
            "--profile",
            "high",
            "--shadow",
        ],
    )
    assert result.exit_code == 0
    assert calls == [
        ReRunRequest(
            profile="high",
            engine="v2",
            shadow=True,
            goals=("inventory",),
        )
    ]


def test_re_refresh_routes_typed_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.re_service import ReRefreshRequest

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.refresh_re",
        lambda request: calls.append(request),
    )
    result = CliRunner().invoke(
        app,
        [
            "re",
            "refresh",
            "--source",
            "api",
            "--source",
            "web",
            "--depth",
            "quick",
            "--re-time-limit-minutes",
            "12",
        ],
    )
    assert result.exit_code == 0
    assert calls == [
        ReRefreshRequest(
            sources=("api", "web"),
            depth="quick",
            re_time_limit_minutes=12,
        )
    ]


def test_re_deepen_routes_typed_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.re_service import ReDeepenRequest

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.deepen_re",
        lambda request: calls.append(request),
    )
    result = CliRunner().invoke(
        app,
        [
            "re",
            "deepen",
            "--to",
            "L3",
            "--source",
            "api",
            "--domain",
            "billing",
            "--semantic-token-limit",
            "4000",
            "--new-audit-epoch",
        ],
    )
    assert result.exit_code == 0
    assert calls == [
        ReDeepenRequest(
            target_layer="L3",
            sources=("api",),
            domains=("billing",),
            semantic_token_limit=4000,
            new_audit_epoch=True,
        )
    ]


def test_re_status_routes_typed_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.re_service import ReStatusRequest

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.show_re_status",
        lambda request: calls.append(request),
    )
    result = CliRunner().invoke(app, ["re", "status", "re-123", "--json"])
    assert result.exit_code == 0
    assert calls == [ReStatusRequest(run_id="re-123", as_json=True)]


def test_re_continue_routes_typed_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.re_service import ReContinueRequest

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.continue_re",
        lambda request: calls.append(request),
    )
    result = CliRunner().invoke(
        app,
        [
            "re",
            "continue",
            "re-123",
            "--re-max-inner",
            "3",
            "--re-token-limit",
            "9000",
            "--re-time-limit-minutes",
            "12",
            "--re-semantic-token-limit",
            "4000",
            "--re-semantic-time-limit-minutes",
            "6",
        ],
    )
    assert result.exit_code == 0
    assert calls == [
        ReContinueRequest(
            run_id="re-123",
            re_max_inner=3,
            re_token_limit=9000,
            re_time_limit_minutes=12,
            re_semantic_token_limit=4000,
            re_semantic_time_limit_minutes=6,
        )
    ]


def test_re_resume_routes_typed_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.re_service import ReResumeRequest

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.resume_re",
        lambda request: calls.append(request),
    )
    result = CliRunner().invoke(
        app,
        [
            "re",
            "resume",
            "Use option 1",
            "--re-max-inner",
            "3",
            "--re-token-limit",
            "9000",
        ],
    )
    assert result.exit_code == 0
    assert calls == [
        ReResumeRequest(
            answer="Use option 1",
            recommended=False,
            banzai=False,
            re_max_inner=3,
            re_token_limit=9000,
        )
    ]


def test_re_publish_routes_typed_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.re_service import RePublishRequest

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.publish_re",
        lambda request: calls.append(request),
    )
    result = CliRunner().invoke(
        app,
        ["re", "publish", "re-123", "--allow-partial", "--commit"],
    )
    assert result.exit_code == 0
    assert calls == [
        RePublishRequest(run_id="re-123", allow_partial=True, commit=True)
    ]


def test_re_finalize_routes_typed_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.re_service import ReFinalizeRequest

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.finalize_re",
        lambda request: calls.append(request),
    )
    result = CliRunner().invoke(
        app,
        ["re", "finalize", "re-123", "--allow-partial"],
    )
    assert result.exit_code == 0
    assert calls == [ReFinalizeRequest(run_id="re-123", allow_partial=True)]


def test_re_synthesize_routes_typed_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.re_service import ReSynthesizeRequest

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.synthesize_re",
        lambda request: calls.append(request),
    )
    result = CliRunner().invoke(
        app,
        [
            "re",
            "synthesize",
            "--from-run",
            "re-123",
            "--accept-partial",
            "api",
            "--accept-partial",
            "web",
            "--token-limit",
            "5000",
            "--active-ms-limit",
            "60000",
        ],
    )
    assert result.exit_code == 0
    assert calls == [
        ReSynthesizeRequest(
            from_run="re-123",
            accept_partial=("api", "web"),
            token_limit=5000,
            active_ms_limit=60000,
        )
    ]


def test_re_execute_run_routes_keyword_identifiers(monkeypatch):
    from echelon.cli_app import app

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.execute_re_run",
        lambda **kwargs: calls.append(kwargs),
    )
    result = CliRunner().invoke(app, ["re", "execute-run", "re-123"])
    assert result.exit_code == 0
    assert calls == [{"run_id": "re-123"}]


def test_re_check_domain_routes_keyword_identifiers(monkeypatch):
    from echelon.cli_app import app

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.check_re_domain",
        lambda **kwargs: calls.append(kwargs),
    )
    result = CliRunner().invoke(
        app,
        ["re", "check-domain", "re-123", "api", "billing"],
    )
    assert result.exit_code == 0
    assert calls == [
        {"run_id": "re-123", "source_id": "api", "domain_id": "billing"}
    ]


def test_run_re_selects_knowledge_handler_and_preserves_limits(monkeypatch):
    from types import SimpleNamespace

    from echelon.re_service import ReRunRequest, run_re

    calls = []
    kernel = SimpleNamespace(
        _cmd_re_knowledge_run=lambda args: calls.append(("knowledge", args)),
        _cmd_re_run=lambda args: calls.append(("legacy", args)),
    )
    monkeypatch.setattr("echelon.re_service._legacy_kernel", lambda: kernel)
    run_re(
        ReRunRequest(
            depth="deep",
            re_token_limit=9000,
            re_time_limit_minutes=12,
        )
    )
    assert calls == [
        (
            "knowledge",
            [
                "--depth",
                "deep",
                "--re-token-limit",
                "9000",
                "--re-time-limit-minutes",
                "12",
            ],
        )
    ]


def test_run_re_selects_legacy_handler_and_preserves_order(monkeypatch):
    from types import SimpleNamespace

    from echelon.re_service import ReRunRequest, run_re

    calls = []
    kernel = SimpleNamespace(
        _cmd_re_knowledge_run=lambda args: calls.append(("knowledge", args)),
        _cmd_re_run=lambda args: calls.append(("legacy", args)),
    )
    monkeypatch.setattr("echelon.re_service._legacy_kernel", lambda: kernel)
    run_re(
        ReRunRequest(
            re_policy="refresh-all",
            re_max_inner=3,
            profile="high",
            reset=True,
            no_reuse=True,
            engine="v2",
            shadow=True,
            goals=("inventory",),
        )
    )
    assert calls == [
        (
            "legacy",
            [
                "--re-policy",
                "refresh-all",
                "--profile",
                "high",
                "--re-max-inner",
                "3",
                "--reset",
                "--no-reuse",
                "--engine",
                "v2",
                "--goal",
                "inventory",
                "--shadow",
            ],
        )
    ]


def test_refresh_re_preserves_legacy_argument_order(monkeypatch):
    from types import SimpleNamespace

    from echelon.re_service import ReRefreshRequest, refresh_re

    calls = []
    kernel = SimpleNamespace(
        _cmd_re_knowledge_refresh=lambda args: calls.append(args),
    )
    monkeypatch.setattr("echelon.re_service._legacy_kernel", lambda: kernel)
    refresh_re(
        ReRefreshRequest(
            sources=("api", "web"),
            depth="quick",
            re_token_limit=3000,
            re_time_limit_minutes=8,
        )
    )
    assert calls == [
        [
            "--source",
            "api",
            "--source",
            "web",
            "--depth",
            "quick",
            "--re-token-limit",
            "3000",
            "--re-time-limit-minutes",
            "8",
        ]
    ]


def test_deepen_re_preserves_legacy_argument_order(monkeypatch):
    from types import SimpleNamespace

    from echelon.re_service import ReDeepenRequest, deepen_re

    calls = []
    kernel = SimpleNamespace(_cmd_re_deepen=lambda args: calls.append(args))
    monkeypatch.setattr("echelon.re_service._legacy_kernel", lambda: kernel)
    deepen_re(
        ReDeepenRequest(
            target_layer="L3",
            sources=("api",),
            domains=("billing",),
            from_run="re-parent",
            token_limit=5000,
            active_ms_limit=60000,
            semantic_token_limit=2500,
            semantic_active_ms_limit=30000,
            new_audit_epoch=True,
        )
    )
    assert calls == [
        [
            "--to",
            "L3",
            "--source",
            "api",
            "--domain",
            "billing",
            "--from-run",
            "re-parent",
            "--token-limit",
            "5000",
            "--active-ms-limit",
            "60000",
            "--semantic-token-limit",
            "2500",
            "--semantic-active-ms-limit",
            "30000",
            "--new-audit-epoch",
        ]
    ]


def test_show_re_status_preserves_legacy_argument_order(monkeypatch):
    from types import SimpleNamespace

    from echelon.re_service import ReStatusRequest, show_re_status

    calls = []
    kernel = SimpleNamespace(_cmd_re_status=lambda args: calls.append(args))
    monkeypatch.setattr("echelon.re_service._legacy_kernel", lambda: kernel)
    show_re_status(ReStatusRequest(run_id="re-123", as_json=True))
    assert calls == [["re-123", "--json"]]


def test_continue_re_preserves_legacy_argument_order(monkeypatch):
    from types import SimpleNamespace

    from echelon.re_service import ReContinueRequest, continue_re

    calls = []
    kernel = SimpleNamespace(_cmd_re_continue=lambda args: calls.append(args))
    monkeypatch.setattr("echelon.re_service._legacy_kernel", lambda: kernel)
    continue_re(
        ReContinueRequest(
            run_id="re-123",
            re_max_inner=3,
            re_token_limit=9000,
            re_time_limit_minutes=12,
            re_semantic_token_limit=4000,
            re_semantic_time_limit_minutes=6,
        )
    )
    assert calls == [
        [
            "re-123",
            "--re-max-inner",
            "3",
            "--re-token-limit",
            "9000",
            "--re-time-limit-minutes",
            "12",
            "--re-semantic-token-limit",
            "4000",
            "--re-semantic-time-limit-minutes",
            "6",
        ]
    ]


def test_resume_re_preserves_legacy_argument_order(monkeypatch):
    from types import SimpleNamespace

    from echelon.re_service import ReResumeRequest, resume_re

    calls = []
    kernel = SimpleNamespace(_cmd_re_resume=lambda args: calls.append(args))
    monkeypatch.setattr("echelon.re_service._legacy_kernel", lambda: kernel)
    resume_re(
        ReResumeRequest(
            answer="Use option 1",
            recommended=True,
            re_max_inner=3,
            re_token_limit=9000,
            re_time_limit_minutes=12,
            re_semantic_token_limit=4000,
            re_semantic_time_limit_minutes=6,
        )
    )
    assert calls == [
        [
            "Use option 1",
            "--recommended",
            "--re-max-inner",
            "3",
            "--re-token-limit",
            "9000",
            "--re-time-limit-minutes",
            "12",
            "--re-semantic-token-limit",
            "4000",
            "--re-semantic-time-limit-minutes",
            "6",
        ]
    ]


def test_publish_re_preserves_legacy_argument_order(monkeypatch):
    from types import SimpleNamespace

    from echelon.re_service import RePublishRequest, publish_re

    calls = []
    kernel = SimpleNamespace(_cmd_re_publish=lambda args: calls.append(args))
    monkeypatch.setattr("echelon.re_service._legacy_kernel", lambda: kernel)
    publish_re(
        RePublishRequest(run_id="re-123", allow_partial=True, commit=True)
    )
    assert calls == [["re-123", "--allow-partial", "--commit"]]


def test_finalize_re_preserves_legacy_argument_order(monkeypatch):
    from types import SimpleNamespace

    from echelon.re_service import ReFinalizeRequest, finalize_re

    calls = []
    kernel = SimpleNamespace(_cmd_re_finalize=lambda args: calls.append(args))
    monkeypatch.setattr("echelon.re_service._legacy_kernel", lambda: kernel)
    finalize_re(ReFinalizeRequest(run_id="re-123", allow_partial=True))
    assert calls == [["re-123", "--allow-partial"]]


def test_synthesize_re_preserves_legacy_argument_order(monkeypatch):
    from types import SimpleNamespace

    from echelon.re_service import ReSynthesizeRequest, synthesize_re

    calls = []
    kernel = SimpleNamespace(_cmd_re_synthesize=lambda args: calls.append(args))
    monkeypatch.setattr("echelon.re_service._legacy_kernel", lambda: kernel)
    synthesize_re(
        ReSynthesizeRequest(
            run_id="re-123",
            allow_partial=True,
            re_token_limit=9000,
            re_time_limit_minutes=12,
        )
    )
    assert calls == [
        [
            "re-123",
            "--allow-partial",
            "--re-token-limit",
            "9000",
            "--re-time-limit-minutes",
            "12",
        ]
    ]


def test_synthesize_re_preserves_protocol_27_argument_order(monkeypatch):
    from types import SimpleNamespace

    from echelon.re_service import ReSynthesizeRequest, synthesize_re

    calls = []
    kernel = SimpleNamespace(_cmd_re_synthesize=lambda args: calls.append(args))
    monkeypatch.setattr("echelon.re_service._legacy_kernel", lambda: kernel)
    synthesize_re(
        ReSynthesizeRequest(
            from_run="re-parent",
            accept_partial=("api", "web"),
            token_limit=5000,
            active_ms_limit=60000,
        )
    )
    assert calls == [
        [
            "--from-run",
            "re-parent",
            "--accept-partial",
            "api",
            "--accept-partial",
            "web",
            "--token-limit",
            "5000",
            "--active-ms-limit",
            "60000",
        ]
    ]


def test_execute_re_run_preserves_legacy_argument_order(monkeypatch):
    from types import SimpleNamespace

    from echelon.re_service import execute_re_run

    calls = []
    kernel = SimpleNamespace(_cmd_re_execute_run=lambda args: calls.append(args))
    monkeypatch.setattr("echelon.re_service._legacy_kernel", lambda: kernel)
    execute_re_run(run_id="re-123")
    assert calls == [["re-123"]]


def test_check_re_domain_preserves_legacy_argument_order(monkeypatch):
    from types import SimpleNamespace

    from echelon.re_service import check_re_domain

    calls = []
    kernel = SimpleNamespace(_cmd_re_check_domain=lambda args: calls.append(args))
    monkeypatch.setattr("echelon.re_service._legacy_kernel", lambda: kernel)
    check_re_domain(run_id="re-123", source_id="api", domain_id="billing")
    assert calls == [["re-123", "api", "billing"]]
