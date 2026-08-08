# Gap Analysis: {Project Name}

**Generated**: {DATE}
**Related**: [constitution.md](constitution.md)
**Preset**: echelon-brownfield-cloud-native

---

## 1. 12-Factor Compliance Gaps

### Current vs Target Compliance

| Factor | Current | Gap | Remediation | Effort |
|--------|---------|-----|-------------|--------|
| **I. Codebase** | {state} | {gap description} | {action} | S/M/L |
| **II. Dependencies** | {state} | {gap description} | {action} | S/M/L |
| **III. Config** | {state} | {gap description} | {action} | S/M/L |
| **IV. Backing Services** | {state} | {gap description} | {action} | S/M/L |
| **V. Build, Release, Run** | {state} | {gap description} | {action} | S/M/L |
| **VI. Processes** | {state} | {gap description} | {action} | S/M/L |
| **VII. Port Binding** | {state} | {gap description} | {action} | S/M/L |
| **VIII. Concurrency** | {state} | {gap description} | {action} | S/M/L |
| **IX. Disposability** | {state} | {gap description} | {action} | S/M/L |
| **X. Dev/Prod Parity** | {state} | {gap description} | {action} | S/M/L |
| **XI. Logs** | {state} | {gap description} | {action} | S/M/L |
| **XII. Admin Processes** | {state} | {gap description} | {action} | S/M/L |

### Critical 12-Factor Violations

| Violation | Location | Impact | Priority |
|-----------|----------|--------|----------|
| Hardcoded config | {files} | Blocks containerization | P1 |
| Local file state | {files} | Breaks scaling | P1 |
| Synchronous init | {code} | Slow startup | P2 |
| Embedded secrets | {files} | Security risk | P1 |

---

## 2. Infrastructure Gaps

### Compute

| Gap | Current | Target | Action | Effort |
|-----|---------|--------|--------|--------|
| Containerization | None/partial | Full containerization | Dockerize all apps | M |
| Orchestration | None | Kubernetes/ECS | Platform setup | L |
| Auto-scaling | Manual | Policy-based | Configure HPA/target tracking | M |
| Multi-AZ | Single location | Multi-AZ | Architecture redesign | M |

### Networking

| Gap | Current | Target | Action | Effort |
|-----|---------|--------|--------|--------|
| VPC setup | N/A | Multi-tier VPC | IaC implementation | M |
| Load balancing | Hardware LB | Cloud LB (ALB/NLB) | Configuration | S |
| Service discovery | Hardcoded | Cloud DNS/mesh | Implementation | M |
| TLS termination | On-prem | Cloud LB/ACM | Certificate setup | S |
| Private connectivity | None | VPN/Direct Connect | Network setup | L |

### Data Services

| Gap | Current | Target | Action | Effort |
|-----|---------|--------|--------|--------|
| Database | Self-managed | Managed (RDS/etc) | Migration | M-L |
| Caching | Self-managed | Managed (ElastiCache) | Migration | S-M |
| Object storage | NAS/SAN | S3/GCS/Blob | Data migration | M |
| Message queues | Self-managed | Managed (SQS/SNS) | Migration | M |

### Security

| Gap | Current | Target | Action | Effort |
|-----|---------|--------|--------|--------|
| Identity | Local accounts | Cloud IAM + SSO | IAM setup | M |
| Secrets | Config files | Secrets Manager | Migration | M |
| Network security | Firewall | Security groups + WAF | Configuration | M |
| Encryption | Partial | At-rest + in-transit | Enable encryption | S |
| Vulnerability scanning | None/manual | Automated (ECR scan) | Pipeline integration | S |

---

## 3. Observability Gaps

### Current vs Target State

| Capability | Current | Target | Gap | Action |
|------------|---------|--------|-----|--------|
| Centralized logging | {state} | CloudWatch/ELK | {gap} | Log aggregation setup |
| Metrics collection | {state} | Prometheus/CloudWatch | {gap} | Instrumentation |
| Distributed tracing | {state} | X-Ray/Jaeger | {gap} | SDK integration |
| Alerting | {state} | CloudWatch Alarms | {gap} | Alert definition |
| Dashboards | {state} | Grafana/CloudWatch | {gap} | Dashboard creation |

### Missing Observability

| Missing | Impact | Priority | Implementation |
|---------|--------|----------|----------------|
| Container metrics | Can't right-size | P1 | cAdvisor/Container Insights |
| Request tracing | Can't debug latency | P2 | OpenTelemetry |
| Cost visibility | Budget overrun risk | P1 | Tagging + Cost Explorer |
| SLO monitoring | No reliability target | P2 | SLI definition + alerting |

