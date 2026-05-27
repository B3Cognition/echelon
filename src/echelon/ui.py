"""Shared UI helpers — branded card output for echelon CLI and harness."""
from __future__ import annotations

import sys
from typing import IO, Any

CARD_INNER = 52  # characters between ╭ and ╮


def banner(
    title: str,
    fields: list[tuple[str, str]],
    subtitle: str = "",
    flush: bool = True,
    file: IO[Any] | None = None,
) -> None:
    """Print a branded echelon card.

    Short single-line values are rendered as an aligned table.
    Multi-line, long (>8 words), or 'echelon ...' values become labeled
    sections with an underline, giving them visual prominence.
    """
    _file = file if file is not None else sys.stdout

    def _p(text: str = "") -> None:
        print(text, flush=flush, file=_file)

    prefix = f"─ ✈ echelon · {title} "
    fill = "─" * max(0, CARD_INNER - len(prefix))
    _p(f"\n╭{prefix}{fill}╮")
    if subtitle:
        body = f"  {subtitle}"
        if len(body) > CARD_INNER:
            body = body[: CARD_INNER - 1] + "…"
        _p(f"│{body.ljust(CARD_INNER)}│")
    _p(f"╰{'─' * CARD_INNER}╯\n")

    def _is_section(val: str) -> bool:
        return "\n" in val or val.strip().startswith("echelon ") or len(val.split()) > 8

    label_w = max((len(k) for k, v in fields if not _is_section(v)), default=0)

    prev_section = False
    prev_inline = False
    for key, val in fields:
        if _is_section(val):
            if prev_inline or prev_section:
                _p()
            _p(f"  {key}")
            _p(f"  {'─' * len(key)}")
            for line in val.strip().splitlines():
                _p(f"  {line}")
            prev_section = True
            prev_inline = False
        else:
            _p(f"  {key.ljust(label_w)}  {val}")
            prev_inline = True
            prev_section = False

    _p()
