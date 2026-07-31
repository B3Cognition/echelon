"""Load neutral Prosaic command artifacts for Echelon provider dispatch."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any

from harness.prompt_framing import COMMANDER_PREAMBLE


class ProsaicPromptLoadError(RuntimeError):
    """Raised when an installed Prosaic bundle cannot provide a command."""


@dataclass(frozen=True)
class ProsaicCommandArtifact:
    """Provider-neutral command prompt returned by ``prosaic inspect``."""

    frontmatter: dict[str, Any]
    body: str


class ProsaicPromptLoader:
    """Load commands from an installer-owned project Prosaic bundle."""

    def __init__(self, project_dir: Path, *, executable: str = "prosaic") -> None:
        self._project_dir = project_dir
        self._source_dir = project_dir / ".echelon" / "prosaic"
        self._executable = executable

    def load_command(self, command_id: str) -> ProsaicCommandArtifact | None:
        """Return a command artifact, or ``None`` when the bundle is not installed."""
        if not (self._source_dir / "commands").is_dir():
            return None

        artifact_id = f"commands/{command_id}.md"
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

        return _parse_command_artifact(artifact_id, result.stdout)

    @staticmethod
    def render_command(body: str, arguments: str) -> str:
        """Render neutral arguments into the provider prompt format."""
        if "{{args}}" in body:
            content = body.replace("{{args}}", arguments)
        else:
            content = f"{body}\n\n## Arguments\n{arguments}"
        return COMMANDER_PREAMBLE + content


def _parse_command_artifact(
    artifact_id: str,
    raw: str,
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
    if artifact.get("type") != "command":
        raise ProsaicPromptLoadError(
            f"Prosaic returned {artifact.get('type')!r} for {artifact_id}, expected command"
        )
    frontmatter = artifact.get("frontmatter")
    body = artifact.get("body")
    if not isinstance(frontmatter, dict) or not isinstance(body, str):
        raise ProsaicPromptLoadError(
            f"Prosaic returned an incomplete command artifact for {artifact_id}"
        )
    return ProsaicCommandArtifact(frontmatter=frontmatter, body=body)
