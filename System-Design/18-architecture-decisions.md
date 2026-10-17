# 18. Architecture Decisions

## ADR-001 — Modular monolith for MVP

Decision:
Use a modular monolith with optional worker.

Reason:
Fast iteration, clear module boundaries, less operational overhead.

Rejected:
Many microservices.

## ADR-002 — Semantic state between ASR and agent

Decision:
Introduce a typed SemanticState.

Reason:
Prevents raw transcript from becoming business action and creates a stable contract between teammates.

## ADR-003 — Business facts come from tools

Decision:
Customer/product/quote/inventory/tax/execution facts must be grounded.

Reason:
LLM memory is not authoritative business state.

## ADR-004 — Deterministic policy boundary

Decision:
LLM proposes; validation and policy constrain.

Reason:
Consequential actions require predictable safeguards.

## ADR-005 — Provider adapters

Decision:
Gnani integrations remain behind interfaces.

Reason:
Protect domain architecture from undocumented or changing provider APIs and enable mocks.

## ADR-006 — Verification after writes

Decision:
Read back important state after execution.

Reason:
Tool acknowledgement does not always prove business state.

## ADR-007 — Failure injection sandbox

Decision:
Build replayable controlled failures into the product.

Reason:
The differentiator is reliability under realistic failure, not only happy-path completion.

## ADR-008 — Structured handoff

Decision:
Escalation creates a context-rich case.

Reason:
A human should not need to reconstruct the conversation.

## ADR-009 — Synthetic business data

Decision:
Use synthetic records for the hackathon.

Reason:
No external ERP dependency and safe reproducibility.

## ADR-010 — Explicit approval

Decision:
Financial/consequential operations require explicit approval where policy says so.

Reason:
Authorization must not be inferred from conversational intent alone.

## ADR-011 — Original audio preservation

Decision:
Never overwrite raw audio.

Reason:
Required for debugging preprocessing and ASR failures.

## ADR-012 — Corrections are events

Decision:
Represent old and new values with supersession.

Reason:
Auditability and correct semantic state.
