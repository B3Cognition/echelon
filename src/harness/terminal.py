"""Terminal output utilities -- banner, colors, formatting.

Per T037:
- Escalation banner for stderr
- Respects NO_COLOR env var
- Adapts to terminal width (default 80 columns)
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional


def get_terminal_width(default: int = 80) -> int:
    """Get terminal width, falling back to default."""
    try:
        return os.get_terminal_size().columns
    except (OSError, ValueError):
        return default


def print_banner(
    header: str,
    body: str,
    *,
    footer: Optional[str] = None,
    file: Any = None,
    width: Optional[int] = None,
) -> None:
    """Print a formatted banner to the given file (default: stderr).

    Args:
        header: Banner header text.
        body: Banner body text.
        footer: Optional footer text.
        file: Output file (default: stderr).
        width: Banner width (default: terminal width or 80).
    """
    if file is None:
        file = sys.stderr

    if width is None:
        width = get_terminal_width()

    separator = "=" * width

    lines = [
        "",
        separator,
        f"  {header}".ljust(width),
        separator,
        "",
    ]

    # Wrap body lines to width
    for line in body.split("\n"):
        if len(line) > width - 4:
            lines.append(f"  {line[:width - 7]}...")
        else:
            lines.append(f"  {line}")

    lines.append("")

    if footer:
        lines.append(f"  {footer}")
        lines.append("")

    lines.append(separator)
    lines.append("")

    for line in lines:
        print(line, file=file)


def print_escalation_banner(
    category: str,
    question: str,
    context: str,
    *,
    spec_id: str = "<spec_id>",
    file: Any = None,
) -> None:
    """Print escalation-specific banner.

    Args:
        category: Escalation category.
        question: Question for the human.
        context: Context summary.
        file: Output file (default: stderr).
    """
    body = f"Question: {question}\n\nContext: {context}"
    print_banner(
        header=f"BLOCKED -- {category}",
        body=body,
        footer=(
            "Next step: append ## Answer to the escalation file, then run "
            f"echelon harness resume {spec_id}"
        ),
        file=file,
    )
