# 9. Execution and Verification

## 9.1 Execution stages

```text
Validated Draft
 ↓
Approval
 ↓
Pre-execution Revalidation
 ↓
Tool Call
 ↓
Immediate Result
 ↓
Read-back Verification
 ↓
Final State
```

## 9.2 Approval

Approval must be explicit and bound to a specific snapshot.

Approval record should contain:

- approver
- target
- transaction snapshot
- timestamp
- policy version
- evidence

If the transaction changes after approval, approval may need to become invalid.

## 9.3 Idempotency

Use an idempotency key for every consequential write.

Example:

`INV:{run_id}:{draft_version}`

A retry must not create duplicate invoices.

## 9.4 Transaction semantics

Where the external system supports transactions, use them.

Where it does not, model a saga/compensation strategy.

Example:

```text
Invoice created
 ↓
Dispatch failed
 ↓
Order remains INVOICE_CREATED_DISPATCH_PENDING
```

Do not pretend the entire workflow succeeded.

## 9.5 Verification

Expected state:

```json
{
  "invoice_total": 107520,
  "customer_id": "CUST-0042",
  "items": [...]
}
```

Observed state comes from read-back.

Compare field-by-field.

Result:

- VERIFIED
- MISMATCH
- UNVERIFIED

## 9.6 False success prevention

The response generator must receive execution status from the verification layer.

It must never infer success from an intended action.

Bad:

"Invoice should have been created, so say it was created."

Good:

"Verification returned VERIFIED, so state invoice creation as completed."

## 9.7 Partial completion

Example:

```text
Invoice = VERIFIED
Dispatch = FAILED
Notification = NOT_ATTEMPTED
```

The user should receive a precise summary.

## 9.8 Recovery

Retries are allowed only for retry-safe failures.

Do not automatically retry an unknown outcome for a non-idempotent write.
