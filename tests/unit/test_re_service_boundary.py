from typer.testing import CliRunner


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
