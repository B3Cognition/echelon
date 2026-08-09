---
name: echelon.cicd
description: "Retired. Re-run echelon delivery init to auto-detect high-confidence verify_command values."
behavior:
  invocation: manual
---

# Retired

`echelon.cicd` is retired.

Do not launch a squad run, create a new spec, generate Dockerfiles, rewrite
deploy config, or create CI workflow files from this command.

For harness verification setup, run:

```bash
echelon delivery init
```

`echelon delivery init` writes a top-level `verify_command` only when it can make
a high-confidence deterministic choice. If detection is ambiguous, add
`verify_command` manually to `.specify/extensions/echelon/echelon-config.yml`,
for example:

```yaml
verify_command: pytest
verify_command: npm test
verify_command: go test ./...
```
