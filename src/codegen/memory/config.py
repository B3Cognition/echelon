"""
config.py — MemoryConfig dataclass and YAML loader.
Spec 024 T-005: Define and load memory-config.yml schema.

FRs: FR-CFG-001 through FR-CFG-009, FR-EPMEM-003, FR-SMEM-003
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_DIR = Path.home() / ".echelon" / "memory"
DEFAULT_EPMEM_DB_PATH = DEFAULT_MEMORY_DIR / "epmem.db"
DEFAULT_SMEM_DB_PATH = DEFAULT_MEMORY_DIR / "smem.db"
DEFAULT_MAX_EPMEM_EPISODES = 10_000
DEFAULT_SMEM_ACCUMULATION_MIN_PSI = 0.70
DEFAULT_EPMEM_IMPASSE_MIN_MATCH_SCORE = 0.80
DEFAULT_EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_MODEL_VERSION = "1.0"


@dataclass
class MemoryConfig:
    """
    Persistent memory configuration for codegen.

    All paths are resolved to absolute Paths on construction.
    Missing optional keys revert to documented defaults without raising.
    """
    epmem_db_path: Path = field(default_factory=lambda: DEFAULT_EPMEM_DB_PATH)
    smem_db_path: Path = field(default_factory=lambda: DEFAULT_SMEM_DB_PATH)
    mempalace_palace_path: Optional[Path] = None
    embedding_model_name: str = DEFAULT_EMBEDDING_MODEL_NAME
    embedding_model_version: str = DEFAULT_EMBEDDING_MODEL_VERSION
    max_epmem_episodes: int = DEFAULT_MAX_EPMEM_EPISODES
    smem_accumulation_min_psi: float = DEFAULT_SMEM_ACCUMULATION_MIN_PSI
    epmem_impasse_min_match_score: float = DEFAULT_EPMEM_IMPASSE_MIN_MATCH_SCORE

    def __post_init__(self) -> None:
        self.epmem_db_path = Path(self.epmem_db_path).expanduser().resolve()
        self.smem_db_path = Path(self.smem_db_path).expanduser().resolve()
        if self.mempalace_palace_path is not None:
            self.mempalace_palace_path = Path(self.mempalace_palace_path).expanduser().resolve()

    @property
    def embedding_model_tag(self) -> str:
        return f"{self.embedding_model_name}@{self.embedding_model_version}"

    @property
    def epmem_pruning_target(self) -> int:
        """80% of max_epmem_episodes — pruning leaves at most this many episodes."""
        return int(self.max_epmem_episodes * 0.80)

    @property
    def epmem_warning_threshold(self) -> int:
        """80% of max_epmem_episodes — emit WARNING when episode count reaches this."""
        return int(self.max_epmem_episodes * 0.80)

    def validate(self) -> None:
        """
        Validate config values. Raises ValueError on invalid config.
        Called by MemoryConfigLoader.load() after parsing.
        """
        if self.max_epmem_episodes < 100:
            raise ValueError(
                f"max_epmem_episodes must be >= 100, got {self.max_epmem_episodes}"
            )
        if not 0.0 < self.smem_accumulation_min_psi <= 1.0:
            raise ValueError(
                f"smem_accumulation_min_psi must be in (0.0, 1.0], "
                f"got {self.smem_accumulation_min_psi}"
            )
        if not 0.0 < self.epmem_impasse_min_match_score <= 1.0:
            raise ValueError(
                f"epmem_impasse_min_match_score must be in (0.0, 1.0], "
                f"got {self.epmem_impasse_min_match_score}"
            )


class MemoryConfigError(Exception):
    """Raised when memory-config.yml cannot be parsed or fails validation."""


class MemoryConfigLoader:
    """
    Loads MemoryConfig from a YAML file.

    - Returns defaults if file is absent (FR-CFG-001).
    - Raises MemoryConfigError on invalid YAML or failed validation.
    - Creates parent directories for epmem_db_path and smem_db_path (FR-CFG-009).
    """

    @staticmethod
    def load(path: Optional[Path] = None) -> MemoryConfig:
        """
        Load MemoryConfig from path.

        Args:
            path: Path to memory-config.yml. If None or file absent, defaults are used.

        Returns:
            MemoryConfig with all fields resolved.

        Raises:
            MemoryConfigError: If the file exists but cannot be parsed or validation fails.
        """
        if path is None or not Path(path).exists():
            if path is not None:
                logger.info(
                    "[MemoryConfig] %s not found — using defaults", path
                )
            cfg = MemoryConfig()
            MemoryConfigLoader._ensure_directories(cfg)  # SEC-025 FIX-5: path 1 of 3
            return cfg

        try:
            import yaml  # type: ignore[import-untyped]
            with open(path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
        except Exception as exc:
            raise MemoryConfigError(
                f"Failed to parse memory-config.yml at {path}: {exc}"
            ) from exc

        if raw is None:
            cfg = MemoryConfig()
            MemoryConfigLoader._ensure_directories(cfg)  # SEC-025 FIX-5: path 2 of 3
            return cfg

        if not isinstance(raw, dict):
            raise MemoryConfigError(
                f"memory-config.yml must be a YAML mapping, got {type(raw).__name__}"
            )

        try:
            cfg = MemoryConfig(
                epmem_db_path=Path(raw["epmem_db_path"])
                    if "epmem_db_path" in raw else DEFAULT_EPMEM_DB_PATH,
                smem_db_path=Path(raw["smem_db_path"])
                    if "smem_db_path" in raw else DEFAULT_SMEM_DB_PATH,
                mempalace_palace_path=Path(raw["mempalace_palace_path"])
                    if "mempalace_palace_path" in raw else None,
                embedding_model_name=raw.get("embedding_model_name", DEFAULT_EMBEDDING_MODEL_NAME),
                embedding_model_version=str(raw.get("embedding_model_version", DEFAULT_EMBEDDING_MODEL_VERSION)),
                max_epmem_episodes=int(raw.get("max_epmem_episodes", DEFAULT_MAX_EPMEM_EPISODES)),
                smem_accumulation_min_psi=float(
                    raw.get("smem_accumulation_min_psi", DEFAULT_SMEM_ACCUMULATION_MIN_PSI)
                ),
                epmem_impasse_min_match_score=float(
                    raw.get("epmem_impasse_min_match_score", DEFAULT_EPMEM_IMPASSE_MIN_MATCH_SCORE)
                ),
            )
        except (TypeError, ValueError) as exc:
            raise MemoryConfigError(
                f"Invalid value in memory-config.yml: {exc}"
            ) from exc

        try:
            cfg.validate()
        except ValueError as exc:
            raise MemoryConfigError(str(exc)) from exc

        MemoryConfigLoader._ensure_directories(cfg)  # SEC-025 FIX-5: path 3 of 3
        return cfg

    @staticmethod
    def _ensure_directories(cfg: MemoryConfig) -> None:
        """
        Create parent directories for epmem_db_path and smem_db_path if absent.

        SEC-025 FIX-5:
        - Sets Unix permissions 0700 on the parent directory via explicit chmod
          (cannot rely on mkdir mode= argument — umask may override it).
        - Sets Unix permissions 0600 on each DB file if it already exists,
          or will be enforced on creation by _enforce_db_file_permissions().
        """
        import os
        for db_path in (cfg.epmem_db_path, cfg.smem_db_path):
            db_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                # Explicit chmod — not relying on mkdir(mode=) which umask overrides.
                os.chmod(db_path.parent, 0o700)
            except OSError:
                pass
            # Correct existing DB file permissions (SEC-025 FIX-5, FR-009).
            if db_path.exists():
                try:
                    os.chmod(db_path, 0o600)
                except OSError:
                    pass
