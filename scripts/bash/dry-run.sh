#!/usr/bin/env bash
# Validate Echelon's canonical Prosaic prose and runtime bundles.
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
SOURCE_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../.." && pwd)"
INPUT_ROOT="${1:-$SOURCE_ROOT}"

python_supports_runtime() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
    >/dev/null 2>&1
}

REQUESTED_PYTHON="${PYTHON:-}"
PYTHON=""
if [[ -n "$REQUESTED_PYTHON" ]] && python_supports_runtime "$REQUESTED_PYTHON"; then
  PYTHON="$REQUESTED_PYTHON"
elif [[ -x "$SOURCE_ROOT/.venv/bin/python" ]] && \
     python_supports_runtime "$SOURCE_ROOT/.venv/bin/python"; then
  PYTHON="$SOURCE_ROOT/.venv/bin/python"
elif [[ -x "$HOME/.echelon/venv/bin/python" ]] && \
     python_supports_runtime "$HOME/.echelon/venv/bin/python"; then
  PYTHON="$HOME/.echelon/venv/bin/python"
else
  for candidate in /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3 \
      python3.12 python3 python; do
    if { [[ -x "$candidate" ]] || command -v "$candidate" >/dev/null 2>&1; } && \
       python_supports_runtime "$candidate"; then
      PYTHON="$candidate"
      break
    fi
  done
fi

