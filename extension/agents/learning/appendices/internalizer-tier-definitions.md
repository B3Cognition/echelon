# Internalizer Tier Definitions

| Tier | Description | Absorption Threshold | Accuracy Threshold |
|------|-------------|---------------------|--------------------|
| **Deep** | Core agents that must fully absorb spec | Configured in `internalization.tiers.deep.absorption_threshold` | Configured in `internalization.tiers.deep.int_accuracy_threshold` |
| **Moderate** | Supporting agents with partial spec needs | Configured in `internalization.tiers.moderate.*` | Configured in `internalization.tiers.moderate.*` |
| **Minimal** | Agents that need only basic awareness | Configured in `internalization.tiers.minimal.*` | Configured in `internalization.tiers.minimal.*` |
| **Exempt** | Agents that do not produce spec-traceable output | N/A — always EXEMPT | N/A — always EXEMPT |
