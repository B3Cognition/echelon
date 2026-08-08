# ADR-001: Service Boundary Definitions

**Status**: Proposed
**Date**: {DATE}
**Deciders**: [REQUIRES INPUT]

## Context

We are decomposing the monolith into microservices. The most critical decision is defining service boundaries that will:
- Enable independent deployment and scaling
- Minimize cross-service coupling
- Align with team structure (Conway's Law)
- Support the business domain model

Incorrectly drawn boundaries lead to:
- Distributed monolith (tight coupling, synchronized deployments)
- Excessive inter-service communication
- Data consistency challenges
- Organizational friction

## Decision Drivers

- **Domain alignment**: Services should map to bounded contexts
- **Data ownership**: Each service should own its data
- **Team autonomy**: One team should own one service
- **Change frequency**: High-churn areas should be isolated
- **Scalability requirements**: Independent scaling needs

## Bounded Contexts Identified

Based on domain analysis:

| Context | Core/Supporting/Generic | Coupling Score | Team |
|---------|------------------------|----------------|------|
| {context} | {type} | {HIGH/MEDIUM/LOW} | [REQUIRES INPUT] |

## Considered Options

### Option 1: Fine-Grained Services (One Aggregate per Service)

Each domain aggregate becomes its own service.

**Pros**:
- Maximum flexibility
- Independent scaling per aggregate
- Clear ownership

**Cons**:
- High operational overhead
- Excessive network calls
- Distributed transaction complexity
- Team cognitive load

### Option 2: Bounded Context Services (Recommended)

One service per bounded context, containing related aggregates.

**Pros**:
- Balanced granularity
- Reduced network calls within context
- Clearer team ownership
- Transactions within service

**Cons**:
- Services may grow large
- Requires discipline to prevent coupling
- May need future decomposition

### Option 3: Module-First (Modular Monolith)

Keep as modules in monolith, extract later when needed.

**Pros**:
- Lower initial complexity
- Easier refactoring
- Shared infrastructure

**Cons**:
- Delayed benefits
- May calcify coupling
- Single deployment unit

## Decision

[REQUIRES INPUT - Select option and define specific boundaries]

**Selected Approach**: Option {X}

**Service Boundaries**:

| Service | Bounded Context(s) | Aggregates | Rationale |
|---------|-------------------|------------|-----------|
| {service-name} | {context} | {aggregates} | {why grouped} |

## Consequences

### Positive

- {consequence}

### Negative

- {consequence}

### Risks

- **Risk**: {risk description}
  - **Mitigation**: {how to address}

## Validation

Before finalizing:

- [ ] Domain experts reviewed boundaries
- [ ] Teams can own services independently
- [ ] Communication patterns identified
- [ ] Data ownership clear
- [ ] No circular dependencies

## Related

- [ADR-002: Communication Patterns](002-communication-patterns-template.md)
- [ADR-003: Data Ownership](003-data-ownership-template.md)
