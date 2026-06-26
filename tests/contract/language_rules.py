"""Language-rule file contract checks migrated from shell tests."""

from __future__ import annotations

from pathlib import Path
import re


def validate_language_rules(root: Path) -> list[str]:
    """Return deterministic language-rule contract failures."""
    failures: list[str] = []
    rules_dir = root / "knowledge-base/language-rules"
    required_files = {
        "typescript.md": [
            ("covers strict mode", re.compile(r"strict")),
            ("covers no-any rule", re.compile(r"any")),
            ("covers error handling", re.compile(r"[Ee]rror [Hh]andling")),
            ("covers null safety", re.compile(r"[Nn]ull")),
        ],
        "python.md": [
            ("covers type hints", re.compile(r"[Tt]ype [Hh]int")),
            ("covers docstrings", re.compile(r"[Dd]ocstring")),
            (
                "covers no bare except",
                re.compile(r"bare.*except|except.*bare|No bare"),
            ),
            ("covers f-strings", re.compile(r"f-string")),
        ],
        "bash.md": [
            ("covers set -euo pipefail", re.compile(r"set -euo pipefail")),
            ("covers variable quoting", re.compile(r"[Qq]uot")),
            ("covers shellcheck compliance", re.compile(r"[Ss]hellcheck|shellcheck")),
        ],
    }

    for file_name, patterns in required_files.items():
        path = rules_dir / file_name
        if not path.exists():
            failures.append(f"{file_name} missing")
            continue
        if not path.is_file():
            failures.append(f"{file_name} is not a file")
            continue
        text = path.read_text(encoding="utf-8")
        if not text:
            failures.append(f"{file_name} is empty")
            continue
        for description, pattern in patterns:
            if not pattern.search(text):
                failures.append(f"{file_name} {description}")

    return failures
