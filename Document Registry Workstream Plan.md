## Document Registry Service – Workstream Plan

### 1. Objectives
- Deliver the Document Registry Service described in the architecture narrative (Section 3.1/3.2).
- Enable deduplicated document ingestion, canonical metadata management, and reliable workflow triggering before MVP code freeze.

### 2. Timeline & Milestones
| Week | Milestone | Owner |
| --- | --- | --- |
| Week 3 | Finalize DB schema + migrations reviewed | Backend (Maria Lopez) |
| Week 4 | Service scaffolding + `POST /registry/documents` endpoint merged with unit tests | Backend (Maria Lopez) |
| Week 5 | Dedup logic + integration tests + `state` endpoint implemented | Backend (Samir Patel) |
| Week 6 | Observability metrics, runbook, and feature-flagged deployment in staging | Infra (Priya Raman) |
| Week 7 | Shadow-write validation complete, flip registry to source-of-truth, retire legacy dedup | Backend + Infra |

### 3. Work Breakdown
1. **DB Layer**
    - Draft SQL migration for `registry_documents` + audit tables.
    - Peer review + apply to dev/staging.
2. **Service Core**
    - FastAPI project bootstrap, CI pipeline setup (lint/test).
    - Shared schema module (Pydantic models) for API contracts.
3. **Dedup Components**
    - DOI + hash checks with fallback fuzzy matcher (Levenshtein ratio threshold 0.9 on normalized titles).
    - Concurrency tests simulating duplicate submissions.
4. **State Machine Hooks**
    - Transition validator, error taxonomy, and integration with Workflow Orchestrator via SQS publisher.
5. **Observability**
    - Prometheus metrics + log enrichment, dashboards in Grafana.
    - On-call runbook entry for registry anomalies.
6. **Rollout Tasks**
    - Feature flag management, shadow-write verification checklist, prod cutover plan.

### 4. Dependencies & Risks
- Requires secrets management (service tokens) from Platform team by Week 4.
- Workflow Orchestrator changes must be ready to consume new state events by Week 5.
- Risk: schema drift between registry and metadata DB; mitigation via nightly consistency job.

### 5. Tracking
- Jira epic `HG-REG-001` with stories for each milestone.
- Weekly check-in (Fridays) between Maria, Samir, Priya, and Alex to unblock issues.
