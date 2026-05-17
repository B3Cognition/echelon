# Specification: {Domain Name}

**Domain**: {NN}-{domain-name}
**Created**: {DATE}
**Status**: Draft (reverse-engineered)
**Dependencies**: {list of prerequisite domain numbers}
**Preset**: echelon-brownfield-compliance
**Data Classification**: [REQUIRES INPUT - Public / Internal / Confidential / Restricted]

---

## Overview

{2-3 sentences describing this domain's purpose and scope}

**Source Files Analyzed**: {list of key files}

---

## Data Classification & Compliance

### Data Assets in This Domain

| Data Element | Classification | PII | PHI | Sensitive | Regulations |
|--------------|----------------|-----|-----|-----------|-------------|
| {field/table} | {level} | YES/NO | YES/NO | YES/NO | {GDPR, HIPAA, etc} |

### Personal Data Processing (GDPR/CCPA)

| Data | Purpose | Legal Basis | Retention | Subject Rights |
|------|---------|-------------|-----------|----------------|
| {data} | {purpose} | {consent/contract/legitimate interest} | {period} | {access/delete/port} |

### Data Flow

```text
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Data Source   │────▶│   This Domain   │────▶│  Data Consumer  │
│   {source}      │     │   Processing    │     │   {consumer}    │
│   {class}       │     │                 │     │   {class}       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌─────────────────┐
                        │   Storage       │
                        │   {location}    │
                        │   Encrypted: Y/N│
                        └─────────────────┘
```

### Third-Party Data Sharing

| Recipient | Data Shared | Purpose | Agreement |
|-----------|-------------|---------|-----------|
| {vendor} | {data types} | {purpose} | DPA/BAA |

---

## Compliance Requirements

### Applicable Controls

| Control | Requirement | Implementation | Status |
|---------|-------------|----------------|--------|
| Encryption at rest | {regulation} | {method} | {IMPLEMENTED/PENDING} |
| Encryption in transit | {regulation} | TLS 1.2+ | {IMPLEMENTED/PENDING} |
| Access logging | {regulation} | Audit trail | {IMPLEMENTED/PENDING} |
| Data minimization | GDPR Art. 5(1)(c) | {approach} | {IMPLEMENTED/PENDING} |
| Retention limits | {regulation} | {policy} | {IMPLEMENTED/PENDING} |

### Access Control Requirements

| Role | Access Level | Data Accessible | Justification |
|------|--------------|-----------------|---------------|
| {role} | Read/Write/Admin | {data types} | {business need} |

### Audit Requirements

| Event | Logged Fields | Retention |
|-------|---------------|-----------|
| Data access | user, timestamp, data_id, action | {period} |
| Data modification | user, timestamp, data_id, old_value, new_value | {period} |
| Data deletion | user, timestamp, data_id, reason | {period} |
| Access denied | user, timestamp, resource, reason | {period} |

---

## Complexity Estimation

| Metric | Value | Compliance Impact |
|--------|-------|-------------------|
| **Files** | {count} | {audit scope} |
| **PII Fields** | {count} | {subject rights scope} |
| **External Integrations** | {count} | {third-party risk} |
| **Data Volume** | {size} | {backup/recovery time} |

**Estimated Complexity**: {Low/Medium/High/Very High}

**Compliance Risk**: {Low/Medium/High}
- {risk factor}: {explanation}

---

## User Scenarios & Testing

### US-{NN}.1 - {Specific Action} (Priority: P1)

As a {specific role}, I need to {specific action with detail} so that {specific outcome}.

**Source Evidence**:
- File: `{path/to/file.ext}:{line}`

**Acceptance Scenarios**:

1. **Given** {precondition}, **When** {action}, **Then** {outcome}

**Compliance Considerations**:
- PII involved: YES/NO
- Consent required: YES/NO
- Audit log entry: {what to log}

---

## Requirements

### Functional Requirements

- **FR-{NN}.001**: System MUST {specific capability}
  - Source: `{file}:{line}`
  - Compliance: {relevant regulation/control}

### Non-Functional Requirements

**Security**:
- **NFR-{NN}.001**: All PII MUST be encrypted at rest using AES-256
- **NFR-{NN}.002**: All data in transit MUST use TLS 1.2 or higher
- **NFR-{NN}.003**: Access attempts MUST be logged with user, timestamp, and outcome

**Data Protection**:
- **NFR-{NN}.004**: Personal data MUST be deletable within {X} days of request
- **NFR-{NN}.005**: Data export MUST complete within {X} days of request
- **NFR-{NN}.006**: Data MUST be automatically deleted after {X} retention period

**Audit**:
- **NFR-{NN}.007**: Audit logs MUST be immutable and retained for {X} years
- **NFR-{NN}.008**: All data access MUST generate an audit event

---

## Key Entities

### {EntityName}

**Purpose**: {what it represents}
**Source**: `{file path}`
**Data Classification**: {classification level}
**Contains PII**: YES/NO

| Attribute | Type | PII | Sensitive | Encryption | Retention |
|-----------|------|-----|-----------|------------|-----------|
| id | UUID | NO | NO | N/A | Indefinite |
| {field} | {type} | YES/NO | YES/NO | {method/N/A} | {period} |

**Data Subject Rights**:
- Accessible: YES/NO
- Modifiable: YES/NO
- Deletable: YES/NO
- Portable: YES/NO

---

## Integration Points

### Internal Services

| Service | Data Exchanged | Classification | Encryption |
|---------|----------------|----------------|------------|
| {service} | {data types} | {level} | YES/NO |

### External Services

| Service | Data Exchanged | Agreement | Security |
|---------|----------------|-----------|----------|
| {vendor} | {data types} | DPA/BAA | {method} |

---

## Edge Cases and Error Handling

### Data Protection Scenarios

| Scenario | Handling | Compliance |
|----------|----------|------------|
| Data subject access request | Export to JSON | GDPR Art. 15 |
| Data deletion request | Cascade delete + anonymize | GDPR Art. 17 |
| Data breach detection | Incident workflow | GDPR Art. 33-34 |
| Consent withdrawal | Stop processing + delete | GDPR Art. 7 |

### Error Scenarios

| Error | Response | Logging |
|-------|----------|---------|
| Unauthorized access | 403 Forbidden | Log attempt |
| Invalid consent | Block operation | Log attempt |
| Encryption failure | Fail closed | Alert + log |

---

## Success Criteria

- **SC-{NN}.001**: All PII fields encrypted at rest
- **SC-{NN}.002**: Data access generates audit log within {X}ms
- **SC-{NN}.003**: Data deletion completes within SLA
- **SC-{NN}.004**: Penetration test passes with no critical findings
- **SC-{NN}.005**: Access controls match role definitions

---

## Compliance Checklist

### Pre-Migration
- [ ] Data inventory complete
- [ ] PII/PHI identified and classified
- [ ] Third-party agreements in place
- [ ] Privacy impact assessment completed

### Implementation
- [ ] Encryption implemented for all sensitive data
- [ ] Access controls implemented per role matrix
- [ ] Audit logging enabled for all access
- [ ] Data retention policies implemented

### Validation
- [ ] Security testing completed
- [ ] Access control testing passed
- [ ] Audit log review completed
- [ ] Compliance controls verified

### Documentation
- [ ] Data flow diagrams updated
- [ ] Privacy notice updated (if needed)
- [ ] Processing records updated
- [ ] Runbook documented
