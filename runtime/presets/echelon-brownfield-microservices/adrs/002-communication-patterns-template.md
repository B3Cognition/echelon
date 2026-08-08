# ADR-002: Inter-Service Communication Patterns

**Status**: Proposed
**Date**: {DATE}
**Deciders**: [REQUIRES INPUT]

## Context

With services decomposed from the monolith, we need to define how they communicate. The choice of communication patterns affects:
- System reliability and resilience
- Data consistency guarantees
- Performance and latency
- Operational complexity
- Team autonomy

## Decision Drivers

- **Consistency requirements**: Strong vs eventual consistency needs
- **Latency tolerance**: User-facing vs background operations
- **Coupling**: Temporal vs logical coupling acceptance
- **Reliability**: Failure handling and recovery
- **Scalability**: Message volume and service scaling

## Communication Needs Analysis

| Source Service | Target Service | Pattern | Consistency | Latency |
|----------------|----------------|---------|-------------|---------|
| {service} | {service} | {Query/Command/Event} | {Strong/Eventual} | {Sync/Async} |

## Considered Options

### Option 1: REST/HTTP Everywhere (Synchronous)

All communication via synchronous HTTP calls.

**Pros**:
- Simple to implement
- Easy to debug
- Familiar to developers
- Strong consistency possible

**Cons**:
- Temporal coupling
- Cascading failures
- Lower availability
- Latency accumulates

### Option 2: Event-Driven Everywhere (Asynchronous)

All communication via asynchronous events.

**Pros**:
- Loose coupling
- High availability
- Natural audit trail
- Scalable

**Cons**:
- Eventual consistency complexity
- Debugging challenges
- Event schema evolution
- Infrastructure overhead

### Option 3: Hybrid Pattern (Recommended)

Synchronous for queries, asynchronous for commands and notifications.

**Pros**:
- Best of both worlds
- Appropriate consistency per use case
- Pragmatic balance

**Cons**:
- Two patterns to maintain
- More design decisions
- Mixed mental model

### Option 4: Service Mesh (RPC + Events)

gRPC for sync, events for async, with service mesh handling cross-cutting.

**Pros**:
- High performance
- Strong typing
- Automatic resilience (retries, circuit breakers)

**Cons**:
- Infrastructure complexity
- Learning curve
- Vendor lock-in risk

## Decision

[REQUIRES INPUT - Select and configure]

**Selected Pattern**: Option {X}

### Synchronous Communication

| Use Case | Protocol | Contract |
|----------|----------|----------|
| Queries / lookups | REST/gRPC | OpenAPI/Protobuf |
| User-facing requests | REST | OpenAPI |
| High-performance internal | gRPC | Protobuf |

**Resilience Configuration**:
- Timeout: {X}ms default
- Retries: {X} with exponential backoff
- Circuit breaker: Open after {X} failures

### Asynchronous Communication

| Use Case | Pattern | Broker |
|----------|---------|--------|
| Domain events | Pub/Sub | {Kafka/RabbitMQ/SNS} |
| Commands | Point-to-point | {SQS/RabbitMQ} |
| Saga orchestration | Request-Reply | {broker} |

**Message Broker**: [REQUIRES INPUT]
**Schema Registry**: [REQUIRES INPUT]
**Event Format**: CloudEvents / Custom

### Saga Pattern

For distributed transactions:

| Saga | Pattern | Services |
|------|---------|----------|
| {saga-name} | Choreography/Orchestration | {list} |

## Event Standards

### Naming Convention

```
{domain}.{aggregate}.{event}

Examples:
- orders.order.created
- inventory.stock.reserved
- payments.payment.completed
```

### Event Schema

```json
{
  "specversion": "1.0",
  "type": "{domain}.{aggregate}.{event}",
  "source": "/{service-name}",
  "id": "{uuid}",
  "time": "{ISO8601}",
  "datacontenttype": "application/json",
  "data": { ... }
}
```

## Consequences

### Positive

- {consequence}

### Negative

- {consequence}

### Risks

- **Risk**: Message loss
  - **Mitigation**: Persistent messaging, idempotent consumers, DLQ

- **Risk**: Event schema evolution
  - **Mitigation**: Schema registry, versioning policy

## Related

- [ADR-001: Service Boundaries](001-service-boundaries-template.md)
- [ADR-003: Data Ownership](003-data-ownership-template.md)
