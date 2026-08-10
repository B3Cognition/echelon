#!/usr/bin/env python3
"""prompt_lint.py — Glossary ambiguity linter for Echelon agent prompts.

Usage:
    python prompt_lint.py [--root <agents_dir>] [--definition <definition.yaml>]
                          [--output json|text] [--no-exit-on-ambiguous]

Scans agent prompt files for glossary terms that have multiple senses (overloaded).
Reports per-file term occurrences with line numbers.
Exits non-zero if ambiguous usage is detected (unless --no-exit-on-ambiguous).

Contracts:
- Default scan root: prosaic/**/*.md
- --root override for test fixtures
- Reports per-file term occurrences with line numbers
- Exits non-zero if ambiguous use detected
- Resolves glossary from definition.yaml glossary: block
- Standard library only (no external deps for core logic)
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent

DEFAULT_AGENTS_ROOT = REPO_ROOT / "prosaic"
DEFAULT_DEFINITION = REPO_ROOT / "runtime" / "workflow" / "definition.yaml"


def _load_glossary(definition_path: Path) -> list:
    """Load glossary terms from definition.yaml.

    Returns list of {term, senses: [{sense, detect, example}]} dicts.
    """
    if not definition_path.exists():
        return []
    try:
        import yaml  # type: ignore
        with definition_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            return []
        return data.get("glossary", [])
    except ImportError:
        # Manual extraction fallback using regex
        return _parse_glossary_manual(definition_path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _parse_glossary_manual(text: str) -> list:
    """Minimal fallback glossary parser — extracts terms from YAML without PyYAML."""
    terms = []
    current_term = None
    current_senses = []
    current_sense = None

    for line in text.splitlines():
        stripped = line.rstrip()

        # Term line
        tm = re.match(r'^  - term:\s+"?([^"]+)"?', stripped)
        if tm:
            if current_term and current_senses:
                terms.append({"term": current_term, "senses": current_senses})
            current_term = tm.group(1).strip()
            current_senses = []
            current_sense = None
            continue

        # Sense line
        sm = re.match(r'^      - sense:\s+"?([^"]+)"?', stripped)
        if sm and current_term:
            if current_sense is not None:
                current_senses.append(current_sense)
            current_sense = {"sense": sm.group(1), "detect": "", "example": ""}
            continue

        # Detect line
        dm = re.match(r'^        detect:\s+"?([^"]+)"?', stripped)
        if dm and current_sense is not None:
            current_sense["detect"] = dm.group(1)
            continue

    # Flush
    if current_sense is not None:
        current_senses.append(current_sense)
    if current_term and current_senses:
        terms.append({"term": current_term, "senses": current_senses})

    return terms


def _scan_file(file_path: Path, terms: list) -> list:
    """Scan a single file for glossary term occurrences.

    Returns list of {term, line_number, line_text, sense_count, ambiguous} dicts.
    """
    findings = []
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return findings

    for term_entry in terms:
        term = term_entry.get("term", "")
        senses = term_entry.get("senses", [])
        sense_count = len(senses)
        is_ambiguous = sense_count > 1

        if not term:
            continue

        # Regex: whole-word match, case-insensitive
        pattern = re.compile(r'\b' + re.escape(term) + r'\b', re.IGNORECASE)

        for lineno, line in enumerate(lines, start=1):
            if pattern.search(line):
                findings.append({
                    "term": term,
                    "line_number": lineno,
                    "line_text": line.strip()[:120],
                    "sense_count": sense_count,
                    "ambiguous": is_ambiguous,
                    "file": str(file_path),
                })

    return findings


def lint_prompts(
    root: Path,
    definition_path: Path,
) -> dict:
    """Run the prompt lint scan.

    Args:
        root:            Root directory to scan for *.md files
        definition_path: Path to definition.yaml with glossary: block

    Returns:
        {files_scanned, terms_loaded, findings, ambiguous_count,
         ambiguous_files, exit_code}
    """
    glossary = _load_glossary(definition_path)

    if not root.exists():
        return {
            "error": f"scan root not found: {root}",
            "files_scanned": 0,
            "terms_loaded": 0,
            "findings": [],
            "ambiguous_count": 0,
            "ambiguous_files": [],
            "exit_code": 2,
        }

    md_files = sorted(root.rglob("*.md"))
    all_findings = []
    ambiguous_files = set()

    for md_file in md_files:
        findings = _scan_file(md_file, glossary)
        all_findings.extend(findings)
        for f in findings:
            if f["ambiguous"]:
                ambiguous_files.add(str(md_file))

    ambiguous_count = sum(1 for f in all_findings if f["ambiguous"])

    return {
        "scan_root": str(root),
        "definition_path": str(definition_path),
        "files_scanned": len(md_files),
        "terms_loaded": len(glossary),
        "findings": all_findings,
        "ambiguous_count": ambiguous_count,
        "ambiguous_files": sorted(ambiguous_files),
        "exit_code": 1 if ambiguous_count > 0 else 0,
    }


def _format_text_report(result: dict) -> str:
    """Format result as human-readable text."""
    lines = []
    lines.append(f"Prompt Lint Report")
    lines.append(f"  Scan root:     {result.get('scan_root', '?')}")
    lines.append(f"  Definition:    {result.get('definition_path', '?')}")
    lines.append(f"  Files scanned: {result['files_scanned']}")
    lines.append(f"  Terms loaded:  {result['terms_loaded']}")
    lines.append(f"  Ambiguous:     {result['ambiguous_count']}")
    lines.append("")

    if result.get("error"):
        lines.append(f"ERROR: {result['error']}")
        return "\n".join(lines)

    # Group by file
    by_file: dict = {}
    for f in result["findings"]:
        by_file.setdefault(f["file"], []).append(f)

    for filepath, findings in sorted(by_file.items()):
        lines.append(f"  {filepath}")
        for f in findings:
            marker = "!" if f["ambiguous"] else " "
            lines.append(
                f"    {marker} L{f['line_number']:4d}  [{f['term']}] ({f['sense_count']} senses)  "
                f"{f['line_text'][:80]}"
            )
        lines.append("")

    if result["ambiguous_count"] > 0:
        lines.append(f"FAIL: {result['ambiguous_count']} ambiguous term occurrences found")
        lines.append("  Ambiguous files:")
        for f in result["ambiguous_files"]:
            lines.append(f"    {f}")
    else:
        lines.append("PASS: no ambiguous term occurrences found")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lint Echelon agent prompts for glossary term ambiguity."
    )
    parser.add_argument(
        "--root", default=None,
        help=f"Scan root directory (default: {DEFAULT_AGENTS_ROOT})"
    )
    parser.add_argument(
        "--definition", default=None,
        help=f"Path to definition.yaml (default: {DEFAULT_DEFINITION})"
    )
    parser.add_argument(
        "--output", choices=["json", "text"], default="text",
        help="Output format (default: text)"
    )
    parser.add_argument(
        "--no-exit-on-ambiguous", action="store_true",
        help="Do not exit non-zero even if ambiguous usages are found"
    )
    args = parser.parse_args()

    root = Path(args.root) if args.root else DEFAULT_AGENTS_ROOT
    definition_path = Path(args.definition) if args.definition else DEFAULT_DEFINITION

    result = lint_prompts(root, definition_path)

    if args.output == "json":
        print(json.dumps(result, indent=2))
    else:
        print(_format_text_report(result))

    if result.get("error"):
        return 2

    if args.no_exit_on_ambiguous:
        return 0
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
