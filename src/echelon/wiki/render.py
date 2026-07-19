"""Standard-Markdown renderer for Echelon's generated human wiki."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from echelon.wiki.model import (
    WikiArtifact,
    WikiDomain,
    WikiModel,
    WikiSource,
    WikiSpec,
    WikiWarning,
)


REQUIRED_PAGES = (
    "Home.md",
    "Reverse Engineering/Index.md",
    "Specs/Index.md",
    "Views/Active Work.md",
    "Views/Decisions.md",
    "Views/Requirements.md",
    "Views/Risks and Issues.md",
    "Views/Verification.md",
    "Warnings.md",
)

_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


class WikiRenderError(RuntimeError):
    """Raised when required wiki navigation cannot be rendered safely."""


@dataclass(frozen=True)
class RenderResult:
    output_pages: tuple[str, ...]
    required_pages: tuple[str, ...]
    warnings: tuple[WikiWarning, ...]


def _frontmatter(model: WikiModel, page_type: str, stable_id: str) -> str:
    return (
        "---\n"
        "echelon_wiki: generated\n"
        f"page_type: {page_type}\n"
        f"stable_id: {stable_id}\n"
        f"generated_at: {model.generated_at}\n"
        "---\n\n"
    )


def _write_page(output_dir: Path, relative: str, content: str) -> None:
    path = output_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def _link(label: str, destination: str) -> str:
    encoded = destination.replace(" ", "%20")
    return f"[{label}]({encoded})"


def _artifact_for(model: WikiModel, stable_id: str) -> WikiArtifact:
    for artifact in model.artifacts:
        if artifact.stable_id == stable_id:
            return artifact
    raise WikiRenderError(f"model references unknown artifact: {stable_id}")


def _home(model: WikiModel) -> str:
    lines = [
        _frontmatter(model, "workspace-home", "workspace:home").rstrip(),
        "",
        f"# {model.workspace_name} — Echelon Wiki",
        "",
        "> Generated navigation. Edit canonical artifacts under `specs/` and `re/`.",
        "",
        "## Start Here",
        "",
        f"- {_link('All specs', 'Specs/Index.md')}",
        f"- {_link('Reverse engineering', 'Reverse Engineering/Index.md')}",
        f"- {_link('Active work', 'Views/Active Work.md')}",
        f"- {_link('Warnings', 'Warnings.md')}",
        "",
        "## Workspace Sources",
        "",
    ]
    if model.sources:
        for source in model.sources:
            published = f"; published `{source.published_path}`" if source.published_path else ""
            lines.append(f"- `{source.source_id}` — `{source.path}`{published}")
    else:
        lines.append("- Planning-only workspace; no implementation sources declared.")

    lines.extend(["", "## Specs", ""])
    if model.specs:
        for spec in model.specs:
            lines.append(
                f"- {_link(spec.title, f'Specs/{spec.spec_id}/Overview.md')} — "
                f"`{spec.lifecycle_status}`"
            )
    else:
        lines.append("- No published specs.")

    lines.extend(["", "## Recent Changes", ""])
    if model.recent_changes:
        for change in model.recent_changes:
            paths = ", ".join(f"`{path}`" for path in change.paths) or "no paths"
            lines.append(
                f"- `{change.commit[:12]}` {change.subject} ({change.committed_at}) — {paths}"
            )
    else:
        lines.append("- No canonical artifact changes found in Git history.")
    return "\n".join(lines)


def _spec_index(model: WikiModel) -> str:
    lines = [
        _frontmatter(model, "spec-index", "spec:index").rstrip(),
        "",
        "# Specs",
        "",
        "| Spec | Status | Targets | Requirements | Tasks |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for spec in model.specs:
        targets = ", ".join(f"`{target}`" for target in spec.targets) or "—"
        lines.append(
            f"| {_link(spec.title, f'{spec.spec_id}/Overview.md')} | "
            f"`{spec.lifecycle_status}` | {targets} | {len(spec.requirement_ids)} | "
            f"{len(spec.task_ids)} |"
        )
    if not model.specs:
        lines.append("| _No published specs_ | — | — | 0 | 0 |")
    return "\n".join(lines)


def _spec_overview(model: WikiModel, spec: WikiSpec) -> str:
    targets = ", ".join(f"`{target}`" for target in spec.targets) or "none"
    lines = [
        _frontmatter(model, "spec-overview", spec.stable_id).rstrip(),
        "",
        f"# {spec.title}",
        "",
        f"Lifecycle status: `{spec.lifecycle_status}`",
        "",
        f"Implementation targets: {targets}",
    ]
    if spec.publication_branch and spec.publication_commit:
        lines.extend(
            [
                "",
                "## Publication Provenance",
                "",
                f"Published from branch: `{spec.publication_branch}`",
                "",
                f"Source commit: `{spec.publication_commit[:12]}`",
            ]
        )
    lines.extend(["", "## Reading Path", ""])
    by_name = {
        Path(_artifact_for(model, artifact_id).source_path).name: _artifact_for(model, artifact_id)
        for artifact_id in spec.artifact_ids
    }
    for name, label in (
        ("spec.md", "Specification"),
        ("plan.md", "Implementation plan"),
        ("tasks.md", "Task ledger"),
        ("verification-summary.md", "Verification summary"),
    ):
        artifact = by_name.get(name)
        if artifact:
            destination = f"../../{artifact.projection_path}"
            lines.append(f"- {_link(label, destination)}")
        else:
            lines.append(f"- {label}: missing")
    lines.extend(
        [
            "",
            "## Inventory",
            "",
            f"- Requirements: {len(spec.requirement_ids)}",
            f"- Tasks: {len(spec.task_ids)}",
            f"- Artifacts: {len(spec.artifact_ids)}",
            f"- {_link('Full artifact inventory', 'Artifacts.md')}",
        ]
    )
    return "\n".join(lines)


def _spec_artifacts(model: WikiModel, spec: WikiSpec) -> str:
    lines = [
        _frontmatter(model, "spec-artifacts", f"{spec.stable_id}:artifacts").rstrip(),
        "",
        f"# {spec.title} Artifacts",
        "",
        "| Artifact | Kind | Projection |",
        "| --- | --- | --- |",
    ]
    for stable_id in spec.artifact_ids:
        artifact = _artifact_for(model, stable_id)
        if artifact.copy_mode == "catalog":
            projection = "catalogued only"
        else:
            projection = _link("open", f"../../{artifact.projection_path}")
        lines.append(
            f"| `{artifact.source_path}` | {artifact.kind} | {projection} |"
        )
    return "\n".join(lines)


def _reverse_engineering(model: WikiModel) -> str:
    lines = [
        _frontmatter(model, "re-index", "re:index").rstrip(),
        "",
        "# Reverse Engineering",
        "",
        "## Sources",
        "",
    ]
    if model.sources:
        for source in model.sources:
            lines.append(
                f"- {_link(source.source_id, _source_page_path(source))} — `{source.path}`"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Domains", ""])
    if model.domains:
        for domain in model.domains:
            destination = _domain_page_path(domain)
            lines.append(f"- {_link(domain.title, destination)} — `{domain.source_id}`")
    else:
        lines.append("- No published RE domains.")
    return "\n".join(lines)


def _artifact_projection(source_path: str) -> str:
    return f"Artifacts/{source_path}"


def _page_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "item"
    if safe == value:
        return safe
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{safe}--{digest}"


def _source_page_path(source: WikiSource) -> str:
    return f"Sources/{_page_component(source.source_id)}.md"


def _domain_page_path(domain: WikiDomain) -> str:
    source = _page_component(domain.source_id)
    domain_id = _page_component(domain.domain_id)
    return f"Domains/{source}--{domain_id}.md"


def _re_source_page(model: WikiModel, source: WikiSource) -> str:
    lines = [
        _frontmatter(model, "re-source", source.stable_id).rstrip(),
        "",
        f"# {source.source_id}",
        "",
        f"Configured source: `{source.path}`",
        "",
        (
            f"Published artifacts: `{source.published_path}`"
            if source.published_path
            else "Published artifacts: unavailable"
        ),
        "",
        "## Domains",
        "",
    ]
    domains = [domain for domain in model.domains if domain.source_id == source.source_id]
    if domains:
        for domain in domains:
            lines.append(f"- {_link(domain.title, f'../{_domain_page_path(domain)}')}")
    else:
        lines.append("- None")
    return "\n".join(lines)


def _re_domain_page(model: WikiModel, domain: WikiDomain) -> str:
    return "\n".join(
        [
            _frontmatter(model, "re-domain", domain.stable_id).rstrip(),
            "",
            f"# {domain.title}",
            "",
            f"Source: `{domain.source_id}`",
            "",
            f"Domain ID: `{domain.domain_id}`",
            "",
            f"Canonical artifact: `{domain.source_path}`",
            "",
            f"- {_link('Open canonical projection', f'../../{_artifact_projection(domain.source_path)}')}",
        ]
    )


def _view(model: WikiModel, kind: str, title: str, predicate) -> str:
    lines = [
        _frontmatter(model, "aggregate-view", f"view:{kind}").rstrip(),
        "",
        f"# {title}",
        "",
    ]
    matching = [artifact for artifact in model.artifacts if predicate(artifact)]
    if matching:
        for artifact in matching:
            lines.append(
                f"- {_link(artifact.title, f'../{artifact.projection_path}')} — "
                f"`{artifact.source_path}`"
            )
    else:
        lines.append("- None")
    return "\n".join(lines)


def _requirements(model: WikiModel) -> str:
    lines = [
        _frontmatter(model, "aggregate-view", "view:requirements").rstrip(),
        "",
        "# Requirements",
        "",
        "| Requirement | Spec |",
        "| --- | --- |",
    ]
    for spec in model.specs:
        for requirement_id in spec.requirement_ids:
            local_id = requirement_id.split(":", 1)[1]
            lines.append(
                f"| `{local_id}` | {_link(spec.title, f'../Specs/{spec.spec_id}/Overview.md')} |"
            )
    if len(lines) == 6:
        lines.append("| _None_ | — |")
    return "\n".join(lines)


def _active_work(model: WikiModel) -> str:
    lines = [
        _frontmatter(model, "aggregate-view", "view:active-work").rstrip(),
        "",
        "# Active Work",
        "",
    ]
    active = [spec for spec in model.specs if spec.lifecycle_status != "landed"]
    if active:
        for spec in active:
            lines.append(
                f"- {_link(spec.title, f'../Specs/{spec.spec_id}/Overview.md')} — "
                f"`{spec.lifecycle_status}`"
            )
    else:
        lines.append("- None")
    return "\n".join(lines)


def _project_markdown(text: str, artifact: WikiArtifact) -> str:
    banner = (
        f"> Generated projection. Canonical source: `{artifact.source_path}`. "
        f"SHA-256: `{artifact.sha256}`.\n\n"
    )
    if text.startswith("---\n"):
        closing = text.find("\n---\n", 4)
        if closing >= 0:
            insertion = closing + len("\n---\n")
            return text[:insertion] + banner + text[insertion:]
    return banner + text


def _warning_page(model: WikiModel, warnings: tuple[WikiWarning, ...]) -> str:
    lines = [
        _frontmatter(model, "warnings", "wiki:warnings").rstrip(),
        "",
        "# Warnings",
        "",
    ]
    if warnings:
        for warning in warnings:
            source = f" (`{warning.source_path}`)" if warning.source_path else ""
            lines.append(f"- **{warning.code}**{source}: {warning.message}")
    else:
        lines.append("- None")
    return "\n".join(lines)


def _without_fenced_code(text: str) -> str:
    lines: list[str] = []
    in_fence = False
    marker = ""
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            current = stripped[:3]
            if not in_fence:
                in_fence = True
                marker = current
            elif current == marker:
                in_fence = False
                marker = ""
            lines.append("")
        elif in_fence:
            lines.append("")
        else:
            lines.append(line)
    return "\n".join(lines)


def validate_rendered_links(output_dir: Path) -> tuple[WikiWarning, ...]:
    """Return warnings for broken local Markdown links outside fenced code."""
    root = output_dir.resolve()
    warnings: list[WikiWarning] = []
    for page in sorted(output_dir.rglob("*.md")):
        text = page.read_text(encoding="utf-8")
        if "](" not in text:
            continue
        text = _without_fenced_code(text)
        for raw_target in _MARKDOWN_LINK_RE.findall(text):
            target = raw_target.strip().strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or target.startswith("#"):
                continue
            path_part = unquote(parsed.path)
            if not path_part:
                continue
            resolved = (page.parent / path_part).resolve()
            if not resolved.is_relative_to(root) or not resolved.exists():
                warnings.append(
                    WikiWarning(
                        "broken-link",
                        f"Local link target does not exist: {target}",
                        page.relative_to(root).as_posix(),
                    )
                )
    return tuple(warnings)


def render_wiki(model: WikiModel, project_root: Path, output_dir: Path) -> RenderResult:
    """Render sorted standard-Markdown navigation and artifact projections."""
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_page(output_dir, "Home.md", _home(model))
    _write_page(output_dir, "Specs/Index.md", _spec_index(model))
    _write_page(output_dir, "Reverse Engineering/Index.md", _reverse_engineering(model))
    for source in model.sources:
        _write_page(
            output_dir,
            f"Reverse Engineering/{_source_page_path(source)}",
            _re_source_page(model, source),
        )
    for domain in model.domains:
        _write_page(
            output_dir,
            f"Reverse Engineering/{_domain_page_path(domain)}",
            _re_domain_page(model, domain),
        )
    _write_page(output_dir, "Views/Active Work.md", _active_work(model))
    _write_page(output_dir, "Views/Requirements.md", _requirements(model))
    _write_page(
        output_dir,
        "Views/Decisions.md",
        _view(model, "decisions", "Decisions", lambda artifact: artifact.kind == "decision"),
    )
    _write_page(
        output_dir,
        "Views/Risks and Issues.md",
        _view(model, "risks", "Risks and Issues", lambda artifact: artifact.kind == "risk"),
    )
    _write_page(
        output_dir,
        "Views/Verification.md",
        _view(
            model,
            "verification",
            "Verification",
            lambda artifact: artifact.kind == "verification",
        ),
    )
    for spec in model.specs:
        _write_page(output_dir, f"Specs/{spec.spec_id}/Overview.md", _spec_overview(model, spec))
        _write_page(output_dir, f"Specs/{spec.spec_id}/Artifacts.md", _spec_artifacts(model, spec))

    warnings = list(model.warnings)
    for artifact in model.artifacts:
        source = project_root / artifact.source_path
        destination = output_dir / artifact.projection_path
        if artifact.copy_mode == "catalog":
            warnings.append(
                WikiWarning(
                    "attachment-catalogued",
                    "Attachment is unsupported or exceeds the 10 MiB copy limit.",
                    artifact.source_path,
                )
            )
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() == ".md":
            projected = _project_markdown(source.read_text(encoding="utf-8"), artifact)
            destination.write_text(projected, encoding="utf-8")
        else:
            shutil.copy2(source, destination)

    obsidian = output_dir / ".obsidian/app.json"
    obsidian.parent.mkdir(parents=True, exist_ok=True)
    obsidian.write_text(
        json.dumps(
            {"newLinkFormat": "relative", "useMarkdownLinks": True},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_page(output_dir, "Warnings.md", _warning_page(model, tuple(warnings)))
    link_warnings = validate_rendered_links(output_dir)
    warnings.extend(link_warnings)
    _write_page(output_dir, "Warnings.md", _warning_page(model, tuple(warnings)))

    for required in REQUIRED_PAGES:
        if not (output_dir / required).is_file():
            raise WikiRenderError(f"required wiki page was not rendered: {required}")
    output_pages = tuple(
        path.relative_to(output_dir).as_posix()
        for path in sorted(output_dir.rglob("*"))
        if path.is_file()
    )
    return RenderResult(output_pages, REQUIRED_PAGES, tuple(warnings))
