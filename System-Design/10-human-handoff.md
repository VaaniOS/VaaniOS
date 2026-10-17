# 10. Human Handoff

## 10.1 Goal

When the agent cannot safely continue, the human should receive enough structured context to act immediately.

## 10.2 Handoff triggers

- ambiguous customer
- conflicting quotes
- policy conflict
- high financial risk
- repeated tool failures
- unsupported request
- authorization problem
- data integrity issue

## 10.3 Handoff packet

```json
{
  "case_id": "HANDOFF-102",
  "priority": "HIGH",
  "customer": {...},
  "original_request": "...",
  "interpreted_request": {...},
  "uncertainties": [...],
  "evidence": [...],
  "attempted_actions": [...],
  "blocked_actions": [...],
  "recommended_action": "...",
  "risk": 0.84
}
```

## 10.4 Evidence

Every critical fact should link to:

- customer record
- quote
- inventory snapshot
- transcript segment
- tool result

## 10.5 Handoff UX

The operator should see:

1. What user asked.
2. What system understood.
3. What it knows.
4. What it does not know.
5. Why it stopped.
6. What action is recommended.

## 10.6 Handoff completion

A human can:

- resolve ambiguity
- edit fields
- approve
- reject
- retry
- close

The resulting action must return to the normal trace and verification pipeline.
