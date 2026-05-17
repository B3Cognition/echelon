# Migration Constitution: {Project Name}

**Generated**: {DATE}
**Source System**: {legacy tech stack}
**Target System**: [REQUIRES INPUT]
**Preset**: revenge-microservices

---

## Part 1: Legacy Analysis

### 1.1 Original Technology Stack

| Component | Technology | Version | Notes |
|-----------|------------|---------|-------|
| Language  | {lang}     | {ver}   | {notes} |
| Framework | {framework}| {ver}   | {notes} |
| Database  | {db}       | {ver}   | {notes} |
| UI        | {ui tech}  | {ver}   | {notes} |
| Build     | {build}    | {ver}   | {notes} |

### 1.2 Monolith Analysis

**Current Architecture**: {monolithic/modular-monolith/distributed-monolith}

**Coupling Assessment**:

| Coupling Type | Severity | Evidence |
|---------------|----------|----------|
| Database coupling | {HIGH/MEDIUM/LOW} | {shared tables, foreign keys across domains} |
| Code coupling | {HIGH/MEDIUM/LOW} | {shared libraries, circular dependencies} |
| Temporal coupling | {HIGH/MEDIUM/LOW} | {synchronous calls, batch dependencies} |
| Deployment coupling | {HIGH/MEDIUM/LOW} | {single deployable, shared release cycle} |

**Domain Boundaries Identified**:

| Domain | Cohesion | Coupling to Others | Decomposition Candidate |
|--------|----------|-------------------|------------------------|
| {domain} | {HIGH/MEDIUM/LOW} | {list of coupled domains} | {YES/NO/MAYBE} |

### 1.3 Problems Identified

#### Hotspots (Frequently Changed Files)

| File | Changes | Period | Likely Cause |
|------|---------|--------|--------------|
| {file} | {count} | {months} | {analysis} |

#### Scalability Bottlenecks

- {bottleneck}: {impact and current workaround}

#### Deployment Pain Points

- {pain point}: {frequency and impact}

### 1.4 Lessons Learned

**Preserve**: {good patterns to keep - e.g., domain logic, algorithms}

**Avoid**: {mistakes to not repeat - e.g., tight coupling, shared database}

**Improve**: {areas needing better approach - e.g., testing, observability}

---

## Part 2: Microservices Target Constitution

### 2.1 Service Design Principles

[REQUIRES INPUT - Select applicable principles]

**Bounded Context Alignment**:
- [ ] Each service owns one bounded context
- [ ] Shared kernel pattern for cross-cutting concerns
- [ ] Anti-corruption layers at integration boundaries

**Data Ownership**:
- [ ] Database per service (strong isolation)
- [ ] Shared database with schema separation (pragmatic)
- [ ] Event-driven data synchronization

**Communication Patterns**:
- [ ] Synchronous REST/gRPC for queries
- [ ] Asynchronous events for commands/notifications
- [ ] Saga pattern for distributed transactions
- [ ] API Gateway for external traffic

**Deployment Independence**:
- [ ] Independent deployment pipelines per service
- [ ] Semantic versioning for APIs
- [ ] Feature flags for gradual rollout

### 2.2 Technology Stack

[REQUIRES INPUT - Define target stack]

| Component | Technology | Version | Rationale |
|-----------|------------|---------|-----------|
| Service Framework | ___ | ___ | ___ |
| API Protocol | REST / gRPC / GraphQL | ___ | ___ |
| Message Broker | Kafka / RabbitMQ / SQS | ___ | ___ |
| Service Discovery | ___ | ___ | ___ |
| API Gateway | ___ | ___ | ___ |
| Container Runtime | Docker / containerd | ___ | ___ |
| Orchestration | Kubernetes / ECS / ___ | ___ | ___ |
| Database(s) | ___ | ___ | ___ |

### 2.3 Cross-Cutting Concerns

[REQUIRES INPUT - Define standards]

**Observability Stack**:
- Logging: {ELK / CloudWatch / Datadog / ___}
- Metrics: {Prometheus / CloudWatch / Datadog / ___}
- Tracing: {Jaeger / X-Ray / Datadog / ___}
- Correlation: {Request ID propagation standard}

**Security**:
- AuthN: {OAuth2 / OIDC / JWT / ___}
- AuthZ: {RBAC / ABAC / ___}
- Service-to-service: {mTLS / API keys / ___}
- Secrets management: {Vault / AWS Secrets Manager / ___}

**Resilience**:
- Circuit breakers: {Resilience4j / Hystrix / ___}
- Retries: {exponential backoff with jitter}
- Timeouts: {standard timeout policy}
- Bulkheads: {thread pool / connection pool isolation}

### 2.4 API Standards

[REQUIRES INPUT or use defaults]

**REST Conventions**:
- URL structure: `/{version}/{resource}/{id}`
- Pagination: `?page=X&size=Y` or cursor-based
- Error format: RFC 7807 Problem Details
- Versioning: URL path / header / content-type

**Event Standards**:
- Schema registry: {Confluent / AWS Glue / ___}
- Event format: CloudEvents / custom
- Naming: `{domain}.{entity}.{action}` (e.g., `orders.order.created`)

### 2.5 Service Boundaries

[REQUIRES INPUT - Confirm or adjust detected boundaries]

Based on domain analysis, proposed services:

| Service | Bounded Context | Dependencies | Database |
|---------|-----------------|--------------|----------|
| {service-name} | {context} | {list} | {type} |

### 2.6 Quality Gates

Before any PR can be merged:

- [ ] Unit test coverage ≥ {X}%
- [ ] Integration tests pass
- [ ] Contract tests pass (consumer-driven)
- [ ] API documentation updated (OpenAPI/AsyncAPI)
- [ ] No breaking API changes without version bump
- [ ] Security scan passes
- [ ] Performance budget maintained

---

## Part 3: Decomposition Strategy

### 3.1 Decomposition Approach

[REQUIRES INPUT - Select approach]

- [ ] **Strangler Fig**: Gradually extract services behind facade
- [ ] **Domain-First**: Extract by bounded context priority
- [ ] **Data-First**: Separate databases before code
- [ ] **Feature-First**: Extract by user-facing feature

### 3.2 Service Extraction Order

Based on coupling analysis and business priority:

| Wave | Services | Rationale |
|------|----------|-----------|
| Wave 1 | {services} | {why first - low coupling, high value} |
| Wave 2 | {services} | {dependencies on Wave 1} |
| Wave 3 | {services} | {remaining domains} |

### 3.3 Data Migration Approach

[REQUIRES INPUT - Select per domain]

| Domain | Approach | Sync Mechanism |
|--------|----------|----------------|
| {domain} | {database per service / shared schema / read replica} | {events / CDC / dual-write} |

---

## Approval

- [ ] Legacy analysis reviewed for accuracy
- [ ] Service boundaries validated by domain experts
- [ ] Technology stack approved by architecture team
- [ ] Decomposition order agreed by stakeholders

**Approved by**: _______________
**Date**: _______________
