import sys

import pytest

from echelon.re_preflight import authorize_knowledge_preflight
from harness.re_v2.knowledge_preflight import KnowledgeRequestEstimate

pytestmark = pytest.mark.unit


ESTIMATE = KnowledgeRequestEstimate(3, 76, 30_245, 1_200_000, 8,
                                    14_000_000, 28_000_000, 28_000_000)


def authorize(**kwargs):
    return authorize_knowledge_preflight(
        ESTIMATE, token_limit=5_000_000, active_ms_limit=10_800_000,
        command=("echelon", "re", "run", "--depth", "deep"), **kwargs)


def test_noninteractive_does_not_silently_authorize_larger_budget(capsys):
    with pytest.raises(ValueError, match="--re-token-limit 28000000"):
        authorize(explicit_token_limit=False)
    output = capsys.readouterr().out
    assert "whole-request" in output
    assert "heuristic" in output
    assert "180 minutes" in output


def test_explicit_lower_limit_is_honored_without_prompt(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("must not prompt"))
    assert authorize(explicit_token_limit=True) == 5_000_000
    assert "below" in capsys.readouterr().out


@pytest.mark.parametrize("answer,approved", [("yes", True), ("n", False), ("", False)])
def test_interactive_increase_requires_positive_confirmation(monkeypatch, answer, approved):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: answer)
    if approved:
        assert authorize(explicit_token_limit=False) == 28_000_000
    else:
        with pytest.raises(ValueError, match="not authorized"):
            authorize(explicit_token_limit=False)


def test_sufficient_configured_limit_needs_no_confirmation(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("must not prompt"))
    assert authorize_knowledge_preflight(
        ESTIMATE, token_limit=50_000_000, active_ms_limit=10_800_000,
        explicit_token_limit=False, command=("echelon", "re", "run")) == 50_000_000


def test_terminal_eof_is_not_approval(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    def eof(_):
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)
    with pytest.raises(ValueError, match="not authorized"):
        authorize(explicit_token_limit=False)
