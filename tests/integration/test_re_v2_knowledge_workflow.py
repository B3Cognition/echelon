"""One logical reviewed-analysis, synthesis, and publication action."""

from __future__ import annotations

import pytest

from harness.re_registry import load_published_index
from tests.integration.test_re_v2_reviewed_synthesis import (
    _reviewed_context_with_executor,
    _synthesis_agent,
)
from tests.unit.test_re_v2_protocol_27_controller import _ScriptedProvider
from tests.unit.test_re_v2_protocol_28_reconciliation import KnowledgeBackend


class _WorkflowProvider:
    def __init__(self) -> None:
        self.analysis = KnowledgeBackend()
        self.synthesis = _ScriptedProvider()

    def execute(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self.analysis.execute(*args, **kwargs)

    def exec_agent(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self.synthesis.exec_agent(*args, **kwargs)


@pytest.mark.integration
def test_workflow_restarts_after_analysis_and_publishes_once(
    tmp_path,
    monkeypatch,
) -> None:
    from harness.prosaic_prompt_loader import ProsaicPromptLoader
    from harness.re_v2.knowledge_workflow import run_knowledge_workflow
    from harness.re_v2.protocol_28.status import protocol_28_status_document

    context = _reviewed_context_with_executor(tmp_path, complete=False)
    provider = _WorkflowProvider()
    monkeypatch.setattr(
        ProsaicPromptLoader,
        "load_subagent",
        lambda _self, _name: _synthesis_agent(),
    )

    def interrupt(point: str) -> None:
        if point == "after_analysis":
            raise RuntimeError("synthetic workflow interruption")

    with pytest.raises(RuntimeError, match="synthetic workflow interruption"):
        run_knowledge_workflow(
            tmp_path,
            context.run_dir.name,
            lambda: provider,
            token_limit=10_000_000,
            active_ms_limit=10_000_000,
            fault_hook=interrupt,
        )
    analysis_calls = len(provider.analysis.calls)
    assert analysis_calls > 0
    assert provider.synthesis.calls == []
    assert load_published_index(tmp_path) is None

    result = run_knowledge_workflow(
        tmp_path,
        context.run_dir.name,
        lambda: provider,
        token_limit=10_000_000,
        active_ms_limit=10_000_000,
    )

    assert result.state == "complete"
    assert result.analysis_run_id == context.run_dir.name
    assert result.synthesis_run_id is not None
    assert result.publication_generation == 1
    assert len(provider.analysis.calls) == analysis_calls
    assert provider.synthesis.calls
    first_synthesis_calls = tuple(provider.synthesis.calls)
    assert protocol_28_status_document(context.run_dir)["workflow_state"] == "complete"

    replayed = run_knowledge_workflow(
        tmp_path,
        context.run_dir.name,
        lambda: pytest.fail("completed workflow invoked a provider"),
        token_limit=10_000_000,
        active_ms_limit=10_000_000,
    )

    assert replayed == result
    assert tuple(provider.synthesis.calls) == first_synthesis_calls
