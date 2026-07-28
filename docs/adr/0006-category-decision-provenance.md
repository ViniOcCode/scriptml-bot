---
title: "ADR-0006: Versioned Category Decision Provenance at the Publisher Boundary"
status: "Accepted"
date: "2026-07-27"
authors: "Architecture / Maintainers"
tags: ["architecture", "category", "safety", "publisher"]
supersedes: "category_ai_suggested metadata flag for strict publisher inputs"
superseded_by: ""
---

# ADR-0006: Versioned Category Decision Provenance at the Publisher Boundary

## Context

The legacy boolean `_meta.category_ai_suggested` could be absent. The reader treated absence as
`false`, so an AI-selected category could bypass `human_review_required` without any evidence of
its origin or review.

## Decision

Strict builder-to-publisher envelopes require `_meta.category_decision` with this versioned shape:

```json
{
  "schema_version": 1,
  "category_id": "MLB123",
  "source": "ai",
  "resolution_mode": "llm_authoritative",
  "confidence": 0.91,
  "review": {
    "status": "unreviewed",
    "evidence": null
  }
}
```

- `category_id` must equal the category ID in every publish body in the envelope.
- `source` is one of `ai`, `operator`, or `marketplace_metadata`; it records the selecting
  authority and is independent of the resolution method.
- `confidence`, when present, is a finite number from zero through one.
- An `approved` review needs immutable evidence with `reference`, `reviewer`, and ISO-8601
  `reviewed_at`. An `unreviewed` decision must carry explicit `null` evidence.
- With `human_review_required: true`, SellerPolicy blocks an AI decision unless the typed review
  is approved. Confidence thresholds evaluate the same typed decision.
- `category_ai_suggested` is forbidden in strict envelopes. The non-strict reader retains it only
  for legacy local inspection; it is not a publication compatibility path.

## Consequences

Malformed, absent, or category/body-mismatched provenance fails before seller policy or remote
calls. This intentionally exposes stale builder artifacts rather than silently downgrading their
risk. The reader strips this metadata before Mercado Livre API calls.
