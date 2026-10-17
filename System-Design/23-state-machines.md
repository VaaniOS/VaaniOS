# 23. State Machines

## 23.1 VoiceRun

```text
CREATED
 ↓
AUDIO_RECEIVED
 ↓
PROCESSING
 ↓
TRANSCRIBED
 ↓
SEMANTIC_READY
 ↓
CONTEXT_READY
 ↓
VALIDATED
 ↓
DECIDED
```

Possible exits:

- BLOCKED
- CLARIFICATION_REQUIRED
- HANDOFF
- APPROVAL_REQUIRED
- EXECUTING
- COMPLETED
- FAILED

## 23.2 Approval

```text
REQUESTED
 ↓
PENDING
 ├── APPROVED
 └── REJECTED
```

Approval can become:

`EXPIRED`

if the underlying snapshot becomes stale.

## 23.3 Execution

```text
NOT_STARTED
 ↓
READY
 ↓
EXECUTING
 ├── SUCCESS
 ├── FAILED
 └── UNKNOWN
```

UNKNOWN requires outcome resolution before another non-idempotent attempt.

## 23.4 Verification

```text
PENDING
 ↓
READ_BACK
 ↓
COMPARE
 ├── VERIFIED
 ├── MISMATCH
 └── UNVERIFIED
```

## 23.5 Handoff

```text
CREATED
 ↓
OPEN
 ↓
ASSIGNED
 ↓
RESOLVED
 ├── RESUME_AUTOMATION
 └── HUMAN_COMPLETED
```

## 23.6 Invariants

- BLOCKED cannot execute.
- APPROVAL_REQUIRED cannot execute until approved.
- REJECTED approval cannot execute.
- UNVERIFIED cannot be reported as completed.
- Ambiguous critical identity cannot proceed to irreversible action.
- Failed tool calls cannot be represented as successful outcomes.
