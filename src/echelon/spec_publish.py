"""Publish committed spec snapshots from canonical local Phase A branches."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from echelon.git_helpers import GitHelperError, run_git


CANONICAL_SPEC_BRANCH_RE = re.compile(
    r"^(?P<number>\d{3,})-(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)$"
)


class SpecPublishError(RuntimeError):
    """Raised when spec catalog publication cannot proceed safely."""


@dataclass(frozen=True)
class SpecPublicationSource:
    spec_id: str
    spec_number: str
    branch: str
    commit: str
    source_path: str


def discover_publication_sources(
    project_root: Path,
    default_branch: str,
) -> tuple[SpecPublicationSource, ...]:
    """Return canonical local branches with a matching committed spec."""

    root = Path(project_root).resolve()
    try:
        output = run_git(
            root,
            "for-each-ref",
            "--format=%(refname:short)%00%(objectname)",
            "refs/heads",
        ).stdout
    except GitHelperError as exc:
        raise SpecPublishError(str(exc)) from exc

    sources: list[SpecPublicationSource] = []
    for line in output.splitlines():
        branch, separator, commit = line.partition("\0")
        if not separator or branch == default_branch:
            continue
        match = CANONICAL_SPEC_BRANCH_RE.fullmatch(branch)
        if match is None:
            continue
        source_path = f"specs/{branch}"
        exists = run_git(
            root,
            "cat-file",
            "-e",
            f"{commit}:{source_path}/spec.md",
            check=False,
        )
        if exists.returncode != 0:
            continue
        sources.append(
            SpecPublicationSource(
                spec_id=branch,
                spec_number=match.group("number"),
                branch=branch,
                commit=commit,
                source_path=source_path,
            )
        )
    return tuple(sorted(sources, key=lambda source: source.branch))


def resolve_publication_sources(
    project_root: Path,
    *,
    identity: str | None,
    publish_all: bool,
    default_branch: str,
) -> tuple[SpecPublicationSource, ...]:
    """Resolve one command form against canonical local branch sources."""

    cleaned_identity = str(identity or "").strip()
    if bool(cleaned_identity) == publish_all:
        raise SpecPublishError("choose exactly one spec identity or --all")

    sources = discover_publication_sources(project_root, default_branch)
    by_number: dict[int, list[SpecPublicationSource]] = {}
    for source in sources:
        by_number.setdefault(int(source.spec_number), []).append(source)

    duplicate_numbers = {
        number: matches for number, matches in by_number.items() if len(matches) > 1
    }
    if publish_all:
        if duplicate_numbers:
            number = sorted(duplicate_numbers)[0]
            candidates = ", ".join(
                source.branch for source in duplicate_numbers[number]
            )
            raise SpecPublishError(
                f"ambiguous spec identity {number:03d}: {candidates}"
            )
        if not sources:
            raise SpecPublishError("no canonical local spec branches are publishable")
        return sources

    if cleaned_identity.isdigit():
        matches = by_number.get(int(cleaned_identity), [])
    else:
        matches = [source for source in sources if source.branch == cleaned_identity]
    if not matches:
        raise SpecPublishError(
            f"no canonical local spec branch matches {cleaned_identity!r}"
        )
    if len(matches) > 1:
        candidates = ", ".join(source.branch for source in matches)
        raise SpecPublishError(
            f"ambiguous spec identity {cleaned_identity!r}: {candidates}"
        )
    return tuple(matches)
