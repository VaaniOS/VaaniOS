# 19. Testing Strategy

## 19.1 Testing pyramid

```text
                 Evaluation
                    /\
                   /  \
             Integration
                /      \
             Unit Tests
```

## 19.2 Unit tests

Audio:
- codec normalization
- VAD segmentation
- quality classification

Semantic:
- correction
- references
- temporal expressions
- ambiguity

Context:
- entity ranking
- quote filtering
- inventory calculation

Policy:
- risk score
- decision matrix
- approval rules

Execution:
- idempotency
- state transitions
- verification comparison

## 19.3 Contract tests

Ensure:

- SemanticState producer matches consumer.
- Tool request schema matches implementation.
- Tool result schema is validated.
- API schemas remain backwards compatible where required.

## 19.4 Integration tests

Minimum:

1. happy path
2. ambiguous customer
3. stale quote
4. inventory shortage
5. invoice failure
6. dispatch failure
7. correction
8. environment change

## 19.5 Golden traces

Store representative expected traces.

Example:

```text
TRANSCRIBED
→ SEMANTIC_COMPILED
→ CUSTOMER_RESOLVED
→ PRODUCT_RESOLVED
→ QUOTE_RESOLVED
→ INVENTORY_VALIDATED
→ APPROVAL_REQUIRED
```

Regression tests compare semantic events rather than fragile timestamps.

## 19.6 Safety tests

Explicitly assert forbidden actions.

Example:

```python
assert "DISPATCH" not in executed_actions
```

when customer identity is ambiguous.

## 19.7 Property-style invariants

Examples:

- If customer resolution is ambiguous, dispatch cannot execute.
- If verification is UNVERIFIED, final status cannot be VERIFIED.
- If an approval is revoked, execution cannot proceed.
- If a tool returns FAILED, user response cannot claim success.
- If quantity is corrected, current state must use the latest valid correction.

## 19.8 Evaluation gates

Before demo:

- zero false-success cases in critical suite
- all core scenarios pass
- no unhandled exceptions in normal flows
- all tool outputs schema validated
