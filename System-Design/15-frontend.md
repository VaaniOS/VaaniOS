# 15. Frontend and UX

## 15.1 Design objective

The UI should make the system's reasoning and safety visible.

Avoid a generic chatbot interface.

The user should see a business workflow.

## 15.2 Main screen

Suggested layout:

```text
┌───────────────────────────────────────────────────────────┐
│ VaaniFlow                              RUN-8F21           │
├───────────────┬───────────────────────────────────────────┤
│ Voice Input   │ Semantic State                            │
│               │ Customer: Sharma Builders                 │
│ waveform      │ Product: UltraTech cement                │
│ quality 72    │ Qty: 200 bags                             │
│ noise: high   │ Price: Historical quote                   │
├───────────────┼───────────────────────────────────────────┤
│ Transcript    │ Business Context                          │
│               │ Quote: Q-1092                             │
│ ...           │ Inventory: 430 bags                      │
├───────────────┴───────────────────────────────────────────┤
│ Decision: APPROVAL REQUIRED                               │
│ Evidence | Validation | Risk | Actions                   │
└───────────────────────────────────────────────────────────┘
```

## 15.3 State visualization

Use status badges:

- green = verified/pass
- amber = warning/review
- red = blocked/failure
- neutral = pending

Do not make color the only signal.

## 15.4 Evidence drawer

Clicking a resolved fact should show its source.

Example:

`₹420`

→ `Quote Q-1092`
→ quoted 2026-10-15
→ customer CUST-0042
→ product PROD-CEM-001

## 15.5 Decision explanation

Show:

"Approval required because transaction value is consequential."

Not:

"Agent confidence = 0.83."

Confidence can be supporting information, not the explanation itself.

## 15.6 Sandbox UI

Controls:

- scenario selector
- fault injection
- run
- trace
- expected behavior
- actual behavior
- pass/fail

## 15.7 Handoff UI

Display:

- original request
- interpreted request
- unresolved issue
- evidence
- recommendation
- action buttons

## 15.8 UX principle

The interface should answer:

1. What did the user say?
2. What did we understand?
3. What did we verify?
4. What are we about to do?
5. What actually happened?
