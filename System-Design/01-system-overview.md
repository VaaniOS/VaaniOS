# 1. System Overview

## 1.1 Product definition

VaaniFlow is a reliability-oriented agentic interface between human voice and business systems.

The product addresses a mismatch:

- humans communicate through speech, shorthand, references, corrections and context;
- business systems require exact IDs, quantities, prices, dates, policies and transaction states.

VaaniFlow acts as the semantic and safety layer between those worlds.

## 1.2 Primary user

The primary user is an SME owner/operator, salesperson, dispatcher or field worker who naturally uses voice notes or calls instead of structured ERP forms.

## 1.3 Secondary user

An operations employee or supervisor receives escalations and approvals.

## 1.4 Canonical scenario

Ramesh sends:

> "Arre Suresh, Sharma Builders ko turant 200 bag Ultratech cement dispatch karo. Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. Invoice bana ke mujhe WhatsApp pe approve karne bhej do."

The system must understand the request without treating the transcript as authoritative business state.

## 1.5 System goals

1. Robustly ingest noisy voice.
2. Preserve multilingual/code-switched meaning.
3. Convert natural language into typed semantic state.
4. Resolve references against authoritative business data.
5. Represent uncertainty explicitly.
6. Prevent unsafe or unsupported actions.
7. Require approval for configured consequential actions.
8. Verify actual business outcomes.
9. Produce useful human handoffs.
10. Make failures observable and evaluable.

## 1.6 Non-goals for MVP

- Full ERP replacement.
- Universal accounting platform.
- General-purpose personal assistant.
- Real biometric authentication without verified provider support.
- Autonomous payment system.
- Universal calendar/reminder product.
- Multi-domain enterprise orchestration platform.
- Perfect multilingual ASR.
- Autonomous execution of every voice command.

## 1.7 Trust boundary

The most important trust boundary is:

```text
UNTRUSTED / PROBABILISTIC
Audio
Transcript
Semantic interpretation
        │
        ▼
GROUNDING + DETERMINISTIC VALIDATION
        │
        ▼
CONTROLLED ACTION
Business tools
        │
        ▼
VERIFIED OUTCOME
```

The LLM may interpret and propose. It must not be the sole authority for irreversible business facts or execution status.

## 1.8 Architectural layers

### Layer A — Perception
Audio quality, preprocessing, ASR.

### Layer B — Semantic interpretation
Intent, entities, references, corrections, constraints, temporal expressions.

### Layer C — Grounding
Customer/product/quote/inventory/business-rule lookup.

### Layer D — Agentic reasoning
Planning, tool selection, missing-information detection, replanning.

### Layer E — Safety
Validation, risk scoring, policy, approval.

### Layer F — Action
Invoice, order, dispatch, notification.

### Layer G — Verification
Read-back, expected-vs-actual comparison, final state.

### Layer H — Observability/evaluation
Trace, provenance, replay, sandbox, metrics.

## 1.9 Key invariants

- No irreversible action from raw transcript.
- No invented business facts.
- No silent ambiguity resolution when risk is material.
- No false success.
- No verification bypass for configured operations.
- Every action must be traceable to an input, policy decision and tool result.
