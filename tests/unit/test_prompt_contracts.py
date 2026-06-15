from tests.kernel.test_prompt_references import (
    test_primary_agent_prompts_have_paired_always_never_rules as _assert_primary_agent_prompts_have_paired_always_never_rules,
)


def test_primary_agent_prompt_rules_are_paired_in_fast_unit_suite() -> None:
    _assert_primary_agent_prompts_have_paired_always_never_rules()
