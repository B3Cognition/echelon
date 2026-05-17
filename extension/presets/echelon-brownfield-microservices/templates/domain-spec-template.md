# Specification: {Domain Name}

**Domain**: {NN}-{domain-name}
**Created**: {DATE}
**Status**: Draft (reverse-engineered)
**Dependencies**: {list of prerequisite domain numbers}
**Preset**: revenge-microservices

---

## Overview

{2-3 sentences describing this domain's purpose and scope}

**Source Files Analyzed**: {list of key files}

---

## Bounded Context

### Context Definition

**Name**: {ContextName}Context
**Type**: {Core / Supporting / Generic}
**Team Ownership**: [REQUIRES INPUT]

### Ubiquitous Language

| Term | Definition | Legacy Term (if different) |
|------|------------|---------------------------|
| {term} | {definition} | {legacy_term or same} |

### Context Boundaries

**This context owns**:
- {aggregate/entity} - {why it belongs here}

**This context does NOT own**:
- {entity} - belongs to {other context}

### Context Relationships

| Related Context | Relationship Type | Integration Pattern |
|-----------------|-------------------|---------------------|
| {context} | {Upstream/Downstream/Partnership} | {Conformist/ACL/Open Host/Shared Kernel} |

```text
┌─────────────────┐     {pattern}     ┌─────────────────┐
│  {ThisContext}  │ ──────────────── │ {OtherContext}  │
│   (Upstream)    │                   │  (Downstream)   │
└─────────────────┘                   └─────────────────┘
```

---

## Service Definition

### Service Overview

**Service Name**: {service-name}-service
**Runtime**: [REQUIRES INPUT - e.g., Python/FastAPI, TypeScript/NestJS]
**Repository**: [REQUIRES INPUT]

### API Contract

#### REST Endpoints

| Method | Path | Description | Request | Response |
|--------|------|-------------|---------|----------|
| GET | /api/v1/{resources} | List all | Query params | 200: Array |
| GET | /api/v1/{resources}/{id} | Get by ID | Path param | 200: Object, 404: Error |
| POST | /api/v1/{resources} | Create | Body | 201: Object, 400: Error |
| PUT | /api/v1/{resources}/{id} | Update | Path + Body | 200: Object, 404: Error |
| DELETE | /api/v1/{resources}/{id} | Delete | Path param | 204: Empty, 404: Error |

#### Events Published

| Event | Trigger | Payload Schema |
|-------|---------|----------------|
| {domain}.{entity}.created | After entity creation | {schema reference} |
| {domain}.{entity}.updated | After entity update | {schema reference} |
| {domain}.{entity}.deleted | After entity deletion | {id, timestamp} |

#### Events Consumed

| Event | Source | Handler |
|-------|--------|---------|
| {other-domain}.{entity}.{action} | {source-service} | {what this service does} |

### Database Schema

**Database Type**: [REQUIRES INPUT - PostgreSQL / MongoDB / DynamoDB / ___]
**Schema Name**: {service_name}

#### Tables/Collections

| Table | Primary Key | Description |
|-------|-------------|-------------|
| {table} | {pk} | {purpose} |

---

## Complexity Estimation

| Metric | Value | Implication |
|--------|-------|-------------|
| **Files** | {count} | {Small: <10, Medium: 10-30, Large: >30} |
| **Lines of Code** | {count} | Scope indicator |
| **Git Commits (6 mo)** | {count} | {High churn = active/complex area} |
| **Contributors** | {count} | {Many = knowledge spread, Few = specialist} |
| **External Dependencies** | {count} | Integration complexity |
| **Hotspot Score** | {Low/Medium/High} | Based on change frequency |

**Estimated Complexity**: {Low/Medium/High/Very High}

**Decomposition Risk**: {Low/Medium/High}
- {risk factor}: {explanation}

---

## User Scenarios & Testing

### US-{NN}.1 - {Specific Action} (Priority: P1)

As a {specific role}, I need to {specific action with detail} so that {specific outcome}.

**Why this priority**: {Extracted from code - is this a core path or edge case?}

**Source Evidence**:
- File: `{path/to/file.ext}:{line}` - {what this reveals}
- Test: `{test file}` - {what behavior is tested}

**Acceptance Scenarios**:

1. **Given** {specific precondition}, **When** {action}, **Then** {outcome}
2. **Given** {error condition}, **When** {trigger}, **Then** {error handling}
3. **Given** {edge case}, **When** {action}, **Then** {expected behavior}

**API Mapping**:
- Endpoint: `{METHOD} /api/v1/{path}`
- Event: `{domain}.{entity}.{action}`

---

## Requirements

### Functional Requirements

**{Capability Category}**

- **FR-{NN}.001**: Service MUST {specific capability}
  - Source: `{file}:{line}`
  - API: `{endpoint or event}`

- **FR-{NN}.002**: Service MUST {validation rule}
  - Source: `{file}:{line}`

### Non-Functional Requirements

**Performance**:
- **NFR-{NN}.001**: Response time P95 < {X}ms for {endpoint}
- **NFR-{NN}.002**: Throughput ≥ {X} requests/second

**Scalability**:
- **NFR-{NN}.003**: Service MUST scale horizontally
- **NFR-{NN}.004**: Database MUST support {X} concurrent connections

**Resilience**:
- **NFR-{NN}.005**: Service MUST handle downstream failures gracefully
- **NFR-{NN}.006**: Circuit breaker MUST open after {X} failures

---

## Key Entities

### {EntityName}

**Purpose**: {what it represents}
**Source**: `{file path}`
**Aggregate Root**: {YES/NO}

| Attribute | Type | Description | Constraints |
|-----------|------|-------------|-------------|
| id | UUID | Unique identifier | Required, immutable |
| {field} | {type} | {purpose} | {validation rules} |

**Invariants**:
- {business rule that must always be true}

**Domain Events**:
- `{Entity}Created` - when {trigger}
- `{Entity}Updated` - when {trigger}

---

## Integration Points

### Synchronous Dependencies

| Service | Endpoint | Purpose | Fallback |
|---------|----------|---------|----------|
| {service} | GET /api/v1/{resource} | {why called} | {cache/default/error} |

### Asynchronous Dependencies

| Service | Event | Purpose | Handling |
|---------|-------|---------|----------|
| {service} | {event.name} | {why consumed} | {idempotent handling} |

### Anti-Corruption Layer

| External System | ACL Component | Translation |
|-----------------|---------------|-------------|
| {legacy system} | {adapter class} | {external model} → {domain model} |

---

## Edge Cases and Error Handling

### Error Scenarios

| Scenario | Detection | Response | Recovery |
|----------|-----------|----------|----------|
| {downstream failure} | {how detected} | {error code, message} | {retry/circuit breaker} |
| {invalid input} | {validation} | 400 Bad Request | {client correction} |
| {not found} | {lookup} | 404 Not Found | {N/A} |
| {conflict} | {optimistic lock} | 409 Conflict | {client retry} |

### Eventual Consistency Scenarios

| Scenario | Window | Detection | Resolution |
|----------|--------|-----------|------------|
| {data sync lag} | {max time} | {how detected} | {compensation action} |

---

## Success Criteria

- **SC-{NN}.001**: Service deploys independently without coordinating with other services
- **SC-{NN}.002**: All API contracts pass consumer-driven contract tests
- **SC-{NN}.003**: Event schema validates against schema registry
- **SC-{NN}.004**: {Measurable outcome from tests/code}

---

## Migration Checklist

### Pre-Migration
- [ ] Bounded context boundaries validated
- [ ] Data ownership confirmed
- [ ] Integration contracts defined
- [ ] Consumer services identified

### Service Setup
- [ ] Repository created
- [ ] CI/CD pipeline configured
- [ ] Observability stack integrated
- [ ] API documentation generated

### Data Migration
- [ ] Schema created in new database
- [ ] Data migration scripts tested
- [ ] Sync mechanism configured
- [ ] Rollback procedure documented

### Integration
- [ ] Events publishing to broker
- [ ] Consumers updated to new events
- [ ] ACL adapters implemented
- [ ] Contract tests passing

### Cutover
- [ ] Traffic routing configured
- [ ] Feature flag enabled
- [ ] Monitoring dashboards ready
- [ ] Runbook documented
