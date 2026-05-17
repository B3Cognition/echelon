# Risk Assessment: {Project Name}

**Generated**: {DATE}
**Related**: [constitution.md](constitution.md)
**Preset**: revenge-compliance
**Applicable Regulations**: {GDPR / HIPAA / SOC 2 / PCI-DSS}

---

## Risk Severity Framework

### Impact Levels

| Level | Impact | Definition | Examples |
|-------|--------|------------|----------|
| 5 | Critical | Regulatory sanctions, significant fines, criminal liability | Data breach >10K records, PHI exposure |
| 4 | High | Major compliance failure, significant business impact | Audit failure, regulatory investigation |
| 3 | Medium | Notable compliance gap, moderate impact | Missing controls, documentation gaps |
| 2 | Low | Minor compliance deviation, limited impact | Training gaps, process inconsistency |
| 1 | Minimal | Negligible compliance impact | Administrative issues |

### Likelihood Levels

| Level | Probability | Definition |
|-------|-------------|------------|
| 5 | Almost Certain | >90% chance, has happened before |
| 4 | Likely | 60-90% chance, expected to occur |
| 3 | Possible | 30-60% chance, could occur |
| 2 | Unlikely | 10-30% chance, not expected |
| 1 | Rare | <10% chance, exceptional circumstances |

---

## Compliance Risk Inventory

### Data Protection Risks

| ID | Risk | Regulation | Likelihood | Impact | Score | Owner | Mitigation |
|----|------|------------|------------|--------|-------|-------|------------|
| DP1 | Unauthorized access to PII | GDPR Art. 32 | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | Access controls, monitoring |
| DP2 | Data breach notification failure | GDPR Art. 33 | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | Incident response plan |
| DP3 | Inadequate encryption | GDPR Art. 32 | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | Encryption standards |
| DP4 | Excessive data retention | GDPR Art. 5 | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | Retention automation |
| DP5 | Failure to honor subject rights | GDPR Art. 15-22 | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | Rights management system |

### Security Risks

| ID | Risk | Regulation | Likelihood | Impact | Score | Owner | Mitigation |
|----|------|------------|------------|--------|-------|-------|------------|
| S1 | Insufficient access control | SOC 2 CC6 | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | RBAC implementation |
| S2 | Missing audit trail | SOC 2 CC7 | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | Comprehensive logging |
| S3 | Unpatched vulnerabilities | SOC 2 CC7 | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | Vulnerability management |
| S4 | Weak authentication | SOC 2 CC6 | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | MFA implementation |

### Third-Party Risks

| ID | Risk | Regulation | Likelihood | Impact | Score | Owner | Mitigation |
|----|------|------------|------------|--------|-------|-------|------------|
| TP1 | Missing processor agreements | GDPR Art. 28 | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | DPA/BAA completion |
| TP2 | Inadequate vendor security | SOC 2 CC9 | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | Vendor assessments |
| TP3 | Unauthorized data sharing | GDPR Art. 6 | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | Data flow controls |

### Operational Risks

| ID | Risk | Regulation | Likelihood | Impact | Score | Owner | Mitigation |
|----|------|------------|------------|--------|-------|-------|------------|
| O1 | Inadequate backup/recovery | HIPAA §164.308 | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | DR testing |
| O2 | Insufficient staff training | HIPAA §164.308 | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | Training program |
| O3 | Missing documentation | SOC 2 CC1 | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | Documentation standards |

---

## Migration-Specific Risks

| ID | Risk | Phase | Likelihood | Impact | Score | Owner | Mitigation |
|----|------|-------|------------|--------|-------|-------|------------|
| M1 | Data loss during migration | Migration | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | Checksums, backups |
| M2 | Encryption gap during transfer | Migration | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | Encrypted transfer only |
| M3 | Access control gap | Cutover | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | Pre-migration access setup |
| M4 | Audit trail discontinuity | Cutover | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | Logging before cutover |
| M5 | Compliance validation failure | Post-migration | {1-5} | {1-5} | {L×I} | [REQUIRES INPUT] | Pre-launch audit |

---

## Risk Heat Map

```text
        Impact →
    L   1   2   3   4   5
    i 5 │   │   │   │   │   │
    k 4 │   │   │   │   │   │
    e 3 │   │   │   │   │   │
    l 2 │   │   │   │   │   │
    i 1 │   │   │   │   │   │
    h   └───┴───┴───┴───┴───┘
```

---

## Risk Response Plan

### Critical Risks (Score ≥ 20)

| Risk | Response | Owner | Timeline | Status |
|------|----------|-------|----------|--------|
| {risk} | {avoid/mitigate/transfer/accept} | {owner} | {date} | {status} |

### High Risks (Score 15-19)

| Risk | Response | Owner | Timeline | Status |
|------|----------|-------|----------|--------|
| {risk} | {response} | {owner} | {date} | {status} |

---

## Regulatory Penalties Reference

| Regulation | Maximum Penalty | Typical Enforcement |
|------------|-----------------|---------------------|
| GDPR | €20M or 4% global revenue | DPA investigation, fines |
| HIPAA | $1.5M per violation category | OCR investigation, CAP |
| SOC 2 | Customer loss, audit failure | Customer trust impact |
| PCI-DSS | $100K/month + card brand fines | Acquiring bank penalties |

---

## Monitoring Schedule

| Risk Category | Review Frequency | Method | Escalation |
|---------------|------------------|--------|------------|
| Data Protection | Monthly | Control testing | DPO |
| Security | Weekly | Automated scanning | CISO |
| Third-Party | Quarterly | Vendor questionnaire | Procurement |
| Migration | Daily during migration | Status checks | Project sponsor |

---

## Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Risk Owner | | | |
| Compliance Officer | | | |
| Executive Sponsor | | | |
