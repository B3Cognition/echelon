# Migration Strategy: {Project Name}

**Generated**: {DATE}
**Related**: [constitution.md](constitution.md)
**Target Cloud**: [REQUIRES INPUT]
**Preset**: revenge-cloud-native

---

## 1. Cloud Migration Assessment

### Current Infrastructure

| Component | Current | Location | Migration Complexity |
|-----------|---------|----------|---------------------|
| Compute | {VMs/bare metal} | {on-prem/colo} | {LOW/MEDIUM/HIGH} |
| Database | {type} | {on-prem/managed} | {LOW/MEDIUM/HIGH} |
| Storage | {type} | {on-prem/NAS} | {LOW/MEDIUM/HIGH} |
| Networking | {type} | {on-prem} | {LOW/MEDIUM/HIGH} |

### Cloud Readiness Score

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Application containerization readiness | {score} | {notes} |
| Data migration complexity | {score} | {notes} |
| Network/connectivity requirements | {score} | {notes} |
| Security/compliance requirements | {score} | {notes} |
| Team cloud expertise | {score} | {notes} |
| **Total** | {total}/25 | |

**Assessment**:
- Score ≥20: Ready for cloud migration
- Score 15-19: Some preparation needed
- Score <15: Significant groundwork required

---

## 2. 7R Analysis by Domain

### Domain Migration Recommendations

| Domain | Recommendation | Rationale | Target Service |
|--------|----------------|-----------|----------------|
| {domain} | **Rehost** | Quick win, low risk | EC2/VMs |
| {domain} | **Replatform** | Use managed DB | RDS + Containers |
| {domain} | **Refactor** | Cloud-native benefits | EKS/Lambda |
| {domain} | **Rebuild** | Legacy, needs rewrite | Serverless |
| {domain} | **Replace** | SaaS available | {SaaS name} |
| {domain} | **Retire** | No longer needed | N/A |
| {domain} | **Retain** | Not ready yet | Keep on-prem |

### 7R Decision Matrix

| Criteria | Rehost | Replatform | Refactor | Rebuild | Replace |
|----------|--------|------------|----------|---------|---------|
| Speed | Fast | Medium | Slow | Slow | Fast |
| Cost (initial) | Low | Medium | High | High | Medium |
| Cost (ongoing) | High | Medium | Low | Low | Variable |
| Risk | Low | Medium | High | High | Medium |
| Cloud benefits | Minimal | Moderate | Maximum | Maximum | Depends |

---

## 3. Target Cloud Architecture

### Architecture Overview

