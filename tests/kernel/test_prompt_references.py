from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]
EXTENSION_ROOT = REPO_ROOT / "extension"
PROMPT_ROOTS = [
    EXTENSION_ROOT / "agents",
    EXTENSION_ROOT / "commands",
    EXTENSION_ROOT / "workflow" / "phases",
]

REFERENCE_RE = re.compile(
    r"`((?:agents/(?:[^`]+/(?:templates|appendices)/[^`]+))|"
    r"(?:workflow/phases/appendices/[^`]+))`"
)


def test_prompt_template_and_appendix_references_exist():
    missing = []

    for root in PROMPT_ROOTS:
        for prompt in root.rglob("*.md"):
            text = prompt.read_text()
            for match in REFERENCE_RE.finditer(text):
                rel_path = match.group(1)
                target = EXTENSION_ROOT / rel_path
                if not target.exists():
                    missing.append(
                        f"{prompt.relative_to(REPO_ROOT)} references missing {rel_path}"
                    )

    assert not missing, "\n".join(missing)


def test_build_finalize_uses_appendices_for_large_reference_sections():
    prompt = EXTENSION_ROOT / "workflow" / "phases" / "build-8-finalize.md"
    text = prompt.read_text()

    assert "workflow/phases/appendices/build-8-verify-gates.md" in text
    assert "workflow/phases/appendices/build-8-summary-reference.md" in text


def test_sage_uses_appendix_for_decision_calibration_reference():
    prompt = EXTENSION_ROOT / "agents" / "exploration" / "sage.md"
    text = prompt.read_text()

    assert "agents/exploration/appendices/sage-decision-calibration-reference.md" in text


def test_sage_uses_appendix_for_understanding_followup_reference():
    prompt = EXTENSION_ROOT / "agents" / "exploration" / "sage.md"
    text = prompt.read_text()

    assert "agents/exploration/appendices/sage-understanding-followup-reference.md" in text


def test_sage_uses_appendix_for_contradiction_detection_reference():
    prompt = EXTENSION_ROOT / "agents" / "exploration" / "sage.md"
    text = prompt.read_text()

    assert "agents/exploration/appendices/sage-contradiction-detection-reference.md" in text


def test_cartographer_uses_appendix_for_brownfield_deep_dive_reference():
    prompt = EXTENSION_ROOT / "agents" / "exploration" / "cartographer.md"
    text = prompt.read_text()

    assert (
        "agents/exploration/appendices/cartographer-golddigger-deep-dive-reference.md"
        in text
    )


def test_commands_use_jsonl_reasoning_journal_name():
    stale = []

    for prompt in (EXTENSION_ROOT / "commands").rglob("*.md"):
        for lineno, line in enumerate(prompt.read_text().splitlines(), start=1):
            if "reasoning-journal.json" in line and "reasoning-journal.jsonl" not in line:
                stale.append(f"{prompt.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")

    assert not stale, "\n".join(stale)
