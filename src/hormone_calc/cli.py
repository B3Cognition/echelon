#!/usr/bin/env python3
"""hormone-calc CLI entry point.

Subcommands:
  compute --agent X --dispatch-id Y --result-file Z [--state path] [--journal path]
    → emits trigger list to stdout, one per line, space-separated args
"""

from __future__ import annotations

import sys
from pathlib import Path


USAGE = """\
Usage: hormone-calc <command> [args...]

Commands:
  compute --agent <AGENT> --dispatch-id <DID> --result-file <PATH>
          [--state <PATH>] [--journal <PATH>] [--config <PATH>]

Output: one trigger per line on stdout, space-separated args.
"""


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        sys.exit(0)

    if args[0] != "compute":
        print(f"hormone-calc: unknown command '{args[0]}'", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    # TODO: parse args, build observable, run triggers, emit output (Task 14 wires this up)
    print("hormone-calc compute: not yet implemented", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
