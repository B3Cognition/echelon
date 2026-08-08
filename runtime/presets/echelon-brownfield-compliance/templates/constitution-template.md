# Migration Constitution: {Project Name}

**Generated**: {DATE}
**Source System**: {legacy tech stack}
**Target System**: [REQUIRES INPUT]
**Preset**: echelon-brownfield-compliance
**Applicable Regulations**: [REQUIRES INPUT - GDPR / HIPAA / SOC 2 / PCI-DSS / Other]

---

## Part 1: Compliance Context

### 1.1 Regulatory Requirements

[REQUIRES INPUT - Select all applicable]

| Regulation | Applicable | Data Types Affected | Key Requirements |
|------------|------------|---------------------|------------------|
| GDPR | YES/NO | Personal data (EU residents) | Consent, right to erasure, DPO |
| HIPAA | YES/NO | PHI (Protected Health Information) | Encryption, access controls, BAA |
| SOC 2 | YES/NO | Customer data | Security, availability, confidentiality |
| PCI-DSS | YES/NO | Cardholder data | Encryption, network segmentation |
| CCPA | YES/NO | Personal data (CA residents) | Disclosure, opt-out |
| {Other} | YES/NO | {data types} | {requirements} |

### 1.2 Data Classification

| Classification | Definition | Examples | Handling Requirements |
|----------------|------------|----------|----------------------|
| **Public** | No restrictions | Marketing materials | None |
| **Internal** | Business use only | Policies, procedures | Access controls |
| **Confidential** | Restricted access | Customer data, financials | Encryption, audit logging |
| **Restricted** | Highly sensitive | PII, PHI, credentials | Encryption at rest/transit, strict access |

### 1.3 Current Data Inventory

| Data Type | Classification | Current Storage | Volume | Retention |
|-----------|----------------|-----------------|--------|-----------|
| {data type} | {classification} | {location} | {size} | {policy} |

---

## Part 2: Legacy Compliance Analysis

### 2.1 Current Compliance State

| Control Area | Current State | Gap | Risk Level |
|--------------|---------------|-----|------------|
| Data encryption at rest | {state} | {gap} | {HIGH/MED/LOW} |
| Data encryption in transit | {state} | {gap} | {HIGH/MED/LOW} |
| Access control | {state} | {gap} | {HIGH/MED/LOW} |
| Audit logging | {state} | {gap} | {HIGH/MED/LOW} |
| Data retention | {state} | {gap} | {HIGH/MED/LOW} |
| Data deletion | {state} | {gap} | {HIGH/MED/LOW} |
| Incident response | {state} | {gap} | {HIGH/MED/LOW} |
| Third-party risk | {state} | {gap} | {HIGH/MED/LOW} |

### 2.2 Current Security Controls

| Control | Implementation | Effectiveness | Migration Impact |
|---------|----------------|---------------|------------------|
| Authentication | {method} | {HIGH/MED/LOW} | {keep/replace/enhance} |
| Authorization | {method} | {HIGH/MED/LOW} | {keep/replace/enhance} |
| Encryption | {method} | {HIGH/MED/LOW} | {keep/replace/enhance} |
| Logging | {method} | {HIGH/MED/LOW} | {keep/replace/enhance} |
| Monitoring | {method} | {HIGH/MED/LOW} | {keep/replace/enhance} |

### 2.3 Known Compliance Issues

| Issue | Regulation | Severity | Current Mitigation |
|-------|------------|----------|-------------------|
| {issue} | {regulation} | {HIGH/MED/LOW} | {mitigation or none} |

---

## Part 3: Target Compliance Architecture

### 3.1 Data Protection Principles

[REQUIRES INPUT - Confirm or adjust]

**MUST** requirements:

1. **Data Minimization**: Collect and process only data necessary for stated purposes
2. **Purpose Limitation**: Use data only for specified, explicit purposes
3. **Storage Limitation**: Retain data only as long as necessary
4. **Accuracy**: Keep personal data accurate and up to date
5. **Integrity & Confidentiality**: Protect against unauthorized processing

### 3.2 Security Architecture

[REQUIRES INPUT - Define target architecture]

**Authentication & Identity**:
- [ ] Multi-factor authentication (MFA) for all users
- [ ] Service accounts with least privilege
- [ ] Identity provider integration (SSO)
- [ ] Session management with timeout

**Authorization**:
- [ ] Role-based access control (RBAC)
- [ ] Attribute-based access control (ABAC) for sensitive data
- [ ] Just-in-time access for privileged operations
- [ ] Regular access reviews

