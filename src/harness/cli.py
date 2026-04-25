#!/usr/bin/env python3
"""harness CLI — terminal entry points for harness commands.

Usage:
  harness init [<target_repo>]
  harness run <spec_id> [strategy=<name>] [mode=<mode>]

init is pure Python (no LLM).
run delegates to StrategyCoordinator via run_skill.
"""

from __future__ import annotations

import sys
from pathlib import Path

USAGE = """\
Usage: harness <command> [args...]

Commands:
  init [<target_repo>]             Initialize harness (no LLM).
                                   Omit target_repo to target current directory.
  run  <spec_id> [strategy=<s>]    Run build→verify→PR loop for a spec.
                                   strategy: default (echelon squad) or codegen (SOAR)
                                   mode:     semi (default) | banzai | guided

Examples:
  harness init
  harness init https://github.com/org/repo
  harness run 001
  harness run 001 strategy=codegen
  harness run 001 strategy=default mode=banzai
"""


# ── init (pure Python, no LLM) ────────────────────────────────────────────

def _cmd_init(args: list[str]) -> None:
    target_repo = args[0] if args else "."
    base_dir = str(Path.cwd())

    # bind_mount_ack: accept via env or flag
    import os
    bind_mount_ack = os.environ.get("HARNESS_BIND_MOUNT_ACK", "").lower() in ("true", "1", "yes")

    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from harness.init import init_harness, InitError
    try:
        config = init_harness(
            target_repo=target_repo,
            base_dir=base_dir,
            bind_mount_ack=bind_mount_ack,
        )
    except InitError as e:
        print(f"✗ harness init failed: {e}", file=sys.stderr)
        sys.exit(1)

    config_file = Path(base_dir) / ".specify" / "extensions" / "harness" / "harness-config.yml"
    mirror_dir = Path(base_dir) / ".specify" / "harness" / "mirror.git"

    image_note = ""
    if config.base_image is None:
        # Image was auto-detected from fingerprint or fell back to ubuntu:22.04 —
        # show the detected_image from config_data written by init_harness.
        try:
            import yaml as _yaml
            raw = _yaml.safe_load(config_file.read_text())
            detected = raw.get("detected_image", "ubuntu:22.04")
            source = raw.get("detected_image_source", "fallback")
            if source == "fallback":
                image_note = (
                    f"\n  ⚠  base_image not detected — using ubuntu:22.04 as fallback.\n"
                    f"     Set base_image in {config_file}\n"
                    f"     once you know your stack (e.g. node:20, python:3.12-slim).\n"
                )
            else:
                image_note = f"\n  base_image    → {detected} (auto-detected: {source})\n"
        except Exception:
            pass

    print(
        f"\n"
        f"╔══════════════════════════════════════════╗\n"
        f"║         harness init — complete          ║\n"
        f"╚══════════════════════════════════════════╝\n"
        f"\n"
        f"  target_repo  → {config.target_repo}\n"
        f"  config       → {config_file}\n"
        f"  mirror       → {mirror_dir}\n"
        f"  provider     → {config.provider}\n"
        f"  pr_host      → {config.pr_host}\n"
        f"{image_note}"
        f"\n"
        f"Next step:\n"
        f"  echelon run \"<feature description>\"\n"
        f"  harness run <spec_id>\n"
    )


# ── run ───────────────────────────────────────────────────────────────────

def _parse_kvs(args: list[str]) -> dict[str, str]:
    """Parse key=value pairs from remaining args."""
    kv: dict[str, str] = {}
    for arg in args:
        if "=" in arg:
            k, _, v = arg.partition("=")
            kv[k.strip()] = v.strip()
    return kv


def _cmd_run(args: list[str]) -> None:
    if not args:
        print("harness run: missing spec_id\n", file=sys.stderr)
        print(USAGE)
        sys.exit(1)

    spec_id = args[0]
    kv = _parse_kvs(args[1:])
    strategy = kv.get("strategy", "default")
    mode = kv.get("mode", "semi")

    # Build message string for parse_intent
    parts = [
        f"spec {spec_id}",
        f"{mode} mode",
        f"strategies={strategy}",
    ]
    user_message = " ".join(parts)

    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from harness.config import load_config
    from harness.docker_provider import DockerWorktreeProvider
    from harness.gitops import GitOpsManager
    from harness.skills.run_skill import run

    config = load_config()
    gitops = GitOpsManager(config)
    provider = DockerWorktreeProvider(buffer_limit_bytes=config.buffer_limit_bytes)

    run(user_message, provider, gitops)


# ── Entry point ───────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        sys.exit(0)

    command = args[0]

    if command == "init":
        _cmd_init(args[1:])
    elif command == "run":
        _cmd_run(args[1:])
    else:
        print(f"harness: unknown command '{command}'\n", file=sys.stderr)
        print(USAGE)
        sys.exit(1)
