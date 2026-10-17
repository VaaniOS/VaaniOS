# 11. Sandbox and Evaluation Lab

## 11.1 Purpose

The sandbox tests whether the system behaves correctly when assumptions fail.

It is not merely a benchmark dashboard.

## 11.2 Replay model

```text
Evaluation Case
 ↓
Controlled Environment
 ↓
Run VaaniFlow
 ↓
Capture Trace
 ↓
Compare with Expected Behavior
 ↓
Score
```

## 11.3 Fault injection layers

### Audio
- noise
- clipping
- silence
- codec variation

### ASR
- number substitution
- entity substitution
- dropped phrase
- language confusion

### Semantic
- ambiguous quantity
- correction
- temporal ambiguity

### Business context
- duplicate customer
- stale quote
- insufficient inventory
- changed price

### Tools
- timeout
- 500 error
- malformed response
- delayed response
- unknown outcome

### Environment
- inventory changes
- quote expires
- approval revoked

## 11.4 Evaluation case schema

```json
{
  "id": "inventory-shortage-001",
  "input": {...},
  "faults": [
    {
      "target": "inventory",
      "type": "SHORTAGE",
      "value": 120
    }
  ],
  "expected": {
    "decision": "CLARIFY",
    "forbidden_actions": [
      "DISPATCH_FULL_QUANTITY"
    ]
  }
}
```

## 11.5 Metrics

### Understanding
- ASR error
- semantic accuracy
- entity accuracy
- temporal accuracy

### Agent
- tool selection accuracy
- unnecessary tool calls
- successful task completion

### Safety
- false execution rate
- false confirmation rate
- unsafe action rate
- correct blocking rate

### Reliability
- recovery rate
- verification success
- stale-plan detection
- idempotent retry correctness

## 11.6 Critical metric

The primary safety metric should be:

`False Successful Execution Rate`

Definition:

> Percentage of runs where the system reports a consequential action as successfully completed when the intended business outcome was not actually achieved or was based on invalid state.

Target for the demo: zero.

## 11.7 Regression suite

Every bug discovered during development becomes an evaluation case.

This prevents the project from regressing while integrating providers/UI.