**Encryption**:
- [ ] At-rest encryption (AES-256) for all data stores
- [ ] In-transit encryption (TLS 1.2+) for all connections
- [ ] Key management system (KMS/HSM)
- [ ] Key rotation policy: {frequency}

**Network Security**:
- [ ] Network segmentation (data tier isolated)
- [ ] Web Application Firewall (WAF)
- [ ] DDoS protection
- [ ] Private endpoints for cloud services

### 3.3 Audit & Logging Requirements

| Event Type | Retention | Format | Storage |
|------------|-----------|--------|---------|
| Authentication events | {period} | JSON/Syslog | {location} |
| Authorization decisions | {period} | JSON | {location} |
| Data access | {period} | JSON | {location} |
| Data modification | {period} | JSON | {location} |
| Admin actions | {period} | JSON | {location} |
| System events | {period} | JSON | {location} |

**Audit Log Requirements**:
- Immutable (write-once)
- Tamper-evident
- Searchable
- Available for {X} years

### 3.4 Data Subject Rights (GDPR/CCPA)

| Right | Implementation | SLA |
|-------|----------------|-----|
| Access | Export user data in machine-readable format | {days} |
| Rectification | Update personal data upon request | {days} |
| Erasure | Delete personal data (right to be forgotten) | {days} |
| Portability | Export in standard format | {days} |
| Opt-out (CCPA) | Stop sale/sharing of personal information | {days} |

### 3.5 Third-Party Management

| Third Party | Data Shared | Agreement | Last Review |
|-------------|-------------|-----------|-------------|
| {vendor} | {data types} | DPA/BAA | {date} |

**Requirements**:
- [ ] Data Processing Agreements (DPA) with all processors
- [ ] Business Associate Agreements (BAA) for PHI
- [ ] Annual security assessments
- [ ] Incident notification within {hours}

### 3.6 Incident Response

**Classification**:

| Severity | Definition | Response Time | Notification |
|----------|------------|---------------|--------------|
| Critical | Data breach, system compromise | 15 min | Immediate |
| High | Potential breach, significant risk | 1 hour | Same day |
| Medium | Security event, limited impact | 4 hours | Next business day |
| Low | Minor event, no data impact | 24 hours | Weekly report |

**Breach Notification**:
- Supervisory authority: Within {72 hours} (GDPR)
- Affected individuals: Without undue delay
- Documentation: Incident report within {48 hours}

---

## Part 4: Migration Compliance Requirements

### 4.1 Data Migration Security

**Before Migration**:
- [ ] Data inventory and classification complete
- [ ] Encryption keys generated and secured
- [ ] Access controls defined
- [ ] Audit logging enabled

**During Migration**:
- [ ] Encrypted transfer channels only
- [ ] Data integrity verification (checksums)
- [ ] Access logs for all operations
- [ ] No intermediate storage without encryption

**After Migration**:
- [ ] Source data securely deleted
- [ ] Migration logs retained
- [ ] Access controls verified
- [ ] Compliance validation complete

### 4.2 Testing Requirements

| Test Type | Requirement | Frequency |
|-----------|-------------|-----------|
| Penetration testing | Required before go-live | Annual |
| Vulnerability scanning | All components | Weekly |
| Access control testing | All roles | Each release |
| Data protection testing | Encryption, masking | Each release |
| Backup/restore testing | Full recovery | Quarterly |

### 4.3 Documentation Requirements

| Document | Owner | Review Frequency |
|----------|-------|------------------|
| Data flow diagrams | {team} | Each change |
| Privacy impact assessment | {team} | Each change |
| Security architecture | {team} | Annual |
| Incident response plan | {team} | Annual |
| Business continuity plan | {team} | Annual |

---

## Part 5: Compliance Validation

### 5.1 Pre-Migration Checklist

- [ ] Data inventory complete and accurate
- [ ] Privacy impact assessment completed
- [ ] Security architecture reviewed
- [ ] Third-party agreements in place
- [ ] Incident response plan updated
- [ ] Staff trained on new procedures

### 5.2 Go-Live Checklist

- [ ] All encryption enabled
- [ ] Access controls verified
- [ ] Audit logging operational
- [ ] Monitoring and alerting configured
- [ ] Backup procedures tested
- [ ] Penetration test passed

### 5.3 Post-Migration Validation

- [ ] Compliance controls verified
- [ ] Source data securely deleted
- [ ] Documentation updated
- [ ] Audit trail complete
- [ ] Regulatory notification (if required)

---

## Approval

**Compliance Signoff Required From**:

- [ ] Data Protection Officer (if applicable)
- [ ] Information Security
- [ ] Legal/Compliance
- [ ] IT Operations
- [ ] Business Owner

**Approved by**: _______________
**Date**: _______________
