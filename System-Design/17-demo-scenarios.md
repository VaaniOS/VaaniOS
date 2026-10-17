# 17. Demo Scenarios

## Scenario 1 — Happy path

Input:
Ramesh's noisy voice note.

Expected:

1. audio quality detected
2. preprocessing
3. transcription
4. semantic extraction
5. customer resolution
6. product resolution
7. historical quote resolution
8. inventory check
9. tax calculation
10. validation pass
11. approval required
12. invoice draft
13. approval
14. invoice creation
15. invoice verification
16. dispatch preparation
17. dispatch verification
18. response

## Scenario 2 — Ambiguous customer

Dataset:
Two customers match "Sharma Builders."

Expected:
- no dispatch
- no invoice execution
- clarification or handoff
- evidence shown

Forbidden:
automatic selection of one customer.

## Scenario 3 — Quantity corruption

Original:
200 bags.

Injected ASR:
2000 bags.

Expected:
- suspicious quantity detected
- financial impact highlighted
- confirmation/clarification

Forbidden:
automatic dispatch of 2000.

## Scenario 4 — Stale historical quote

Historical quote exists but expired.

Expected:
- quote lookup returns stale
- no blind application
- clarification or handoff

## Scenario 5 — Inventory shortage

Requested:
200.

Available:
120.

Expected:
- block full dispatch
- offer valid alternatives if policy permits
- no false dispatch success

## Scenario 6 — Invoice failure

Invoice API returns error.

Expected:
- invoice status FAILED
- validated draft preserved
- user informed
- no "invoice created" message

## Scenario 7 — Dispatch failure

Invoice verified.
Dispatch API fails.

Expected:
- invoice VERIFIED
- dispatch FAILED
- no false claim
- workflow remains recoverable

## Scenario 8 — User correction

"200 bags—actually 220."

Expected:
- semantic current quantity 220
- correction event preserved
- pricing/inventory recalculated for 220

## Scenario 9 — Environment change

Initial inventory:
430.

Before execution:
inventory changes to 150.

Expected:
- pre-execution revalidation
- stale plan invalidated
- replan/clarify

## Scenario 10 — Tool unknown outcome

API times out after request may have been accepted.

Expected:
- do not blindly retry non-idempotent write
- mark UNKNOWN
- read-back if safe
- resolve outcome before reporting
