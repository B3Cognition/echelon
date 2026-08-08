# Migration Strategy: {Project Name}

**Generated**: {DATE}
**Related**: [constitution.md](constitution.md)
**Preset**: echelon-brownfield-microservices

---

## 1. Decomposition Assessment

### Monolith Characteristics

| Characteristic | Current State | Impact on Decomposition |
|----------------|---------------|------------------------|
| Codebase size | {LOC} | {larger = more complex} |
| Database tables | {count} | {shared tables = harder} |
| Team size | {count} | {Conway's Law alignment} |
| Deployment frequency | {per week/month} | {coupling indicator} |
| Test coverage | {%} | {safety net for changes} |

### Decomposition Readiness Score

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Clear domain boundaries | {score} | {evidence} |
| Database separation feasibility | {score} | {foreign keys, transactions} |
| Team structure alignment | {score} | {team per service?} |
| Testing infrastructure | {score} | {CI/CD, contract tests} |
| Observability maturity | {score} | {logging, tracing} |
| **Total** | {total}/25 | |

**Readiness Assessment**:
- Score ≥20: Ready for aggressive decomposition
- Score 15-19: Phased decomposition recommended
- Score <15: Foundation work needed first

---

## 2. Service Decomposition Strategy

### 2.1 Domain Analysis Summary

| Domain | Bounded Context | Coupling Score | Decomposition Priority |
|--------|-----------------|----------------|----------------------|
| {domain} | {context} | {HIGH/MEDIUM/LOW} | P1/P2/P3 |

### 2.2 Decomposition Pattern

[REQUIRES INPUT - Select pattern]

#### Option A: Strangler Fig (Recommended for high coupling)

```text
┌─────────────────────────────────────────────────┐
│                  API Gateway                     │
└─────────────────────────────────────────────────┘
         │                           │
         ▼                           ▼
┌─────────────────┐         ┌─────────────────┐
│   New Service   │         │    Monolith     │
│   (extracted)   │         │  (shrinking)    │
└─────────────────┘         └─────────────────┘

Wave 1: Route /orders/* → new Order Service
Wave 2: Route /inventory/* → new Inventory Service
Wave N: Decommission monolith
```

**Pros**: Low risk, gradual migration, easy rollback
**Cons**: Longer timeline, facade complexity

#### Option B: Domain-First (Recommended for clear boundaries)

```text
Identify → Extract → Integrate → Validate → Deploy

1. Extract domain code to new repository
2. Set up database for service
3. Implement API/event contracts
4. Deploy alongside monolith
5. Route traffic to new service
```

**Pros**: Clean separation, aligned with DDD
**Cons**: Requires clear boundaries, database splitting complexity

#### Option C: Branch by Abstraction (Recommended for shared code)

```text
1. Create abstraction layer over shared code
2. Implement new service behind abstraction
3. Gradually shift traffic to new implementation
4. Remove old implementation
```

**Pros**: Continuous delivery, no big bang
**Cons**: Temporary complexity, discipline required

**Selected Pattern**: [REQUIRES INPUT]

### 2.3 Service Extraction Order

Based on domain coupling analysis:

```text
Wave 1: Foundation Services (low coupling, enable others)
├── {service-1}: {rationale}
└── {service-2}: {rationale}

Wave 2: Core Domain Services (business critical)
├── {service-3}: {rationale}
└── {service-4}: {rationale}

Wave 3: Supporting Services (can wait)
├── {service-5}: {rationale}
└── {service-6}: {rationale}

Wave 4: Monolith Retirement
└── Decommission remaining monolith components
```

---

## 3. Data Decomposition Strategy

### 3.1 Current Database Analysis

| Database | Tables | Services Using | Shared Tables |
|----------|--------|----------------|---------------|
| {db} | {count} | {list} | {count} |

### 3.2 Data Ownership Matrix

| Table/Entity | Owner Service | Consumers | Access Pattern |
|--------------|---------------|-----------|----------------|
| {table} | {service} | {list} | {sync API / async event / read replica} |

### 3.3 Database Split Strategy

[REQUIRES INPUT - Select per domain]

| Domain | Strategy | Implementation |
|--------|----------|----------------|
| {domain} | Database per service | New schema, data migration |
| {domain} | Schema per service | Shared DB, isolated schema |
| {domain} | Shared with ACL | Read through anti-corruption layer |

### 3.4 Data Synchronization

| Data Flow | Source | Target | Mechanism | Latency |
|-----------|--------|--------|-----------|---------|
| {entity} sync | {service A} | {service B} | {CDC/Events/API} | {ms/s/min} |

**Event Sourcing Candidates**:
- [ ] {domain} - {rationale for event sourcing}

---

## 4. Integration Strategy

### 4.1 Communication Patterns

| Pattern | Use Case | Implementation |
|---------|----------|----------------|
| Synchronous REST | Queries, user-facing | OpenAPI 3.0, versioned |
| Synchronous gRPC | Internal, high-perf | Protocol buffers |
| Async Events | Commands, notifications | Kafka/RabbitMQ |
| Saga | Distributed transactions | Choreography/Orchestration |

### 4.2 API Gateway Strategy

[REQUIRES INPUT - Select approach]

- [ ] **Single Gateway**: All traffic through one gateway
- [ ] **Backend for Frontend (BFF)**: Gateway per client type
- [ ] **Service Mesh**: Sidecar proxies (Istio/Linkerd)

### 4.3 Service Discovery

[REQUIRES INPUT - Select approach]

- [ ] **Client-side**: Services discover each other (Consul/Eureka)
- [ ] **Server-side**: Load balancer routes (AWS ALB/K8s Service)
- [ ] **DNS-based**: Service mesh DNS (CoreDNS)

---

## 5. Migration Waves

### Wave 1: Foundation (Weeks {X}-{Y})

**Services**: {list}

**Exit Criteria**:
- [ ] Services deployed and healthy
- [ ] API contracts validated
- [ ] Monitoring dashboards operational
- [ ] Runbooks documented

**Rollback Plan**: {approach}

### Wave 2: Core Features (Weeks {X}-{Y})

**Services**: {list}

**Dependencies**: Wave 1 complete

**Exit Criteria**:
- [ ] Core user journeys functional
- [ ] Performance baselines met
- [ ] Contract tests passing

**Rollback Plan**: {approach}

### Wave 3: Supporting Features (Weeks {X}-{Y})

**Services**: {list}

**Dependencies**: Wave 2 complete

**Exit Criteria**:
- [ ] All features migrated
- [ ] Monolith traffic ≤ 10%
- [ ] Data sync lag acceptable

**Rollback Plan**: {approach}

### Wave 4: Monolith Retirement (Weeks {X}-{Y})

**Actions**:
- [ ] Route all traffic to new services
- [ ] Disable monolith endpoints
- [ ] Archive monolith codebase
- [ ] Decommission infrastructure

**Exit Criteria**:
- [ ] Monolith fully decommissioned
- [ ] All data migrated
- [ ] Documentation updated

---

## 6. Risk Mitigation

### Distributed System Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Network partition | MEDIUM | HIGH | Circuit breakers, graceful degradation |
| Data inconsistency | HIGH | HIGH | Eventual consistency patterns, saga |
| Cascading failures | MEDIUM | HIGH | Bulkheads, timeouts, retry limits |
| Observability gaps | HIGH | MEDIUM | Distributed tracing, correlation IDs |
| API versioning conflicts | MEDIUM | MEDIUM | Consumer-driven contracts, deprecation policy |

### Decomposition-Specific Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Wrong service boundaries | MEDIUM | HIGH | Start with modular monolith, validate |
| Distributed monolith | HIGH | HIGH | Avoid sync calls, prefer events |
| Shared database coupling | HIGH | MEDIUM | Database per service mandate |
| Team cognitive load | MEDIUM | MEDIUM | Service ownership model, documentation |

---

## 7. Success Metrics

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Deployment frequency | {current} | {per service/day} | CI/CD metrics |
| Lead time for changes | {current} | {hours} | Commit to production |
| Mean time to recovery | {current} | {minutes} | Incident duration |
| Change failure rate | {current} | {<15%} | Failed deployments |
| Service independence | N/A | 100% | Deploy without coordination |
| Contract test coverage | N/A | {>80%} | Pact/other tool |

---

## 8. Team Organization

### Service Ownership

| Service | Owning Team | On-Call | Expertise |
|---------|-------------|---------|-----------|
| {service} | {team} | {rotation} | {skills needed} |

### Communication Patterns

- Service API changes: RFC process, deprecation notice
- Cross-team dependencies: Architecture review
- Incident response: On-call escalation path
