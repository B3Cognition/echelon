# Migration Constitution: {Project Name}

**Generated**: {DATE}
**Source System**: {legacy tech stack}
**Target Cloud**: [REQUIRES INPUT - AWS / Azure / GCP / Multi-cloud]
**Preset**: revenge-cloud-native

---

## Part 1: Legacy Analysis

### 1.1 Original Technology Stack

| Component | Technology | Version | Cloud Migration Impact |
|-----------|------------|---------|----------------------|
| Language  | {lang}     | {ver}   | {container-ready / needs work} |
| Framework | {framework}| {ver}   | {cloud-native / needs adaptation} |
| Database  | {db}       | {ver}   | {managed service available / custom} |
| Storage   | {storage}  | {ver}   | {object storage / block / file} |
| Messaging | {mq}       | {ver}   | {managed service / self-hosted} |

### 1.2 12-Factor App Assessment

Rate current compliance (1-5, where 5 = fully compliant):

| Factor | Score | Current State | Gap |
|--------|-------|---------------|-----|
| **I. Codebase** | {1-5} | {description} | {gap} |
| **II. Dependencies** | {1-5} | {description} | {gap} |
| **III. Config** | {1-5} | {description} | {gap} |
| **IV. Backing Services** | {1-5} | {description} | {gap} |
| **V. Build, Release, Run** | {1-5} | {description} | {gap} |
| **VI. Processes** | {1-5} | {description} | {gap} |
| **VII. Port Binding** | {1-5} | {description} | {gap} |
| **VIII. Concurrency** | {1-5} | {description} | {gap} |
| **IX. Disposability** | {1-5} | {description} | {gap} |
| **X. Dev/Prod Parity** | {1-5} | {description} | {gap} |
| **XI. Logs** | {1-5} | {description} | {gap} |
| **XII. Admin Processes** | {1-5} | {description} | {gap} |

**Total Score**: {sum}/60
**Cloud Readiness**: {Not Ready (<30) / Needs Work (30-45) / Ready (45+)}

### 1.3 Infrastructure Dependencies

| Dependency | Current | Cloud Equivalent | Migration Approach |
|------------|---------|------------------|-------------------|
| {component} | {on-prem tech} | {cloud service} | {lift-shift / replace / refactor} |

### 1.4 Problems Identified

#### Anti-Patterns for Cloud

| Anti-Pattern | Location | Impact | Remediation |
|--------------|----------|--------|-------------|
| Hardcoded IPs/paths | {files} | Breaks in cloud | Externalize config |
| Local file storage | {files} | Stateful containers | Object storage |
| Sticky sessions | {code} | No horizontal scale | Stateless + cache |
| Long-running processes | {code} | No graceful shutdown | Add signal handling |
| Embedded secrets | {files} | Security risk | Secrets manager |

### 1.5 Lessons Learned

**Preserve**: {patterns that work well for cloud}

**Avoid**: {anti-patterns to eliminate}

**Improve**: {areas that block cloud-native operation}

---

## Part 2: Cloud-Native Target Constitution

### 2.1 Cloud Platform

[REQUIRES INPUT - Select target platform]

**Primary Cloud**:
- [ ] AWS
- [ ] Azure
- [ ] GCP
- [ ] Other: ___

**Multi-Cloud Strategy**:
- [ ] Single cloud (all-in)
- [ ] Primary + DR in secondary
- [ ] Cloud-agnostic (portable)

### 2.2 12-Factor Compliance Targets

| Factor | Target | Implementation |
|--------|--------|----------------|
| **I. Codebase** | Single repo per service | Git + CI/CD |
| **II. Dependencies** | Explicitly declared | Package manager + lock file |
| **III. Config** | Environment variables | {ConfigMap / Secrets Manager / Parameter Store} |
| **IV. Backing Services** | Attached resources | Connection strings from config |
| **V. Build, Release, Run** | Strict separation | {CI/CD pipeline} |
| **VI. Processes** | Stateless | External session store |
| **VII. Port Binding** | Self-contained | Embedded server |
| **VIII. Concurrency** | Process model | Horizontal scaling |
| **IX. Disposability** | Fast startup/shutdown | Signal handling, health checks |
| **X. Dev/Prod Parity** | Containers everywhere | Same image all environments |
| **XI. Logs** | Event streams | stdout → log aggregator |
| **XII. Admin Processes** | One-off tasks | Jobs / Lambda / Cloud Run |

### 2.3 Target Technology Stack

[REQUIRES INPUT - Define target stack]

