from __future__ import annotations

import io

from echelon.ui import CARD_INNER, banner


def _box_lines(output: str) -> list[str]:
    return [
        line for line in output.splitlines()
        if line.startswith(("╭", "│", "╰"))
    ]


def test_banner_wraps_operational_subtitle_at_fixed_width() -> None:
    buf = io.StringIO()

    banner(
        "EXTENSION DRIFT",
        [("installed", ".specify/extensions/echelon")],
        subtitle="Installed Echelon extension differs from this checkout",
        file=buf,
    )

    output = buf.getvalue()
    assert "…" not in output
    assert "Installed Echelon extension differs from this" in output
    assert "checkout" in output
    assert all(len(line) == CARD_INNER + 2 for line in _box_lines(output))


def test_banner_wraps_long_subtitle_without_ellipsis() -> None:
    subtitle = (
        "Installed Echelon extension differs from the trusted source extension "
        "configured for this project"
    )
    buf = io.StringIO()

    banner("EXTENSION DRIFT", [], subtitle=subtitle, file=buf)

    output = buf.getvalue()
    assert "…" not in output
    assert "Installed Echelon extension differs from the" in output
    assert "trusted source extension configured for this" in output
    assert "project" in output
    assert all(len(line) == CARD_INNER + 2 for line in _box_lines(output))
