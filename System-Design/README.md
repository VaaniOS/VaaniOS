# VaaniFlow — System Design

**Speak it. Structure it. Execute it.**

This folder is the canonical architectural reference for VaaniFlow.

VaaniFlow is an agentic voice-to-business-action platform for Indian SMEs. It transforms noisy, multilingual, contextual voice instructions into structured business state, grounds that state in business data, validates consequential actions, and either executes, asks for clarification/approval, or hands off to a human.

## Architectural north star

```text
Human Voice
   ↓
Audio Intelligence
   ↓
ASR
   ↓
Semantic Voice Compiler
   ↓
Business Context Resolution
   ↓
Validation + Risk + Policy
   ↓
Execute / Clarify / Confirm / Approve / Handoff / Block
   ↓
Tool Execution
   ↓
Verification
   ↓
Response + Trace
```

The architecture is intentionally provider-agnostic. Gnani Prisma/Timbre integrations are adapters, not the domain architecture.

## Documents

| Document | Purpose |
|---|---|
| `01-system-overview.md` | Product boundary, goals, non-goals, actors, lifecycle |
| `02-architecture.md` | Detailed component and deployment architecture |
| `03-data-model.md` | Domain entities, schemas, state transitions, provenance |
| `04-audio-pipeline.md` | Audio preprocessing and ASR architecture |
| `05-semantic-compiler.md` | Voice-to-structured-state design |
| `06-context-resolution.md` | Entity, temporal, quote, inventory and business context |
| `07-agent-orchestration.md` | Agent loop, planning, tool use and replanning |
| `08-validation-policy-risk.md` | Deterministic safeguards, risk and decision policy |
| `09-execution-verification.md` | Approval, tool execution, idempotency and verification |
| `10-human-handoff.md` | Intelligent escalation and handoff packet |
| `11-sandbox-evaluation.md` | Failure injection, replay and metrics |
| `12-observability.md` | Tracing, provenance, audit and diagnostics |
| `13-api-contracts.md` | HTTP/API boundaries |
| `14-security-privacy.md` | Threat model and data protection |
| `15-frontend.md` | Operator dashboard and UX |
| `16-development-plan.md` | Parallel team plan and implementation sequence |
| `17-demo-scenarios.md` | Happy path and failure demonstrations |
| `18-architecture-decisions.md` | ADR-style decisions and rationale |
| `19-testing-strategy.md` | Unit, integration, evaluation and regression testing |
| `20-gnani-integration.md` | Provider adapter strategy and integration boundaries |
| `21-event-system.md` | Event/commitment extraction and future triggers |
| `22-repository-blueprint.md` | Recommended repository layout and module responsibilities |
| `23-state-machines.md` | Run, approval, execution and handoff state machines |
| `24-agent-reliability.md` | Reliability invariants and failure semantics |

## Source of truth

`CLAUDE.md` remains the operating contract for Claude Code. This folder explains the architecture in greater depth. If implementation differs from the architecture, update the relevant design document or record an ADR rather than silently drifting.

## Core principle

> Raw speech must never directly become an irreversible business action.

## Demo domain

The canonical demo is a wholesale construction-material business. The system must be designed generically enough to support other operational domains later, but the MVP should not become a multi-domain platform.

## Important implementation rule

Synthetic business data is acceptable for the hackathon. Fake architecture is not.

Do not hard-code the Ramesh scenario into production components.
