from __future__ import annotations

import io
import os

from echelon.ui import banner


def test_banner_expands_to_fit_operational_subtitle(monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.get_terminal_size",
        lambda fallback: os.terminal_size((100, 24)),
    )
    buf = io.StringIO()

    banner(
        "EXTENSION DRIFT",
        [("installed", ".specify/extensions/echelon")],
        subtitle="Installed Echelon extension differs from this checkout",
        file=buf,
    )

    output = buf.getvalue()
    assert "Installed Echelon extension differs from this checkout" in output
    assert "…" not in output


def test_banner_wraps_long_subtitle_without_ellipsis(monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.get_terminal_size",
        lambda fallback: os.terminal_size((60, 24)),
    )
    subtitle = (
        "Installed Echelon extension differs from the trusted source extension "
        "configured for this project"
    )
    buf = io.StringIO()

    banner("EXTENSION DRIFT", [], subtitle=subtitle, file=buf)

    output = buf.getvalue()
    assert "…" not in output
    assert "Installed Echelon extension differs from the trusted" in output
    assert "source extension configured for this project" in output
