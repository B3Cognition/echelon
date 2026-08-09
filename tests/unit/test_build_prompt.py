"""Tests for BuildPromptBuilder."""
from __future__ import annotations
import pytest
from harness.build_prompt import BuildPromptBuilder


@pytest.mark.unit
class TestBuildPromptBuilder:
    def setup_method(self):
        self.builder = BuildPromptBuilder()

    def test_build_prompt_contains_worktree_path(self):
        prompt = self.builder.build_prompt(
            worktree_path="/wt/001",
            spec_content="FR-001: login",
            tasks_content="Task 1: impl",
            build_skill="echelon.build",
        )
        assert "/wt/001" in prompt

    def test_build_prompt_forbids_global_filesystem_search(self):
        prompt = self.builder.build_prompt(
            worktree_path="/wt/001",
            spec_content="spec",
            tasks_content="tasks",
            build_skill="echelon.build",
        )

        assert "Do not search outside the worktree" in prompt
        assert "do not run global `find`" in prompt
        assert "If required Echelon files are missing" in prompt

    def test_build_prompt_forbids_stopping_on_next_phase(self):
        prompt = self.builder.build_prompt(
            worktree_path="/wt/001",
            spec_content="spec",
            tasks_content="tasks",
            build_skill="echelon.build",
        )

        assert "Ralph does not consume `next_phase`" in prompt
        assert "Do not end after build-1-init" in prompt
        assert "Ralph owns the outer loop" in prompt
        assert ".harness-build-status.json" in prompt

    def test_build_prompt_defines_iteration_status_contract(self):
        prompt = self.builder.build_prompt(
            worktree_path="/wt/001",
            spec_content="spec",
            tasks_content="tasks",
            build_skill="echelon.build",
        )

        assert '"status": "done"' in prompt
        assert "completed_task_ids" in prompt
        assert "one bounded verified progress slice" in prompt
        assert "Ralph will mark those tasks DONE, verify, commit, and start another invocation" in prompt
        assert "iteration completed useful verified progress" in prompt
        assert "overall spec is still incomplete" in prompt
        assert '"status": "blocked"' in prompt
        assert '"status": "impasse"' not in prompt

    def test_build_prompt_forbids_direct_task_file_progress_edits(self):
        prompt = self.builder.build_prompt(
            worktree_path="/wt/001",
            spec_content="spec",
            tasks_content="tasks",
            build_skill="echelon.build",
        )

        assert "Do not edit `tasks.md`" in prompt
        assert "Ralph owns task progress writes" in prompt
        assert "completed_task_ids" in prompt

    def test_build_prompt_forbids_native_task_planning_tools_and_group_ids(self):
        prompt = self.builder.build_prompt(
            worktree_path="/wt/001",
            spec_content="spec",
            tasks_content="tasks",
            build_skill="echelon.build",
        )

        assert "Do not use native task-planning tools" in prompt
        assert "TaskCreate" in prompt
        assert "TaskUpdate" in prompt
        assert "Never report ranges or grouped task labels" in prompt
        assert "T-063..T-068" in prompt

    def test_build_prompt_contains_spec(self):
        prompt = self.builder.build_prompt(
            worktree_path="/wt/001",
            spec_content="FR-001: login endpoint",
            tasks_content="Task 1: impl",
            build_skill="echelon.build",
        )
        assert "FR-001: login endpoint" in prompt

    def test_build_prompt_contains_skill(self):
        prompt = self.builder.build_prompt(
            worktree_path="/wt/001",
            spec_content="spec",
            tasks_content="tasks",
            build_skill="speckit-codegen-build",
        )
        assert "speckit-codegen-build" in prompt

    def test_build_prompt_includes_lessons_when_present(self):
        prompt = self.builder.build_prompt(
            worktree_path="/wt/001",
            spec_content="spec",
            tasks_content="tasks",
            build_skill="echelon.build",
            lessons="NEVER hardcode ports",
        )
        assert "NEVER hardcode ports" in prompt

    def test_build_prompt_omits_lessons_section_when_empty(self):
        prompt = self.builder.build_prompt(
            worktree_path="/wt/001",
            spec_content="spec",
            tasks_content="tasks",
            build_skill="echelon.build",
            lessons="",
        )
        assert "Mandatory Constraints" not in prompt

    def test_build_prompt_includes_bugfix_when_present(self):
        prompt = self.builder.build_prompt(
            worktree_path="/wt/001",
            spec_content="spec",
            tasks_content="tasks",
            build_skill="echelon.build",
            bugfix_content="Root cause: null pointer in auth.py:42",
        )
        assert "Root cause: null pointer" in prompt

    def test_feedback_prompt_contains_failure_output(self):
        prompt = self.builder.feedback_prompt(
            worktree_path="/wt/001",
            spec_content="spec",
            failures_output="AssertionError: expected 200 got 404",
            outer_iter=1,
        )
        assert "AssertionError: expected 200 got 404" in prompt
        assert "/wt/001" in prompt

    def test_feedback_prompt_says_do_not_rebuild(self):
        prompt = self.builder.feedback_prompt(
            worktree_path="/wt/001",
            spec_content="spec",
            failures_output="test failed",
            outer_iter=1,
        )
        # Must not re-run the full build pipeline
        assert "do not re-run" in prompt.lower() or "do not run" in prompt.lower()

    def test_feedback_prompt_forbids_manual_verify_spec_regeneration(self):
        prompt = self.builder.feedback_prompt(
            worktree_path="/wt/001",
            spec_content="spec",
            failures_output=(
                "fulfillment report is stale for current HEAD abc123: "
                "Run `echelon spec verify 001` before convergence."
            ),
            outer_iter=1,
        )

        assert "Do not run `echelon spec verify`" in prompt
        assert "Ralph owns fulfillment refresh" in prompt
        assert "Do not hand-edit `fulfillment-report.md` or `fulfillment-gaps.md`" in prompt

    def test_feedback_prompt_includes_lessons(self):
        prompt = self.builder.feedback_prompt(
            worktree_path="/wt/001",
            spec_content="spec",
            failures_output="test failed",
            outer_iter=1,
            lessons="ALWAYS use https",
        )
        assert "ALWAYS use https" in prompt

    def test_build_prompt_includes_pitfalls_when_present(self):
        prompt = self.builder.build_prompt(
            worktree_path="/wt/001",
            spec_content="spec",
            tasks_content="tasks",
            build_skill="echelon.build",
            pitfalls="NEVER use sync I/O in async handlers",
        )
        assert "NEVER use sync I/O in async handlers" in prompt
        assert "Mandatory Constraints" in prompt

    def test_build_prompt_omits_lessons_section_when_pitfalls_also_empty(self):
        prompt = self.builder.build_prompt(
            worktree_path="/wt/001",
            spec_content="spec",
            tasks_content="tasks",
            build_skill="echelon.build",
            lessons="",
            pitfalls="",
        )
        assert "Mandatory Constraints" not in prompt

    def test_build_prompt_includes_strategy_context_when_present(self):
        prompt = self.builder.build_prompt(
            worktree_path="/wt/001",
            spec_content="spec",
            tasks_content="tasks",
            build_skill="echelon.build",
            strategy_context="Use the SOAR pipeline",
        )
        assert "Use the SOAR pipeline" in prompt
        assert "Strategy Context" in prompt
