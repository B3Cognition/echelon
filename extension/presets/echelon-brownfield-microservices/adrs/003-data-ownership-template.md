# ADR-003: Data Ownership and Database Strategy

**Status**: Proposed
**Date**: {DATE}
**Deciders**: [REQUIRES INPUT]

## Context

Decomposing the monolith requires deciding how to handle data that was previously in a single database. This decision affects:
- Service independence and autonomy
- Data consistency guarantees
- Query complexity
- Operational overhead
- Migration complexity

The shared database is currently the primary source of coupling. Cross-table joins, foreign keys, and transactions span what will become service boundaries.

## Decision Drivers

- **Service autonomy**: Services should own their data
- **Consistency requirements**: Transaction boundaries
- **Query patterns**: Cross-domain queries, reporting
- **Migration complexity**: Data movement and sync
- **Operational cost**: Multiple databases vs shared

## Current Database Analysis

| Table/Entity | Current DB | Used By | FK Dependencies |
|--------------|------------|---------|-----------------|
| {table} | {db} | {services} | {list} |

**Coupling Score**: {HIGH/MEDIUM/LOW}
**Shared Transaction Boundaries**: {count}
**Cross-Domain Joins**: {count}

## Considered Options

### Option 1: Database Per Service (Strongest Isolation)

Each service has its own database, technology choice independent.

```text
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Service A  │  │  Service B  │  │  Service C  │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │
┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
│ PostgreSQL  │  │   MongoDB   │  │   DynamoDB  │
└─────────────┘  └─────────────┘  └─────────────┘
```

**Pros**:
- Full autonomy
- Independent scaling
- Technology flexibility
- Clear ownership

**Cons**:
- Cross-service queries complex
- Data duplication needed
- Distributed transactions (sagas)
- Higher operational cost

### Option 2: Shared Database, Separate Schemas

Single database instance, schema per service.

```text
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Service A  │  │  Service B  │  │  Service C  │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │
       └────────────────┼────────────────┘
                        │
              ┌─────────▼─────────┐
              │    PostgreSQL     │
              │  ┌─────┬─────┐    │
              │  │ A   │ B   │ C  │
              │  └─────┴─────┘    │
              └───────────────────┘
```

**Pros**:
- Simpler operations
- Cross-schema queries possible
- Lower infrastructure cost
- Easier migration path

**Cons**:
- Coupling risk
- Schema boundary discipline required
- Technology lock-in
- Scaling limits

### Option 3: Shared Database Transitionally (Migration Path)

Start with shared database, migrate to separate as services mature.

**Pros**:
- Gradual migration
- Lower initial risk
- Learn boundaries first

**Cons**:
- Technical debt
- Delayed autonomy
- May never complete migration

### Option 4: Hybrid (Recommended for Most Cases)

Critical/high-volume services get own database, others share.

**Pros**:
- Pragmatic balance
- Cost effective
- Autonomy where it matters

**Cons**:
- Inconsistent architecture
- Decision overhead

## Decision

[REQUIRES INPUT - Select and assign]

**Selected Strategy**: Option {X}

### Database Assignments

| Service | Database | Type | Rationale |
|---------|----------|------|-----------|
| {service} | {own/shared} | {PostgreSQL/MongoDB/etc} | {why} |

### Data Ownership Matrix

| Entity | Owner Service | Access Pattern for Others |
|--------|---------------|--------------------------|
| {entity} | {service} | API / Event / Read Replica / N/A |

## Data Synchronization

### Event-Driven Sync

| Source | Event | Consumers | Data Replicated |
|--------|-------|-----------|-----------------|
| {service} | {entity}.updated | {services} | {fields} |

### Change Data Capture (CDC)

| Source Table | Target Service | Mechanism | Latency |
|--------------|----------------|-----------|---------|
| {table} | {service} | Debezium/DMS | {ms/s} |

### API Access

| Data | Owner | API Endpoint | Caching |
|------|-------|--------------|---------|
| {data} | {service} | GET /api/v1/{resource} | {TTL} |

## Cross-Service Query Strategy

| Query Need | Solution |
|------------|----------|
| Reporting / Analytics | Data warehouse (BigQuery/Redshift) |
| Real-time dashboard | Materialized views via events |
| Cross-domain search | Elasticsearch index |
| Ad-hoc joins | CQRS read models |

## Migration Plan

### Phase 1: Schema Separation

```sql
-- Move tables to service-specific schemas
ALTER TABLE orders SET SCHEMA orders_service;
ALTER TABLE inventory SET SCHEMA inventory_service;
```

### Phase 2: Remove Foreign Keys

```sql
-- Replace FK with application-level validation
ALTER TABLE orders DROP CONSTRAINT fk_customer;
-- Service validates customer exists via API
```

### Phase 3: Database Separation

For services requiring full isolation:

1. Create new database
2. Set up CDC or dual-write
3. Migrate application to new DB
4. Verify data consistency
5. Cut over traffic
6. Decommission old tables

## Consequences

### Positive

- {consequence}

### Negative

- {consequence}

### Risks

- **Risk**: Data inconsistency during sync
  - **Mitigation**: Idempotent consumers, reconciliation jobs

- **Risk**: Query performance degradation
  - **Mitigation**: Caching, read replicas, CQRS

- **Risk**: Migration data loss
  - **Mitigation**: Dual-write period, rollback plan

## Related

- [ADR-001: Service Boundaries](001-service-boundaries-template.md)
- [ADR-002: Communication Patterns](002-communication-patterns-template.md)
