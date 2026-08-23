from __future__ import annotations

from pathlib import Path
import re

import yaml

from harness.prompt_markdown import read_prompt_markdown


ROOT = Path(__file__).resolve().parents[2]
BASELINER = ROOT / "prosaic" / "subagents" / "echelon.re-baseliner.md"


def _rule_sections(body: str) -> list[str]:
    return re.findall(
        r"(?ms)^### Rule \d+[^\n]*\n(?P<body>.*?)(?=^### Rule |^## |\Z)",
        body,
    )


def _output_contract(body: str) -> dict[str, object]:
    match = re.search(r"(?ms)^## Output Block\n+```yaml\n(.*?)```", body)
    assert match is not None, "baseliner must expose a machine-readable output block"
    loaded = yaml.safe_load(match.group(1))
    assert isinstance(loaded, dict)
    return loaded


def test_baseliner_has_neutral_write_scoped_execution_metadata() -> None:
    prompt = read_prompt_markdown(BASELINER)

    assert prompt.had_frontmatter is True
    assert prompt.metadata == {
        "name": "echelon.re-baseliner",
        "description": "RE-BASELINER — authors one bounded compact baseline payload",
        "execution": "agent",
        "tools": "write",
        "color": "orange",
        "model_tier": "strong",
        "effort": "high",
    }


def test_every_baseliner_behavior_rule_has_an_always_never_pair() -> None:
    body = read_prompt_markdown(BASELINER).body
    sections = _rule_sections(body)

    assert len(sections) >= 6
    for section in sections:
        always = [line for line in section.splitlines() if line.startswith("ALWAYS ")]
        never = [line for line in section.splitlines() if line.startswith("NEVER ")]
        assert len(always) == 1
        assert len(never) == 1


def test_baseliner_rules_close_the_authority_escape_routes() -> None:
    body = read_prompt_markdown(BASELINER).body
    always_rules = "\n".join(
        line for line in body.splitlines() if line.startswith("ALWAYS ")
    ).lower()
    never_rules = "\n".join(
        line for line in body.splitlines() if line.startswith("NEVER ")
    ).lower()

    for required in (
        "bounded context",
        "semantic",
        "evidence",
        "not_established",
        "authorial payload",
        "done",
    ):
        assert required in always_rules
    for forbidden in (
        "filesystem discovery",
        "live source workspace",
        "controller state",
        "identity",
        "coverage",
        "semantic audit",
        "workspace synthesis",
        "full quality",
    ):
        assert forbidden in never_rules


def test_baseliner_limits_write_authority_to_the_candidate_payload() -> None:
    body = read_prompt_markdown(BASELINER).body

    assert (
        "ALWAYS use write authority only to write exactly `baseline.json` in the "
        "supplied candidate root."
    ) in body
    assert (
        "NEVER perform filesystem discovery, read the live source workspace, or "
        "write any other path."
    ) in body


def test_baseliner_result_block_is_the_exact_minimal_transport_contract() -> None:
    body = read_prompt_markdown(BASELINER).body

    assert _output_contract(body) == {
        "echelon_result": {"verdict": "DONE", "state_updates": {}}
    }
