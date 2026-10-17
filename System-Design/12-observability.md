# 12. Observability, Trace and Provenance

## 12.1 Run ID

Every user interaction receives a globally unique run_id.

Every downstream event carries it.

## 12.2 Trace stages

Recommended:

1. INGESTED
2. AUDIO_ANALYZED
3. AUDIO_PROCESSED
4. TRANSCRIBED
5. SEMANTIC_COMPILED
6. CONTEXT_RESOLVED
7. VALIDATED
8. DECISION_MADE
9. APPROVAL_REQUESTED
10. APPROVED
11. TOOL_EXECUTED
12. VERIFIED
13. RESPONSE_GENERATED
14. COMPLETED

Failure variants:

- FAILED
- BLOCKED
- HANDOFF
- UNVERIFIED

## 12.3 Trace event schema

```json
{
  "run_id": "...",
  "event_id": "...",
  "timestamp": "...",
  "stage": "QUOTE_LOOKUP",
  "component": "HistoricalQuoteResolver",
  "input_ref": "...",
  "output_ref": "...",
  "latency_ms": 84,
  "status": "SUCCESS",
  "provenance": [...]
}
```

## 12.4 LLM observability

Log:

- model/provider identifier
- prompt version
- schema version
- latency
- token/cost metadata where available
- structured output validation result

Avoid storing secrets or unnecessary raw user data.

## 12.5 Tool observability

For each tool:

- tool name
- arguments hash
- sanitized arguments
- result status
- error
- duration
- retry count
- idempotency key

## 12.6 Provenance graph

Important facts can be represented as:

```text
Transcript segment
      ↓
Semantic field
      ↓
Resolver
      ↓
Business record
      ↓
Validation
      ↓
Decision
      ↓
Action
```

This enables "Why did the agent do that?" debugging.

## 12.7 Privacy

Raw audio should have configurable retention.
Logs should use redaction.
Sensitive fields should not appear in ordinary application logs.
