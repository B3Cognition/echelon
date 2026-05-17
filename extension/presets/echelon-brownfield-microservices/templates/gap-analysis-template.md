# Gap Analysis: {Project Name}

**Generated**: {DATE}
**Related**: [constitution.md](constitution.md)
**Preset**: echelon-brownfield-microservices

---

## 1. Feature Parity Gaps

### Critical Features

| Feature | Legacy | Target Service | Gap | Priority |
|---------|--------|----------------|-----|----------|
| {feature} | Exists | {service-name} | {description} | P1/P2/P3 |

### Features to Deprecate

| Feature | Reason | Impact | Migration Path |
|---------|--------|--------|----------------|
| {feature} | {why removing} | {who affected} | {alternative} |

### New Capabilities (Microservices-Enabled)

| Capability | Business Value | Enabled By | Priority |
|------------|---------------|------------|----------|
| Independent scaling | Cost optimization | Service isolation | P1 |
| Faster deployments | Agility | Smaller deployables | P1 |
| Technology diversity | Best tool for job | Service autonomy | P2 |
| {capability} | {value} | {enabler} | P1/P2/P3 |

---

## 2. Distributed Systems Gaps

### Observability

| Component | Current | Target | Gap | Action |
|-----------|---------|--------|-----|--------|
| Distributed tracing | {none/partial} | Full trace propagation | {gap} | Implement OpenTelemetry |
| Correlation IDs | {none/partial} | Request ID in all logs | {gap} | Middleware implementation |
| Service dependency map | {none/partial} | Auto-generated map | {gap} | Service mesh or APM tool |
| Centralized logging | {current} | Structured JSON logs | {gap} | Log aggregation setup |
| Metrics aggregation | {current} | Per-service dashboards | {gap} | Prometheus/Grafana |
| Alerting | {current} | Service-level SLOs | {gap} | Alert manager config |

### Resilience Patterns

| Pattern | Current | Target | Gap | Action |
|---------|---------|--------|-----|--------|
| Circuit breakers | {none/partial} | All external calls | {gap} | Resilience4j/Hystrix |
| Retries with backoff | {none/partial} | Exponential + jitter | {gap} | HTTP client config |
| Timeouts | {none/partial} | All calls have timeout | {gap} | Client configuration |
| Bulkheads | {none} | Thread pool isolation | {gap} | Service design |
| Rate limiting | {none/partial} | API gateway + per-service | {gap} | Implementation needed |
| Graceful degradation | {none} | Fallback responses | {gap} | Handler implementation |

### Data Consistency

| Scenario | Current | Target | Gap | Action |
|----------|---------|--------|-----|--------|
| Cross-service transactions | {ACID in monolith} | Saga pattern | Distributed coordination | Implement saga orchestrator |
| Read-after-write | {immediate} | Eventual consistency | User experience | UI optimistic updates |
| Data synchronization | {none} | Event-driven sync | Real-time replication | CDC or event publishing |
| Conflict resolution | {DB locks} | Optimistic locking | Concurrent updates | Version vectors |

---

## 3. Infrastructure Gaps

### Container & Orchestration

| Component | Current | Target | Gap | Effort |
|-----------|---------|--------|-----|--------|
| Container runtime | {none/Docker} | {Docker/containerd} | {gap} | {S/M/L} |
| Container registry | {none/current} | {ECR/GCR/Harbor} | {gap} | {S/M/L} |
| Orchestration | {none/current} | {Kubernetes/ECS} | {gap} | {S/M/L} |
| Service mesh | {none} | {Istio/Linkerd/none} | {gap} | {S/M/L} |
| Secrets management | {env vars/files} | {Vault/Secrets Manager} | {gap} | {S/M/L} |

### Networking

| Component | Current | Target | Gap | Effort |
|-----------|---------|--------|-----|--------|
| Service discovery | {none/DNS} | {Consul/K8s DNS} | {gap} | {S/M/L} |
| Load balancing | {current} | {per-service LB} | {gap} | {S/M/L} |
| API gateway | {none/current} | {Kong/AWS API GW} | {gap} | {S/M/L} |
| Internal DNS | {current} | {service.namespace} | {gap} | {S/M/L} |
| mTLS | {none} | {service mesh/manual} | {gap} | {S/M/L} |

### Message Infrastructure

| Component | Current | Target | Gap | Effort |
|-----------|---------|--------|-----|--------|
| Message broker | {none/current} | {Kafka/RabbitMQ/SQS} | {gap} | {S/M/L} |
| Schema registry | {none} | {Confluent/Glue} | {gap} | {S/M/L} |
| Dead letter queues | {none} | Per-topic DLQ | {gap} | {S/M/L} |
| Event replay | {none} | Retention + replay | {gap} | {S/M/L} |

### CI/CD

