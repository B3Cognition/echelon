"""Unit tests for scripts/sue_challenge.py — SUE challenge script (spec 030).

The script is loaded via importlib (ADR-008) because scripts/ is not a package.
All tests run offline: model commands are tmp_path-generated stub executables
(FR-043); no network, no live model (SC-002).

Covers tasks T-001..T-014: shared constants and dataclasses, argument handling
(FR-001..FR-004, FR-007, NFR-003), pre-flight and exit-code spine (FR-005,
FR-006, FR-012, FR-042, NFR-005), prompt assembly (FR-014, FR-015, FR-018,
FR-021, FR-022, FR-023), the isolated subprocess runner (FR-010, FR-011,
FR-043), staged tolerant extraction (FR-026, FR-027), round-1/round-2 strict
validation (FR-016, FR-017, FR-019, FR-020, FR-024, FR-025), the corrective
retry loop with debug dumps (FR-013, FR-028..FR-031), deterministic partition
plus ranking (FR-009, FR-032, FR-033), report and summary rendering (FR-035..
FR-039, FR-041, NFR-004), the wired end-to-end pipeline (FR-008, FR-020,
FR-034, FR-040, FR-042), the standalone-contract gate (FR-045, NFR-002), and
the SC-003 exit-code matrix with the NFR-001 subprocess-invocation bound.

FR-044 behavior-group coverage sweep (all 7 deterministic groups):
1. argument handling      -> TestArgumentHandling
2. prompt assembly        -> TestPromptAssembly
3. extraction             -> TestExtractJsonObject
4. validation + bijection -> TestValidateRound1, TestValidateRound2
5. filtering + ranking    -> TestPartitionAndRank
6. report rendering       -> TestRenderReport, TestRenderSummary
7. exit codes             -> TestPreflight, TestExecuteRound, TestMainPipeline,
                             TestExitCodeMatrixAndBounds
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import importlib.util
import json
import os
import shlex
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sue_challenge.py"


def _load_module(name: str = "sue_challenge"):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclasses resolves string annotations (PEP 563)
    # through sys.modules[cls.__module__].
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sue = _load_module()


def _make_stub(path: Path, body: str) -> str:
    """Write an executable /bin/sh stub honouring the stub replay contract."""
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


# ---------------------------------------------------------------------------
# T-001 — shared constants and dataclasses (contract anchor, ISS-206)
# ---------------------------------------------------------------------------


class TestConstants:
    def test_categories_exactly_five_tokens(self):
        assert sue.CATEGORIES == (
            "ambiguity",
            "hidden-assumption",
            "contradiction",
            "undefined-term",
            "missing-boundary",
        )

    def test_verdicts_exactly_three_tokens(self):
        assert sue.VERDICTS == ("ANSWERED", "UNANSWERABLE", "CONTRADICTED")

    @pytest.mark.parametrize("qid", ["Q1", "Q2", "Q15", "Q100"])
    def test_question_id_re_accepts(self, qid):
        assert sue.QUESTION_ID_RE.match(qid)

    @pytest.mark.parametrize("qid", ["Q0", "Q01", "q1", "", "Q", "Q1x", "1Q", " Q1"])
    def test_question_id_re_rejects(self, qid):
        assert sue.QUESTION_ID_RE.match(qid) is None

    def test_artifact_names(self):
        assert sue.REPORT_FILENAME == "socratic-challenge.md"
        assert sue.DEBUG_DIR_NAME == ".sue-debug"

    def test_exit_code_constants(self):
        assert sue.EXIT_SUCCESS == 0
        assert sue.EXIT_BAD_INPUT == 1
        assert sue.EXIT_MODEL_COMMAND_MISSING == 2
        assert sue.EXIT_UNUSABLE_OUTPUT == 3

    def test_prompt_templates_are_module_constants(self):
        assert "{numbered_spec}" in sue.ROUND1_PROMPT_TEMPLATE
        assert "{max_questions}" in sue.ROUND1_PROMPT_TEMPLATE
        assert "{numbered_spec}" in sue.ROUND2_PROMPT_TEMPLATE
        assert "{questions_json}" in sue.ROUND2_PROMPT_TEMPLATE


class TestDataclasses:
    @pytest.mark.parametrize(
        "name,expected_fields",
        [
            (
                "RunConfig",
                {
                    "spec_path",
                    "max_questions",
                    "model_command",
                    "timeout_seconds",
                    "model_protocol",
                    "model",
                    "reasoning_effort",
                },
            ),
            ("ModelInvocation", {"argv", "stdin_text"}),
            ("SpecDocument", {"path", "lines"}),
            ("SocraticQuestion", {"id", "question", "target", "lines", "category"}),
            ("Answer", {"id", "verdict", "answer", "evidence_lines"}),
            ("Finding", {"rank", "question", "answer"}),
            ("CallOutcome", {"kind", "stdout", "stderr", "duration_seconds"}),
            ("ParseFailure", {"reason", "is_timeout"}),
        ],
    )
    def test_entity_field_sets_match_data_model(self, name, expected_fields):
        cls = getattr(sue, name)
        assert dataclasses.is_dataclass(cls)
        assert {f.name for f in dataclasses.fields(cls)} == expected_fields

    def test_instantiation(self):
        config = sue.RunConfig(
            spec_path=Path("spec.md"),
            max_questions=15,
            model_command="claude",
            timeout_seconds=300.0,
        )
        assert config.max_questions == 15
        question = sue.SocraticQuestion(
            id="Q1", question="What?", target="general", lines=[1], category="ambiguity"
        )
        answer = sue.Answer(id="Q1", verdict="ANSWERED", answer="Yes.", evidence_lines=[1])
        finding = sue.Finding(rank=1, question=question, answer=answer)
        assert finding.rank == 1
        outcome = sue.CallOutcome(kind="ok", stdout="{}", stderr="", duration_seconds=0.1)
        assert outcome.kind == "ok"
        failure = sue.ParseFailure(reason="no JSON object found")
        assert failure.is_timeout is False

    def test_import_is_side_effect_free(self, capsys):
        _load_module("sue_challenge_reimport")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


# ---------------------------------------------------------------------------
# T-002 — argument handling (FR-044 group 1)
# ---------------------------------------------------------------------------


def _one_stderr_line(capsys) -> str:
    err = capsys.readouterr().err
    lines = [line for line in err.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected exactly 1 stderr diagnostic line, got: {err!r}"
    return lines[0]


class TestArgumentHandling:
    def test_defaults_are_15_claude_300(self, monkeypatch):
        monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
        monkeypatch.delenv("CODEX_CI", raising=False)
        monkeypatch.delenv("ECHELON_LLM", raising=False)
        config = sue.parse_args(["spec.md"])
        assert config.spec_path == Path("spec.md")
        assert config.max_questions == 15
        assert config.model_command == "claude"
        assert config.timeout_seconds == 300

    def test_codex_uses_visible_economical_model_profile(self):
        config = sue.parse_args([
            "spec.md", "--model-cmd", "codex=codex",
        ])
        assert config.model == "gpt-5.6-luna"
        assert config.reasoning_effort == "low"

    def test_codex_model_and_reasoning_can_be_overridden(self):
        config = sue.parse_args([
            "spec.md",
            "--model-cmd", "codex=codex",
            "--model", "gpt-5.6-terra",
            "--reasoning-effort", "medium",
        ])
        assert config.model == "gpt-5.6-terra"
        assert config.reasoning_effort == "medium"

    def test_non_codex_model_override_is_rejected(self, capsys):
        assert sue.main([
            "spec.md",
            "--model-cmd", "claude=claude",
            "--model", "gpt-5.6-luna",
        ]) == sue.EXIT_BAD_INPUT
        assert "--model is supported only for codex" in capsys.readouterr().err

    def test_option_overrides(self):
        config = sue.parse_args(
            ["spec.md", "--questions", "7", "--claude-cmd", "mymodel --flag", "--timeout", "42"]
        )
        assert config.max_questions == 7
        assert config.model_command == "mymodel --flag"
        assert config.timeout_seconds == 42

    def test_claude_cmd_splits_per_shell_quoting(self):
        config = sue.parse_args(["spec.md", "--claude-cmd", "claude --safe-mode"])
        assert shlex.split(config.model_command)[0] == "claude"
        config = sue.parse_args(["spec.md", "--claude-cmd", "'my cmd' --x"])
        assert shlex.split(config.model_command)[0] == "my cmd"

    def test_zero_word_claude_cmd_is_argument_error_exit_1(self, capsys):
        assert sue.main(["spec.md", "--claude-cmd", "   "]) == 1
        _one_stderr_line(capsys)

    def test_help_contains_exactly_one_egress_disclosure(self, capsys):
        assert sue.main(["--help"]) == 0
        out = capsys.readouterr().out
        assert out.count("sent to the model provider") == 1

    def test_missing_positional_is_exit_1(self, capsys):
        assert sue.main([]) == 1
        _one_stderr_line(capsys)

    def test_extra_positional_is_exit_1(self, capsys):
        assert sue.main(["a.md", "b.md"]) == 1
        _one_stderr_line(capsys)

    @pytest.mark.parametrize(
        "extra",
        [
            ["--questions", "0"],
            ["--questions", "-1"],
            ["--timeout", "0"],
            ["--timeout", "-1"],
        ],
    )
    def test_non_positive_numeric_options_exit_1(self, extra, capsys):
        # ISS-308: RunConfig bounds are > 0 for both numeric options.
        assert sue.main(["spec.md", *extra]) == 1
        _one_stderr_line(capsys)

    def test_unbalanced_quote_claude_cmd_is_argument_error_exit_1(self, capsys):
        # shlex.split raises ValueError on unbalanced quotes; that must surface
        # as the exit-1 bad-input class with 1 diagnostic line, not a traceback.
        assert sue.main(["spec.md", "--claude-cmd", "claude '"]) == 1
        _one_stderr_line(capsys)

    @pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
    def test_non_finite_timeout_is_argument_error(self, value, capsys):
        # nan/inf would corrupt or disable the per-call budget arithmetic.
        with pytest.raises(sue.ArgumentFailure):
            sue.parse_args(["spec.md", "--timeout", value])
        assert sue.main(["spec.md", "--timeout", value]) == 1
        _one_stderr_line(capsys)

    def test_sub_second_timeout_parses_as_float_seconds(self):
        # ISS-305: the timeout test matrix drives 0.2-0.5 s budgets.
        config = sue.parse_args(["spec.md", "--timeout", "0.3"])
        assert config.timeout_seconds == pytest.approx(0.3)

    def test_argument_errors_never_surface_as_exit_2(self, capsys):
        # U-007: exit 2 is reserved for executable-not-found.
        for argv in [[], ["--questions", "x", "spec.md"], ["spec.md", "--claude-cmd", ""]]:
            assert sue.main(argv) == 1
            capsys.readouterr()


# ---------------------------------------------------------------------------
# T-003 — pre-flight, fail() choke point, exit-code spine (AC-013/AC-014/AC-019)
# ---------------------------------------------------------------------------


class TestPreflight:
    def _call_marker_stub(self, tmp_path: Path) -> tuple[str, Path]:
        """Stub that records that a model call was launched."""
        marker = tmp_path / "model-was-called"
        stub = _make_stub(
            tmp_path / "marker-stub.sh",
            f'cat > /dev/null\ntouch "{marker}"\necho "{{}}"\n',
        )
        return stub, marker

    def test_missing_spec_exit_1_zero_model_calls(self, tmp_path, capsys):
        stub, marker = self._call_marker_stub(tmp_path)
        rc = sue.main([str(tmp_path / "absent.md"), "--claude-cmd", shlex.quote(stub)])
        assert rc == 1
        assert not marker.exists()
        _one_stderr_line(capsys)

    def test_empty_spec_exit_1_zero_model_calls(self, tmp_path, capsys):
        """FR-005: a whitespace-only specification is unchallengeable."""
        spec = tmp_path / "spec.md"
        spec.write_text("  \n\n\t\n")
        stub, marker = self._call_marker_stub(tmp_path)
        rc = sue.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 1
        assert not marker.exists()
        _one_stderr_line(capsys)

    def test_spec_named_as_report_exit_1_never_overwritten(self, tmp_path, capsys):
        """FR-034/FR-042 collision: challenging a file named socratic-challenge.md
        must exit 1 before any model call, leaving the file byte-identical."""
        spec = tmp_path / sue.REPORT_FILENAME
        original = "# A previous report being (wrongly) challenged\n"
        spec.write_text(original)
        stub, marker = self._call_marker_stub(tmp_path)
        rc = sue.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 1
        assert not marker.exists()
        assert spec.read_text() == original
        _one_stderr_line(capsys)

    def test_spec_path_is_directory_exit_1(self, tmp_path, capsys):
        stub, marker = self._call_marker_stub(tmp_path)
        rc = sue.main([str(tmp_path), "--claude-cmd", shlex.quote(stub)])
        assert rc == 1
        assert not marker.exists()
        _one_stderr_line(capsys)

    @pytest.mark.skipif(os.geteuid() == 0, reason="permission checks are bypassed as root")
    def test_unreadable_spec_exit_1_zero_model_calls(self, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text("# Spec\n")
        spec.chmod(0o000)
        stub, marker = self._call_marker_stub(tmp_path)
        try:
            rc = sue.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        finally:
            spec.chmod(0o644)
        assert rc == 1
        assert not marker.exists()
        _one_stderr_line(capsys)

    @pytest.mark.skipif(os.geteuid() == 0, reason="permission checks are bypassed as root")
    def test_readonly_spec_dir_exit_1_zero_model_calls(self, tmp_path, capsys):
        spec_dir = tmp_path / "locked"
        spec_dir.mkdir()
        spec = spec_dir / "spec.md"
        spec.write_text("# Spec\n")
        stub, marker = self._call_marker_stub(tmp_path)
        spec_dir.chmod(0o555)
        try:
            rc = sue.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        finally:
            spec_dir.chmod(0o755)
        assert rc == 1
        assert not marker.exists()
        _one_stderr_line(capsys)

    def test_missing_executable_exit_2_with_one_install_pointer(self, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text("# Spec\n")
        rc = sue.main([str(spec), "--claude-cmd", "sue-missing-cmd-98765"])
        assert rc == 2
        line = _one_stderr_line(capsys)
        assert line.lower().count("install") == 1
        assert not (tmp_path / sue.REPORT_FILENAME).exists()

    def test_preflight_checks_readable_before_executable(self, tmp_path, capsys):
        # Missing spec AND missing executable: the readable check wins (exit 1).
        rc = sue.main([str(tmp_path / "absent.md"), "--claude-cmd", "sue-missing-cmd-98765"])
        assert rc == 1
        capsys.readouterr()

    @pytest.mark.skipif(os.geteuid() == 0, reason="permission checks are bypassed as root")
    def test_preflight_checks_writable_before_executable(self, tmp_path, capsys):
        spec_dir = tmp_path / "locked"
        spec_dir.mkdir()
        spec = spec_dir / "spec.md"
        spec.write_text("# Spec\n")
        spec_dir.chmod(0o555)
        try:
            rc = sue.main([str(spec), "--claude-cmd", "sue-missing-cmd-98765"])
        finally:
            spec_dir.chmod(0o755)
        assert rc == 1
        capsys.readouterr()

    def test_spec_file_never_written_on_preflight_failure(self, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        content = "# Spec\nA line.\n"
        spec.write_text(content)
        sue.main([str(spec), "--claude-cmd", "sue-missing-cmd-98765"])
        assert spec.read_text() == content
        capsys.readouterr()


class TestLoadSpec:
    def test_lines_are_newline_stripped_and_ordered(self, tmp_path):
        spec = tmp_path / "spec.md"
        spec.write_text("first\nsecond\n\nfourth\n")
        doc = sue.load_spec(spec)
        assert doc.path == spec
        assert doc.lines == ["first", "second", "", "fourth"]

    def test_undecodable_bytes_are_replaced_not_fatal(self, tmp_path):
        # ISS-210: a decodable-with-replacement file proceeds.
        spec = tmp_path / "spec.md"
        spec.write_bytes(b"good line\n\xff\xfe bad bytes\n")
        doc = sue.load_spec(spec)
        assert doc.lines[0] == "good line"
        assert "�" in doc.lines[1]


# ---------------------------------------------------------------------------
# T-004 — prompt assembly (FR-044 group 2)
# ---------------------------------------------------------------------------


def _neutral_doc() -> "sue.SpecDocument":
    # Fixture lines deliberately avoid the 5 category tokens so leakage
    # assertions on the round-2 prompt are meaningful.
    return sue.SpecDocument(
        path=Path("fixture.md"),
        lines=["# Fixture", "", "- **FR-001**: The system does X.", "A closing line."],
    )


class TestPromptAssembly:
    def test_numbered_text_is_one_based_and_covers_every_line(self):
        doc = sue.SpecDocument(path=Path("f.md"), lines=["alpha", "beta", "gamma"])
        assert sue.numbered_text(doc) == "1: alpha\n2: beta\n3: gamma"

    def test_numbered_text_empty_spec(self):
        doc = sue.SpecDocument(path=Path("f.md"), lines=[])
        assert sue.numbered_text(doc) == ""

    def test_round1_prompt_carries_numbered_spec_and_instruction(self):
        doc = _neutral_doc()
        prompt = sue.build_round1_prompt(doc, 15)
        assert "1: # Fixture" in prompt
        assert "4: A closing line." in prompt
        assert "at most 15" in prompt
        for token in sue.CATEGORIES:
            assert token in prompt
        assert "JSON" in prompt

    def test_round1_prompt_respects_configured_cap(self):
        prompt = sue.build_round1_prompt(_neutral_doc(), 7)
        assert "at most 7" in prompt
        assert "at most 15" not in prompt

    def test_round2_prompt_carries_both_content_blocks(self):
        doc = _neutral_doc()
        pairs = [("Q1", "What does X mean?"), ("Q2", "Where is the edge of X?")]
        prompt = sue.build_round2_prompt(doc, pairs)
        assert "1: # Fixture" in prompt
        assert '"id": "Q1"' in prompt
        assert '"question": "What does X mean?"' in prompt
        assert '"id": "Q2"' in prompt
        for verdict in sue.VERDICTS:
            assert verdict in prompt

    def test_round2_prompt_has_zero_round1_leakage(self):
        # AC-011 counting convention: zero category tokens, zero targets,
        # zero line arrays, zero round-1 reasoning in the round-2 prompt.
        doc = _neutral_doc()
        prompt = sue.build_round2_prompt(doc, [("Q1", "A probing question?")])
        for token in sue.CATEGORIES:
            assert token not in prompt
        assert "category" not in prompt
        assert "target" not in prompt
        # Distinctive round-1-only values can never appear: the builder only
        # receives (id, question) pairs (FR-022 structural guarantee).
        assert "FR-777" not in prompt
        assert "[101, 202]" not in prompt


# ---------------------------------------------------------------------------
# T-005 — isolated subprocess runner (AC-011, AC-012, FR-010, FR-011, FR-043)
# ---------------------------------------------------------------------------


class TestRunModelCall:
    def _config(self, tmp_path: Path, command: str, timeout: float = 10.0):
        return sue.RunConfig(
            spec_path=tmp_path / "spec.md",
            max_questions=15,
            model_command=command,
            timeout_seconds=timeout,
        )

    def test_codex_round_invocation_uses_schema_and_final_output(self, tmp_path, monkeypatch):
        captured = {}

        def fake_run(request):
            captured["request"] = request
            final_output = '{"questions":[]}'
            return sue.runner.ColdReaderResult(
                run_id=request.run_id,
                status="success",
                provider=request.provider,
                model_requested=request.model,
                model_reported=request.model,
                reasoning_effort=request.reasoning_effort,
                protocol="codex-stdin",
                argv_redacted=("codex", "exec", "-"),
                duration_seconds=0.1,
                exit_code=0,
                raw_output="",
                final_output=final_output,
                stderr="",
                raw_output_digest=hashlib.sha256(b"").hexdigest(),
                final_output_digest=hashlib.sha256(final_output.encode()).hexdigest(),
                usage=None,
            )

        monkeypatch.setattr(sue.runner, "run_cold_reader", fake_run)
        config = sue.RunConfig(
            spec_path=tmp_path / "spec.md",
            max_questions=1,
            model_command="codex",
            timeout_seconds=10,
            model_protocol="codex-stdin",
            model="gpt-5.6-luna",
            reasoning_effort="low",
        )

        outcome = sue.run_model_call(
            config, "PROMPT", output_schema=sue.ROUND1_OUTPUT_SCHEMA
        )

        assert outcome.stdout == '{"questions":[]}'
        assert captured["request"].model == "gpt-5.6-luna"
        assert captured["request"].reasoning_effort == "low"
        assert captured["request"].output_schema == sue.ROUND1_OUTPUT_SCHEMA

    def test_claude_and_copilot_calls_do_not_use_codex_runner(self, tmp_path, monkeypatch):
        def unexpected_runner_call(_request):
            raise AssertionError("only Codex calls may use sue_runner")

        monkeypatch.setattr(sue.runner, "run_cold_reader", unexpected_runner_call)
        claude = _make_stub(tmp_path / "claude.sh", 'cat > /dev/null\necho claude')
        copilot = _make_stub(tmp_path / "copilot.sh", 'echo copilot')

        claude_outcome = sue.run_model_call(
            sue.RunConfig(tmp_path / "spec.md", 1, shlex.quote(claude), 10), "PROMPT"
        )
        copilot_outcome = sue.run_model_call(
            sue.RunConfig(
                tmp_path / "spec.md", 1, shlex.quote(copilot), 10,
                model_protocol="copilot-argv",
            ),
            "PROMPT",
        )

        assert claude_outcome.kind == "ok"
        assert copilot_outcome.kind == "ok"

    def test_rounds_receive_distinct_strict_output_schemas(self, tmp_path, monkeypatch):
        spec = tmp_path / "spec.md"
        spec.write_text("# Spec\nA requirement.\n")
        schemas = []
        question = sue.SocraticQuestion(
            id="Q1", question="What?", target="general", lines=[1], category="ambiguity"
        )
        answer = sue.Answer(
            id="Q1", verdict="ANSWERED", answer="The text says so.", evidence_lines=[1]
        )

        def fake_execute(_config, _prompt, _validator, round_no, _spec_dir, output_schema=None):
            schemas.append(output_schema)
            return ([question], False) if round_no == 1 else [answer]

        monkeypatch.setattr(sue, "preflight", lambda _config: None)
        monkeypatch.setattr(sue, "execute_round", fake_execute)

        assert sue.main([str(spec), "--claude-cmd", "claude"]) == sue.EXIT_SUCCESS
        assert schemas == [sue.ROUND1_OUTPUT_SCHEMA, sue.ROUND2_OUTPUT_SCHEMA]
        assert schemas[0] != schemas[1]
        assert schemas[0]["required"] == ["questions"]
        assert schemas[1]["required"] == ["answers"]

    def test_explicit_selection_overrides_all_env_signals(self):
        # Design test 1: explicit beats ECHELON_LLM and runtime markers.
        env = {"ECHELON_LLM": "claude", "CODEX_THREAD_ID": "t-1"}
        command, protocol = sue.resolve_model_command("codex=mycodex", env)
        assert (command, protocol) == ("mycodex", "codex-stdin")

    def test_echelon_llm_codex_selects_codex_protocol(self):
        command, protocol = sue.resolve_model_command(None, {"ECHELON_LLM": "codex"})
        assert (command, protocol) == ("codex", "codex-stdin")

    def test_codex_thread_marker_selects_codex_without_echelon_llm(self):
        command, protocol = sue.resolve_model_command(None, {"CODEX_THREAD_ID": "t"})
        assert protocol == "codex-stdin"

    def test_claude_fallback_without_signals(self):
        command, protocol = sue.resolve_model_command(None, {})
        assert (command, protocol) == ("claude", "claude-stdin")

    def test_invalid_echelon_llm_falls_through_to_markers(self):
        command, protocol = sue.resolve_model_command(
            None, {"ECHELON_LLM": "gemini", "CODEX_CI": "1"})
        assert protocol == "codex-stdin"

    def test_env_copilot_is_ignored_with_warning(self, capsys):
        # Review finding 2: argv-transport providers must be explicit — an
        # ambient env var must never silently enable prompt-in-argv exposure.
        command, protocol = sue.resolve_model_command(
            None, {"ECHELON_LLM": "copilot"})
        assert (command, protocol) == ("claude", "claude-stdin")
        assert "ECHELON_LLM=copilot ignored" in capsys.readouterr().err

    def test_unsupported_explicit_prefix_fails_before_subprocess(self):
        with pytest.raises(sue.ArgumentFailure, match="unsupported model provider"):
            sue.resolve_model_command("gemini=gemini", {})

    def test_unknown_bare_basename_keeps_claude_stdin_protocol(self, tmp_path):
        command, protocol = sue.resolve_model_command("/x/stub.sh --flag", {})
        assert protocol == "claude-stdin"

    def test_codex_invocation_uses_stdin_and_isolated_exec_args(self, tmp_path):
        # Design test 5: prompt on stdin, ephemeral read-only exec sandbox.
        config = sue.RunConfig(
            spec_path=tmp_path / "spec.md", max_questions=1,
            model_command="codex", timeout_seconds=10,
            model_protocol="codex-stdin",
        )
        invocation = sue.build_model_invocation(config, "PROMPT")
        assert invocation.argv == [
            "codex", "exec", "--ephemeral", "--skip-git-repo-check",
            "--sandbox", "read-only", "-",
        ]
        assert invocation.stdin_text == "PROMPT"

    def test_model_cmd_and_claude_cmd_are_aliases(self, tmp_path):
        spec = tmp_path / "spec.md"
        spec.write_text("# s\n")
        for flag in ("--model-cmd", "--claude-cmd"):
            config = sue.parse_args([str(spec), flag, "claude=/x/claude"])
            assert config.model_command == "/x/claude"
            assert config.model_protocol == "claude-stdin"

    def test_claude_model_invocation_uses_stdin_and_one_print_flag(self, tmp_path):
        config = self._config(tmp_path, "claude")
        invocation = sue.build_model_invocation(config, "PROMPT")
        assert invocation.argv == ["claude", "-p"]
        assert invocation.stdin_text == "PROMPT"

    def test_copilot_model_invocation_passes_prompt_as_argument(self, tmp_path):
        config = sue.RunConfig(
            spec_path=tmp_path / "spec.md",
            max_questions=1,
            model_command="copilot --no-color",
            timeout_seconds=10,
            model_protocol="copilot-argv",
        )
        invocation = sue.build_model_invocation(config, "PROMPT")
        assert invocation.argv == [
            "copilot",
            "--no-color",
            "-p",
            "PROMPT",
            "-s",
            "--no-custom-instructions",
        ]
        assert invocation.stdin_text is None

    def test_copilot_oversized_prompt_is_guarded_not_launched(self, tmp_path):
        """Argv-transport prompts are size-guarded against the OS argv limit;
        the failure is a named failed CallOutcome, never a subprocess launch."""
        config = sue.RunConfig(
            spec_path=tmp_path / "spec.md",
            max_questions=1,
            model_command="copilot",
            timeout_seconds=10,
            model_protocol="copilot-argv",
        )
        huge = "x" * (sue.ARGV_PROMPT_LIMIT + 1)
        with pytest.raises(sue.ArgvTransportOverflow):
            sue.build_model_invocation(config, huge)
        outcome = sue.run_model_call(config, huge)
        assert outcome.kind == "failed"
        assert "argv" in outcome.stderr and "200000" in outcome.stderr

    def test_claude_stdin_protocol_has_no_size_guard(self, tmp_path):
        config = self._config(tmp_path, "claude")
        huge = "x" * (sue.ARGV_PROMPT_LIMIT + 1)
        invocation = sue.build_model_invocation(config, huge)
        assert invocation.stdin_text == huge

    def test_recording_stub_cwd_argv_stdin(self, tmp_path):
        record = tmp_path / "record"
        record.mkdir()
        stub = _make_stub(
            tmp_path / "recorder.sh",
            f'cat > "{record}/stdin.txt"\n'
            f'pwd > "{record}/cwd.txt"\n'
            f'printf \'%s\\n\' "$@" > "{record}/argv.txt"\n'
            'echo \'{"ok": 1}\'\n',
        )
        outcome = sue.run_model_call(self._config(tmp_path, shlex.quote(stub)), "PROMPT TEXT")
        assert outcome.kind == "ok"
        assert '{"ok": 1}' in outcome.stdout
        # Prompt arrives on stdin, read to EOF (never via argv).
        assert (record / "stdin.txt").read_text() == "PROMPT TEXT"
        # argv tail is exactly the appended -p flag (ADR-003).
        argv_lines = (record / "argv.txt").read_text().splitlines()
        assert argv_lines[-1] == "-p"
        # cwd is a fresh sue-challenge-* temp directory outside the repository
        # (AC-012), removed after the call.
        cwd = Path((record / "cwd.txt").read_text().strip())
        assert cwd.name.startswith("sue-challenge-")
        repo = REPO_ROOT.resolve()
        assert repo != cwd.resolve()
        assert repo not in cwd.resolve().parents
        assert not cwd.exists()

    def test_fresh_cwd_per_invocation(self, tmp_path):
        log = tmp_path / "cwds.txt"
        stub = _make_stub(
            tmp_path / "cwd-logger.sh",
            f'cat > /dev/null\npwd >> "{log}"\necho ok\n',
        )
        config = self._config(tmp_path, shlex.quote(stub))
        sue.run_model_call(config, "one")
        sue.run_model_call(config, "two")
        cwds = log.read_text().splitlines()
        assert len(cwds) == 2
        assert cwds[0] != cwds[1]

    def test_timeout_kills_and_preserves_partial_output(self, tmp_path):
        log = tmp_path / "cwd.txt"
        stub = _make_stub(
            tmp_path / "sleeper.sh",
            f'cat > /dev/null\npwd > "{log}"\nprintf "partial-output"\nsleep 5\n',
        )
        # 1.0s budget: the stub must reach printf before the kill; sub-second
        # budgets race with process startup under machine load (flake source).
        outcome = sue.run_model_call(self._config(tmp_path, shlex.quote(stub), timeout=1.0), "x")
        assert outcome.kind == "timeout"
        assert "partial-output" in outcome.stdout
        # Temp cwd is removed on the timeout path too.
        cwd = Path(log.read_text().strip())
        assert not cwd.exists()

    def test_timeout_kills_grandchildren_within_budget(self, tmp_path):
        # A model command that forks children holding the stdout pipe must not
        # extend the timeout: the whole process group is killed.
        stub = _make_stub(
            tmp_path / "forker.sh",
            'cat > /dev/null\nsleep 30 &\nprintf "partial-output"\nsleep 30\n',
        )
        start = time.monotonic()
        outcome = sue.run_model_call(self._config(tmp_path, shlex.quote(stub), timeout=0.3), "x")
        elapsed = time.monotonic() - start
        assert outcome.kind == "timeout"
        assert elapsed < 10, f"timeout path took {elapsed:.1f}s — grandchild held the pipe"

    def test_malformed_command_string_never_raises(self, tmp_path):
        # Unbalanced quotes reach run_model_call only if callers skip
        # parse_args; the contract is that it never raises.
        outcome = sue.run_model_call(self._config(tmp_path, "cmd '"), "x")
        assert outcome.kind == "failed"

    def test_missing_executable_is_launch_missing(self, tmp_path):
        outcome = sue.run_model_call(self._config(tmp_path, "sue-definitely-missing-xyz"), "x")
        assert outcome.kind == "launch_missing"

    def test_nonzero_exit_is_failed(self, tmp_path):
        stub = _make_stub(tmp_path / "angry.sh", 'cat > /dev/null\necho noise\nexit 3\n')
        outcome = sue.run_model_call(self._config(tmp_path, shlex.quote(stub)), "x")
        assert outcome.kind == "failed"
        assert "noise" in outcome.stdout

    def test_empty_stdout_is_failed(self, tmp_path):
        stub = _make_stub(tmp_path / "mute.sh", "cat > /dev/null\nexit 0\n")
        outcome = sue.run_model_call(self._config(tmp_path, shlex.quote(stub)), "x")
        assert outcome.kind == "failed"

    def test_duration_is_recorded(self, tmp_path):
        stub = _make_stub(tmp_path / "quick.sh", "cat > /dev/null\necho ok\n")
        outcome = sue.run_model_call(self._config(tmp_path, shlex.quote(stub)), "x")
        assert outcome.duration_seconds >= 0

    def test_operator_supplied_command_line_with_extra_args(self, tmp_path):
        # FR-043/FR-007: the full command line is split per shell quoting; the
        # stub sees its own argv plus the appended -p.
        record = tmp_path / "argv.txt"
        stub = _make_stub(
            tmp_path / "argful.sh",
            f'cat > /dev/null\nprintf \'%s\\n\' "$@" > "{record}"\necho ok\n',
        )
        config = self._config(tmp_path, f"{shlex.quote(stub)} --safe-mode")
        outcome = sue.run_model_call(config, "x")
        assert outcome.kind == "ok"
        assert record.read_text().splitlines() == ["--safe-mode", "-p"]


# ---------------------------------------------------------------------------
# T-006 — staged tolerant JSON extraction (FR-026/FR-027; FR-044 group 3)
# ---------------------------------------------------------------------------


class TestExtractJsonObject:
    def test_clean_json_object(self):
        assert sue.extract_json_object('{"questions": []}') == {"questions": []}

    def test_fenced_json_object(self):
        raw = 'Here you go:\n```json\n{"a": 1}\n```\nHope that helps!'
        assert sue.extract_json_object(raw) == {"a": 1}

    def test_fence_without_language_tag(self):
        assert sue.extract_json_object('```\n{"a": 1}\n```') == {"a": 1}

    def test_prose_wrapped_nested_object(self):
        raw = 'Sure! The answer is {"a": {"b": 2}} as requested.'
        assert sue.extract_json_object(raw) == {"a": {"b": 2}}

    def test_multiple_objects_first_wins(self):
        raw = 'First {"first": 1} then {"second": 2}.'
        assert sue.extract_json_object(raw) == {"first": 1}

    def test_unparseable_first_candidate_falls_through_to_next(self):
        raw = '{oops} then {"ok": true}'
        assert sue.extract_json_object(raw) == {"ok": True}

    def test_escaped_quote_and_brace_inside_string_literal(self):
        raw = 'noise {"text": "a \\" quote and a } brace"} trailing'
        assert sue.extract_json_object(raw) == {"text": 'a " quote and a } brace'}

    def test_zero_objects_is_parse_failure_with_reason(self):
        result = sue.extract_json_object("no json here at all")
        assert isinstance(result, sue.ParseFailure)
        assert result.reason
        assert result.is_timeout is False

    def test_empty_input_is_parse_failure(self):
        assert isinstance(sue.extract_json_object(""), sue.ParseFailure)

    def test_top_level_array_is_parse_failure(self):
        # A JSON array at top level is not an object (T-006 contract).
        assert isinstance(sue.extract_json_object('[{"a": 1}]'), sue.ParseFailure)

    def test_never_raises_on_adversarial_input(self):
        for raw in ["{", "}", '{"a"', "``` {", '{"a": "unterminated', "{not json}"]:
            result = sue.extract_json_object(raw)
            assert isinstance(result, (dict, sue.ParseFailure))

    def test_brace_noise_extraction_stays_linear(self):
        # Degenerate model output (a wall of braces) must fail fast on the
        # parse-failure path, never hang past the subprocess timeout.
        start = time.monotonic()
        result = sue.extract_json_object("{" * 200_000)
        elapsed = time.monotonic() - start
        assert isinstance(result, sue.ParseFailure)
        assert elapsed < 2.0, f"brace-noise extraction took {elapsed:.1f}s"


# ---------------------------------------------------------------------------
# T-007 — round-1 validation (FR-016/FR-017/FR-019/FR-020; FR-044 group 4)
# ---------------------------------------------------------------------------


def _q(qid="Q1", question="What does X mean?", target="general", lines=None, category="ambiguity"):
    return {
        "id": qid,
        "question": question,
        "target": target,
        "lines": [1] if lines is None else lines,
        "category": category,
    }


class TestValidateRound1:
    def test_valid_questions_round_trip(self):
        obj = {"questions": [_q(), _q(qid="Q2", category="contradiction", target="FR-001")]}
        questions, truncated = sue.validate_round1(obj, 15)
        assert truncated is False
        assert [q.id for q in questions] == ["Q1", "Q2"]
        assert isinstance(questions[0], sue.SocraticQuestion)
        assert questions[1].target == "FR-001"
        assert questions[1].category == "contradiction"

    def test_empty_list_is_valid(self):
        # FR-020: an empty question list is a success, not a failure.
        questions, truncated = sue.validate_round1({"questions": []}, 15)
        assert questions == []
        assert truncated is False

    def test_missing_questions_key_is_parse_failure(self):
        result = sue.validate_round1({}, 15)
        assert isinstance(result, sue.ParseFailure)
        assert "questions" in result.reason

    def test_questions_not_a_list_is_parse_failure(self):
        assert isinstance(sue.validate_round1({"questions": "Q1"}, 15), sue.ParseFailure)

    def test_item_not_an_object_is_parse_failure(self):
        assert isinstance(sue.validate_round1({"questions": ["Q1"]}, 15), sue.ParseFailure)

    def test_duplicate_ids_are_parse_failure_naming_offender(self):
        # FR-017: duplicate question identifiers are a validation failure.
        result = sue.validate_round1({"questions": [_q(), _q()]}, 15)
        assert isinstance(result, sue.ParseFailure)
        assert "duplicate" in result.reason
        assert "Q1" in result.reason

    @pytest.mark.parametrize(
        "field,value,needle",
        [
            ("id", "Q0", "Q0"),
            ("id", "q1", "q1"),
            ("id", None, "id"),
            ("question", "", "question"),
            ("question", None, "question"),
            ("target", "", "target"),
            ("target", None, "target"),
            ("lines", "1,2", "lines"),
            ("lines", [1, "2"], "lines"),
            ("lines", [True], "lines"),
            ("lines", None, "lines"),
            ("category", "speling", "speling"),
            ("category", None, "category"),
        ],
    )
    def test_field_violations_name_the_offender(self, field, value, needle):
        item = _q()
        item[field] = value
        result = sue.validate_round1({"questions": [item]}, 15)
        assert isinstance(result, sue.ParseFailure)
        assert needle in result.reason

    @pytest.mark.parametrize("field", ["id", "question", "target", "lines", "category"])
    def test_missing_field_is_parse_failure(self, field):
        item = _q()
        del item[field]
        result = sue.validate_round1({"questions": [item]}, 15)
        assert isinstance(result, sue.ParseFailure)
        assert field in result.reason

    def test_extra_keys_are_tolerated(self):
        # Strictness applies to the contract fields; models may add noise keys.
        item = _q()
        item["confidence"] = 0.9
        questions, _ = sue.validate_round1({"questions": [item]}, 15)
        assert questions[0].id == "Q1"

    def test_truncation_boundary_exactly_n_keeps_all_without_flag(self):
        items = [_q(qid=f"Q{i}") for i in range(1, 4)]
        questions, truncated = sue.validate_round1({"questions": items}, 3)
        assert [q.id for q in questions] == ["Q1", "Q2", "Q3"]
        assert truncated is False

    def test_truncation_boundary_n_plus_one_keeps_first_n_with_flag(self):
        # FR-019: first N in returned order, truncation flag set.
        items = [_q(qid=f"Q{i}") for i in range(1, 5)]
        questions, truncated = sue.validate_round1({"questions": items}, 3)
        assert [q.id for q in questions] == ["Q1", "Q2", "Q3"]
        assert truncated is True


# ---------------------------------------------------------------------------
# T-008 — round-2 validation with identifier bijection (FR-024/FR-025; AC-018)
# ---------------------------------------------------------------------------


def _a(qid="Q1", verdict="ANSWERED", answer="Because the text says so.", evidence=None):
    return {
        "id": qid,
        "verdict": verdict,
        "answer": answer,
        "evidence_lines": [1] if evidence is None else evidence,
    }


def _questions_for(*ids):
    return [
        sue.SocraticQuestion(
            id=qid, question=f"{qid}?", target="general", lines=[1], category="ambiguity"
        )
        for qid in ids
    ]


class TestValidateRound2:
    def test_exact_bijection_passes_in_round1_order(self):
        obj = {"answers": [_a(qid="Q2", verdict="CONTRADICTED"), _a(qid="Q1")]}
        answers = sue.validate_round2(obj, _questions_for("Q1", "Q2"))
        assert [a.id for a in answers] == ["Q1", "Q2"]
        assert isinstance(answers[0], sue.Answer)
        assert answers[1].verdict == "CONTRADICTED"

    def test_empty_answers_for_empty_questions(self):
        assert sue.validate_round2({"answers": []}, []) == []

    def test_missing_answers_key_is_parse_failure(self):
        result = sue.validate_round2({}, _questions_for("Q1"))
        assert isinstance(result, sue.ParseFailure)
        assert "answers" in result.reason

    def test_missing_id_names_offender(self):
        result = sue.validate_round2({"answers": [_a(qid="Q1")]}, _questions_for("Q1", "Q2"))
        assert isinstance(result, sue.ParseFailure)
        assert "Q2" in result.reason

    def test_duplicate_id_names_offender(self):
        result = sue.validate_round2(
            {"answers": [_a(qid="Q1"), _a(qid="Q1"), _a(qid="Q2")]},
            _questions_for("Q1", "Q2"),
        )
        assert isinstance(result, sue.ParseFailure)
        assert "Q1" in result.reason

    def test_unknown_id_names_offender(self):
        result = sue.validate_round2(
            {"answers": [_a(qid="Q1"), _a(qid="Q9")]}, _questions_for("Q1")
        )
        assert isinstance(result, sue.ParseFailure)
        assert "Q9" in result.reason

    def test_missing_plus_unknown_names_every_offender(self):
        # AC-018: the reason names every offending id, not just the first.
        result = sue.validate_round2(
            {"answers": [_a(qid="Q1"), _a(qid="Q9")]}, _questions_for("Q1", "Q2")
        )
        assert isinstance(result, sue.ParseFailure)
        assert "Q2" in result.reason
        assert "Q9" in result.reason

    def test_pre_truncation_ids_are_unknown_after_truncation(self):
        # Answers for questions cut by FR-019 truncation violate the bijection.
        result = sue.validate_round2(
            {"answers": [_a(qid="Q1"), _a(qid="Q2"), _a(qid="Q3")]},
            _questions_for("Q1", "Q2"),
        )
        assert isinstance(result, sue.ParseFailure)
        assert "Q3" in result.reason

    @pytest.mark.parametrize(
        "field,value,needle",
        [
            ("verdict", "MAYBE", "MAYBE"),
            ("verdict", "answered", "answered"),
            ("verdict", None, "verdict"),
            ("answer", "", "answer"),
            ("answer", None, "answer"),
            ("evidence_lines", [1, "x"], "evidence_lines"),
            ("evidence_lines", None, "evidence_lines"),
            ("id", None, "id"),
        ],
    )
    def test_field_violations_name_the_offender(self, field, value, needle):
        item = _a()
        item[field] = value
        result = sue.validate_round2({"answers": [item]}, _questions_for("Q1"))
        assert isinstance(result, sue.ParseFailure)
        assert needle in result.reason

    def test_item_not_an_object_is_parse_failure(self):
        result = sue.validate_round2({"answers": ["Q1"]}, _questions_for("Q1"))
        assert isinstance(result, sue.ParseFailure)

    def test_adversarial_ids_yield_single_line_bounded_reason(self):
        # FR-028/NFR-005: model-controlled ids are named through a truncated
        # repr, so the reason stays one bounded line even when the id carries
        # newlines and bulk content.
        evil_id = "QX\nSECRET-LINE-TWO " + "Y" * 500
        result = sue.validate_round2(
            {"answers": [_a(qid=evil_id)]}, _questions_for("Q1")
        )
        assert isinstance(result, sue.ParseFailure)
        assert "\n" not in result.reason
        assert len(result.reason) < 300


# ---------------------------------------------------------------------------
# T-009 — retry prompt, round execution loop, debug dumps
# (FR-013, FR-028..FR-031; AC-015, AC-016, AC-017)
# ---------------------------------------------------------------------------


def _round1_reply(*ids) -> str:
    return json.dumps({"questions": [_q(qid=qid) for qid in ids]})


def _make_replay_stub(tmp_path: Path, name: str, replies: list[str]) -> tuple[str, Path, Path]:
    """Numbered replay-sequence stub: call N records stdin-N and replays reply-N."""
    stub_dir = tmp_path / f"{name}-stub"
    stub_dir.mkdir()
    for i, content in enumerate(replies, start=1):
        (stub_dir / f"reply-{i}.txt").write_text(content)
    count_file = stub_dir / "count"
    stub = _make_stub(
        stub_dir / f"{name}.sh",
        f'n=$(cat "{count_file}" 2>/dev/null || echo 0)\n'
        "n=$((n+1))\n"
        f'printf %s "$n" > "{count_file}"\n'
        f'cat > "{stub_dir}/stdin-$n.txt"\n'
        f'cat "{stub_dir}/reply-$n.txt"\n',
    )
    return stub, count_file, stub_dir


class TestBuildRetryPrompt:
    def test_timeout_retry_is_identical_prompt(self):
        # FR-029: a timeout retry re-issues the same prompt, 0 appended text.
        failure = sue.ParseFailure(reason="model call timed out", is_timeout=True)
        assert sue.build_retry_prompt("ORIGINAL PROMPT", failure) == "ORIGINAL PROMPT"

    def test_corrective_retry_keeps_original_and_names_reason(self):
        # FR-028: original prompt + corrective instruction naming the failure.
        failure = sue.ParseFailure(reason="duplicate question id Q3")
        retry = sue.build_retry_prompt("ORIGINAL PROMPT", failure)
        assert retry.startswith("ORIGINAL PROMPT")
        assert "duplicate question id Q3" in retry
        assert retry != "ORIGINAL PROMPT"


class TestExecuteRound:
    def _config(self, command: str, timeout: float = 10.0):
        return sue.RunConfig(
            spec_path=Path("spec.md"),
            max_questions=15,
            model_command=command,
            timeout_seconds=timeout,
        )

    @staticmethod
    def _r1_validator(obj):
        return sue.validate_round1(obj, 15)

    def test_valid_first_attempt_is_one_invocation(self, tmp_path):
        stub, count, _ = _make_replay_stub(tmp_path, "ok", [_round1_reply("Q1")])
        spec_dir = tmp_path / "specdir"
        spec_dir.mkdir()
        result = sue.execute_round(
            self._config(shlex.quote(stub)), "PROMPT", self._r1_validator, 1, spec_dir
        )
        questions, truncated = result
        assert [q.id for q in questions] == ["Q1"]
        assert truncated is False
        assert int(count.read_text()) == 1
        assert not (spec_dir / sue.DEBUG_DIR_NAME).exists()

    def test_invalid_then_valid_is_two_invocations(self, tmp_path):
        # AC-016: first output invalid, retry valid — exactly 2 invocations.
        stub, count, stub_dir = _make_replay_stub(
            tmp_path, "retry", ["GARBAGE-MARKER-XYZ no json here", _round1_reply("Q1", "Q2")]
        )
        spec_dir = tmp_path / "specdir"
        spec_dir.mkdir()
        result = sue.execute_round(
            self._config(shlex.quote(stub)), "PROMPT-BODY", self._r1_validator, 1, spec_dir
        )
        questions, _ = result
        assert [q.id for q in questions] == ["Q1", "Q2"]
        assert int(count.read_text()) == 2
        assert not (spec_dir / sue.DEBUG_DIR_NAME).exists()
        # FR-028: the retry carries the original prompt plus a corrective
        # instruction, echoing 0 lines of the prior output.
        second_stdin = (stub_dir / "stdin-2.txt").read_text()
        first_stdin = (stub_dir / "stdin-1.txt").read_text()
        assert first_stdin == "PROMPT-BODY"
        assert second_stdin.startswith("PROMPT-BODY")
        assert second_stdin != first_stdin
        assert "GARBAGE-MARKER-XYZ" not in second_stdin

    def test_double_failure_exits_3_with_four_dump_files(self, tmp_path):
        # AC-015: second failure → exit 3, raw output of both attempts dumped.
        stub, count, _ = _make_replay_stub(tmp_path, "bad", ["BAD-ONE", "BAD-TWO"])
        spec_dir = tmp_path / "specdir"
        spec_dir.mkdir()
        result = sue.execute_round(
            self._config(shlex.quote(stub)), "PROMPT", self._r1_validator, 1, spec_dir
        )
        assert isinstance(result, sue.RoundExit)
        assert result.exit_code == sue.EXIT_UNUSABLE_OUTPUT == 3
        assert result.diagnostic
        assert int(count.read_text()) == 2
        debug_dir = spec_dir / sue.DEBUG_DIR_NAME
        names = sorted(p.name for p in debug_dir.iterdir())
        assert names == [
            "round1-attempt1-stderr.txt",
            "round1-attempt1-stdout.txt",
            "round1-attempt2-stderr.txt",
            "round1-attempt2-stdout.txt",
        ]
        assert (debug_dir / "round1-attempt1-stdout.txt").read_text() == "BAD-ONE"
        assert (debug_dir / "round1-attempt2-stdout.txt").read_text() == "BAD-TWO"

    def test_double_timeout_exits_3_with_timeout_prefixed_dumps(self, tmp_path):
        # AC-017 + FR-029 + FR-013: timeout retries re-issue the identical
        # prompt, each attempt gets a fresh full budget, dumps carry the
        # TIMEOUT first line (ISS-207).
        stub_dir = tmp_path / "sleep-stub"
        stub_dir.mkdir()
        count_file = stub_dir / "count"
        stub = _make_stub(
            stub_dir / "sleeper.sh",
            f'n=$(cat "{count_file}" 2>/dev/null || echo 0)\n'
            "n=$((n+1))\n"
            f'printf %s "$n" > "{count_file}"\n'
            f'cat > "{stub_dir}/stdin-$n.txt"\n'
            'printf "PARTIAL-OUT"\n'
            "sleep 30\n",
        )
        spec_dir = tmp_path / "specdir"
        spec_dir.mkdir()
        # 1.0s budget: each attempt's stub must write count/stdin and printf
        # before the kill; sub-second budgets race with process startup under
        # machine load (flake source).
        timeout = 1.0
        start = time.monotonic()
        result = sue.execute_round(
            self._config(shlex.quote(stub), timeout=timeout),
            "IDENTICAL PROMPT",
            self._r1_validator,
            1,
            spec_dir,
        )
        elapsed = time.monotonic() - start
        assert isinstance(result, sue.RoundExit)
        assert result.exit_code == 3
        # FR-013: each attempt received its own fresh budget.
        assert elapsed >= 2 * timeout
        assert elapsed < 20
        assert int(count_file.read_text()) == 2
        assert (stub_dir / "stdin-1.txt").read_text() == "IDENTICAL PROMPT"
        assert (stub_dir / "stdin-2.txt").read_text() == "IDENTICAL PROMPT"
        debug_dir = spec_dir / sue.DEBUG_DIR_NAME
        for attempt in (1, 2):
            dump = (debug_dir / f"round1-attempt{attempt}-stdout.txt").read_text()
            assert dump.splitlines()[0] == f"TIMEOUT after {timeout:g}s"
            assert "PARTIAL-OUT" in dump

    def test_validation_failure_retry_never_echoes_prior_output_lines(self, tmp_path):
        # FR-028 through the *validation* failure path (not extraction): the
        # first reply is valid JSON violating the bijection with a
        # model-controlled multi-line id; the corrective retry must carry a
        # single-line bounded reason, never the raw newline-embedded content.
        evil_id = "Q1\nSECRET-LINE-TWO " + "Z" * 200
        bad_reply = json.dumps(
            {
                "answers": [
                    {"id": evil_id, "verdict": "ANSWERED", "answer": "a", "evidence_lines": []}
                ]
            }
        )
        good_reply = json.dumps({"answers": [_a(qid="Q1")]})
        stub, count, stub_dir = _make_replay_stub(tmp_path, "evil", [bad_reply, good_reply])
        spec_dir = tmp_path / "specdir"
        spec_dir.mkdir()
        questions = _questions_for("Q1")
        result = sue.execute_round(
            self._config(shlex.quote(stub)),
            "R2 PROMPT",
            lambda obj: sue.validate_round2(obj, questions),
            2,
            spec_dir,
        )
        assert [a.id for a in result] == ["Q1"]
        assert int(count.read_text()) == 2
        retry_stdin = (stub_dir / "stdin-2.txt").read_text()
        # The raw newline-carrying model content never lands in the retry
        # prompt; the corrective block appends exactly one bounded reason.
        assert "Q1\nSECRET-LINE-TWO" not in retry_stdin
        corrective = retry_stdin.removeprefix("R2 PROMPT")
        assert "Z" * 100 not in corrective  # bulk id content truncated away

    def test_dump_write_failure_still_returns_round_exit(self, tmp_path):
        # The debug dump is best-effort: a file squatting on the .sue-debug
        # name must not turn exit 3 into a traceback (NFR-005).
        stub, count, _ = _make_replay_stub(tmp_path, "nodump", ["BAD-ONE", "BAD-TWO"])
        spec_dir = tmp_path / "specdir"
        spec_dir.mkdir()
        (spec_dir / sue.DEBUG_DIR_NAME).write_text("a file, not a directory")
        result = sue.execute_round(
            self._config(shlex.quote(stub)), "PROMPT", self._r1_validator, 1, spec_dir
        )
        assert isinstance(result, sue.RoundExit)
        assert result.exit_code == 3
        assert "\n" not in result.diagnostic

    def test_round2_double_failure_adds_zero_round1_calls(self, tmp_path):
        # FR-031: a round-2 failure never re-runs round 1.
        stub, count, _ = _make_replay_stub(
            tmp_path, "seq", [_round1_reply("Q1"), "BAD", "BAD-AGAIN"]
        )
        spec_dir = tmp_path / "specdir"
        spec_dir.mkdir()
        config = self._config(shlex.quote(stub))
        round1 = sue.execute_round(config, "R1 PROMPT", self._r1_validator, 1, spec_dir)
        questions, _ = round1
        assert int(count.read_text()) == 1
        round2 = sue.execute_round(
            config,
            "R2 PROMPT",
            lambda obj: sue.validate_round2(obj, questions),
            2,
            spec_dir,
        )
        assert isinstance(round2, sue.RoundExit)
        # Exactly 2 round-2 attempts on top of the single round-1 call.
        assert int(count.read_text()) == 3
        names = sorted(p.name for p in (spec_dir / sue.DEBUG_DIR_NAME).iterdir())
        assert len(names) == 4
        assert all(name.startswith("round2-") for name in names)


# ---------------------------------------------------------------------------
# T-010 — deterministic partition and ranking (FR-009/FR-032/FR-033; AC-004)
# ---------------------------------------------------------------------------


def _answer_obj(qid: str, verdict: str):
    return sue.Answer(id=qid, verdict=verdict, answer=f"answer for {qid}", evidence_lines=[1])


class TestPartitionAndRank:
    def _fixture(self):
        questions = _questions_for("Q1", "Q2", "Q3", "Q4", "Q5")
        verdicts = {
            "Q1": "ANSWERED",
            "Q2": "UNANSWERABLE",
            "Q3": "CONTRADICTED",
            "Q4": "ANSWERED",
            "Q5": "CONTRADICTED",
        }
        answers = [_answer_obj(q.id, verdicts[q.id]) for q in questions]
        return questions, answers

    def test_partition_yields_exactly_two_groups(self):
        questions, answers = self._fixture()
        findings, audit = sue.partition_answers(questions, answers)
        assert [f.question.id for f in findings] == ["Q2", "Q3", "Q5"]
        assert all(f.answer.verdict in ("CONTRADICTED", "UNANSWERABLE") for f in findings)
        assert [(q.id, a.verdict) for q, a in audit] == [
            ("Q1", "ANSWERED"),
            ("Q4", "ANSWERED"),
        ]

    def test_partition_is_answer_order_independent(self):
        # The join runs over round-1 question order, so a shuffled answer list
        # yields identical output.
        questions, answers = self._fixture()
        assert sue.partition_answers(questions, list(reversed(answers))) == (
            sue.partition_answers(questions, answers)
        )

    def test_rank_contradicted_first_stable_dense(self):
        # AC-004/FR-033: all CONTRADICTED before all UNANSWERABLE, round-1
        # order within class, dense 1-based ranks.
        questions, answers = self._fixture()
        findings, _ = sue.partition_answers(questions, answers)
        ranked = sue.rank_findings(findings)
        assert [(f.rank, f.question.id, f.answer.verdict) for f in ranked] == [
            (1, "Q3", "CONTRADICTED"),
            (2, "Q5", "CONTRADICTED"),
            (3, "Q2", "UNANSWERABLE"),
        ]

    def test_all_answered_yields_zero_findings(self):
        questions = _questions_for("Q1", "Q2")
        answers = [_answer_obj(q.id, "ANSWERED") for q in questions]
        findings, audit = sue.partition_answers(questions, answers)
        assert findings == []
        assert len(audit) == 2
        assert sue.rank_findings(findings) == []

    def test_rank_is_pure_and_repeatable(self):
        questions, answers = self._fixture()
        findings, _ = sue.partition_answers(questions, answers)
        assert sue.rank_findings(findings) == sue.rank_findings(findings)


# ---------------------------------------------------------------------------
# T-011 — report and summary rendering (FR-035..FR-039, FR-041, NFR-004;
# FR-044 group 6; AC-002, AC-007, AC-008, AC-009, AC-020)
# ---------------------------------------------------------------------------


_REPORT_SPEC_LINES = [
    "# Demo Spec",
    "The system does X.",
    "The system does not do X.",
    "A trailing line.",
]


def _report_spec() -> "sue.SpecDocument":
    return sue.SpecDocument(path=Path("demo/spec.md"), lines=list(_REPORT_SPEC_LINES))


def _render_fixture():
    """Mixed-verdict fixture: 1 CONTRADICTED, 1 UNANSWERABLE, 1 ANSWERED."""
    questions = _questions_for("Q1", "Q2", "Q3")
    answers = [
        sue.Answer(id="Q1", verdict="CONTRADICTED", answer="Both sides.", evidence_lines=[2, 3]),
        sue.Answer(id="Q2", verdict="UNANSWERABLE", answer="The gap is G.", evidence_lines=[]),
        sue.Answer(id="Q3", verdict="ANSWERED", answer="Line two says so.", evidence_lines=[2]),
    ]
    findings, audit = sue.partition_answers(questions, answers)
    return questions, sue.rank_findings(findings), audit


class TestRenderReport:
    def _report(self, truncated=False):
        questions, ranked, audit = _render_fixture()
        return sue.render_report(_report_spec(), "2026-07-18", questions, ranked, audit, truncated)

    def test_exactly_three_sections_in_order(self):
        # FR-035: header, findings, audit appendix — in that order.
        report = self._report()
        header = report.index("# Socratic Challenge Report")
        findings = report.index("## Findings")
        audit = report.index("## Audit appendix")
        assert header < findings < audit
        assert report.count("## Findings") == 1
        assert report.count("## Audit appendix") == 1

    def test_header_states_exactly_five_facts(self):
        # AC-002/FR-036: spec path, run date, provider, question count,
        # finding count (provider fact added by runtime provider selection).
        report = self._report()
        head = report.split("## Findings")[0]
        assert "- **Specification:** demo/spec.md" in head
        assert "- **Run date:** 2026-07-18" in head
        assert "- **Provider:** claude" in head
        assert "- **Questions:** 3" in head
        assert "- **Findings:** 2" in head
        # Exactly the 5 base facts: no truncation note without the flag.
        assert len([l for l in head.splitlines() if l.startswith("- **")]) == 5
        assert "truncated" not in head

    def test_truncation_note_renders_only_when_flag_set(self):
        # AC-020/FR-019/FR-036: exactly 1 truncation note when the flag is set.
        report = self._report(truncated=True)
        head = report.split("## Findings")[0]
        assert head.count("truncated to the first 3") == 1
        # 5 base facts (incl. provider) + the truncation note.
        assert len([l for l in head.splitlines() if l.startswith("- **")]) == 6

    def test_findings_entries_state_four_elements_in_rank_order(self):
        # FR-037: verdict, question, target, evidence — ranked per FR-033.
        report = self._report()
        assert "### 1. [CONTRADICTED] Q1?" in report
        assert "### 2. [UNANSWERABLE] Q2?" in report
        assert report.index("### 1. [CONTRADICTED]") < report.index("### 2. [UNANSWERABLE]")
        assert report.count("- **Target:** general") == 2
        assert "- **Evidence:**" in report

    def test_evidence_quotes_exactly_one_spec_line_per_cited_number(self):
        # AC-009/FR-039/FR-018: quoted text is read from the spec, 1-based.
        report = self._report()
        assert "  > line 2: The system does X." in report
        assert "  > line 3: The system does not do X." in report

    def test_unanswerable_findings_state_the_named_gap(self):
        # FR-039: the answer text (the named gap) renders in the entry body.
        report = self._report()
        assert "The gap is G." in report
        assert "  > (0 lines cited)" in report

    def test_out_of_range_citations_render_deterministic_marker(self):
        # ADR-007/ISS-202: line 0 and beyond-range lines never fail rendering.
        questions = _questions_for("Q1")
        answers = [
            sue.Answer(id="Q1", verdict="CONTRADICTED", answer="A.", evidence_lines=[0, 2, 999])
        ]
        findings, audit = sue.partition_answers(questions, answers)
        report = sue.render_report(
            _report_spec(), "2026-07-18", questions, sue.rank_findings(findings), audit, False
        )
        assert "  > line 0: (not present in the specification)" in report
        assert "  > line 999: (not present in the specification)" in report
        assert "  > line 2: The system does X." in report

    def test_audit_appendix_is_exactly_one_collapsed_details_block(self):
        # AC-008/FR-038: exactly 1 <details> block holding every ANSWERED entry.
        report = self._report()
        assert report.count("<details>") == 1
        assert report.count("</details>") == 1
        assert report.count("<summary>") == 1
        assert "<summary>Audit appendix — 1 ANSWERED question(s)</summary>" in report
        details = report.split("<details>")[1].split("</details>")[0]
        assert "### Q3 — Q3?" in details
        assert "- **Answer:** Line two says so." in details
        assert "  > line 2: The system does X." in details

    def test_zero_findings_statement_with_full_audit_appendix(self):
        # AC-007/FR-041: the clean-specification outcome.
        questions = _questions_for("Q1", "Q2")
        answers = [_answer_obj(q.id, "ANSWERED") for q in questions]
        findings, audit = sue.partition_answers(questions, answers)
        report = sue.render_report(
            _report_spec(), "2026-07-18", questions, sue.rank_findings(findings), audit, False
        )
        assert "0 findings" in report
        assert "- **Findings:** 0" in report
        assert "<summary>Audit appendix — 2 ANSWERED question(s)</summary>" in report
        assert "### Q1 — Q1?" in report
        assert "### Q2 — Q2?" in report

    def test_zero_questions_report(self):
        # AC-006/FR-020 wording path: 0 questions, 0 findings, 0 audit entries.
        report = sue.render_report(_report_spec(), "2026-07-18", [], [], [], False)
        assert "- **Questions:** 0" in report
        assert "- **Findings:** 0" in report
        assert "0 findings" in report
        assert "<summary>Audit appendix — 0 ANSWERED question(s)</summary>" in report

    def test_multiline_question_text_stays_on_one_heading_line(self):
        # Model-controlled question text is only validated as non-empty; an
        # embedded newline must not break the heading or summary line shape.
        question = sue.SocraticQuestion(
            id="Q1",
            question="What\ndoes\n\n  X mean?",
            target="general",
            lines=[1],
            category="ambiguity",
        )
        answer = sue.Answer(id="Q1", verdict="UNANSWERABLE", answer="Gap.", evidence_lines=[1])
        ranked = sue.rank_findings([sue.Finding(rank=0, question=question, answer=answer)])
        report = sue.render_report(_report_spec(), "2026-07-18", [question], ranked, [], False)
        assert "### 1. [UNANSWERABLE] What does X mean?" in report
        summary = sue.render_summary(ranked)
        assert "1. [UNANSWERABLE] What does X mean?" in summary
        # counts line + "Top findings:" label + exactly 1 one-line entry
        assert len(summary.splitlines()) == 3

    def test_double_render_is_byte_identical(self):
        # NFR-004: identical validated inputs give byte-identical bodies.
        assert self._report() == self._report()

    def test_run_date_is_injected_and_isolated_to_one_line(self):
        # NFR-004: outside the run-date field the bodies are identical.
        questions, ranked, audit = _render_fixture()
        spec = _report_spec()
        one = sue.render_report(spec, "2026-07-18", questions, ranked, audit, False)
        two = sue.render_report(spec, "2027-01-01", questions, ranked, audit, False)
        differing = [
            (a, b) for a, b in zip(one.splitlines(), two.splitlines()) if a != b
        ]
        assert differing == [("- **Run date:** 2026-07-18", "- **Run date:** 2027-01-01")]


class TestRenderSummary:
    def test_counts_per_verdict_class(self):
        _, ranked, _ = _render_fixture()
        summary = sue.render_summary(ranked)
        assert "CONTRADICTED: 1" in summary
        assert "UNANSWERABLE: 1" in summary

    def test_top_three_in_rank_order(self):
        # FR-040: at most 3 findings echoed, in FR-033 rank order.
        questions = _questions_for("Q1", "Q2", "Q3", "Q4")
        answers = [_answer_obj(q.id, "UNANSWERABLE") for q in questions[:3]] + [
            _answer_obj("Q4", "CONTRADICTED")
        ]
        findings, _ = sue.partition_answers(questions, answers)
        ranked = sue.rank_findings(findings)
        summary = sue.render_summary(ranked)
        assert "CONTRADICTED: 1" in summary
        assert "UNANSWERABLE: 3" in summary
        listed = [l for l in summary.splitlines() if l.strip().startswith(("1.", "2.", "3.", "4."))]
        assert len(listed) == 3
        assert listed[0].strip().startswith("1. [CONTRADICTED] Q4?")
        assert listed[1].strip().startswith("2. [UNANSWERABLE] Q1?")
        assert listed[2].strip().startswith("3. [UNANSWERABLE] Q2?")

    def test_zero_findings_summary_states_zero_counts(self):
        summary = sue.render_summary([])
        assert "CONTRADICTED: 0" in summary
        assert "UNANSWERABLE: 0" in summary


# ---------------------------------------------------------------------------
# T-012 — wired main pipeline, end-to-end through the stub seam
# (FR-008, FR-020, FR-034, FR-040, FR-042; AC-001, AC-003, AC-005, AC-006,
#  AC-010, AC-021)
# ---------------------------------------------------------------------------


def _round2_reply(verdicts: dict[str, str]) -> str:
    return json.dumps(
        {
            "answers": [
                {
                    "id": qid,
                    "verdict": verdict,
                    "answer": f"answer for {qid}",
                    "evidence_lines": [2],
                }
                for qid, verdict in verdicts.items()
            ]
        }
    )


def _full_round1_reply(id_question_pairs: list[tuple[str, str]]) -> str:
    return json.dumps(
        {
            "questions": [
                {
                    "id": qid,
                    "question": question,
                    "target": "general",
                    "lines": [2],
                    "category": "ambiguity",
                }
                for qid, question in id_question_pairs
            ]
        }
    )


def _write_fixture_spec(tmp_path: Path) -> Path:
    spec_dir = tmp_path / "specdir"
    spec_dir.mkdir(exist_ok=True)
    spec = spec_dir / "spec.md"
    spec.write_text("\n".join(_REPORT_SPEC_LINES) + "\n")
    return spec


class TestMainPipeline:
    def _happy_stub(self, tmp_path: Path, name: str = "happy"):
        return _make_replay_stub(
            tmp_path,
            name,
            [
                _full_round1_reply(
                    [("Q1", "Is X contradicted?"), ("Q2", "Is anything answered?")]
                ),
                _round2_reply({"Q1": "CONTRADICTED", "Q2": "ANSWERED"}),
            ],
        )

    def test_full_run_two_calls_report_written_exit_0(self, tmp_path, capsys):
        # AC-001/AC-021/FR-008: exactly 2 model calls, report beside the spec,
        # exit 0 — entirely through the real stub subprocess seam (FR-043).
        spec = _write_fixture_spec(tmp_path)
        stub, count, _ = self._happy_stub(tmp_path)
        rc = sue.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 0
        assert int(count.read_text()) == 2
        report_path = spec.parent / sue.REPORT_FILENAME
        assert report_path.exists()
        report = report_path.read_text()
        assert "### 1. [CONTRADICTED] Is X contradicted?" in report
        assert "  > line 2: The system does X." in report
        assert "<summary>Audit appendix — 1 ANSWERED question(s)</summary>" in report
        assert capsys.readouterr().err == ""

    def test_stdout_summary_states_counts_and_top_findings(self, tmp_path, capsys):
        # AC-005/FR-040: per-class counts plus top findings in rank order.
        spec = _write_fixture_spec(tmp_path)
        stub, _, _ = self._happy_stub(tmp_path)
        assert sue.main([str(spec), "--claude-cmd", shlex.quote(stub)]) == 0
        out = capsys.readouterr().out
        assert "CONTRADICTED: 1" in out
        assert "UNANSWERABLE: 0" in out
        assert "1. [CONTRADICTED] Is X contradicted?" in out

    def test_rerun_overwrites_keeping_exactly_one_report(self, tmp_path, capsys):
        # AC-003/FR-034: plain overwrite, 0 historical copies.
        spec = _write_fixture_spec(tmp_path)
        first_stub, _, _ = _make_replay_stub(
            tmp_path,
            "first",
            [
                _full_round1_reply([("Q1", "FIRST-RUN-MARKER question?")]),
                _round2_reply({"Q1": "UNANSWERABLE"}),
            ],
        )
        assert sue.main([str(spec), "--claude-cmd", shlex.quote(first_stub)]) == 0
        second_stub, _, _ = _make_replay_stub(
            tmp_path,
            "second",
            [
                _full_round1_reply([("Q1", "SECOND-RUN-MARKER question?")]),
                _round2_reply({"Q1": "UNANSWERABLE"}),
            ],
        )
        assert sue.main([str(spec), "--claude-cmd", shlex.quote(second_stub)]) == 0
        reports = [p for p in spec.parent.iterdir() if "socratic-challenge" in p.name]
        assert [p.name for p in reports] == [sue.REPORT_FILENAME]
        content = reports[0].read_text()
        assert "SECOND-RUN-MARKER" in content
        assert "FIRST-RUN-MARKER" not in content
        capsys.readouterr()

    def test_zero_question_run_skips_round_2(self, tmp_path, capsys):
        # AC-006/FR-020: valid empty round-1 list -> exactly 1 model call,
        # zero-question report, exit 0.
        spec = _write_fixture_spec(tmp_path)
        stub, count, _ = _make_replay_stub(
            tmp_path, "empty", [json.dumps({"questions": []})]
        )
        rc = sue.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 0
        assert int(count.read_text()) == 1
        report = (spec.parent / sue.REPORT_FILENAME).read_text()
        assert "- **Questions:** 0" in report
        assert "- **Findings:** 0" in report
        assert "0 findings" in report
        assert capsys.readouterr().err == ""

    def test_spec_file_never_written_across_outcomes(self, tmp_path, capsys):
        # AC-010/FR-042: the challenged spec is byte-identical after success,
        # exit-3, and exit-2 outcomes.
        spec = _write_fixture_spec(tmp_path)
        digest_before = hashlib.sha256(spec.read_bytes()).hexdigest()
        happy_stub, _, _ = self._happy_stub(tmp_path)
        assert sue.main([str(spec), "--claude-cmd", shlex.quote(happy_stub)]) == 0
        bad_stub, _, _ = _make_replay_stub(tmp_path, "bad", ["BAD", "BAD-AGAIN"])
        assert sue.main([str(spec), "--claude-cmd", shlex.quote(bad_stub)]) == 3
        assert sue.main([str(spec), "--claude-cmd", "sue-missing-cmd-98765"]) == 2
        assert hashlib.sha256(spec.read_bytes()).hexdigest() == digest_before
        capsys.readouterr()

    def test_round1_double_failure_exits_3_writes_no_report(self, tmp_path, capsys):
        # AC-015 through main: exit 3, dumps written, 0 reports.
        spec = _write_fixture_spec(tmp_path)
        stub, count, _ = _make_replay_stub(tmp_path, "r1bad", ["BAD", "BAD-AGAIN"])
        rc = sue.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 3
        assert int(count.read_text()) == 2
        assert not (spec.parent / sue.REPORT_FILENAME).exists()
        assert (spec.parent / sue.DEBUG_DIR_NAME).is_dir()
        _one_stderr_line(capsys)

    def test_round2_double_failure_adds_zero_round1_calls(self, tmp_path, capsys):
        # FR-031 through the real pipeline: 1 round-1 call + 2 round-2 attempts.
        spec = _write_fixture_spec(tmp_path)
        stub, count, _ = _make_replay_stub(
            tmp_path,
            "r2bad",
            [_full_round1_reply([("Q1", "A question?")]), "BAD", "BAD-AGAIN"],
        )
        rc = sue.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 3
        assert int(count.read_text()) == 3
        names = sorted(p.name for p in (spec.parent / sue.DEBUG_DIR_NAME).iterdir())
        assert all(name.startswith("round2-") for name in names)
        assert not (spec.parent / sue.REPORT_FILENAME).exists()
        _one_stderr_line(capsys)

    def test_retry_then_success_completes_at_exit_0(self, tmp_path, capsys):
        # AC-016 end-to-end: invalid round-1 output, corrective retry succeeds,
        # the run completes at exit code 0 with 3 total invocations.
        spec = _write_fixture_spec(tmp_path)
        stub, count, _ = _make_replay_stub(
            tmp_path,
            "recover",
            [
                "GARBAGE not json",
                _full_round1_reply([("Q1", "A question?")]),
                _round2_reply({"Q1": "ANSWERED"}),
            ],
        )
        rc = sue.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 0
        assert int(count.read_text()) == 3
        assert (spec.parent / sue.REPORT_FILENAME).exists()
        capsys.readouterr()

    def test_truncation_note_lands_in_report_via_main(self, tmp_path, capsys):
        # AC-020 end-to-end: over-cap round-1 output -> first-N kept, header
        # carries exactly 1 truncation note.
        spec = _write_fixture_spec(tmp_path)
        stub, count, _ = _make_replay_stub(
            tmp_path,
            "overcap",
            [
                _full_round1_reply([("Q1", "One?"), ("Q2", "Two?"), ("Q3", "Three?")]),
                _round2_reply({"Q1": "ANSWERED", "Q2": "ANSWERED"}),
            ],
        )
        rc = sue.main([str(spec), "--claude-cmd", shlex.quote(stub), "--questions", "2"])
        assert rc == 0
        report = (spec.parent / sue.REPORT_FILENAME).read_text()
        assert "- **Questions:** 2" in report
        assert report.count("truncated to the first 2") == 1
        capsys.readouterr()


# ---------------------------------------------------------------------------
# T-013 — standalone-contract gate (FR-045, NFR-002; feasibility risk-5
# anti-coupling gate)
# ---------------------------------------------------------------------------


class TestStandaloneContract:
    def _imported_top_level_modules(self) -> set[str]:
        tree = ast.parse(SCRIPT_PATH.read_text())
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.add(node.module.split(".")[0])
        return modules

    def test_import_scan_zero_project_and_third_party_imports(self):
        # FR-045: 0 orchestration-package imports, 0 non-stdlib imports.
        modules = self._imported_top_level_modules()
        forbidden = {"harness", "echelon", "codegen", "understanding"}
        assert not modules & forbidden, f"project-package imports found: {modules & forbidden}"
        non_stdlib = modules - set(sys.stdlib_module_names)
        assert not non_stdlib, f"non-stdlib imports found: {non_stdlib}"

    def test_source_references_zero_orchestration_config_or_state_files(self):
        # FR-045/A-003: argv + spec file are the only inputs; no orchestration
        # configuration or state file names appear in the source.
        source = SCRIPT_PATH.read_text()
        for needle in ("echelon-config", ".specify", "state.json", "definition.yaml"):
            assert needle not in source, f"orchestration coupling: {needle!r} in script source"

    def test_stubbed_run_completes_in_clean_environment(self, tmp_path):
        # NFR-002/SC-005: a fresh-checkout-shaped run — out-of-repo cwd,
        # minimal environment, standard runtime only — completes with exactly
        # 1 command invocation and 0 additional installed components.
        spec = _write_fixture_spec(tmp_path)
        stub, count, _ = _make_replay_stub(
            tmp_path,
            "clean",
            [
                _full_round1_reply([("Q1", "A question?")]),
                _round2_reply({"Q1": "ANSWERED"}),
            ],
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), str(spec), "--claude-cmd", shlex.quote(stub)],
            cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert int(count.read_text()) == 2
        assert (spec.parent / sue.REPORT_FILENAME).exists()


# ---------------------------------------------------------------------------
# T-014 — SC-003 exit-code matrix and the NFR-001 invocation bound
# ---------------------------------------------------------------------------


class TestExitCodeMatrixAndBounds:
    def test_sc003_exit_1_bad_argument(self, tmp_path, capsys):
        assert sue.main([]) == 1
        line = _one_stderr_line(capsys)
        assert "bad input" in line

    def test_sc003_exit_1_missing_spec(self, tmp_path, capsys):
        assert sue.main([str(tmp_path / "absent.md")]) == 1
        line = _one_stderr_line(capsys)
        assert "bad input" in line

    def test_sc003_exit_2_missing_executable(self, tmp_path, capsys):
        spec = _write_fixture_spec(tmp_path)
        assert sue.main([str(spec), "--claude-cmd", "sue-missing-cmd-98765"]) == 2
        line = _one_stderr_line(capsys)
        assert "model command unavailable" in line

    def test_sc003_exit_3_unusable_output(self, tmp_path, capsys):
        spec = _write_fixture_spec(tmp_path)
        stub, _, _ = _make_replay_stub(tmp_path, "matrix3", ["BAD", "BAD-AGAIN"])
        assert sue.main([str(spec), "--claude-cmd", shlex.quote(stub)]) == 3
        line = _one_stderr_line(capsys)
        assert "unusable model output" in line

    def test_at_most_four_subprocess_invocations_per_run(self, tmp_path, capsys):
        # NFR-001 structural bound: the worst terminating success path is
        # 2 attempts per round x 2 rounds = 4 subprocess invocations, bounding
        # wall-clock at 4 timeout budgets plus local processing.
        spec = _write_fixture_spec(tmp_path)
        stub, count, _ = _make_replay_stub(
            tmp_path,
            "worst",
            [
                "GARBAGE round-1 attempt 1",
                _full_round1_reply([("Q1", "A question?")]),
                "GARBAGE round-2 attempt 1",
                _round2_reply({"Q1": "ANSWERED"}),
            ],
        )
        rc = sue.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 0
        assert int(count.read_text()) == 4
        capsys.readouterr()

    def test_failure_paths_never_exceed_four_invocations(self, tmp_path, capsys):
        # NFR-001 on the exit-3 path: a double round-2 failure terminates after
        # 3 invocations (1 round-1 + 2 round-2) — under the 4-budget bound.
        spec = _write_fixture_spec(tmp_path)
        stub, count, _ = _make_replay_stub(
            tmp_path,
            "bounded",
            [_full_round1_reply([("Q1", "A question?")]), "BAD", "BAD-AGAIN"],
        )
        assert sue.main([str(spec), "--claude-cmd", shlex.quote(stub)]) == 3
        assert int(count.read_text()) <= 4
        capsys.readouterr()
