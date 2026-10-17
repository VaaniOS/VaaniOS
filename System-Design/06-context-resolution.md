# 6. Context Resolution

## 6.1 Purpose

Convert references in semantic state into authoritative business facts.

## 6.2 Resolution pipeline

```text
Semantic Reference
 ↓
Candidate Retrieval
 ↓
Candidate Ranking
 ↓
Confidence / Uniqueness
 ↓
Resolve OR Mark Ambiguous
 ↓
Attach Provenance
```

## 6.3 Customer resolution

Candidate signals:

- exact name
- aliases
- phone number
- address
- historical relationship
- recent conversation
- customer code

Never resolve solely from fuzzy name similarity when multiple high-risk candidates exist.

## 6.4 Product resolution

Signals:

- brand
- SKU
- aliases
- packaging
- unit
- category
- prior customer usage

"UltraTech cement" may remain ambiguous.

## 6.5 Temporal resolution

All dates use:

- business timezone
- current run timestamp
- locale-aware rules

Store both surface expression and resolved value.

Do not let an LLM silently reinterpret "parso."

## 6.6 Historical quote resolution

Required filters:

- customer
- product
- quote date
- quote status
- validity
- currency
- unit

If multiple quotes remain:

```text
AMBIGUOUS_QUOTE
```

If no valid quote:

```text
QUOTE_NOT_FOUND
```

Do not invent a replacement price.

## 6.7 Inventory

Inventory lookup must account for:

```text
available
reserved
sellable
warehouse
version
```

Do not use stale inventory for irreversible execution without revalidation.

## 6.8 Tax rules

Tax is a business rule lookup, not an LLM memory task.

Input:

- customer
- product
- jurisdiction
- transaction type
- taxable amount

Output:

- tax components
- rates
- totals
- rule version
- provenance

## 6.9 Context snapshot

Before consequential execution, persist a snapshot of the facts used to make the decision.

This enables later explanation:

"Why did the system use ₹420?"

Answer:

"Quote Q-1092, retrieved at time T, customer CUST-0042, product PROD-CEM-001."

## 6.10 Revalidation

Context may become stale between planning and execution.

At the execution boundary, re-check critical facts:

- inventory
- quote validity
- order duplication
- approval state
- policy version
