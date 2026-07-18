"""Unit tests for scripts/sue_challenge.py — SUE challenge script (spec 030).

The script is loaded via importlib (ADR-008) because scripts/ is not a package.
All tests run offline: model commands are tmp_path-generated stub executables
(FR-043); no network, no live model (SC-002).

Covers tasks T-001..T-005: shared constants and dataclasses, argument handling
(FR-001..FR-004, FR-007, NFR-003), pre-flight and exit-code spine (FR-005,
FR-006, FR-012, FR-042, NFR-005), prompt assembly (FR-014, FR-015, FR-018,
FR-021, FR-022, FR-023), and the isolated subprocess runner (FR-010, FR-011,
FR-043).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import os
import shlex
import stat
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
            ("RunConfig", {"spec_path", "max_questions", "model_command", "timeout_seconds"}),
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
    def test_defaults_are_15_claude_300(self):
        config = sue.parse_args(["spec.md"])
        assert config.spec_path == Path("spec.md")
        assert config.max_questions == 15
        assert config.model_command == "claude"
        assert config.timeout_seconds == 300

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
        outcome = sue.run_model_call(self._config(tmp_path, shlex.quote(stub), timeout=0.3), "x")
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
