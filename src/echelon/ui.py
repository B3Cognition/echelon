"""Shared UI helpers — branded card output for echelon CLI and harness."""
from __future__ import annotations

CARD_INNER = 52  # characters between ╭ and ╮


def banner(
    title: str,
    fields: list[tuple[str, str]],
    subtitle: str = "",
    flush: bool = True,
) -> None:
    """Print a branded echelon card.

    Short single-line values are rendered as an aligned table.
    Multi-line, long (>8 words), or 'echelon ...' values become labeled
    sections with an underline, giving them visual prominence.
    """
    prefix = f"─ ✈ echelon · {title} "
    fill = "─" * max(0, CARD_INNER - len(prefix))
    print(f"\n╭{prefix}{fill}╮", flush=flush)
    if subtitle:
        body = f"  {subtitle}"
        if len(body) > CARD_INNER:
            body = body[: CARD_INNER - 1] + "…"
        print(f"│{body.ljust(CARD_INNER)}│", flush=flush)
    print(f"╰{'─' * CARD_INNER}╯\n", flush=flush)

    def _is_section(val: str) -> bool:
        return "\n" in val or val.strip().startswith("echelon ") or len(val.split()) > 8

    label_w = max((len(k) for k, v in fields if not _is_section(v)), default=0)

    prev_section = False
    prev_inline = False
    for key, val in fields:
        if _is_section(val):
            if prev_inline or prev_section:
                print(flush=flush)
            print(f"  {key}", flush=flush)
            print(f"  {'─' * len(key)}", flush=flush)
            for line in val.strip().splitlines():
                print(f"  {line}", flush=flush)
            prev_section = True
            prev_inline = False
        else:
            print(f"  {key.ljust(label_w)}  {val}", flush=flush)
            prev_inline = True
            prev_section = False

    print(flush=flush)
