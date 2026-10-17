# 21. Event and Commitment System

## 21.1 Purpose

Extract future commitments from voice instructions.

Examples:

- deliver Friday
- dispatch tomorrow
- follow up next week
- remind me at 5
- approval pending

## 21.2 Event model

```json
{
  "event_id": "...",
  "event_type": "DELIVERY",
  "target_time": "...",
  "timezone": "Asia/Kolkata",
  "owner": "...",
  "dependencies": [],
  "source_run_id": "...",
  "status": "PENDING"
}
```

## 21.3 Event lifecycle

```text
DETECTED
 ↓
VALIDATED
 ↓
SCHEDULED
 ↓
PENDING
 ↓
TRIGGERED
 ↓
COMPLETED
```

Alternative:

```text
PENDING → CANCELLED
PENDING → BLOCKED
```

## 21.4 Dependency awareness

An event should not trigger an action if prerequisites are unresolved.

Example:

```text
Delivery Friday
requires:
- customer resolved
- order exists
- inventory available
```

## 21.5 MVP boundary

Event detection is a subsystem.

Do not build a full calendar or task-management product.