```text
┌─────────────────────────────────────────────────────────────────┐
│                         Internet                                 │
└─────────────────────────────┬───────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│                    [Cloud Provider]                              │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    CDN / WAF / API Gateway                 │  │
│  └─────────────────────────────┬─────────────────────────────┘  │
│                                │                                 │
│  ┌─────────────────────────────▼─────────────────────────────┐  │
│  │                    Load Balancer                           │  │
│  └────────────┬───────────────────────────────┬──────────────┘  │
│               │                               │                  │
│  ┌────────────▼────────────┐    ┌────────────▼────────────┐    │
│  │    Container Cluster     │    │    Container Cluster     │   │
│  │      (AZ-1)              │    │      (AZ-2)              │   │
│  └────────────┬────────────┘    └────────────┬────────────┘    │
│               │                               │                  │
│  ┌────────────▼───────────────────────────────▼────────────┐    │
│  │              Private Subnet (Data Tier)                  │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │    │
│  │  │   Database   │  │    Cache     │  │   Storage    │   │    │
│  │  │   (Multi-AZ) │  │  (Cluster)   │  │ (Replicated) │   │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘   │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### Service Mapping

| Current Component | Target Cloud Service | Rationale |
|-------------------|---------------------|-----------|
| App servers | {EKS/ECS/GKE/AKS} | {why} |
| Database | {RDS/Aurora/Cloud SQL} | {why} |
| Cache | {ElastiCache/Memorystore} | {why} |
| File storage | {S3/GCS/Blob} | {why} |
| Message queue | {SQS/SNS/Pub/Sub} | {why} |
| Cron jobs | {Lambda/Cloud Functions} | {why} |

---

## 4. Migration Waves

### Wave 0: Foundation (Weeks 1-4)

**Goal**: Establish cloud landing zone

**Tasks**:
- [ ] Cloud accounts/projects setup
- [ ] Networking (VPC, subnets, peering/VPN)
- [ ] IAM structure and policies
- [ ] CI/CD pipeline to cloud
- [ ] Container registry
- [ ] Observability stack
- [ ] IaC repository

**Exit Criteria**:
- [ ] Can deploy test container to cloud
- [ ] Connectivity to on-prem verified
- [ ] Logging and monitoring operational

### Wave 1: Quick Wins (Weeks 5-8)

**Domains**: {low-risk, high-value domains}

**Approach**: Rehost/Replatform

**Tasks**:
- [ ] Containerize applications
- [ ] Migrate databases (if applicable)
- [ ] Deploy to cloud
- [ ] Validate functionality
- [ ] Route traffic

**Exit Criteria**:
- [ ] Applications running in cloud
- [ ] Performance baseline established
- [ ] Rollback verified

### Wave 2: Core Migration (Weeks 9-16)

**Domains**: {core business domains}

**Approach**: Replatform/Refactor

**Tasks**:
- [ ] Adopt managed services
- [ ] Implement cloud-native patterns
- [ ] Migrate data
- [ ] Update integrations
- [ ] Performance optimization

**Exit Criteria**:
- [ ] Core domains cloud-native
- [ ] Data fully migrated
- [ ] SLOs met

### Wave 3: Optimization (Weeks 17-20)

**Domains**: {remaining domains}

**Tasks**:
- [ ] Complete remaining migrations
- [ ] Decommission on-prem
- [ ] Cost optimization
- [ ] Documentation

**Exit Criteria**:
- [ ] All workloads in cloud
- [ ] On-prem decommissioned
- [ ] Cost targets met

---

## 5. Data Migration Strategy

### Database Migration

| Database | Size | Approach | Downtime |
|----------|------|----------|----------|
| {db-name} | {GB} | {DMS/dump-restore/CDC} | {expected} |

**Migration Steps**:
1. Schema migration (create target)
2. Initial data load
3. Continuous replication (CDC)
4. Validation
5. Cutover (stop writes, final sync, switch)

### File Storage Migration

| Storage | Size | Approach | Duration |
|---------|------|----------|----------|
| {storage} | {TB} | {DataSync/Transfer/rsync} | {estimated} |

### Cutover Strategy

[REQUIRES INPUT - Select approach]

- [ ] **Big bang**: Stop source, migrate, start target
- [ ] **Dual write**: Write to both during transition
- [ ] **Shadow traffic**: Replicate reads, validate

---

## 6. Networking Strategy

### Connectivity

| Connection | Type | Bandwidth | Latency |
|------------|------|-----------|---------|
| On-prem ↔ Cloud | {VPN/Direct Connect} | {Gbps} | {ms} |
| Cloud ↔ SaaS | {Internet/PrivateLink} | {Gbps} | {ms} |

### DNS Migration

| Record | Current | Target | TTL Strategy |
|--------|---------|--------|--------------|
| {domain} | {on-prem IP} | {cloud LB} | Lower → migrate → restore |

---

## 7. Rollback Strategy

### Rollback Triggers

| Trigger | Threshold | Action |
|---------|-----------|--------|
| Error rate | > 5% | Automatic rollback |
| Latency | > 2x baseline | Alert + manual decision |
| Data inconsistency | Any | Immediate rollback |

### Rollback Procedure

1. Route traffic back to on-prem
2. Stop cloud instances
3. Verify on-prem healthy
4. Sync any cloud-written data back
5. Post-mortem and re-plan

---

## 8. Risk Mitigation

### Migration Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Data loss during migration | LOW | CRITICAL | Backups, validation |
| Extended downtime | MEDIUM | HIGH | Rehearsals, rollback ready |
| Performance degradation | MEDIUM | MEDIUM | Baseline, monitoring |
| Cost overrun | MEDIUM | MEDIUM | Budget alerts, right-sizing |
| Security exposure | LOW | CRITICAL | Security review, least privilege |

---

## 9. Success Metrics

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Availability | {current} | 99.9% | CloudWatch/Datadog |
| Latency P95 | {current} | {target} | APM |
| Deployment frequency | {current} | Daily capable | CI/CD metrics |
| Infrastructure cost | {current} | {target} | Cost explorer |
| Recovery time | {current} | < 1 hour | DR testing |