| Component | Technology | Cloud Service | Rationale |
|-----------|------------|---------------|-----------|
| Compute | Containers | {EKS/ECS/AKS/GKE} | ___ |
| Database | ___ | {RDS/Aurora/Cloud SQL} | ___ |
| Cache | ___ | {ElastiCache/MemoryDB} | ___ |
| Object Storage | ___ | {S3/Blob/GCS} | ___ |
| Message Queue | ___ | {SQS/SNS/EventBridge} | ___ |
| Secrets | ___ | {Secrets Manager/Vault} | ___ |
| Logging | ___ | {CloudWatch/Datadog} | ___ |
| Monitoring | ___ | {CloudWatch/Prometheus} | ___ |

### 2.4 Container Strategy

[REQUIRES INPUT - Select approach]

**Base Images**:
- [ ] Official language images (python:3.x, node:lts)
- [ ] Distroless images (security-hardened)
- [ ] Organization base images
- [ ] Cloud-provider optimized images

**Container Registry**:
- [ ] ECR / ACR / GCR (cloud-native)
- [ ] Docker Hub
- [ ] Self-hosted (Harbor/Nexus)

**Orchestration**:
- [ ] Kubernetes (EKS/AKS/GKE)
- [ ] Managed containers (ECS/Cloud Run/App Service)
- [ ] Serverless containers (Fargate/Cloud Run)

### 2.5 Infrastructure as Code

[REQUIRES INPUT - Select tools]

**IaC Tool**:
- [ ] Terraform (multi-cloud)
- [ ] CloudFormation (AWS)
- [ ] Pulumi
- [ ] CDK

**GitOps**:
- [ ] ArgoCD
- [ ] Flux
- [ ] None (CI/CD push)

### 2.6 Security Principles

**Identity & Access**:
- [ ] Cloud IAM for service identity
- [ ] OIDC federation for humans
- [ ] Service accounts per service
- [ ] Least privilege policies

**Network Security**:
- [ ] VPC isolation
- [ ] Security groups / NSGs
- [ ] Private subnets for data tier
- [ ] WAF for public endpoints

**Data Protection**:
- [ ] Encryption at rest (KMS)
- [ ] Encryption in transit (TLS)
- [ ] Secrets in secrets manager
- [ ] No credentials in code/images

### 2.7 Observability Stack

[REQUIRES INPUT - Select tools]

| Capability | Tool | Integration |
|------------|------|-------------|
| Logging | {CloudWatch/Datadog/ELK} | stdout → aggregator |
| Metrics | {CloudWatch/Prometheus/Datadog} | /metrics endpoint |
| Tracing | {X-Ray/Jaeger/Datadog} | OpenTelemetry SDK |
| Alerting | {CloudWatch/PagerDuty/OpsGenie} | SLO-based alerts |

### 2.8 Cost Management

**Tagging Strategy**:
```
Environment: dev/staging/prod
Team: {team-name}
Service: {service-name}
CostCenter: {cost-center}
```

**Cost Controls**:
- [ ] Budget alerts configured
- [ ] Right-sizing recommendations enabled
- [ ] Reserved/Spot instances for predictable workloads
- [ ] Auto-scaling with min/max limits

### 2.9 Quality Gates

Before any deployment to production:

- [ ] Container image scanned for vulnerabilities
- [ ] Infrastructure changes reviewed (terraform plan)
- [ ] All tests pass (unit, integration, contract)
- [ ] Performance baseline maintained
- [ ] Secrets rotated and not hardcoded
- [ ] Logging and monitoring configured
- [ ] Runbook documented

---

## Part 3: Migration Approach

### 3.1 Migration Pattern

[REQUIRES INPUT - Select approach]

- [ ] **Lift and Shift**: Containerize as-is, optimize later
- [ ] **Lift and Reshape**: Containerize with cloud service adoption
- [ ] **Re-architect**: Significant changes for cloud-native

### 3.2 Environment Strategy

| Environment | Purpose | Cloud Account | Parity |
|-------------|---------|---------------|--------|
| dev | Development | {account-id} | Full |
| staging | Pre-production | {account-id} | Full |
| prod | Production | {account-id} | Baseline |

### 3.3 Rollout Strategy

[REQUIRES INPUT - Select approach]

- [ ] **Big bang**: All traffic to cloud at once
- [ ] **Canary**: Gradual traffic shift (1% → 10% → 50% → 100%)
- [ ] **Blue-green**: Parallel environments, instant cutover
- [ ] **Strangler fig**: Feature-by-feature migration

---

## Approval

- [ ] 12-factor assessment reviewed
- [ ] Cloud platform approved
- [ ] Security requirements verified
- [ ] Cost estimates accepted
- [ ] Operations team prepared

**Approved by**: _______________
**Date**: _______________
