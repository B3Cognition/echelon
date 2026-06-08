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
        "Do not search for implementation code outside the worktree; do not run global `find` commands or scan parent/user directories.\n"
        "Use the exact spec artifact paths in Harness Context; they may be outside the worktree in targeted polyrepo runs.\n"
        "If required Echelon runtime files are missing from the worktree, report the setup failure instead of using copies from another path.\n"
        "Do not run git commands. Do not commit. Do not push.\n"
        "Ralph does not consume `next_phase` from your final message; do not stop at phase boundaries.\n"
        "Do not end after build-1-init or any intermediate build phase. Continue the build workflow until true BUILD_DONE, BLOCKED, or ERROR.\n"
        "A successful build must write `.harness-build-status.json`; a missing marker is treated as build_incomplete.\n"
        "Signal completion by running the skill shown in the prompt.\n"
    )

    def build_prompt(
        self,
        *,
        worktree_path: str,
        spec_content: str,
        tasks_content: str,
        build_skill: str,
        strategy_context: str = "",
        lessons: str = "",
        pitfalls: str = "",
        bugfix_content: str = "",
    ) -> str:
        """Prompt for a fresh build (outer_iter == 0) or a full rebuild."""
        parts = [
            self.SYSTEM_PREAMBLE,
            f"## Worktree\n{worktree_path}",
            f"## Spec\n{spec_content}",
            f"## Tasks\n{tasks_content}",
        ]

        if lessons or pitfalls:
            constraints = "\n".join(filter(None, [lessons, pitfalls]))
            parts.append(f"## Mandatory Constraints (Lessons)\n{constraints}")

        if bugfix_content:
            parts.append(f"## Bugfix Context\n{bugfix_content}")

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
            "Edit only the files needed to fix the listed failures."
        )

        return "\n\n".join(parts)
