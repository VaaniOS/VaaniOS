# 24. Agent Reliability

## 24.1 Reliability model

VaaniFlow treats agentic behavior as a controlled system rather than unconstrained autonomous reasoning.

Reliability comes from multiple layers:

```text
Better perception
+
Better semantic representation
+
Grounded context
+
Deterministic validation
+
Explicit policy
+
Controlled side effects
+
Verification
+
Evaluation
```

## 24.2 Failure classes

### Perception failure
Audio/ASR misunderstood speech.

### Semantic failure
The transcript is correct but meaning is interpreted incorrectly.

### Grounding failure
The correct entity exists but is resolved incorrectly.

### Reasoning failure
The agent chooses an inappropriate plan.

### Policy failure
The system allows an unsafe action.

### Tool failure
The external operation fails.

### Verification failure
The operation result cannot be established.

### Communication failure
The final response misrepresents system state.

Each class should be distinguishable in traces.

## 24.3 Reliability invariant

The weakest layer must not silently promote uncertainty into certainty.

Example:

```text
ASR uncertain
→ semantic uncertain
→ context uncertain
→ policy sees uncertainty
→ action blocked/clarified
```

Not:

```text
ASR uncertain
→ LLM guesses
→ execution
→ "Done!"
```

## 24.4 Confidence propagation

Confidence should be treated as evidence, not permission.

A 0.95 model confidence cannot override a business-policy block.

## 24.5 Shadow execution

Future extension:

Run a proposed action in a sandbox without side effects.

Compare:

- expected state
- proposed tool calls
- risk
- policy

Only then allow real execution.

## 24.6 Adaptive autonomy

Future extension:

```text
Low risk + stable context
→ more autonomous

High uncertainty / high risk
→ supervised

Critical ambiguity
→ human control
```

This is post-MVP.

## 24.7 Plan invalidation

Every plan should have assumptions.

Example:

```text
Plan assumption:
inventory >= 200
```

If inventory becomes 120, invalidate the affected plan rather than executing stale intent.

## 24.8 Reliability-first product philosophy

The strongest product behavior is not:

"the agent always completes tasks."

It is:

"the agent completes valid tasks and knows when it must not act."
