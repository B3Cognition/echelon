STATUS: DONE

Files changed:
- tests/fixtures/ai_cli/opencode-run-json.jsonl
- tests/fixtures/ai_cli/copilot-prompt-json.jsonl
- .superpowers/sdd/task-1-report.md

Commands run:
- opencode run --format json "Say hello in one short sentence. Do not modify files." > /tmp/egr097-opencode.jsonl
- head -20 /tmp/egr097-opencode.jsonl
- copilot -p "Say hello in one short sentence. Do not modify files." --output-format json --stream off --silent > /tmp/egr097-copilot.jsonl
- head -40 /tmp/egr097-copilot.jsonl
- jq -c . tests/fixtures/ai_cli/opencode-run-json.jsonl >/dev/null && jq -c . tests/fixtures/ai_cli/copilot-prompt-json.jsonl >/dev/null
- wc -l tests/fixtures/ai_cli/opencode-run-json.jsonl tests/fixtures/ai_cli/copilot-prompt-json.jsonl
- git diff --check

Test/validation results:
- OpenCode CLI capture exited 0 and produced 3 JSONL events, including a text event with assistant content and a step-finish event.
- Copilot CLI capture exited 0 and produced 12 JSONL events, including assistant.message and result events.
- Saved fixtures parse successfully with jq.
- Saved fixture line counts: OpenCode 3, Copilot 4.
- git diff --check passed.

Commits created:
- eab7b18 test: capture OpenCode and Copilot CLI output fixtures

Concerns:
- None.

Fix note:
- 2026-07-05: Marked Task 1 steps complete in docs/superpowers/plans/2026-07-05-egr-097-opencode-copilot-backends.md after review noted the required plan tracking update was omitted from the fixture capture commit. Later task checkboxes remain unchanged.
