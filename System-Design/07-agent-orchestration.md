# 7. Agent Orchestration

## 7.1 Role of the agent

The agent is a reasoning/orchestration component, not the source of truth.

It should:

- understand what information is missing
- choose tools
- sequence tool calls
- synthesize grounded context
- propose actions
- replan when context changes
- explain unresolved issues

## 7.2 Agent loop

```text
Semantic State
 ↓
Assess missing information
 ↓
Select tool
 ↓
Execute tool
 ↓
Observe result
 ↓
Update working context
 ↓
Validate
 ↓
Need more information?
 ├── yes → select next tool
 └── no → policy decision
```

## 7.3 Tool categories

### Retrieval
- customer lookup
- product lookup
- quote lookup
- inventory lookup
- order lookup

### Rules
- tax calculation
- pricing policy
- approval policy

### Actions
- create draft
- create invoice
- create dispatch
- notify customer

### Verification
- read invoice
- read order
- read dispatch
- compare state

## 7.4 Tool contracts

Every tool should define:

- name
- purpose
- input schema
- output schema
- side-effect level
- idempotency behavior
- failure modes
- authorization requirement

## 7.5 Side-effect classification

READ_ONLY:
No business state change.

DRAFT:
Creates temporary/reviewable state.

REVERSIBLE_WRITE:
Changes state but can be safely undone.

IRREVERSIBLE_WRITE:
High-consequence external effect.

Policy should treat these differently.

## 7.6 Agent stopping conditions

Stop and ask/hand off when:

- required entity is ambiguous
- critical fact is unavailable
- quote conflicts
- tool fails repeatedly
- risk threshold exceeded
- authorization absent
- business policy prohibits action

## 7.7 Replanning

If inventory changes after initial planning:

```text
Old plan
→ environment change
→ invalidate affected assumption
→ re-read inventory
→ regenerate plan
```

Do not blindly continue with a stale plan.

## 7.8 Prompt discipline

Prompts should tell the model:

- what state it has
- what tools exist
- which facts are authoritative
- which actions are prohibited
- when it must stop

Do not rely on "please be careful" as a safety mechanism.
