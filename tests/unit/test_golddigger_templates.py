from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "extension" / "agents" / "exploration" / "golddigger.md"


class TestGolddiggerTemplates:
    def test_golddigger_prompt_uses_canonical_agent_label(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "agent: speckit-echelon-golddigger (GOLDDIGGER)" in text
        assert "agent: EXTRACT" not in text

    def test_golddigger_derives_polyrepo_mode_from_manifest_count(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert '.mode // (if (.repo_count // 0) > 1 then "polyrepo" else "single" end)' in text
        assert "jq -r '.mode' \"$MANIFEST\"" not in text

    def test_golddigger_generates_manifest_before_mode_detection(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert 'DISCOVER_REPOS="${EXTENSION_PATH:-.specify/extensions/echelon}/scripts/bash/re/discover-repos.sh"' in text
        assert '"$DISCOVER_REPOS" "$REPOS_MANIFEST"' in text
        assert "Do not infer single-repo mode from missing manifests" in text
        assert 'MODE="single"' not in text

    def test_golddigger_uses_explicit_re_runtime_args_not_local_config(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "ALWAYS write extraction config overrides" not in text
        assert "cat > .specify/extensions/echelon/local-config.yml" not in text
        assert "active via `local-config.yml`" not in text
        assert "--profile" in text
        assert "--output" in text
        assert "--manifest" in text
        assert "RE_OUTPUT_DIR" in text
