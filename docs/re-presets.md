Analysis: revenge Extension Integration with Spec-Kit
Question 1: Should revenge use spec-kit's analyze/clarify workflows?
Current State:

Spec-Kit Command Purpose Human Required?
/speckit.analyze Cross-artifact consistency check (spec → plan → tasks) No (read-only)
/speckit.clarify Ask 5 targeted questions to reduce ambiguity Yes (interactive Q&A)
revenge Command Purpose Human Required?
analyze Extract data from code → analysis.json No
verify Check spec coverage against codebase No
expand Fill coverage gaps automatically No
Key Insight: The revenge extension is designed around "code is truth" - extracting specifications from code without human intervention during extraction. Spec-kit's clarify requires human input, which breaks that model.

Recommendations:

Use /speckit.analyze after replan + retasks

The spec-kit analyze command checks consistency across spec.md/plan.md/tasks.md. Since revenge generates all three artifacts per domain, this is a natural fit:

respecify → replan → retasks → /speckit.analyze (per domain)
This could be added as an optional hook in the extension manifest:

hooks:
  after_tasks:
    command: "speckit.analyze"
    optional: true
    prompt: "Run consistency analysis on generated artifacts?"
Create /speckit.revenge.validate (new command)

A revenge specific validation that applies analyze-style checks but resolves ambiguities by going back to code:

Detection Spec-Kit Analyze Action revenge Validate Action
Ambiguity Flag for human Search code for clarification
Underspecification Report gap Read deeper into source
Inconsistency Report conflict Check code for truth
Unresolvable N/A Flag as [REQUIRES INPUT]
This would run after respecify to improve spec quality before reconstitute.

Don't use /speckit.clarify directly

Clarify is inherently interactive. Instead, revenge should:

Auto-resolve what it can from code
Mark genuinely unresolvable items with [REQUIRES INPUT]
Let /speckit.revenge.retarget handle the human-input phase
Proposed Workflow Enhancement:

Current:
  analyze → respecify → verify ⟳ expand → reconstitute → retarget → replan → retasks

Enhanced:
  analyze → respecify → validate → verify ⟳ expand → reconstitute → retarget → replan → retasks → /speckit.analyze
                         ↑                                                                           ↑
                    NEW: auto-resolve                                                          Hook into spec-kit
                    ambiguities from code
Question 2: Should revenge add presets?
Current State:

Spec-kit presets override templates (spec-template.md, plan-template.md, etc.)
revenge generates its own artifacts (constitution.md, migration-strategy.md, risk-matrix.md, etc.)
Different migration scenarios have fundamentally different needs
Recommendation: Yes, add presets

Migration scenarios are diverse enough to warrant domain-specific templates:

Preset Primary Focus Key Additions
revenge-cloud-native Cloud migration 12-factor assessment, containerization checklist, cloud service mapping
revenge-microservices Decomposition DDD bounded contexts, API contracts, event storming templates
revenge-legacy-modernization In-place modernization Strangler fig detailed planning, co-existence patterns
revenge-data-intensive Data migration focus Schema evolution, ETL templates, data quality sections
revenge-compliance Regulated industries HIPAA/SOC2/GDPR checklists, audit trail requirements
What presets would provide:

Custom strategic artifact templates:

migration-strategy.md - Different sections per migration type
risk-matrix.md - Domain-specific risk categories
gap-analysis.md - Tailored gap categories
Custom domain spec templates:

Different user story formats
Additional sections (e.g., compliance mapping, data lineage)
Custom ADR templates:

Pre-populated decision drivers relevant to the domain
Example preset structure:

presets/revenge-cloud-native/
├── preset.yml
├── templates/
│   ├── migration-strategy-template.md    # Adds 12-factor assessment
│   ├── constitution-template.md          # Adds cloud principles section
│   ├── risk-matrix-template.md           # Cloud-specific risk categories
│   └── domain-spec-template.md           # Adds containerization checklist
└── adrs/
    └── 001-cloud-provider-template.md    # Pre-populated cloud ADR
Summary Table
Enhancement Value Effort Recommendation
Hook into /speckit.analyze after retasks High - catches consistency issues Low - just add hook Do it
Create /speckit.revenge.validate High - auto-resolves ambiguities Medium - new command Consider for v1.1
Add cloud-native preset High - common use case Medium Start here
Add compliance preset High - differentiator Medium Second priority
Add microservices preset Medium - specialized Medium Third priority
Would you like me to draft the implementation for any of these enhancements?
