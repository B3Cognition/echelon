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
    r"`(agents/(?:[^`]+/(?:templates|appendices)/[^`]+))`"
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
