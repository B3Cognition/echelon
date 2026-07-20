from __future__ import annotations

import json

import pytest

from echelon.cli import _cmd_re_check_domain
from tests.unit.test_re_publication import write_valid_re_run


def test_check_domain_reports_pass_for_a_valid_staged_spec(
    tmp_path, monkeypatch, capsys
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    monkeypatch.chdir(tmp_path)

    _cmd_re_check_domain([run_dir.name, "api", "001-re-domain"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True


def test_check_domain_exits_nonzero_and_reports_failures(
    tmp_path, monkeypatch, capsys
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text("# Architecture summary\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_re_check_domain([run_dir.name, "api", "001-re-domain"])

    assert exc_info.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is False
    assert payload["failures"][0]["domain_id"] == "001-re-domain"


def test_check_domain_reports_semantic_preflight_failure(
    tmp_path, monkeypatch, capsys
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace(
            "## Behavior Coverage", "## Removed Behavior Coverage"
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_re_check_domain([run_dir.name, "api", "001-re-domain"])

    assert exc_info.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    finding = payload["failures"][0]["semantic_preflight_findings"][0]
    assert finding["code"] == "behavior_coverage_missing"
