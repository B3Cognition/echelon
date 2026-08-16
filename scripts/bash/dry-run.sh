#!/usr/bin/env bash
# Validate Echelon's canonical Prosaic prose and runtime bundles.
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
SOURCE_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../.." && pwd)"
INPUT_ROOT="${1:-$SOURCE_ROOT}"

if [[ -x "$SOURCE_ROOT/.venv/bin/python" ]]; then
  PYTHON="$SOURCE_ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

export PYTHONPATH="$SOURCE_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON" - "$SOURCE_ROOT" <<'PY'
from __future__ import annotations

import ast
import importlib
import os
import pkgutil
from pathlib import Path
import sys
import tempfile


source_root = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix="echelon-re-static-") as temporary:
    scratch = Path(temporary)
    os.chdir(scratch)
    os.environ["ECHELON_HOME"] = str(scratch / "echelon-home")

    package = importlib.import_module("harness.re_v2")
    module_names = [package.__name__]
    module_names.extend(
        module.name
        for module in pkgutil.walk_packages(
            package.__path__,
            prefix=f"{package.__name__}.",
        )
    )
    for module_name in sorted(module_names):
        importlib.import_module(module_name)

    cli_tree = ast.parse(
        (source_root / "src" / "echelon" / "cli_app.py").read_text(
            encoding="utf-8"
        )
    )
    commands: set[str] = set()
    run_options: set[str] = set()
    for node in ast.walk(cli_tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "re_app"
            and node.func.attr == "add_typer"
        ):
            for keyword in node.keywords:
                if (
                    keyword.arg == "name"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    commands.add(keyword.value.value)
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        command_name: str | None = None
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "re_app"
                and decorator.func.attr == "command"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                command_name = decorator.args[0].value
                commands.add(command_name)
        if command_name != "run":
            continue
        for default in node.args.defaults:
            if not isinstance(default, ast.Call):
                continue
            for argument in default.args:
                if isinstance(argument, ast.Constant) and isinstance(
                    argument.value, str
                ):
                    run_options.add(argument.value)

    required_commands = {
        "continue",
        "finalize",
        "memory",
        "publish",
        "refresh",
        "resume",
        "run",
        "status",
        "synthesize",
    }
    missing_commands = required_commands - commands
    if missing_commands:
        raise SystemExit(
            "RE commands are missing: " + ", ".join(sorted(missing_commands))
        )
    missing_options = {"--engine", "--shadow"} - run_options
    if missing_options:
        raise SystemExit(
            "RE v2 creation options are missing: "
            + ", ".join(sorted(missing_options))
        )
    if any(scratch.iterdir()):
        raise SystemExit("static RE validation created workspace/provider state")

print(
    f"PASS: {len(module_names)} RE v2 modules import; "
    "RE commands and --engine/--shadow are exposed without runtime work"
)
PY

exec "$PYTHON" -m harness.bundle_validator "$INPUT_ROOT"
