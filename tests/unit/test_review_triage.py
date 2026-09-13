"""Tests for deterministic, host-owned PR review triage turns."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from harness.ai_cli_backend import CliRunResult
from harness.prosaic_prompt_loader import ProsaicCommandArtifact
from harness.review_artifacts import ReviewAllocation
from harness.review_loop import ReviewComment
from harness.review_triage import (
    ReviewTriageExecutionError,
    group_review_comments,
    parse_composer_reply,
    parse_diagnostic_reply,
    run_diagnostic_role,
    stage_composer_output,
)
from harness.review_triage_io import ReviewReadChannel, ReviewTriageError


def _comment(
    comment_id: str,
    *,
    path: str | None,
    line: int | None,
    seconds: int,
    reviewer: str = "reviewer",
    inline: bool = True,
) -> ReviewComment:
    return ReviewComment(
        comment_id=comment_id,
        path=path,
        line=line,
        body=f"finding {comment_id}",
        reviewer=reviewer,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds),
        is_inline=inline,
    )


def _allocation(tmp_path: Path, *, comments: int = 1) -> ReviewAllocation:
    attempt = tmp_path / "state/review-staging/attempt"
    attempt.mkdir(parents=True)
    names = tuple(f"review-fix-{index}.md" for index in range(1, comments + 1))
    task_ids = tuple(f"T-{index:06d}" for index in range(1, comments * 3 + 1))
    return ReviewAllocation(
        attempt_id="attempt",
        comment_ids=tuple(f"c{index}" for index in range(1, comments + 1)),
        attempt_dir=attempt,
        artifact_names=names,
        task_ids=task_ids,
        status_file=tmp_path / "state/default-review-status.json",
        journal_file=tmp_path / "state/default-review-publication.json",
    )


def _composer_envelope(*, artifact: str = "review-fix-1.md") -> dict[str, object]:
    return {
        "manifest": {
            "status": "review_fix_queued",
            "groups": 1,
            "artifacts": [artifact],
            "tasks": [
                {
                    "task_id": f"T-{index:06d}",
                    "review_task_id": f"RF1-T{index}",
                    "artifact": artifact,
                }
                for index in (1, 2, 3)
            ],
            "tasks_append": "tasks-append.md",
        },
        "artifacts": {artifact: "# Review Fix 1\n"},
        "tasks_append": (
            "- [ ] T-000001 complexity=standard phase=review-fix req=FR-001 depends=none\n\n"
            "  **Title:** RF1-T1 - Write failing test\n\n"
            "- [ ] T-000002 complexity=standard phase=review-fix req=FR-001 "
            "depends=T-000001\n\n"
            "  **Title:** RF1-T2 - Implement review fix\n\n"
            "- [ ] T-000003 complexity=standard phase=review-fix req=FR-001 "
            "depends=T-000002\n\n"
            "  **Title:** RF1-T3 - Verify review fix\n"
        ),
    }


def test_group_review_comments_uses_deterministic_transitive_components() -> None:
    comments = [
        _comment("d", path="src/app.py", line=20, seconds=1),
        _comment("c", path="src/app.py", line=7, seconds=1),
        _comment("a", path="src/app.py", line=1, seconds=0),
        _comment("b", path="src/app.py", line=4, seconds=1),
    ]

    groups = group_review_comments(comments, 3)

    assert [[c.comment_id for c in group] for group in groups] == [
        ["a", "b", "c"],
        ["d"],
    ]


def test_group_review_comments_keeps_inline_and_review_level_comments_separate() -> None:
    comments = [
        _comment("r3", path=None, line=None, seconds=119, inline=False),
        _comment("inline", path="src/app.py", line=1, seconds=30),
        _comment("r1", path=None, line=None, seconds=0, inline=False),
        _comment("r2", path=None, line=None, seconds=60, inline=False),
        _comment("other", path=None, line=None, seconds=30, reviewer="other", inline=False),
    ]

    groups = group_review_comments(comments, 3)

    assert [[c.comment_id for c in group] for group in groups] == [
        ["r1", "r2", "r3"],
        ["inline"],
        ["other"],
    ]


@pytest.mark.parametrize(
    "reply",
    [
        '{"action":"result","analysis":"ok","analysis":"duplicate"}',
        '{"action":"result","analysis":"ok","extra":1}',
        '{"action":"result","analysis":""}',
        '{"action":"blocked","reason":NaN}',
        '{"action":"read","request":{"op":"list_directory","root":"worktree","path":"."},"extra":1}',
    ],
)
def test_diagnostic_parser_rejects_non_closed_or_nonfinite_json(reply: str) -> None:
    with pytest.raises(ReviewTriageError):
        parse_diagnostic_reply(reply)


def test_diagnostic_role_services_json_framed_reads_and_retains_usage(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    spec = tmp_path / "spec"
    invocation = tmp_path / "invocation"
    worktree.mkdir()
    spec.mkdir()
    invocation.mkdir()
    (worktree / "src.py").write_text("evidence\n", encoding="utf-8")
    responses = [
        (
            json.dumps(
                {
                    "action": "read",
                    "request": {
                        "op": "read_file",
                        "root": "worktree",
                        "path": "src.py",
                        "start_line": 1,
                        "line_count": 1,
                    },
                }
            ),
            3,
        ),
        (json.dumps({"action": "result", "analysis": "root cause"}), None),
    ]
    prompts: list[str] = []

    class Provider:
        def run_review_triage_turn(self, cwd, prompt, *, frontmatter, timeout_ms):
            prompts.append(prompt)
            response, usage = responses.pop(0)
            process = subprocess.run(
                [sys.executable, "-c", "import sys; print(sys.argv[1])", response],
                capture_output=True,
                text=True,
                check=True,
            )
            return CliRunResult(0, process.stdout.strip(), "", token_usage=usage)

    artifact = ProsaicCommandArtifact(
        frontmatter={"name": "echelon.review-debugger", "model_tier": "strong", "effort": "medium"},
        body="Diagnose root cause only.",
    )
    with ReviewReadChannel(worktree, spec) as channel:
        result = run_diagnostic_role(
            Provider(),
            invocation,
            artifact,
            assignment={"group": [{"comment_id": "c1"}], "prior_results": {}},
            read_channel=channel,
            deadline=10**12,
        )

    assert result.analysis == "root cause"
    assert result.usage.total_tokens >= 4
    assert [record.estimated for record in result.usage.records] == [False, True]
    assert '"type":"untrusted_read_result"' in prompts[1].replace(" ", "")
    assert "evidence\\n" in prompts[1]


def test_diagnostic_role_allows_a_result_after_32_reads_but_not_a_33rd(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    spec = tmp_path / "spec"
    invocation = tmp_path / "invocation"
    worktree.mkdir()
    spec.mkdir()
    invocation.mkdir()
    artifact = ProsaicCommandArtifact(
        frontmatter={"name": "echelon.review-debugger", "model_tier": "strong", "effort": "medium"},
        body="Diagnose root cause only.",
    )
    read_reply = json.dumps(
        {
            "action": "read",
            "request": {"op": "list_directory", "root": "worktree", "path": "."},
        }
    )

    class Provider:
        def __init__(self, final: str):
            self.final = final
            self.calls = 0

        def run_review_triage_turn(self, cwd, prompt, *, frontmatter, timeout_ms):
            self.calls += 1
            stdout = read_reply if self.calls <= 32 else self.final
            return CliRunResult(0, stdout, "", token_usage=1)

    with ReviewReadChannel(worktree, spec) as channel:
        succeeds = Provider(json.dumps({"action": "result", "analysis": "done"}))
        result = run_diagnostic_role(
            succeeds,
            invocation,
            artifact,
            assignment={"group": [], "prior_results": {}},
            read_channel=channel,
            deadline=10**12,
        )
        exceeds = Provider(read_reply)
        with pytest.raises(ReviewTriageExecutionError, match="read request limit") as caught:
            run_diagnostic_role(
                exceeds,
                invocation,
                artifact,
                assignment={"group": [], "prior_results": {}},
                read_channel=channel,
                deadline=10**12,
            )

    assert result.analysis == "done"
    assert succeeds.calls == 33
    assert exceeds.calls == 33
    assert caught.value.usage.total_tokens == 33


def test_composer_parser_rejects_model_selected_stage_paths(tmp_path: Path) -> None:
    allocation = _allocation(tmp_path)
    envelope = _composer_envelope(artifact="../outside.md")

    with pytest.raises(ReviewTriageError):
        parse_composer_reply(json.dumps(envelope), allocation=allocation, group_count=1)


def test_malformed_nonempty_tasks_append_is_rejected_before_any_staging_write(
    tmp_path: Path,
) -> None:
    allocation = _allocation(tmp_path)
    envelope = _composer_envelope()
    envelope["tasks_append"] = "not a canonical task row\n"

    with pytest.raises(ReviewTriageError):
        parse_composer_reply(json.dumps(envelope), allocation=allocation, group_count=1)

    assert list(allocation.attempt_dir.iterdir()) == []
    assert not allocation.status_file.exists()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda text: text.replace('"groups": 1', '"groups": NaN'),
        lambda text: text.replace('"groups": 1', '"groups": 1, "groups": 1'),
        lambda text: text.replace('"tasks_append": "tasks-append.md"', '"tasks_append": "other.md"', 1),
        lambda text: text.replace('"T-000003"', '"T-999999"'),
        lambda text: json.dumps({**json.loads(text), "tasks_append": ""}),
    ],
)
def test_composer_parser_rejects_nonfinite_duplicate_or_partial_envelopes(
    tmp_path: Path, mutate
) -> None:
    allocation = _allocation(tmp_path)
    text = mutate(json.dumps(_composer_envelope()))

    with pytest.raises(ReviewTriageError):
        parse_composer_reply(text, allocation=allocation, group_count=1)


def test_staging_rejects_preexisting_entries_before_any_write(tmp_path: Path) -> None:
    allocation = _allocation(tmp_path)
    (allocation.attempt_dir / "debris").write_text("existing", encoding="utf-8")
    composition = parse_composer_reply(
        json.dumps(_composer_envelope()), allocation=allocation, group_count=1
    )

    with pytest.raises(ReviewTriageExecutionError):
        stage_composer_output(allocation, composition)

    assert not allocation.status_file.exists()
    assert not (allocation.attempt_dir / "review-fix-1.md").exists()


def test_staging_rejects_a_symlinked_attempt_directory(tmp_path: Path) -> None:
    allocation = _allocation(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    allocation.attempt_dir.rmdir()
    allocation.attempt_dir.symlink_to(outside, target_is_directory=True)
    composition = parse_composer_reply(
        json.dumps(_composer_envelope()), allocation=allocation, group_count=1
    )

    with pytest.raises(ReviewTriageExecutionError):
        stage_composer_output(allocation, composition)

    assert list(outside.iterdir()) == []
    assert not allocation.status_file.exists()
