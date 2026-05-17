# ADR-002: Container and Orchestration Strategy

**Status**: Proposed
**Date**: {DATE}
**Deciders**: [REQUIRES INPUT]

## Context

We are containerizing applications for cloud deployment. We need to decide:
- Container runtime and base images
- Orchestration platform
- Deployment model (managed vs self-managed)
- Container registry

## Decision Drivers

- **Operational complexity**: Team capacity to manage infrastructure
- **Scalability requirements**: Auto-scaling needs
- **Cost**: Infrastructure and operational costs
- **Portability**: Ability to move between clouds/environments
- **Existing skills**: Team experience with container technologies

## Application Analysis

| Application | Language | State | Scaling Need | Startup Time |
|-------------|----------|-------|--------------|--------------|
| {app} | {lang} | Stateless/Stateful | {horizontal/vertical} | {seconds} |

## Considered Options

### Option 1: Managed Kubernetes (EKS/AKS/GKE)

**Pros**:
- Full Kubernetes API
- Portable between clouds
- Rich ecosystem (Helm, operators)
- Auto-scaling, self-healing

**Cons**:
- Steep learning curve
- Higher base cost
- Complex networking
- Requires cluster management

### Option 2: Managed Containers (ECS/Cloud Run/App Service)

**Pros**:
- Simpler than Kubernetes
- Lower operational overhead
- Pay-per-use (some options)
- Cloud-native integration

**Cons**:
- Less portable
- Limited customization
- Vendor-specific concepts

### Option 3: Serverless Containers (Fargate/Cloud Run)

**Pros**:
- No cluster management
- Pay only for execution
- Automatic scaling
- Simple deployment

**Cons**:
- Cold start latency
- Less control
- Cost at scale can be higher
- Limited networking options

### Option 4: Self-Managed Kubernetes

**Pros**:
- Full control
- Works anywhere
- No vendor lock-in

**Cons**:
- High operational burden
- Security responsibility
- Upgrade complexity
- Requires expertise

## Comparison Matrix

| Criteria | Managed K8s | Managed Container | Serverless | Self-Managed |
|----------|-------------|-------------------|------------|--------------|
| Portability | 5 | 2 | 3 | 5 |
| Simplicity | 2 | 4 | 5 | 1 |
| Scalability | 5 | 4 | 5 | 5 |
| Cost (small) | 2 | 4 | 5 | 3 |
| Cost (large) | 4 | 3 | 2 | 4 |
| Team skills | {score} | {score} | {score} | {score} |

## Decision

[REQUIRES INPUT - Select strategy]

### Container Runtime

**Selected**: {Docker/containerd}

### Base Images

**Strategy**:
- [ ] Official language images (e.g., python:3.11-slim)
- [ ] Distroless images (for production)
- [ ] Organization base images
- [ ] Cloud-optimized (e.g., AWS-optimized images)

### Orchestration Platform

**Selected**: {EKS/ECS/GKE/etc}

**Rationale**: {Why this platform}

### Container Registry

**Selected**: {ECR/GCR/ACR/Docker Hub/Harbor}

**Configuration**:
- Image scanning: Enabled
- Lifecycle policies: {retention rules}
- Cross-region replication: {if needed}

## Container Standards

### Dockerfile Requirements

```dockerfile
# Required patterns
FROM {base-image}

# Security: non-root user
RUN adduser -D appuser
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=3s \
  CMD curl -f http://localhost:8080/health || exit 1

# Metadata
LABEL maintainer="team@company.com"
LABEL version="1.0"
```

### Resource Limits

| Workload Type | CPU Request | CPU Limit | Memory Request | Memory Limit |
|---------------|-------------|-----------|----------------|--------------|
| Web service | 100m | 500m | 128Mi | 512Mi |
| API service | 200m | 1000m | 256Mi | 1Gi |
| Worker | 500m | 2000m | 512Mi | 2Gi |

### Image Size Targets

| Image Type | Target Size | Strategy |
|------------|-------------|----------|
| Production | < 200MB | Multi-stage, distroless |
| Development | < 500MB | Include dev tools |

## Consequences

### Positive

- {consequence}

### Negative

- {consequence}

### Risks

- **Risk**: Container image vulnerabilities
  - **Mitigation**: Automated scanning, regular base image updates

- **Risk**: Resource contention
  - **Mitigation**: Resource limits, pod disruption budgets

## Related

- [ADR-001: Cloud Provider](001-cloud-provider-template.md)
