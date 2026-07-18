"""Unit tests for scripts/sue_challenge.py — SUE challenge script (spec 030).

The script is loaded via importlib (ADR-008) because scripts/ is not a package.
All tests run offline: model commands are tmp_path-generated stub executables
(FR-043); no network, no live model (SC-002).

Covers tasks T-001..T-010: shared constants and dataclasses, argument handling
(FR-001..FR-004, FR-007, NFR-003), pre-flight and exit-code spine (FR-005,
FR-006, FR-012, FR-042, NFR-005), prompt assembly (FR-014, FR-015, FR-018,
FR-021, FR-022, FR-023), the isolated subprocess runner (FR-010, FR-011,
FR-043), staged tolerant extraction (FR-026, FR-027), round-1/round-2 strict
validation (FR-016, FR-017, FR-019, FR-020, FR-024, FR-025), the corrective
retry loop with debug dumps (FR-013, FR-028..FR-031), and deterministic
partition plus ranking (FR-009, FR-032, FR-033).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
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
        timeout = 0.3
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
