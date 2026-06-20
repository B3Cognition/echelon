#!/usr/bin/env python3
"""CLI for Lexicon — deterministic validation of controlled specifications.

    lexicon validate spec.md --type spec --glossary glossary.md [--json]

Exits 0 when the artifact passes every hard gate, 1 otherwise — so it drops
into CI or an echelon `commander_internal` phase the same way
`understanding --validate` does.
"""

from __future__ import annotations

import json as _json
import re
import sys
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .validity import validate as _validate

app = typer.Typer(
    name="lexicon",
    help="Deterministic validation of Lexicon controlled specifications.",
    add_completion=False,
)

_BOLD_TERM_RE = re.compile(r"\*\*([^*]+)\*\*")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"lexicon version {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Lexicon controlled-specification validator."""


def _load_glossary(path: Optional[Path]) -> set[str]:
    """Read approved terms from a glossary file.

    Accepts one term per line; also harvests **bold** terms so a real
    glossary.md works. Blank lines and ``#`` comments are ignored.
    """
    if path is None:
        return set()
    terms: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        bold = _BOLD_TERM_RE.findall(line)
        if bold:
            terms.update(t.strip() for t in bold)
        else:
            terms.add(line)
    return terms


@app.command()
def validate(
    spec: Path = typer.Argument(..., exists=True, readable=True, help="Artifact file to validate."),
    artifact_type: Optional[str] = typer.Option(
        None, "--type", help="Override artifact type (spec|story|article|tasks). Default: read from ARTIFACT header.",
    ),
    glossary: Optional[Path] = typer.Option(
        None, "--glossary", exists=True, readable=True,
        help="Glossary file of approved terms (one per line or **bold** in markdown).",
    ),
    spec_ref: Optional[Path] = typer.Option(
        None, "--spec-ref", exists=True, readable=True,
        help="spec.md for cross-document checks (used with --type tasks)."),
    as_json: bool = typer.Option(False, "--json", help="Emit a machine-readable report."),
) -> None:
    """Validate an artifact against the Lexicon hard-gate stack."""
    text = spec.read_text(encoding="utf-8")

    if (artifact_type or "").lower() == "tasks":
        from .tasks import validate_tasks
        from .tasks_score import task_quality
        spec_text = spec_ref.read_text(encoding="utf-8") if spec_ref else None
        report = validate_tasks(text, glossary=_load_glossary(glossary), spec_text=spec_text)
        if as_json:
            typer.echo(_json.dumps({
                "file": str(spec),
                "ok": report.ok,
                "parse_pass": report.parse_pass,
                "soft_score": task_quality(text),
                "findings": [
                    {"code": f.code, "message": f.message, "line": f.line, "span": f.span}
                    for f in report.findings
                ],
            }, indent=2))
        elif report.ok:
            typer.echo(f"✓ {spec}: valid [TASKS] (soft={task_quality(text)['overall']:.2f})")
        else:
            typer.echo(f"✗ {spec}: invalid")
            for f in report.findings:
                typer.echo(f"  {spec}:{f.line}  [{f.code}] {f.message}")
        raise typer.Exit(code=0 if report.ok else 1)

    report = _validate(
        text,
        glossary=_load_glossary(glossary),
        artifact_type=artifact_type.upper() if artifact_type else None,
    )

    if as_json:
        typer.echo(
            _json.dumps(
                {
                    "file": str(spec),
                    "ok": report.ok,
                    "parse_pass": report.parse_pass,
                    "artifact_type": report.artifact_type,
                    "term_resolution": report.term_resolution,
                    "determinism": report.determinism,
                    "completeness": report.completeness,
                    "observability": report.observability,
                    "example_coverage": report.example_coverage,
                    "findings": [
                        {"code": f.code, "message": f.message, "line": f.line, "span": f.span}
                        for f in report.findings
                    ],
                },
                indent=2,
            )
        )
    elif report.ok:
        typer.echo(
            f"✓ {spec}: valid [{report.artifact_type}] "
            f"(T={report.term_resolution:.2f} D={report.determinism:.2f} "
            f"C={report.completeness:.2f} O={report.observability:.2f} "
            f"E={report.example_coverage:.2f})"
        )
    else:
        typer.echo(f"✗ {spec}: invalid")
        for f in report.findings:
            typer.echo(f"  {spec}:{f.line}  [{f.code}] {f.message}")

    raise typer.Exit(code=0 if report.ok else 1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
