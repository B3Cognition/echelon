#!/usr/bin/env python3
"""Sync EGR register rows to GitHub issues.

The source of truth remains docs/findings/echelon-grounded-review-register.md.
This script creates one issue per EGR row, labels it by priority/status, and
closes historical fixed or accepted-risk findings. It is intentionally
idempotent: existing issues are matched by the EGR ID in the title.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_REPO = "B3Cognition/echelon"
DEFAULT_REGISTER = Path("docs/findings/echelon-grounded-review-register.md")

LABELS: dict[str, tuple[str, str]] = {
    "egr": ("5319e7", "Echelon Grounded Review finding"),
    "priority:P0": ("b60205", "P0: must fix before serious use"),
    "priority:P1": ("d93f0b", "P1: important for reliability"),
    "priority:P2": ("fbca04", "P2: useful improvement"),
    "priority:P3": ("0e8a16", "P3: optional / future enhancement"),
    "status:fixed": ("0e8a16", "EGR has been fixed and verified"),
    "status:backlog": ("1d76db", "EGR is queued for implementation"),
    "status:open": ("1d76db", "EGR is confirmed and open"),
    "status:in-progress": ("c5def5", "EGR implementation is in progress"),
    "status:accepted-risk": ("6e7781", "EGR is intentionally accepted risk"),
    "status:superseded": ("bfd4f2", "EGR was superseded by another finding"),
}

CLOSE_REASON_BY_STATUS = {
    "fixed": "completed",
    "accepted-risk": "not planned",
    "superseded": "not planned",
}

MANAGED_LABEL_PREFIXES = ("priority:", "status:")


@dataclass(frozen=True)
class EgrFinding:
    id: str
    priority: str
    status: str
    finding: str
    evidence: str
    next_action: str

    @property
    def title(self) -> str:
        return f"{self.id}: {strip_md(self.finding)}"

    @property
    def labels(self) -> list[str]:
        return ["egr", f"priority:{self.priority}", f"status:{self.status}"]


def strip_md(text: str) -> str:
    return text.replace("`", "").replace("**", "").strip()


def run_gh(args: list[str], *, dry_run: bool = False) -> str:
    cmd = ["gh", *args]
    if dry_run:
        print("$ " + " ".join(cmd))
        return ""
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout.strip()


def parse_register(path: Path) -> list[EgrFinding]:
    rows: list[EgrFinding] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| EGR-"):
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) < 6:
            raise ValueError(f"cannot parse EGR row: {line}")
        rows.append(EgrFinding(*parts[:6]))
    return rows


def existing_labels(repo: str) -> set[str]:
    raw = run_gh(["label", "list", "--repo", repo, "--limit", "500", "--json", "name"])
    return {item["name"] for item in json.loads(raw or "[]")}


def ensure_labels(repo: str, required: set[str], *, dry_run: bool) -> None:
    existing = set() if dry_run else existing_labels(repo)
    for name in sorted(required):
        if name in existing:
            continue
        color, description = LABELS.get(name, ("ededed", "EGR sync label"))
        run_gh(
            [
                "label",
                "create",
                name,
                "--repo",
                repo,
                "--color",
                color,
                "--description",
                description,
            ],
            dry_run=dry_run,
        )


def find_issue(repo: str, egr_id: str) -> dict | None:
    raw = run_gh(
        [
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "all",
            "--search",
            f"{egr_id} in:title",
            "--json",
            "number,title,state,url,labels",
            "--limit",
            "20",
        ]
    )
    for item in json.loads(raw or "[]"):
        if item["title"].startswith(f"{egr_id}:"):
            return item
    return None


def issue_body(egr: EgrFinding, register_path: Path) -> str:
    return "\n".join(
        [
            f"<!-- egr-sync: {egr.id} -->",
            f"# {egr.id}",
            "",
            f"**Priority:** `{egr.priority}`",
            f"**Status:** `{egr.status}`",
            "",
            "## Finding",
            "",
            egr.finding,
            "",
            "## Evidence",
            "",
            egr.evidence,
            "",
            "## Next Action",
            "",
            egr.next_action,
            "",
            "## Source",
            "",
            f"Synced from `{register_path}`. The EGR register remains the source of truth.",
            "",
        ]
    )


def create_issue(repo: str, egr: EgrFinding, register_path: Path, *, dry_run: bool) -> str:
    args = [
        "issue",
        "create",
        "--repo",
        repo,
        "--title",
        egr.title,
        "--body",
        issue_body(egr, register_path),
    ]
    for label in egr.labels:
        args.extend(["--label", label])
    return run_gh(args, dry_run=dry_run)


def issue_from_url(url: str) -> dict | None:
    match = re.search(r"/issues/(\d+)\s*$", url.strip())
    if not match:
        return None
    return {"number": int(match.group(1)), "url": url.strip(), "state": "OPEN"}


def update_issue(repo: str, number: int, egr: EgrFinding, register_path: Path, *, dry_run: bool) -> None:
    args = [
        "issue",
        "edit",
        str(number),
        "--repo",
        repo,
        "--title",
        egr.title,
        "--body",
        issue_body(egr, register_path),
    ]
    for label in egr.labels:
        args.extend(["--add-label", label])
    run_gh(args, dry_run=dry_run)


def reconcile_managed_labels(repo: str, issue: dict, egr: EgrFinding, *, dry_run: bool) -> None:
    desired = set(egr.labels)
    current = {
        label["name"] if isinstance(label, dict) else str(label)
        for label in issue.get("labels", [])
    }
    stale = sorted(
        label
        for label in current
        if label not in desired
        and (label in {"egr"} or label.startswith(MANAGED_LABEL_PREFIXES))
    )
    for label in stale:
        run_gh(
            ["issue", "edit", str(issue["number"]), "--repo", repo, "--remove-label", label],
            dry_run=dry_run,
        )


def reconcile_state(repo: str, issue: dict, egr: EgrFinding, *, dry_run: bool) -> None:
    number = str(issue["number"])
    should_close_reason = CLOSE_REASON_BY_STATUS.get(egr.status)
    if should_close_reason and issue["state"] == "OPEN":
        run_gh(
            ["issue", "close", number, "--repo", repo, "--reason", should_close_reason],
            dry_run=dry_run,
        )
    elif not should_close_reason and issue["state"] == "CLOSED":
        run_gh(["issue", "reopen", number, "--repo", repo], dry_run=dry_run)


def sync(repo: str, register_path: Path, *, dry_run: bool) -> int:
    findings = parse_register(register_path)
    if not findings:
        raise RuntimeError(f"no EGR rows found in {register_path}")

    required_labels = {label for egr in findings for label in egr.labels}
    ensure_labels(repo, required_labels, dry_run=dry_run)

    created = updated = 0
    for egr in findings:
        if dry_run:
            print(f"# sync {egr.id} ({egr.status})")
            create_issue(repo, egr, register_path, dry_run=True)
            continue

        issue = find_issue(repo, egr.id)
        if issue is None:
            url = create_issue(repo, egr, register_path, dry_run=False)
            created += 1
            issue = issue_from_url(url) or find_issue(repo, egr.id)
            print(f"created {egr.id}: {url}")
        else:
            update_issue(repo, int(issue["number"]), egr, register_path, dry_run=False)
            updated += 1
            print(f"updated {egr.id}: {issue['url']}")

        if issue is not None:
            reconcile_managed_labels(repo, issue, egr, dry_run=False)
            reconcile_state(repo, issue, egr, dry_run=False)

    print(f"synced {len(findings)} EGR issues ({created} created, {updated} updated)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"GitHub repo, default: {DEFAULT_REPO}")
    parser.add_argument(
        "--register",
        type=Path,
        default=DEFAULT_REGISTER,
        help=f"EGR register path, default: {DEFAULT_REGISTER}",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print gh commands without changing GitHub")
    args = parser.parse_args(argv)
    return sync(args.repo, args.register, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
