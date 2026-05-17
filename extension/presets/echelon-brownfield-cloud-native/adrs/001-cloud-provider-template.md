# ADR-001: Cloud Provider Selection

**Status**: Proposed
**Date**: {DATE}
**Deciders**: [REQUIRES INPUT]

## Context

We are migrating from on-premises infrastructure to cloud. Selecting the right cloud provider is a foundational decision that affects:
- Available managed services
- Cost structure
- Team skills requirements
- Vendor lock-in level
- Compliance capabilities

## Decision Drivers

- **Existing expertise**: Team familiarity with cloud platforms
- **Service availability**: Required managed services in target regions
- **Cost model**: Pricing for expected usage patterns
- **Compliance**: Regulatory requirements (data residency, certifications)
- **Integration**: Connectivity with existing systems and SaaS
- **Strategic alignment**: Organization's cloud strategy

## Workload Analysis

| Workload Type | Count | Requirements |
|---------------|-------|--------------|
| Web applications | {count} | {requirements} |
| Batch processing | {count} | {requirements} |
| Data storage | {count} | {requirements} |
| ML/AI | {count} | {requirements} |

## Considered Options

### Option 1: AWS (Amazon Web Services)

**Pros**:
- Largest market share, mature services
- Broadest service portfolio
- Strong enterprise support
- Global presence

**Cons**:
- Complex pricing
- Steep learning curve
- Vendor lock-in risk

**Key Services for Migration**:
- Compute: EC2, ECS, EKS, Lambda
- Database: RDS, Aurora, DynamoDB
- Storage: S3, EBS, EFS
- Messaging: SQS, SNS, EventBridge

### Option 2: Microsoft Azure

**Pros**:
- Strong Microsoft/Enterprise integration
- Hybrid cloud capabilities
- Comprehensive compliance certifications
- Good developer tools

**Cons**:
- Some services less mature than AWS
- Naming/organization can be confusing

**Key Services for Migration**:
- Compute: VMs, AKS, App Service, Functions
- Database: Azure SQL, Cosmos DB
- Storage: Blob, Files
- Messaging: Service Bus, Event Hubs

### Option 3: Google Cloud Platform (GCP)

**Pros**:
- Strong Kubernetes (GKE is native)
- Best-in-class data/ML services
- Competitive pricing (sustained use)
- Modern, developer-friendly

**Cons**:
- Smaller market share
- Fewer regions
- Fewer enterprise features

**Key Services for Migration**:
- Compute: GCE, GKE, Cloud Run, Functions
- Database: Cloud SQL, Firestore, BigQuery
- Storage: Cloud Storage
- Messaging: Pub/Sub

### Option 4: Multi-Cloud

**Pros**:
- Avoid vendor lock-in
- Best-of-breed services
- DR/compliance flexibility

**Cons**:
- Highest complexity
- Skills spread thin
- Integration challenges
- Higher cost (no volume discounts)

## Comparison Matrix

| Criteria | AWS | Azure | GCP | Multi |
|----------|-----|-------|-----|-------|
| Service breadth | 5 | 4 | 4 | 5 |
| Kubernetes | 4 | 4 | 5 | 5 |
| Enterprise support | 5 | 5 | 3 | 3 |
| Pricing | 3 | 3 | 4 | 2 |
| Team skills | {score} | {score} | {score} | {score} |
| Compliance | {score} | {score} | {score} | {score} |

## Decision

[REQUIRES INPUT - Select provider]

**Selected Provider**: {Provider}

**Rationale**: {Why this provider best fits our needs}

**Multi-cloud Strategy** (if applicable):
- Primary: {provider} for {workloads}
- Secondary: {provider} for {workloads}

## Consequences

### Positive

- {consequence}

### Negative

- {consequence}

### Risks

- **Risk**: Vendor lock-in
  - **Mitigation**: Use containers, avoid proprietary services where practical

- **Risk**: Cost overrun
  - **Mitigation**: Budget alerts, reserved capacity, regular optimization

## Related

- [ADR-002: Container Strategy](002-container-strategy-template.md)
