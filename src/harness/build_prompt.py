"""BuildPromptBuilder — constructs self-contained prompts for claude -p."""
from __future__ import annotations


class BuildPromptBuilder:
    """Builds prompts for LLM build and feedback invocations.

    All context is explicit — spec, tasks, lessons, failure output.
    No shared state between iterations; each prompt is self-contained.
    """

    SYSTEM_PREAMBLE = (
        "You are invoked by an external orchestrator to implement or fix code.\n"
        "Write all files to the worktree path shown below.\n"
        "Treat that worktree as the only implementation project root for code reads, searches, edits, and tests.\n"
        "Do not search outside the worktree for implementation code; do not run global `find` commands or scan parent/user directories.\n"
        "Use the exact spec artifact paths in Harness Context as read-only planning inputs. They may be outside the worktree only when `spec_artifacts_mode` is `external`.\n"
        "Do not edit `tasks.md`, `spec.md`, or other spec artifacts for progress tracking. Ralph owns task progress writes; report completed work only through `completed_task_ids` in `.harness-build-status.json`.\n"
        "If required Echelon files are missing from the worktree, report the setup failure instead of using copies from another path.\n"
        "Do not run git commands. Do not commit. Do not push.\n"
        "Ralph does not consume `next_phase` from your final message; do not stop at phase boundaries.\n"
        "Do not end after build-1-init or any intermediate build phase. Continue until this invocation has produced one bounded verified progress slice, is genuinely blocked, or hit an error.\n"
        "Ralph owns the outer loop. After one verified progress slice, write `.harness-build-status.json` and stop; do not keep selecting more tasks in the same invocation.\n"
        "Do not use native task-planning tools such as TaskCreate or TaskUpdate. Select work only from canonical task rows in `tasks.md`.\n"
        "A successful build invocation must write `.harness-build-status.json`; a missing marker is treated as build_incomplete.\n"
        "Signal completion by running the skill shown in the prompt.\n"
    )

    STATUS_CONTRACT = (
        "## Harness Build Status Contract\n"
        "Before you stop, write `.harness-build-status.json` in the worktree root.\n"
        "A harness build invocation is one bounded verified progress slice, not the whole MVP and not the whole build state machine.\n"
        "When you finish a task or coherent small batch and its required quality gates pass, immediately write the status marker and stop. Include `completed_task_ids` with the exact canonical task IDs completed in this slice. Ralph will mark those tasks DONE, verify, commit, and start another invocation if more work remains.\n"
        "Never report ranges or grouped task labels as completed IDs. `T-063..T-068`, `T-095..T-149`, and `Enemy Combat all tasks` are invalid progress identities; expand them to exact canonical IDs such as `[\"T-063\", \"T-064\"]`.\n"
        "Use exactly one of these statuses:\n"
        '- `{"status": "done", "reason": "<short evidence>", "completed_task_ids": ["T-001"]}` when this iteration completed useful verified progress. '
        "Use `done` even when the overall spec is still incomplete and more tasks remain.\n"
        '- `{"status": "blocked", "reason": "<specific external blocker>"}` only when no further implementation progress is possible without human input, missing credentials, unavailable tooling, or a contradictory spec decision.\n'
        '- `{"status": "error", "reason": "<failed command or unexpected failure>"}` when you attempted implementation but verification is failing unexpectedly.\n'
        "Do not use `impasse` for ordinary partial progress. An incomplete MVP is not a blocker by itself.\n"
    )

    def build_prompt(
        self,
        *,
        worktree_path: str,
        spec_content: str,
        tasks_content: str,
        build_skill: str,
        strategy_context: str = "",
        stack_context: str = "",
        lessons: str = "",
        pitfalls: str = "",
        bugfix_content: str = "",
    ) -> str:
        """Prompt for a fresh build (outer_iter == 0) or a full rebuild."""
        parts = [
            self.SYSTEM_PREAMBLE,
            self.STATUS_CONTRACT,
            f"## Worktree\n{worktree_path}",
            f"## Spec\n{spec_content}",
            f"## Tasks\n{tasks_content}",
        ]

        if lessons or pitfalls:
            constraints = "\n".join(filter(None, [lessons, pitfalls]))
            parts.append(f"## Mandatory Constraints (Lessons)\n{constraints}")

        if bugfix_content:
            parts.append(f"## Bugfix Context\n{bugfix_content}")

        if stack_context:
            parts.append(f"## Echelon Stack Context\n{stack_context}")

        if strategy_context:
            parts.append(f"## Strategy Context\n{strategy_context}")

        parts.append(
            f"## Action\nRun `/{build_skill}` to implement the tasks above.\n"
            f"Write all output files to: {worktree_path}\n"
            "Do not return only an `echelon_result.state_updates.next_phase` handoff. "
            "The harness process running this prompt will not dispatch that handoff for you."
        )

        return "\n\n".join(parts)

    def feedback_prompt(
        self,
        *,
        worktree_path: str,
        spec_content: str,
        failures_output: str,
        outer_iter: int,
        lessons: str = "",
    ) -> str:
        """Prompt for a targeted fix after Docker verification failed."""
        parts = [
            self.SYSTEM_PREAMBLE,
            self.STATUS_CONTRACT,
            f"## Worktree\n{worktree_path}",
            f"## Spec\n{spec_content}",
        ]

        if lessons:
            parts.append(f"## Mandatory Constraints (Lessons)\n{lessons}")

        parts.append(
            f"## Verification Failures (iteration {outer_iter})\n{failures_output}"
        )

        parts.append(
            f"## Action\nFix the failures listed above by editing files in {worktree_path} directly.\n"
            "Do not re-run the full build pipeline. Do not run git commands.\n"
            "Do not run `echelon spec verify`. Ralph owns fulfillment refresh and regeneration of verify-spec artifacts.\n"
            "Do not hand-edit `fulfillment-report.md` or `fulfillment-gaps.md`; treat them as read-only evidence.\n"
            "Edit only the files needed to fix the listed failures."
        )

        return "\n\n".join(parts)
