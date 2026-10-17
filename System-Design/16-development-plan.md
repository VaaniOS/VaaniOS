# 16. Development Plan and Team Split

## 16.1 Two vertical tracks

The project should not be split into "AI vs backend."

Both developers own AI-heavy vertical subsystems.

### Track A — Understanding

Primary owner:

- audio pipeline
- ASR adapter
- semantic compiler
- corrections
- references
- ambiguity
- temporal parsing
- semantic evaluation
- input evaluation (ADR-013) and the `UnderstandResult` handoff

Core question:

> What did the human actually mean?

### Track B — Action

Primary owner:

- business context
- agent orchestration
- tool layer
- validation
- risk
- policy
- handoff
- approval
- execution
- verification

Core question:

> Given what the human meant and what the business knows, what should happen?

## 16.2 Shared

Both own:

- domain contract design
- sandbox
- trace
- integration
- frontend
- final testing
- demo
- presentation

## 16.3 Phase 0 — Together

Finalize:

- repository audit
- domain schemas
- API contracts
- state machines
- mock data
- demo scenario
- evaluation scenarios

## 16.4 Phase 1 — Parallel

Track A:
Audio → ASR → SemanticState

Track B:
Business DB → Context → Agent → Validation → Policy → Execution

## 16.5 Phase 2 — Contract integration

Connect:

```text
Track A SemanticState
        ↓
Track B Context Resolver
```

Then:

```text
Track B Decision
        ↓
Response / UI
```

## 16.6 Phase 3 — Shared sandbox

Track A builds understanding failures.
Track B builds agent/execution failures.

Both integrate them into replay.

## 16.7 Phase 4 — UI

Track A:
Voice intake + semantic state.

Track B:
Context + decision + execution.

Merge into a unified trace.

## 16.8 Git strategy

Suggested branches:

- `main`
- `feature/audio-semantic`
- `feature/agent-execution`
- `feature/sandbox`
- `feature/dashboard`

Avoid simultaneous editing of shared contract files after they are stabilized.

## 16.9 Integration checkpoints

Checkpoint 1:
SemanticState serializes/deserializes correctly.

Checkpoint 2:
Mock business tools consume SemanticState.

Checkpoint 3:
End-to-end happy path.

Checkpoint 4:
One failure path.

Checkpoint 5:
Sandbox replay.

Checkpoint 6:
Real provider adapter.

Checkpoint 7:
Final demo.

## 16.10 Definition of done

A feature requires:

- implementation
- typed contract
- happy-path test
- failure-path test
- observable errors
- documentation if architecture changes

For consequential actions:

- validation
- policy
- explicit execution
- verification
