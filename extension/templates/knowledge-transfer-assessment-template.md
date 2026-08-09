## Knowledge Transfer Assessment

**Date:** {ISO-8601}
**Assessed by:** echelon-mirror (MIRROR)
**Project:** {feature name}

### Risk Table

| Knowledge Area | Documentation Level | Concentration Risk | Transfer Ready | Action Needed |
|---------------|--------------------|--------------------|---------------|---------------|
| Architecture | {HIGH/MEDIUM/LOW} | {single-agent/distributed} | {YES/NO} | {action or NONE} |
| Feature extension | {HIGH/MEDIUM/LOW} | {single-agent/distributed} | {YES/NO} | {action or NONE} |
| Debug pipeline | {HIGH/MEDIUM/LOW} | {single-agent/distributed} | {YES/NO} | {action or NONE} |
| Domain knowledge | {HIGH/MEDIUM/LOW} | {single-agent/distributed} | {YES/NO} | {action or NONE} |
| Test strategy | {HIGH/MEDIUM/LOW} | {single-agent/distributed} | {YES/NO} | {action or NONE} |
| Deployment/config | {HIGH/MEDIUM/LOW} | {single-agent/distributed} | {YES/NO} | {action or NONE} |

### Documentation Level Criteria
- **HIGH**: Comprehensive docs exist - ADRs, guides, examples, glossary entries
- **MEDIUM**: Partial docs - some decisions documented, but gaps in rationale or examples
- **LOW**: Tribal knowledge only - understanding exists in reasoning journal or agent context, not in durable docs

### Concentration Risk Criteria
- **single-agent**: Only one agent or specialist worked with this area; no cross-validation occurred
- **distributed**: Multiple agents interacted with this area; knowledge is redundant

### Overall Verdict
- **TRANSFER_READY**: All areas HIGH or MEDIUM with no single-agent concentration
- **AT_RISK**: One or more areas LOW, or critical areas have single-agent concentration
- **NOT_READY**: Multiple areas LOW with single-agent concentration - significant knowledge loss risk

### Recommended Actions
1. {Specific action to close the most critical gap}
2. {Next priority action}
