"""State-location contracts for the deployed Prosaic/runtime bundle."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"
PROSAIC = ROOT / "prosaic"


def test_runtime_uses_echelon_owned_standalone_re_state() -> None:
    config = (RUNTIME / "config-template.yml").read_text(encoding="utf-8")
    discovery = (RUNTIME / "scripts" / "bash" / "re" / "discover-repos.sh").read_text(
        encoding="utf-8"
    )
    analysis = (RUNTIME / "scripts" / "bash" / "re" / "run-analysis.sh").read_text(
        encoding="utf-8"
    )
    bridge = (RUNTIME / "scripts" / "node" / "codegraph" / "codegraph-bridge.js").read_text(
        encoding="utf-8"
    )

    for text in (config, discovery, analysis, bridge):
        assert ".echelon/re" in text
        assert ".specify/echelon/re" not in text


def test_prosaic_re_commands_describe_echelon_owned_standalone_state() -> None:
    command = (PROSAIC / "commands" / "echelon.re-extract.md").read_text(
        encoding="utf-8"
    )

    assert "standalone `re-*`: `.echelon/re/state.json`" in command
    assert ".specify/echelon/re" not in command


def test_prosaic_runtime_does_not_direct_agents_to_legacy_squad_storage() -> None:
    commander = (PROSAIC / "subagents" / "echelon.commander.md").read_text(
        encoding="utf-8"
    )
    init = (PROSAIC / "commands" / "echelon.init.md").read_text(encoding="utf-8")
    veteran = (PROSAIC / "subagents" / "echelon.veteran.md").read_text(
        encoding="utf-8"
    )

    assert ".specify/squad" not in commander
    assert ".specify/squad" not in init
    assert ".specify/squad-global" not in veteran
    assert "~/.echelon/knowledge-base/" in veteran
