from __future__ import annotations

import pytest

from harness.prompt_markdown import FrontmatterParseError, parse_prompt_markdown


def test_parse_prompt_markdown_strips_leading_yaml_frontmatter() -> None:
    parsed = parse_prompt_markdown(
        "---\n"
        "model: local-qwen\n"
        "reasoning_effort: high\n"
        "temperature: 0.1\n"
        "---\n"
        "# Agent\n"
        "Runtime instructions.\n"
    )

    assert parsed.had_frontmatter is True
    assert parsed.metadata == {
        "model": "local-qwen",
        "reasoning_effort": "high",
        "temperature": 0.1,
    }
    assert parsed.body == "# Agent\nRuntime instructions.\n"


def test_parse_prompt_markdown_leaves_non_frontmatter_markdown_unchanged() -> None:
    text = "# Agent\n\n---\n\nThis horizontal rule stays in the body.\n"

    parsed = parse_prompt_markdown(text)

    assert parsed.had_frontmatter is False
    assert parsed.metadata == {}
    assert parsed.body == text


def test_parse_prompt_markdown_recovers_unquoted_colon_scalars() -> None:
    parsed = parse_prompt_markdown(
        "---\n"
        "description: Reviews traces: especially ambiguous inputs\n"
        "model: local-qwen\n"
        "---\n"
        "# Agent\n"
    )

    assert parsed.metadata["description"] == "Reviews traces: especially ambiguous inputs"
    assert parsed.metadata["model"] == "local-qwen"
    assert parsed.body == "# Agent\n"


def test_parse_prompt_markdown_rejects_invalid_frontmatter() -> None:
    with pytest.raises(FrontmatterParseError):
        parse_prompt_markdown("---\nmodel: [unterminated\n---\n# Agent\n")
