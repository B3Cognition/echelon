"""Echelon run-directory discovery around the shared transcript writer."""
from pathlib import Path
from typing import Mapping
from prosaic_runtime.openai_compatible_transcript import (
    ProviderTranscript, _configured_dir, open_provider_transcript as _open_transcript,
)


def open_provider_transcript(cwd: Path, features: Mapping[str, object],
                             request_metadata: Mapping[str, object]) -> ProviderTranscript:
    metadata = dict(request_metadata)
    if _configured_dir(features, metadata) is None:
        detected = _detect_run_dir(cwd)
        if detected is not None:
            metadata["provider_transcript_dir"] = str(detected)
    return _open_transcript(cwd, features, metadata)


def _detect_run_dir(cwd: Path) -> Path | None:
    resolved = cwd.resolve(strict=False)
    if (
        (resolved / "state.json").exists()
        or (resolved / "re-execution-plan.json").exists()
        or (resolved / "re-source-index.json").exists()
    ):
        return resolved
    if "runs" in resolved.parts:
        return resolved
    return None