if [[ -z "$PYTHON" ]]; then
  echo "ERROR: Python 3.11+ is required for Echelon bundle validation." >&2
  exit 1
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

    legacy_cli_tree = ast.parse(
        (source_root / "src" / "echelon" / "cli.py").read_text(
            encoding="utf-8"
        )
    )
    creation_functions = [
        node
        for node in legacy_cli_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_run_re_v2_create"
    ]
    if len(creation_functions) != 1:
        raise SystemExit("RE v2 creation function is missing or ambiguous")
    preparation_functions = [
        node
        for node in legacy_cli_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_prepare_re_v22_creation"
    ]
    if len(preparation_functions) != 1:
        raise SystemExit("RE protocol-2.2 preparation function is missing or ambiguous")
    creation_function = creation_functions[0]
    preparation_function = preparation_functions[0]
    workspace_imports = [
        node
        for node in ast.walk(preparation_function)
        if isinstance(node, ast.ImportFrom)
        and node.module == "harness.re_v2.workspace_snapshot"
        and any(alias.name == "capture_workspace_snapshot" for alias in node.names)
    ]
    if len(workspace_imports) != 1:
        raise SystemExit("RE v2 creation must import capture_workspace_snapshot")
    preparation_calls = sorted(
        node.lineno
        for node in ast.walk(preparation_function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "capture_workspace_snapshot"
    )
    creation_calls = {
        name: sorted(
            node.lineno
            for node in ast.walk(creation_function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == name
        )
        for name in (
            "_prepare_re_v26_creation",
            "create_protocol_26_run_store",
            "_activate_re_v2_run",
        )
    }
    if len(preparation_calls) != 1 or any(
        len(lines) != 1 for lines in creation_calls.values()
    ):
        raise SystemExit("RE v2 creation lifecycle calls are missing or ambiguous")
    if not (
        creation_calls["_prepare_re_v26_creation"][0]
        < creation_calls["create_protocol_26_run_store"][0]
        < creation_calls["_activate_re_v2_run"][0]
    ):
        raise SystemExit(
            "RE v2 source capture must precede run creation and activation"
        )

    cli_tree = ast.parse(
        (source_root / "src" / "echelon" / "cli_app.py").read_text(
            encoding="utf-8"
        )
    )
    def is_named_attribute(
        node: ast.AST,
        owner: str,
        attribute: str,
    ) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == owner
            and node.attr == attribute
        )

    def option_switches(node: ast.AST) -> set[str]:
        if not (
            isinstance(node, ast.Call)
            and is_named_attribute(node.func, "typer", "Option")
        ):
            return set()
        return {
            argument.value
            for argument in node.args
            if isinstance(argument, ast.Constant)
            and isinstance(argument.value, str)
            and argument.value.startswith("--")
        }

    def direct_call(statement: ast.stmt) -> ast.Call | None:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            return statement.value
        return None

    def is_args_method(call: ast.Call | None, method: str) -> bool:
        return bool(
            call is not None
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "args"
            and call.func.attr == method
        )

    def is_engine_branch(node: ast.If) -> bool:
        test = node.test
        return bool(
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "engine"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Is)
            and len(test.comparators) == 1
            and is_named_attribute(test.comparators[0], "ReEngine", "V2")
        )

    def routes_engine(node: ast.If) -> bool:
        for statement in node.body:
            call = direct_call(statement)
            if not is_args_method(call, "extend") or len(call.args) != 1:
                continue
            value = call.args[0]
            if not isinstance(value, (ast.List, ast.Tuple)) or len(value.elts) != 2:
                continue
            switch, selected = value.elts
            if (
                isinstance(switch, ast.Constant)
                and switch.value == "--engine"
                and isinstance(selected, ast.Attribute)
                and isinstance(selected.value, ast.Name)
                and selected.value.id == "engine"
                and selected.attr == "value"
            ):
                return True
        return False

    def routes_shadow(node: ast.If) -> bool:
        if not isinstance(node.test, ast.Name) or node.test.id != "shadow":
            return False
        for statement in node.body:
            call = direct_call(statement)
            if (
                is_args_method(call, "append")
                and len(call.args) == 1
                and isinstance(call.args[0], ast.Constant)
                and call.args[0].value == "--shadow"
            ):
                return True
        return False

    def routes_legacy_run(statement: ast.stmt) -> bool:
        call = direct_call(statement)
        return bool(
            call is not None
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "_cmd_re_run"
            and isinstance(call.func.value, ast.Call)
            and isinstance(call.func.value.func, ast.Name)
            and call.func.value.func.id == "_legacy_cli"
            and len(call.args) == 1
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id == "args"
        )

    root_attachments = []
    for statement in cli_tree.body:
        call = direct_call(statement)
        if not (
            call is not None
            and is_named_attribute(call.func, "app", "add_typer")
            and call.args
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id == "re_app"
        ):
            continue
        names = [
            keyword.value.value
            for keyword in call.keywords
            if keyword.arg == "name"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        ]
        root_attachments.extend(names)
    if root_attachments != ["re"]:
        raise SystemExit("RE Typer root attachment is missing or ambiguous")

    commands: set[str] = set()
    hidden_commands: set[str] = set()
    run_functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
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
                if any(
                    keyword.arg == "hidden"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in decorator.keywords
                ):
                    hidden_commands.add(command_name)
        if command_name != "run":
            continue
        run_functions.append(node)

    required_commands = {
        "continue",
        "analyze",
        "check-domain",
        "execute-run",
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
    required_hidden_commands = {"analyze", "check-domain", "execute-run"}
    visible_internal_commands = required_hidden_commands - hidden_commands
    if visible_internal_commands:
        raise SystemExit(
            "RE internal commands are not hidden: "
            + ", ".join(sorted(visible_internal_commands))
        )
    if len(run_functions) != 1:
        raise SystemExit("RE run callback is missing or ambiguous")
    run_function = run_functions[0]
    positional = [*run_function.args.posonlyargs, *run_function.args.args]
    defaults = run_function.args.defaults
    parameter_defaults = {
        argument.arg: default
        for argument, default in zip(positional[-len(defaults):], defaults)
    }
    option_owners = {
        parameter: option_switches(default)
        for parameter, default in parameter_defaults.items()
    }
    for parameter, switch in (("engine", "--engine"), ("shadow", "--shadow")):
        if option_owners.get(parameter) != {switch}:
            raise SystemExit(
                f"RE run option ownership is invalid: {parameter} -> {switch}"
            )
        conflicting = sorted(
            owner
            for owner, switches in option_owners.items()
            if owner != parameter and switch in switches
        )
        if conflicting:
            raise SystemExit(
                f"RE run option ownership is ambiguous: {switch} also belongs to "
                + ", ".join(conflicting)
            )
    engine_branches = [
        node for node in run_function.body if isinstance(node, ast.If) and is_engine_branch(node)
    ]
    if len(engine_branches) != 1 or not routes_engine(engine_branches[0]):
        raise SystemExit("RE run --engine callback routing is invalid")
    shadow_branches = [
        node for node in run_function.body if isinstance(node, ast.If) and routes_shadow(node)
    ]
    if len(shadow_branches) != 1:
        raise SystemExit("RE run --shadow callback routing is invalid")
    if not run_function.body or not routes_legacy_run(run_function.body[-1]):
        raise SystemExit("RE run legacy callback routing is invalid")
    if any(scratch.iterdir()):
        raise SystemExit("static RE validation created workspace/provider state")

print(
    f"PASS: {len(module_names)} RE v2 modules import; "
    "RE root, composite creation order, complete command surface, and run option routing are valid "
    "without runtime work"
)
PY

exec "$PYTHON" -m harness.bundle_validator "$INPUT_ROOT"
