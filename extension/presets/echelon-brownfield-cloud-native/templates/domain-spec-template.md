# Specification: {Domain Name}

**Domain**: {NN}-{domain-name}
**Created**: {DATE}
**Status**: Draft (reverse-engineered)
**Dependencies**: {list of prerequisite domain numbers}
**Preset**: revenge-cloud-native

---

## Overview

{2-3 sentences describing this domain's purpose and scope}

**Source Files Analyzed**: {list of key files}

---

## Cloud Migration Assessment

### 7R Recommendation

**Recommendation**: [REQUIRES INPUT]

| Option | Fit | Rationale |
|--------|-----|-----------|
| Retain | {YES/NO} | {why or why not} |
| Retire | {YES/NO} | {why or why not} |
| Rehost | {YES/NO} | {why or why not} |
| Replatform | {YES/NO} | {why or why not} |
| Refactor | {YES/NO} | {why or why not} |
| Rebuild | {YES/NO} | {why or why not} |
| Replace | {YES/NO} | {why or why not} |

### 12-Factor Compliance (This Domain)

| Factor | Current | Target | Work Required |
|--------|---------|--------|---------------|
| Config | {state} | Env vars | {work} |
| Backing Services | {state} | Attached | {work} |
| Statelessness | {state} | Stateless | {work} |
| Logs | {state} | stdout | {work} |
| Disposability | {state} | Fast start/stop | {work} |

---

## Container Specification

### Container Image

**Base Image**: [REQUIRES INPUT - e.g., python:3.11-slim, node:20-alpine]
**Multi-stage Build**: {YES/NO}
**Target Size**: {< X MB}

### Dockerfile Outline

```dockerfile
# Build stage
FROM {base-image} AS builder
# Install dependencies
# Build application

# Runtime stage
FROM {runtime-image}
# Copy artifacts
# Set non-root user
# Configure health check
# Set entrypoint
```

### Resource Requirements

| Resource | Request | Limit | Notes |
|----------|---------|-------|-------|
| CPU | {100m} | {500m} | {based on profiling} |
| Memory | {128Mi} | {512Mi} | {based on profiling} |
| Storage | {ephemeral} | {X Gi} | {if needed} |

### Health Checks

| Check | Endpoint | Interval | Timeout |
|-------|----------|----------|---------|
| Liveness | /health/live | 30s | 5s |
| Readiness | /health/ready | 10s | 5s |
| Startup | /health/startup | 5s | 60s |

---

## Cloud Service Mapping

### Compute

| Current | Target Cloud Service | Notes |
|---------|---------------------|-------|
| {VM/bare metal} | {ECS/EKS/Lambda/etc} | {rationale} |

### Data Stores

| Current | Target Cloud Service | Migration |
|---------|---------------------|-----------|
| {database} | {RDS/DynamoDB/etc} | {approach} |
| {cache} | {ElastiCache/etc} | {approach} |
| {file storage} | {S3/EFS/etc} | {approach} |

### Messaging

| Current | Target Cloud Service | Migration |
|---------|---------------------|-----------|
| {queue/broker} | {SQS/SNS/EventBridge} | {approach} |

### External Dependencies

| Current | Target | Connectivity |
|---------|--------|--------------|
| {service} | {cloud or keep} | {VPN/PrivateLink/Internet} |

---

## Complexity Estimation

| Metric | Value | Cloud Impact |
|--------|-------|--------------|
| **Files** | {count} | {container complexity} |
| **Lines of Code** | {count} | {build time} |
| **External Dependencies** | {count} | {connectivity setup} |
| **State** | {stateless/stateful} | {migration complexity} |
| **Config Files** | {count} | {externalization work} |

**Estimated Complexity**: {Low/Medium/High/Very High}

**Cloud Migration Risk**: {Low/Medium/High}
- {risk factor}: {explanation}

---

## User Scenarios & Testing

### US-{NN}.1 - {Specific Action} (Priority: P1)

As a {specific role}, I need to {specific action with detail} so that {specific outcome}.

**Source Evidence**:
- File: `{path/to/file.ext}:{line}`

**Acceptance Scenarios**:

1. **Given** {precondition}, **When** {action}, **Then** {outcome}
2. **Given** {error condition}, **When** {trigger}, **Then** {error handling}

**Cloud Considerations**:
- Latency: {expected change from cloud deployment}
- Availability: {target availability}
- Scaling: {auto-scale trigger}

---

## Requirements

### Functional Requirements

- **FR-{NN}.001**: Service MUST {specific capability}
  - Source: `{file}:{line}`
  - Cloud impact: {none/adaptation needed}

### Non-Functional Requirements

**Performance (Cloud-Adjusted)**:
- **NFR-{NN}.001**: Cold start time < {X}s
- **NFR-{NN}.002**: Response time P95 < {X}ms (accounting for cloud networking)

**Scalability**:
- **NFR-{NN}.003**: Auto-scale from {min} to {max} instances
- **NFR-{NN}.004**: Scale up when CPU > {X}% or requests > {Y}/s

**Availability**:
- **NFR-{NN}.005**: Target availability {99.9%}
- **NFR-{NN}.006**: Multi-AZ deployment for high availability

**Resilience**:
- **NFR-{NN}.007**: Handle AZ failure gracefully
- **NFR-{NN}.008**: Graceful degradation when dependencies unavailable

---

## Key Entities

### {EntityName}

**Purpose**: {what it represents}
**Source**: `{file path}`
**Cloud Storage**: [REQUIRES INPUT - RDS/DynamoDB/S3/etc]

| Attribute | Type | Description | Constraints |
|-----------|------|-------------|-------------|
| id | UUID | Unique identifier | Required |
| {field} | {type} | {purpose} | {validation} |

---

## Configuration Requirements

### Environment Variables

| Variable | Description | Example | Secret |
|----------|-------------|---------|--------|
| DATABASE_URL | Database connection | postgres://... | YES |
| LOG_LEVEL | Logging verbosity | INFO | NO |
| {VAR_NAME} | {description} | {example} | YES/NO |

### Secrets

| Secret | Source | Rotation |
|--------|--------|----------|
| DB_PASSWORD | Secrets Manager | 30 days |
| API_KEY | Secrets Manager | 90 days |

---

## Integration Points

### Internal Services

| Service | Protocol | Cloud Connectivity |
|---------|----------|-------------------|
| {service} | REST/gRPC | Service discovery / ALB |

### External Services

| Service | Protocol | Cloud Connectivity |
|---------|----------|-------------------|
| {external} | HTTPS | NAT Gateway / VPN |

---

## Edge Cases and Error Handling

### Cloud-Specific Scenarios

| Scenario | Detection | Response |
|----------|-----------|----------|
| Instance termination | SIGTERM | Graceful shutdown, drain connections |
| AZ failure | Health check failure | Traffic routes to healthy AZ |
| Rate limiting (cloud service) | 429 response | Exponential backoff |
| Spot instance interruption | 2-min warning | Checkpoint and migrate |

---

## Success Criteria

- **SC-{NN}.001**: Container starts in < {X}s
- **SC-{NN}.002**: Passes 12-factor compliance check
- **SC-{NN}.003**: Auto-scales under load test
- **SC-{NN}.004**: Zero downtime deployment verified
- **SC-{NN}.005**: Logs appear in centralized logging within {X}s

---

## Migration Checklist

### Containerization
- [ ] Dockerfile created and optimized
- [ ] Multi-stage build implemented
- [ ] Non-root user configured
- [ ] Health checks implemented
- [ ] Image scanned for vulnerabilities

### Configuration
- [ ] All config externalized to env vars
- [ ] Secrets moved to secrets manager
- [ ] Config validated at startup

### Cloud Services
- [ ] Database migrated/provisioned
- [ ] Storage migrated to object storage
- [ ] Message queues provisioned
- [ ] IAM roles configured

### Observability
- [ ] Logs to stdout in JSON format
- [ ] Metrics endpoint exposed
- [ ] Tracing instrumented
- [ ] Dashboards created
- [ ] Alerts configured

### Networking
- [ ] Security groups configured
- [ ] Load balancer configured
- [ ] DNS/service discovery set up
- [ ] TLS certificates provisioned

### Deployment
- [ ] CI/CD pipeline configured
- [ ] IaC for all resources
- [ ] Auto-scaling policies set
- [ ] Rollback procedure tested