---

## 4. CI/CD Gaps

### Pipeline Gaps

| Gap | Current | Target | Action | Effort |
|-----|---------|--------|--------|--------|
| Container build | None | Multi-stage Dockerfile | Create Dockerfiles | M |
| Image registry | None | ECR/GCR/ACR | Registry setup | S |
| Image scanning | None | Automated on push | Integrate scanner | S |
| IaC pipeline | None | Terraform in CI | Pipeline creation | M |
| GitOps | None | ArgoCD/Flux | Setup GitOps | M |
| Progressive delivery | None | Canary/blue-green | Implement strategy | M |

### Deployment Gaps

| Gap | Current | Target | Action |
|-----|---------|--------|--------|
| Rollback capability | Manual | Automated | Pipeline configuration |
| Feature flags | None | LaunchDarkly/etc | Integration |
| Environment parity | Different configs | Identical containers | Containerization |

---

## 5. Resilience Gaps

### Availability Gaps

| Gap | Current | Target | Action |
|-----|---------|--------|--------|
| Multi-AZ deployment | Single AZ | Multi-AZ | Architecture change |
| Health checks | None | Liveness + Readiness | Implementation |
| Graceful shutdown | Abrupt termination | SIGTERM handling | Code changes |
| Circuit breakers | None | Per external call | Library integration |

### Recovery Gaps

| Gap | Current | Target | Action |
|-----|---------|--------|--------|
| Backup strategy | {state} | Automated daily | Configuration |
| Point-in-time recovery | {state} | Enabled | Database config |
| DR plan | None/manual | Documented + tested | Documentation |
| RTO/RPO definition | Undefined | RTO: {X}h, RPO: {X}h | Define + validate |

---

## 6. Cost Optimization Gaps

### Current vs Cloud Projected

| Resource | Current Cost | Cloud Projected | Optimization |
|----------|--------------|-----------------|--------------|
| Compute | {cost} | {projected} | Right-sizing, spot/reserved |
| Database | {cost} | {projected} | Managed service, sizing |
| Storage | {cost} | {projected} | Tiering, lifecycle |
| Network | {cost} | {projected} | VPC endpoints, data transfer |

### Cost Controls Missing

| Control | Status | Target | Action |
|---------|--------|--------|--------|
| Budget alerts | Missing | All accounts | Configure budgets |
| Resource tagging | Missing | All resources | Tagging policy |
| Idle resource cleanup | Manual | Automated | Scripts/tools |
| Reserved capacity | None | Predictable workloads | RI/Savings Plans |

---

## 7. Skills Gaps

### Cloud Platform Skills

| Skill | Current Level | Required | Gap | Training |
|-------|---------------|----------|-----|----------|
| {Cloud} fundamentals | {1-5} | 4 | {delta} | {plan} |
| Container orchestration | {1-5} | 4 | {delta} | {plan} |
| IaC (Terraform/etc) | {1-5} | 4 | {delta} | {plan} |
| Cloud networking | {1-5} | 3 | {delta} | {plan} |
| Cloud security | {1-5} | 4 | {delta} | {plan} |

### Operational Skills

| Skill | Current Level | Required | Gap | Training |
|-------|---------------|----------|-----|----------|
| Kubernetes operations | {1-5} | {level} | {delta} | {plan} |
| Cloud monitoring | {1-5} | {level} | {delta} | {plan} |
| Incident response (cloud) | {1-5} | {level} | {delta} | {plan} |
| Cost management | {1-5} | {level} | {delta} | {plan} |

---

## 8. Gap Closure Timeline

### Priority Matrix

| Category | Critical | High | Medium | Low |
|----------|----------|------|--------|-----|
| 12-Factor | {count} | {count} | {count} | {count} |
| Infrastructure | {count} | {count} | {count} | {count} |
| Observability | {count} | {count} | {count} | {count} |
| CI/CD | {count} | {count} | {count} | {count} |
| Resilience | {count} | {count} | {count} | {count} |
| Skills | {count} | {count} | {count} | {count} |

### Wave Alignment

| Wave | Gaps Addressed | Exit Criteria |
|------|----------------|---------------|
| Wave 0 | Foundation (infra, CI/CD basics) | Can deploy to cloud |
| Wave 1 | 12-Factor critical, containerization | Apps containerized |
| Wave 2 | Data migration, observability | Data in cloud |
| Wave 3 | Optimization, remaining gaps | Fully cloud-native |
