"""Narrow persistence helpers shared by deterministic Lexicon gates."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Mapping


def write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    """Write one JSON gate report durably without exposing a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
