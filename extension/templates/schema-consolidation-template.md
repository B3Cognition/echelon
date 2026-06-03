# Schema Consolidation

**Date:** {ISO-8601}
**Run:** {run_id}
**Mode:** {online_replay | offline_consolidation | mental_simulation}

## Promoted Schemas

| Schema ID | Domain | Pattern | Supporting Traces | Outcome Signal Avg | Notes |
|-----------|--------|---------|-------------------|--------------------|-------|
| {schema_id} | {domain} | {pattern_description} | {count} | {0.0-1.0} | {notes} |

## Reinforced Schemas

| Schema ID | Prior Support | New Support | Last Reinforced | Notes |
|-----------|---------------|-------------|-----------------|-------|
| {schema_id} | {count} | {count} | {ISO-8601} | {notes} |

## Consolidated Traces

| Trace ID | Source Run | Domain | Consolidated Into | Salience Change |
|----------|------------|--------|-------------------|-----------------|
| {trace_id} | {run_id} | {domain} | {schema_id} | {change} |

## Simulation Results

| Query Summary | Causal Coherence | Depth Used | Supporting Fragments | Result |
|---------------|------------------|------------|----------------------|--------|
| {agent-generated summary} | coherent/partial/failed | {depth} | {fragment_ids} | {summary} |

## Consolidation Log

- **Schemas promoted:** {count}
- **Schemas reinforced:** {count}
- **Traces consolidated:** {count}
- **Unavailable fallback:** {none or reason}
