"""
tsconfig_extractor.py — Extracts rules from tsconfig.json files.
Spec 018 F3 T-011.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Human-readable descriptions for common compilerOptions
_TSCONFIG_DESCRIPTIONS: dict[str, str] = {
    "strict": "TypeScript strict mode enabled",
    "noImplicitAny": "TypeScript noImplicitAny enabled",
    "strictNullChecks": "TypeScript strictNullChecks enabled",
    "noUnusedLocals": "TypeScript noUnusedLocals enabled",
    "noUnusedParameters": "TypeScript noUnusedParameters enabled",
    "exactOptionalPropertyTypes": "TypeScript exactOptionalPropertyTypes enabled",
    "noImplicitReturns": "TypeScript noImplicitReturns enabled",
    "noFallthroughCasesInSwitch": "TypeScript noFallthroughCasesInSwitch enabled",
    "esModuleInterop": "TypeScript esModuleInterop enabled",
    "moduleResolution": "TypeScript moduleResolution: {value}",
    "target": "TypeScript compile target: {value}",
    "module": "TypeScript module system: {value}",
    "lib": "TypeScript lib: {value}",
    "outDir": "TypeScript outDir: {value}",
    "rootDir": "TypeScript rootDir: {value}",
    "baseUrl": "TypeScript baseUrl: {value}",
    "declaration": "TypeScript declaration files enabled",
    "sourceMap": "TypeScript sourceMap enabled",
    "allowJs": "TypeScript allowJs enabled",
    "checkJs": "TypeScript checkJs enabled",
    "skipLibCheck": "TypeScript skipLibCheck enabled",
    "forceConsistentCasingInFileNames": "TypeScript forceConsistentCasingInFileNames enabled",
    "isolatedModules": "TypeScript isolatedModules enabled",
    "jsx": "TypeScript JSX: {value}",
    "paths": "TypeScript path aliases configured",
    "resolveJsonModule": "TypeScript resolveJsonModule enabled",
    "experimentalDecorators": "TypeScript experimentalDecorators enabled",
    "emitDecoratorMetadata": "TypeScript emitDecoratorMetadata enabled",
}


def extract(root: str) -> list:
    """
    Find tsconfig.json files under root and extract compilerOptions as rules.

    Args:
        root: Directory root to search.

    Returns:
        List of ExtractedRule objects.
    """
    from src.codegen.extract.constitution_extractor import ExtractedRule
    from src.codegen.security.path_safety import PathSafety

    rules: list[ExtractedRule] = []
    safety = PathSafety(root)

    for filepath in safety.safe_walk(root, skip_hidden=True):
        if os.path.basename(filepath) != "tsconfig.json":
            continue
        try:
            with open(filepath, encoding="utf-8") as fh:
                content = fh.read()
            data = json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("tsconfig_extractor: skipping %s — %s", filepath, exc)
            continue

        compiler_opts = data.get("compilerOptions", {})
        if not isinstance(compiler_opts, dict):
            continue

        for key, value in compiler_opts.items():
            template = _TSCONFIG_DESCRIPTIONS.get(key)
            if template is None:
                raw_text = f"TypeScript compilerOptions.{key}: {value}"
            else:
                raw_text = template.format(value=value) if "{value}" in template else template

            # Boolean false values are not enforced — skip them
            if isinstance(value, bool) and not value:
                continue

            rules.append(
                ExtractedRule(
                    source_type="tsconfig",
                    raw_text=raw_text,
                    category="S",
                    confidence=0.85,
                    source="direct",
                )
            )

    return rules
