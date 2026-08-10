#!/usr/bin/env python3
"""CLI for Lexicon — deterministic validation of controlled specifications.

    lexicon validate spec.md --type spec --glossary glossary.md [--json]

Exits 0 when the artifact passes every hard gate, 1 otherwise — so it drops
into CI or an echelon `commander_internal` phase the same way
`understanding --validate` does.
"""

from __future__ import annotations

import json as _json
import sys
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .glossary import load_glossary_terms as _load_glossary
from .validity import validate as _validate

app = typer.Typer(
    name="lexicon",
    help="Deterministic validation of Lexicon controlled specifications.",
    add_completion=False,
)

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


@app.command()
def validate(
    spec: Path = typer.Argument(..., exists=True, readable=True, help="Artifact file to validate."),
    artifact_type: Optional[str] = typer.Option(
        None, "--type", help="Override artifact type (spec|story|article|tasks|structural). Default: read from ARTIFACT header.",
    ),
    glossary: Optional[Path] = typer.Option(
        None, "--glossary", exists=True, readable=True,
        help="Glossary file of approved terms (one per line, ### headings, or **bold** Markdown).",
    ),
    spec_ref: Optional[Path] = typer.Option(
        None, "--spec-ref", exists=True, readable=True,
        help="spec.md for cross-document checks (used with --type tasks/structural)."),
    source_ref: Optional[Path] = typer.Option(
        None, "--source-ref", exists=True, readable=True,
        help="Source artifact for derived Lexicon freshness and ID-equivalence checks."),
    as_json: bool = typer.Option(False, "--json", help="Emit a machine-readable report."),
    artifact_key: Optional[str] = typer.Option(
        None, "--artifact", help="governance.artifacts key (used with --type structural).",
    ),
) -> None:
    """Validate an artifact against the Lexicon hard-gate stack."""
    text = spec.read_text(encoding="utf-8")

    if (artifact_type or "").lower() == "structural":
        from .manifest import load_governance
        from .structural import structural_validate
        from .structural_score import structural_quality

        # Resolve the deployed runtime, or the checked-out runtime during development.
        # Pick the first whose
        # governance.artifacts mapping contains the requested artifact_key.
        _candidate_bases = [
            Path(".echelon/runtime"),
            Path("runtime"),
        ]
        chosen_base = None
        governance: dict = {}
        for _base in _candidate_bases:
            _cfg = _base / "echelon-config.yml"
            _gov = load_governance(_cfg)
            if artifact_key and artifact_key in _gov:
                chosen_base = _base
                governance = _gov
                break

        if chosen_base is None or not artifact_key or artifact_key not in governance:
            typer.echo(f"unknown governance artifact {artifact_key!r}", err=True)
            raise typer.Exit(2)

        entry = governance[artifact_key]
        # Resolve the template to an absolute path so structural_validate's
        # internal `_TEMPLATES / entry["template"]` resolves correctly regardless
        # of cwd — Path("anything") / "<absolute>" yields the absolute path.
        if entry.get("template"):
            abs_template = (chosen_base / "templates" / entry["template"]).resolve()
            entry = {**entry, "template": str(abs_template)}

        spec_text = spec_ref.read_text(encoding="utf-8") if spec_ref else ""
        report = structural_validate(text, entry, spec_text)
        score = structural_quality(text, entry, spec_text)
        payload = {
            "file": str(spec),
            "ok": report.ok,
            "soft_score": score,
            "findings": [
                {"code": f.code, "message": f.message, "line": f.line, "span": f.span}
                for f in report.findings
            ],
        }
        if as_json:
            typer.echo(_json.dumps(payload, indent=2))
        else:
            status = "OK" if report.ok else "FAIL"
            typer.echo(
                f"{status} structural:{artifact_key} "
                f"soft={score:.2f} findings={len(report.findings)}"
            )
            if not report.ok:
                for f in report.findings:
                    typer.echo(f"  {spec}:{f.line}  [{f.code}] {f.message}")
        raise typer.Exit(0 if report.ok else 1)

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
    if source_ref is not None:
        from .source_contract import source_contract_findings

        report.findings.extend(source_contract_findings(text, source_ref))
        report.ok = not report.findings

    if as_json:
        typer.echo(
            _json.dumps(
                {
                    "file": str(spec),
                    "ok": report.ok,
                    "source_ref": str(source_ref) if source_ref else None,
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
