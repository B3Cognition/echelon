"""Application service for installed Prosaic skill commands."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from harness.llm_provider import AICodingCliProvider
from harness.llm_tool_policy import build_opencode_skill_command
from harness.prosaic_prompt_loader import (
    ProsaicPromptLoadError,
    ProsaicPromptLoader,
    RenderedProsaicCommand,
)
from harness.provider_capability import ProviderCapability
from harness.skill_loader import build_skill_prompt


SKILL_MAP = {
    "bugfix": "echelon.bugfix",
    "review": "echelon.review",
    "change": "echelon.change",
    "verify-spec": "echelon.verify-spec",
    "reopen": "echelon.reopen",
}


def _load_prosaic_command(
    skill_base: str,
    arguments: str,
    project_root: Path,
) -> RenderedProsaicCommand | None:
    try:
        artifact = ProsaicPromptLoader(project_root).load_command(skill_base)
    except ProsaicPromptLoadError as exc:
        print(f"echelon: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if artifact is None:
        return None
    return ProsaicPromptLoader.render_command(artifact, arguments)


def _skill_required_capability(command: str) -> ProviderCapability:
    if command == "review":
        return ProviderCapability.BUILD
    return ProviderCapability.ARTIFACT


def _skill_not_found_msg(skill_base: str, project_root: Path) -> str:
    return (
        f"echelon: command prose '{skill_base}' not found.\n"
        "Expected at:\n"
        f"  {project_root / '.echelon' / 'prosaic' / 'commands' / f'{skill_base}.md'}\n"
        "Run: echelon workspace migrate-to-prosaic"
    )


def dispatch_skill(
    command: str,
    arguments: Sequence[str],
    *,
    project_root: Path,
) -> NoReturn:
    """Run one installed skill command and exit with its provider status."""
    from echelon import cli as shared

    rendered_arguments = " ".join(arguments)
    if not rendered_arguments:
        print(f"echelon {command}: missing arguments\n", file=sys.stderr)
        print(shared.USAGE)
        raise SystemExit(1)

    skill_base = SKILL_MAP[command]
    shared._require_provider_capability(
        f"echelon {command}",
        _skill_required_capability(command),
        project_dir=project_root,
    )
    try:
        config = shared._load_cli_config(project_root)
    except Exception as exc:
        print(f"echelon {command}: invalid LLM tool policy: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    cli = config.llm.cli

    prosaic_command = _load_prosaic_command(
        skill_base,
        rendered_arguments,
        project_root,
    )
    prompt = prosaic_command.prompt if prosaic_command is not None else None
    skill_path: Path | None = None
    if prompt is None:
        skill_path = shared._find_skill(skill_base, project_root, cli)
        if skill_path is None:
            print(_skill_not_found_msg(skill_base, project_root), file=sys.stderr)
            raise SystemExit(1)

    if cli == "opencode" and prompt is None:
        bin_ = shutil.which(cli) or cli
        cmd = build_opencode_skill_command(
            bin_,
            skill_base,
            rendered_arguments,
            config.llm.tool_policy,
        )
        result = subprocess.run(cmd, cwd=str(project_root))
        raise SystemExit(result.returncode)

    if prompt is None:
        assert skill_path is not None
        prompt = build_skill_prompt(skill_path, rendered_arguments)
    metadata = (
        {"prompt_metadata": prosaic_command.frontmatter}
        if prosaic_command is not None
        else None
    )
    result = AICodingCliProvider(config).run_prompt_result(
        str(project_root),
        prompt,
        request_metadata=metadata,
    )
    raise SystemExit(result.exit_code)
