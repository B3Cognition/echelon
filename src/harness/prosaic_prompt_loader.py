"""Load neutral Prosaic command artifacts for Echelon provider dispatch."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any

from harness.prompt_companions import append_prompt_companions
from harness.prompt_framing import COMMANDER_PREAMBLE


class ProsaicPromptLoadError(RuntimeError):
    """Raised when an installed Prosaic bundle cannot provide a command."""


@dataclass(frozen=True)
class ProsaicCommandArtifact:
    """Provider-neutral command prompt returned by ``prosaic inspect``."""

    frontmatter: dict[str, Any]
    body: str


@dataclass(frozen=True)
class RenderedProsaicCommand:
    """Rendered command prompt together with its provider metadata."""

    prompt: str
    frontmatter: dict[str, Any]


class ProsaicPromptLoader:
    """Load commands from an installer-owned project Prosaic bundle."""

    def __init__(self, project_dir: Path, *, executable: str = "prosaic") -> None:
        self._project_dir = project_dir
        self._source_dir = project_dir / ".echelon" / "prosaic"
        self._executable = executable

    def load_command(self, command_id: str) -> ProsaicCommandArtifact | None:
        """Return a command artifact, or ``None`` when the bundle is not installed."""
        return self._load_artifact("commands", command_id, "command")

    def load_subagent(self, agent_id: str) -> ProsaicCommandArtifact | None:
        """Return a subagent artifact, or ``None`` when the bundle is not installed."""
        return self._load_artifact("subagents", agent_id, "subagent")

    def _load_artifact(
        self,
        directory: str,
        artifact_name: str,
        expected_type: str,
    ) -> ProsaicCommandArtifact | None:
        if not (self._source_dir / directory).is_dir():
            return None

        artifact_id = f"{directory}/{artifact_name}.md"
        try:
            result = subprocess.run(
                [
                    self._executable,
                    "inspect",
                    artifact_id,
                    "--source",
                    str(self._source_dir),
                ],
                cwd=str(self._project_dir),
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise ProsaicPromptLoadError(
                f"cannot execute Prosaic for {artifact_id}: {exc}"
            ) from exc

        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise ProsaicPromptLoadError(
                f"Prosaic could not inspect {artifact_id}: {detail}"
            )

        artifact = _parse_command_artifact(
            artifact_id,
            result.stdout,
            expected_type=expected_type,
        )
        return ProsaicCommandArtifact(
            frontmatter=artifact.frontmatter,
            body=append_prompt_companions(
                artifact.body,
                (self._source_dir, self._source_dir.parent / "runtime"),
            ),
        )

    @staticmethod
    def render_command(
        artifact: ProsaicCommandArtifact, arguments: str
    ) -> RenderedProsaicCommand:
        """Render neutral arguments into the provider prompt format."""
        body = artifact.body
        if "{{args}}" in body:
            content = body.replace("{{args}}", arguments)
        else:
            content = f"{body}\n\n## Arguments\n{arguments}"
        return RenderedProsaicCommand(
            prompt=COMMANDER_PREAMBLE + content,
            frontmatter=artifact.frontmatter,
        )


def _parse_command_artifact(
    artifact_id: str,
    raw: str,
    *,
    expected_type: str = "command",
) -> ProsaicCommandArtifact:
    try:
        artifact = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProsaicPromptLoadError(
            f"Prosaic returned invalid JSON for {artifact_id}: {exc.msg}"
        ) from exc

    if not isinstance(artifact, dict):
        raise ProsaicPromptLoadError(
            f"Prosaic returned an invalid artifact for {artifact_id}: expected object"
        )
    if artifact.get("type") != expected_type:
        raise ProsaicPromptLoadError(
            f"Prosaic returned {artifact.get('type')!r} for {artifact_id}, "
            f"expected {expected_type}"
        )
    frontmatter = artifact.get("frontmatter")
    body = artifact.get("body")
    if not isinstance(frontmatter, dict) or not isinstance(body, str):
        raise ProsaicPromptLoadError(
            f"Prosaic returned an incomplete command artifact for {artifact_id}"
        )
    return ProsaicCommandArtifact(frontmatter=frontmatter, body=body)
