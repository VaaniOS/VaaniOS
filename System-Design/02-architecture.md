# 2. Detailed Architecture

## 2.1 Logical architecture

```text
                         ┌─────────────────────┐
                         │   Voice / WhatsApp  │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ Audio Intelligence  │
                         │ VAD / Denoise / QA  │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │       ASR           │
                         │ Prisma / Mock       │
                         └──────────┬──────────┘
                                    │
                                    ▼
                  ┌─────────────────────────────────┐
                  │    Semantic Voice Compiler      │
                  │ intent/entities/references/etc.│
                  └───────────────┬─────────────────┘
                                  │
                                  ▼
                  ┌─────────────────────────────────┐
                  │     Context Resolution Layer    │
                  │ customer/product/quote/stock   │
                  └───────────────┬─────────────────┘
                                  │
                                  ▼
                  ┌─────────────────────────────────┐
                  │ Agent Orchestrator + Tools      │
                  └───────────────┬─────────────────┘
                                  │
                                  ▼
                  ┌─────────────────────────────────┐
                  │ Validation / Risk / Policy      │
                  └───────────────┬─────────────────┘
                                  │
                    ┌─────────────┼──────────────┐
                    ▼             ▼              ▼
                 CLARIFY       APPROVE        HANDOFF
                                  │
                                  ▼
                         ┌─────────────────┐
                         │ Tool Execution  │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │ Verification    │
                         └────────┬────────┘
                                  │
                         ┌────────┴────────┐
                         ▼                 ▼
                    Spoken Reply       Trace/Audit
```

## 2.2 Component ownership

### Audio subsystem
Owns audio normalization, VAD, quality assessment and preprocessing.

### ASR adapter
Converts audio artifact to transcript plus metadata.

### Semantic compiler
Converts transcript into typed semantic state.

### Context resolver
Grounds references in business records.

### Agent orchestrator
Chooses tools and sequences reasoning.

### Validation engine
Performs deterministic correctness checks.

### Policy engine
Maps validated state/risk to an allowed action.

### Execution engine
Performs business operations through idempotent tools.

### Verification engine
Checks whether the intended state actually occurred.

### Handoff engine
Produces actionable human escalation.

### Trace engine
Records the entire run.

### Evaluation engine
Replays controlled cases and computes metrics.

## 2.3 Runtime topology

For MVP:

```text
Next.js Web
    │
    ▼
FastAPI Modular Monolith
    ├── Audio
    ├── Semantic
    ├── Context
    ├── Agent
    ├── Policy
    ├── Execution
    ├── Trace
    └── Evaluation
    │
    ├── PostgreSQL
    ├── Redis (optional)
    └── Object storage/local artifacts
```

Use a worker only for expensive/long-running audio or evaluation jobs.

Do not introduce Kubernetes, service meshes or many microservices for the hackathon.

## 2.4 Dependency direction

Preferred dependency flow:

```text
API
 ↓
Application Services
 ↓
Domain
 ↑
Infrastructure / Providers
```

Domain code should not import FastAPI, PostgreSQL, Gnani SDKs or UI code.

Provider adapters implement interfaces defined by the application/domain boundary.

## 2.5 Sync vs async

Use synchronous execution for the demo where latency is acceptable.

Use asynchronous jobs for:

- long audio preprocessing
- batch evaluation
- expensive model inference
- large replay suites

Do not make every operation asynchronous merely because agents are involved.

## 2.6 Failure containment

Provider failure must not corrupt domain state.

Example:

```text
Prisma unavailable
   ↓
ASRProviderError
   ↓
Run = BLOCKED_AT_ASR
   ↓
No semantic execution
```

Tool failure:

```text
Invoice API error
   ↓
Execution = FAILED
   ↓
Draft remains
   ↓
No false success
```

## 2.7 Idempotency boundary

Every consequential write should have an idempotency key derived from the run and logical action.

Example:

`run_id + action_type + entity_version`

Repeated execution must not create duplicate invoices/orders.
