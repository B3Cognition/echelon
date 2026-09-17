"""Resolve the delivery build command before model execution.

This is command setup, not a gate executor. Ralph still owns the surrounding
delivery loop; review sequencing is migrated separately.
"""

from pathlib import Path

from harness.prompt_companions import PromptCompanionError
from harness.prompt_framing import DELIVERY_PREAMBLE
from harness.prompt_markdown import FrontmatterParseError
from harness.prosaic_prompt_loader import ProsaicPromptLoader, ProsaicPromptLoadError


class DeliveryPromptError(RuntimeError):
    """A delivery build cannot safely dispatch its configured command."""


def resolve_delivery_build_prompt(
    build_command: str, arguments: str, project_dir: Path,
) -> str:
    """Load one canonical build command, with no bare-prompt fallback.

    Strategy shell commands are a sandbox execution feature. The LLM path
    supports the canonical build command and passes task data in arguments.
    """
    if build_command.split() != ["echelon", "build"]:
        raise DeliveryPromptError(
            f"Unsupported LLM delivery command {build_command!r}; "
            "configure 'echelon build' and put task instructions in strategy context."
        )
    command_path = project_dir / ".echelon/prosaic/commands/echelon.build.md"
    if not command_path.is_file():
        raise DeliveryPromptError(
            f"Missing canonical delivery command echelon.build: {command_path}. "
            "Run 'echelon workspace migrate-to-prosaic' to refresh the workspace bundle."
        )
    try:
        artifact = ProsaicPromptLoader(project_dir).load_command("echelon.build")
    except (ProsaicPromptLoadError, PromptCompanionError, FrontmatterParseError, OSError, UnicodeError) as exc:
        raise DeliveryPromptError(f"Cannot load delivery command echelon.build: {exc}") from exc
    if artifact is None or artifact.frontmatter.get("name") != "echelon.build":
        raise DeliveryPromptError("Canonical delivery command must declare name: echelon.build")
    if not artifact.body.strip():
        raise DeliveryPromptError("Canonical delivery command echelon.build has an empty body")
    return ProsaicPromptLoader.render_command(
        artifact, arguments, preamble=DELIVERY_PREAMBLE,
    ).prompt
