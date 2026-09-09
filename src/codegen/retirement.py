"""SOAR execution is retired; shared codegen utilities remain available."""
import shlex
from pathlib import Path

MESSAGE = "SOAR/codegen execution is disabled pending removal. Use the default delivery strategy."


def require_soar() -> None:
    raise RuntimeError(MESSAGE)


def reject_soar_command(command: str) -> None:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    tokens = list(lexer)
    if any(Path(token).name.lower() in {"codegen", "codegenlight", "soar", "soar96", "soar-cli", "jsoar"}
           or token in {"codegen.cli.codegen_cli", "src.codegen.cli.codegen_cli"}
           for token in tokens):
        require_soar()
    for index, token in enumerate(tokens[:-1]):
        if token in {"-c", "-lc", "-ic"}:
            reject_soar_command(tokens[index + 1])
