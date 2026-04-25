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
        "Do not run git commands. Do not commit. Do not push.\n"
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
            f"Write all output files to: {worktree_path}"
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
