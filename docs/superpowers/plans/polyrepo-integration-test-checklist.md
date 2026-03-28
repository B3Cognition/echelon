# Polyrepo Integration Test Checklist

Run `/speckit.squad.run` against your polyrepo (top-dir with cpp/, fet-frontend-libs/, video-player/).

## Pre-flight
- [ ] spec-kit initialized in top-dir (`specify init --here`)
- [ ] reverse-eng extension installed (with System 1 polyrepo changes)
- [ ] cognitive-squad extension installed (with System 2 polyrepo changes)

## During Squad Run — Verify
- [ ] GOLDDIGGER detects polyrepo mode (check state.json for `golddigger_mode: "polyrepo-survey"`)
- [ ] GOLDDIGGER writes `golddigger_artifacts` to state.json (not brownfield-index.md)
- [ ] Small repos auto-promoted to full depth (check `golddigger_notes`)
- [ ] Per-repo analysis.json files exist in `.specify/reverse-eng/{repo}/`
- [ ] cross-repo.json exists and has dependency links
- [ ] SCOUT reads artifact paths from state.json (check reasoning journal)
- [ ] SCOUT produces per-repo boundaries in boundaries.md
- [ ] Cross-repo dependencies appear in mental-model.md or boundaries.md
- [ ] No `brownfield-index.md` file is produced anywhere

## Mode 2 (if triggered)
- [ ] Mode 2 requests include `repo` field
- [ ] Cache path uses `{repo}--{domain}.md` format
- [ ] Requesting agent receives cache file in next context pack

## Regression
- [ ] Single-repo squad run still works (run against any single repo)
- [ ] GOLDDIGGER failure → SCOUT falls back to manual analysis
