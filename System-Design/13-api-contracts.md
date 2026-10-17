# 13. API Contracts

## 13.1 Run lifecycle

### POST /runs

Creates a run.

Response:

```json
{
  "run_id": "RUN-123",
  "status": "CREATED"
}
```

### POST /runs/{run_id}/audio

Uploads audio.

### POST /runs/{run_id}/process

Starts processing.

### GET /runs/{run_id}

Returns current state.

## 13.2 Semantic endpoint

### GET /runs/{run_id}/semantic-state

Returns versioned semantic state.

## 13.3 Validation

### GET /runs/{run_id}/validation

Returns checks, issues, warnings and risk.

## 13.4 Approval

### POST /runs/{run_id}/approve

Body should include approval intent/version to prevent approving stale data.

### POST /runs/{run_id}/reject

Rejects current draft.

## 13.5 Clarification

### POST /runs/{run_id}/clarify

Adds user-provided clarification and resumes from the correct state.

## 13.6 Handoff

### POST /runs/{run_id}/handoff

Creates or updates a handoff case.

## 13.7 Search endpoints

- GET /customers/search
- GET /products/search
- GET /quotes/search
- GET /inventory/search

These should be read-only.

## 13.8 Sandbox

### POST /sandbox/scenarios/{scenario_id}/run

Runs an evaluation case with fault injection.

## 13.9 API rules

- typed request/response schemas
- stable error codes
- no provider payloads leaking into public domain contracts
- authentication middleware before production deployment
- idempotency headers for writes
- correlation IDs
