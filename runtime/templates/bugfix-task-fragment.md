## Bugfix {n}: {Bug Summary}

Append bugfix work as normal canonical task rows. Use `BF1-T1` only as the
human-facing bugfix item label inside the title or description; the executable
canonical row still uses the next available `T-###` ID.

```markdown
- [ ] T-101 complexity=standard phase=bugfix req=FR-001 depends=none

  **Title:** BF1-T1 - Add regression coverage for {bug}
```
