# Gap Analysis: {Project Name}

**Generated**: {DATE}
**Related**: [constitution.md](constitution.md)
**Preset**: revenge-compliance
**Applicable Regulations**: {GDPR / HIPAA / SOC 2 / PCI-DSS}

---

## 1. Regulatory Compliance Gaps

### GDPR Compliance (if applicable)

| Requirement | Article | Current | Target | Gap | Priority |
|-------------|---------|---------|--------|-----|----------|
| Lawful basis documented | Art. 6 | {state} | Documented | {gap} | P1 |
| Consent management | Art. 7 | {state} | Granular consent | {gap} | P1 |
| Privacy notice | Art. 13-14 | {state} | Comprehensive | {gap} | P1 |
| Data subject rights | Art. 15-22 | {state} | Automated | {gap} | P1 |
| Data protection by design | Art. 25 | {state} | Embedded | {gap} | P2 |
| Records of processing | Art. 30 | {state} | Maintained | {gap} | P2 |
| Security measures | Art. 32 | {state} | Appropriate | {gap} | P1 |
| Breach notification | Art. 33-34 | {state} | 72hr capable | {gap} | P1 |
| DPO appointment | Art. 37 | {state} | If required | {gap} | P2 |
| International transfers | Art. 44-49 | {state} | Safeguards | {gap} | P1 |

### HIPAA Compliance (if applicable)

| Requirement | Section | Current | Target | Gap | Priority |
|-------------|---------|---------|--------|-----|----------|
| Risk analysis | §164.308(a)(1) | {state} | Documented | {gap} | P1 |
| Access controls | §164.312(a) | {state} | Implemented | {gap} | P1 |
| Audit controls | §164.312(b) | {state} | Comprehensive | {gap} | P1 |
| Encryption | §164.312(e) | {state} | At rest + transit | {gap} | P1 |
| BAAs with vendors | §164.314 | {state} | All vendors | {gap} | P1 |
| Breach notification | §164.400 | {state} | 60-day capable | {gap} | P1 |
| Training | §164.308(a)(5) | {state} | Annual | {gap} | P2 |

### SOC 2 Compliance (if applicable)

| Criterion | Category | Current | Target | Gap | Priority |
|-----------|----------|---------|--------|-----|----------|
| Access controls | CC6 | {state} | Role-based | {gap} | P1 |
| System monitoring | CC7 | {state} | Continuous | {gap} | P1 |
| Change management | CC8 | {state} | Controlled | {gap} | P1 |
| Risk management | CC3 | {state} | Documented | {gap} | P2 |
| Vendor management | CC9 | {state} | Assessed | {gap} | P2 |

---

## 2. Technical Control Gaps

### Data Protection Controls

| Control | Current | Target | Gap | Effort |
|---------|---------|--------|-----|--------|
| Encryption at rest | {state} | AES-256 all sensitive | {gap} | {S/M/L} |
| Encryption in transit | {state} | TLS 1.2+ all connections | {gap} | {S/M/L} |
| Key management | {state} | HSM/KMS | {gap} | {S/M/L} |
| Data masking | {state} | PII masked in non-prod | {gap} | {S/M/L} |
| Tokenization | {state} | Sensitive data tokenized | {gap} | {S/M/L} |

### Access Control Gaps

| Control | Current | Target | Gap | Effort |
|---------|---------|--------|-----|--------|
| Authentication | {state} | MFA for all users | {gap} | {S/M/L} |
| Authorization | {state} | RBAC/ABAC | {gap} | {S/M/L} |
| Session management | {state} | Timeout, secure tokens | {gap} | {S/M/L} |
| Privileged access | {state} | Just-in-time, logged | {gap} | {S/M/L} |
| Service accounts | {state} | Least privilege | {gap} | {S/M/L} |

### Audit & Monitoring Gaps

| Control | Current | Target | Gap | Effort |
|---------|---------|--------|-----|--------|
| Access logging | {state} | All data access logged | {gap} | {S/M/L} |
| Log immutability | {state} | Write-once storage | {gap} | {S/M/L} |
| Log retention | {state} | {X} years | {gap} | {S/M/L} |
| Real-time alerting | {state} | Security events | {gap} | {S/M/L} |
| Log analysis | {state} | SIEM integration | {gap} | {S/M/L} |

---

## 3. Process & Documentation Gaps

### Policies and Procedures

| Document | Current | Target | Gap | Owner |
|----------|---------|--------|-----|-------|
| Information security policy | {state} | Approved, current | {gap} | {owner} |
| Access control policy | {state} | Approved, current | {gap} | {owner} |
| Data classification policy | {state} | Approved, current | {gap} | {owner} |
| Incident response plan | {state} | Tested, current | {gap} | {owner} |
| Business continuity plan | {state} | Tested, current | {gap} | {owner} |
| Privacy notice | {state} | Compliant, current | {gap} | {owner} |

### Operational Processes

| Process | Current | Target | Gap | Owner |
|---------|---------|--------|-----|-------|
| Access provisioning | {state} | Documented, enforced | {gap} | {owner} |
| Access review | {state} | Quarterly | {gap} | {owner} |
| Vulnerability management | {state} | Continuous | {gap} | {owner} |
| Patch management | {state} | SLA-based | {gap} | {owner} |
| Incident response | {state} | Tested | {gap} | {owner} |
| Change management | {state} | Documented | {gap} | {owner} |

---

## 4. Third-Party Gaps

### Vendor Agreements

| Vendor | Data Shared | Agreement | Gap | Priority |
|--------|-------------|-----------|-----|----------|
| {vendor} | {data types} | {DPA/BAA/None} | {gap} | P1/P2/P3 |

### Vendor Security

| Vendor | Assessment | Last Review | Gap | Action |
|--------|------------|-------------|-----|--------|
| {vendor} | {SOC 2/ISO 27001/None} | {date} | {gap} | {action} |

---

## 5. Skills and Training Gaps

| Skill Area | Current | Required | Gap | Training Plan |
|------------|---------|----------|-----|---------------|
| Data protection awareness | {state} | All staff | {gap} | {plan} |
| Security best practices | {state} | All staff | {gap} | {plan} |
| Incident response | {state} | Response team | {gap} | {plan} |
| Compliance requirements | {state} | Key roles | {gap} | {plan} |
| Secure development | {state} | Developers | {gap} | {plan} |

---

## 6. Gap Closure Plan

### Priority Matrix

| Category | Critical | High | Medium | Low |
|----------|----------|------|--------|-----|
| Regulatory | {count} | {count} | {count} | {count} |
| Technical Controls | {count} | {count} | {count} | {count} |
| Process/Docs | {count} | {count} | {count} | {count} |
| Third-Party | {count} | {count} | {count} | {count} |
| Skills | {count} | {count} | {count} | {count} |

### Remediation Timeline

| Wave | Gaps Addressed | Deadline | Owner |
|------|----------------|----------|-------|
| Immediate | Critical regulatory gaps | {date} | {owner} |
| Pre-migration | Technical controls | {date} | {owner} |
| Migration | Process implementation | {date} | {owner} |
| Post-migration | Validation, training | {date} | {owner} |

---

## Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Compliance Officer | | | |
| Information Security | | | |
| Business Owner | | | |