| Component | Current | Target | Gap | Effort |
|-----------|---------|--------|-----|--------|
| Pipeline per service | {monorepo} | Independent pipelines | {gap} | {S/M/L} |
| Contract testing | {none} | Pact or similar | {gap} | {S/M/L} |
| Canary deployments | {none} | Progressive rollout | {gap} | {S/M/L} |
| Feature flags | {none/current} | Per-service flags | {gap} | {S/M/L} |
| Rollback automation | {manual} | Automatic on failure | {gap} | {S/M/L} |

---

## 4. API & Contract Gaps

### API Standards

| Standard | Current | Target | Gap | Action |
|----------|---------|--------|-----|--------|
| OpenAPI specs | {none/partial} | All REST APIs | {gap} | Spec generation |
| AsyncAPI specs | {none} | All event schemas | {gap} | Schema definitions |
| API versioning | {none/breaking} | Semantic versioning | {gap} | Version strategy |
| Error format | {inconsistent} | RFC 7807 | {gap} | Error handler |
| Pagination | {inconsistent} | Cursor-based standard | {gap} | API guidelines |

### Contract Testing

| Gap | Current | Target | Action |
|-----|---------|--------|--------|
| Consumer contracts | {none} | All service pairs | Pact implementation |
| Provider verification | {none} | CI pipeline check | Pipeline integration |
| Breaking change detection | {manual} | Automated CI check | Schema comparison |

---

## 5. Skills Gaps

### Distributed Systems Skills

| Skill | Current Level | Required Level | Gap | Training Plan |
|-------|---------------|----------------|-----|---------------|
| Event-driven architecture | {1-5} | {1-5} | {delta} | {plan} |
| Saga patterns | {1-5} | {1-5} | {delta} | {plan} |
| API design (REST/gRPC) | {1-5} | {1-5} | {delta} | {plan} |
| Message broker operations | {1-5} | {1-5} | {delta} | {plan} |
| Container orchestration | {1-5} | {1-5} | {delta} | {plan} |
| Observability tooling | {1-5} | {1-5} | {delta} | {plan} |
| Resilience patterns | {1-5} | {1-5} | {delta} | {plan} |

### Operational Skills

| Skill | Current Level | Required Level | Gap | Training Plan |
|-------|---------------|----------------|-----|---------------|
| Kubernetes operations | {1-5} | {1-5} | {delta} | {plan} |
| Service mesh management | {1-5} | {1-5} | {delta} | {plan} |
| Distributed debugging | {1-5} | {1-5} | {delta} | {plan} |
| Incident response (distributed) | {1-5} | {1-5} | {delta} | {plan} |

---

## 6. Organizational Gaps

### Team Structure

| Gap | Current | Target | Action |
|-----|---------|--------|--------|
| Service ownership | Shared ownership | Team per service | Reorganize teams |
| On-call rotation | {current} | Per-service rotation | On-call setup |
| Cross-team dependencies | High | Minimized | API contracts |
| Knowledge silos | {current} | Documented services | Runbooks, ADRs |

### Process Gaps

| Gap | Current | Target | Action |
|-----|---------|--------|--------|
| API change process | Ad-hoc | RFC + deprecation | Process definition |
| Incident escalation | {current} | Service-aware routing | Runbook updates |
| Release coordination | All services together | Independent releases | Pipeline changes |

---

## 7. Testing Gaps

| Testing Type | Current | Target | Gap | Priority |
|--------------|---------|--------|-----|----------|
| Unit tests | {coverage}% | ≥{X}% per service | {gap}% | P1 |
| Integration tests | {coverage}% | Service boundary tests | {gap} | P1 |
| Contract tests | {none} | All service pairs | Full coverage | P1 |
| E2E tests | {current} | Critical paths only | Reduce scope | P2 |
| Chaos engineering | {none} | Failure injection | New capability | P3 |
| Load tests | {current} | Per-service baseline | Individual services | P2 |

---

## 8. Gap Closure Plan

### Priority Matrix

| Gap Category | Critical | High | Medium | Low |
|--------------|----------|------|--------|-----|
| Distributed Systems | {count} | {count} | {count} | {count} |
| Infrastructure | {count} | {count} | {count} | {count} |
| API & Contracts | {count} | {count} | {count} | {count} |
| Skills | {count} | {count} | {count} | {count} |
| Organizational | {count} | {count} | {count} | {count} |
| Testing | {count} | {count} | {count} | {count} |

### Timeline

| Wave | Gaps Addressed | Exit Criteria |
|------|----------------|---------------|
| Foundation | Observability, CI/CD, Container infra | Services deployable |
| Wave 1 | Resilience patterns, Message infra | Core services resilient |
| Wave 2 | Contract testing, API standards | All contracts validated |
| Wave 3 | Skills training, Team structure | Teams self-sufficient |
