## HelioGraph RAG – Engineering & Infrastructure Readiness

This document captures the shared assumptions and commitments backing the MVP SLAs defined in the PRD.

---
### 1. Scope
- Document ingestion pipeline (upload/API import → searchable)
- RAG query service with provenance payloads
- Knowledge graph visualization (subgraphs ≤200 nodes)

---
### 2. Target SLAs (from PRD)
- Ingest turnaround: ≤10 min avg, ≤20 min P95 for 20-page PDFs
- RAG response latency: ≤8 s P95 for corpora up to 1k docs
- Graph render time: ≤3 s to interactive for ≤200-node subgraphs

---
### 3. Hardware & Deployment Profile (Phase 0 MVP)
| Component | Instance/Class | Key Specs | Notes |
| --- | --- | --- | --- |
| API Gateway + Registry | 2× c7g.large | 2 vCPU / 4 GiB RAM | Active/active behind ALB; auto-scale target 60% CPU |
| Workflow Workers | 4× g5.xlarge | 4 vCPU / 16 GiB RAM / 1× A10G | Hosts PDF parsing + embeddings; autoscale via SQS depth |
| Vector DB (Qdrant) | 1× m6i.xlarge | 4 vCPU / 16 GiB RAM / NVMe | 500k chunks capacity MVP |
| Graph DB (Neo4j) | 1× r6i.xlarge | 4 vCPU / 32 GiB RAM | HA later; daily snapshots to S3 |
| Object Store | S3 Standard | N/A | Lifecycle policy: IA after 30 days |

Local deployment target: single workstation w/ 12-core CPU, 64 GiB RAM, RTX 4090 or equivalent; enables offline demos with reduced throughput expectations.

---
### 4. Workload Assumptions
- Average document: 20 pages, 8k tokens, 5 MB PDF
- Batch ingest: up to 50 PDFs/day/user, concurrent uploads ≤5
- Query mix: 60% “summary”, 25% “compare”, 15% graph exploration
- Concurrency: 30 simultaneous chat sessions, 10 active ingest jobs

---
### 5. Validation Plan
1. **Synthetic Load Tests**
   - Replay 50-document ingest batch using recorded PDFs; measure stage-level timings and overall SLA adherence.
   - Use Locust/Grafana k6 to simulate 30 concurrent queries hitting `/api/query`.
2. **Real-User Beta**
   - Invite 3 researchers to ingest their corpora and log real timings.
   - Capture Grafana dashboards + trace exports for sign-off packet.

---
### 6. Mitigation & Contingency
- If ingest P95 >20 min: add two worker nodes and enable GPU sharing via MIG; throttle API imports per user.
- If RAG latency >8 s: increase vector DB cache size, pre-fetch graph expansions, evaluate smaller generation model (e.g., Mistral 7B).
- If graph render >3 s: cap initial node count to 150 and lazy-load neighbors, optimize serialization size.
- If hardware unavailable: fall back to on-prem GPU (A100) or temporarily relax SLA with stakeholder approval.

---
### 7. Ownership & Sign-off
- **Engineering Lead:** Alex Chen – accountable for pipeline code paths, owns ingest latency SLA.
- **Infra Lead:** Priya Raman – accountable for capacity planning, observability, and scaling mitigations.
- **Load/Latency Testing Schedule:**
    - Week 5 Friday: Synthetic ingest/retrieval load test dry run (Alex + Priya).
    - Week 6 Tuesday: Full SLA validation with observers from QA; k6 and Locust reports published same day.
    - Week 6 Thursday: Sign-off meeting to review dashboards, trace exports, and contingency posture.
- Sign-off checklist (due before MVP code freeze):
  - [ ] Load-test report attached
  - [ ] Grafana dashboards bookmarked
  - [ ] Runbook updated with scaling steps above
