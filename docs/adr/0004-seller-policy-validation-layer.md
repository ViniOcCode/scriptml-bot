---
title: "ADR-0004: Seller Policy Validation Layer"
status: "Accepted"
date: "2026-03-24"
authors: "Architecture / Maintainers"
tags: ["architecture", "decision", "validation", "policy"]
supersedes: ""
superseded_by: ""
---

# ADR-0004: Seller Policy Validation Layer

## Status

Proposed | **Accepted** | Rejected | Superseded | Deprecated

## Context

The JSON payload publisher (ADR-0003) needs to enforce seller-specific business rules before
sending a payload to the Mercado Livre API. These rules are account-level constraints that
vary per tenant and are not enforced by the ML API itself at the time of listing creation
(some are only surfaced as moderation rejections after publishing).

Key constraints:
- Rules must be configurable per-tenant without code changes (YAML-driven).
- Violations must be classifiable as blocking errors or non-blocking warnings, so that
  operators can choose to publish with warnings but never with errors.
- The validator must be completely pure (no API calls, no I/O side effects) to make it
  testable and usable in `--dry-run` mode.
- Category-level listing type overrides must be applied before validation so the final
  payload is policy-compliant before posting.
- The validator must gate AI-suggested categories that have not been human-reviewed,
  preventing unreviewed ML-generated categorizations from reaching production.

## Decision

Introduce a dedicated `SellerPolicyValidator` in
`mercadolivre_upload/application/validators/seller_policy.py` backed by a `seller.yaml`
configuration file (git-ignored, per-tenant):

- **`SellerConfig`** — Pydantic v2 `BaseModel` with nested sub-models (`ListingConfig`,
  `PricingConfig`, `ShippingConfig`, `CategoriesConfig`, `BatchConfig`). Loaded via
  `load_seller_config(path)` or `default_seller_config()` for tests.
- **`PolicyViolation`** — `@dataclass` with `field`, `message`, and `severity`
  (`Literal["error", "warning"]`).
- **`PolicyResult`** — `@dataclass` with `violations: list[PolicyViolation]` and `has_errors` /
  `has_warnings` computed properties.
- **`SellerPolicyValidator.validate(payload, ai_suggested)`** — pure function returning
  `PolicyResult`; checks listing type allowlist, price min/max, blocked categories, and AI
  review gate.
- **`SellerPolicyValidator.apply_overrides(payload)`** — returns a copy of the payload with
  per-category `listing_type_id` overrides applied before validation.

`config/seller.example.yaml` is versioned as the canonical template. `config/seller.yaml` is
git-ignored (added to `.gitignore`) so per-tenant secrets and policy do not leak into the repo.

## Consequences

### Positive

- **POS-001**: Policy is fully declarative — operators modify `seller.yaml` without touching
  Python code to change listing type rules, price limits, or blocked categories.
- **POS-002**: Pure validator (no I/O) is trivially testable and safe in `--dry-run` mode;
  all 11 policy tests run without mocking any external dependency.
- **POS-003**: Pydantic v2 validation on `SellerConfig` load catches malformed YAML at startup,
  not at publish time — fail-fast for configuration errors.
- **POS-004**: `apply_overrides()` before `validate()` ensures the published payload always
  reflects the seller's category-level listing type rules, preventing post-publish moderation.
- **POS-005**: AI-review gate (`human_review_required: true` + `ai_suggested=True`) provides a
  hard stop for unreviewed ML-generated categories before any API call is made.

### Negative

- **NEG-001**: `seller.yaml` is git-ignored and must be provisioned manually per environment;
  there is no automatic secret management or rotation mechanism.
- **NEG-002**: `default_seller_config()` returns permissive defaults (all listing types allowed,
  wide price range) — a missing `seller.yaml` silently allows all payloads through rather than
  failing closed.
- **NEG-003**: Per-category `listing_type_id` overrides in `seller.yaml` must be kept in sync
  with ML category hierarchy changes; no automated validation against the live ML API.
- **NEG-004**: Price variance alert (`variance_alert_pct`) is declared in the config schema but
  not implemented in the validator — it is a stub for future implementation.

## Alternatives Considered

### Inline validation in `PublishJsonUseCase`

- **ALT-001**: **Description**: Embed the listing type check, price check, and category block
  logic directly in `execute()` as conditional statements.
- **ALT-002**: **Rejection Reason**: Hard-codes policy in application logic; adding or removing
  a rule requires code changes and a new release. Makes the use-case harder to test in isolation
  and couples business rules to orchestration concerns.

### JSON Schema validation only

- **ALT-003**: **Description**: Use JSON Schema (via `jsonschema` library) to validate the payload
  against a static schema before posting.
- **ALT-004**: **Rejection Reason**: JSON Schema is appropriate for structural validation (field
  types, required keys) but cannot express dynamic business rules like "price must be above the
  seller's configured minimum" or "this seller's account is not allowed to use `bronze` listing
  type". Structural validation is already handled by `JsonPayloadReader.read()`.

### Remote policy service

- **ALT-005**: **Description**: Query an external policy API (e.g., a rules engine service) at
  publish time to validate the payload.
- **ALT-006**: **Rejection Reason**: Introduces network dependency in the publish critical path,
  adds latency, and creates a failure mode (policy service unavailable → cannot publish). The
  seller rule set is small and stable enough for local YAML configuration.

## Implementation Notes

- **IMP-001**: `load_seller_config(path: Path) -> SellerConfig` raises `FileNotFoundError` if
  `seller.yaml` is absent. The CLI command catches this and prints an actionable error message
  pointing to `config/seller.example.yaml`.
- **IMP-002**: `default_seller_config()` is used in tests to avoid dependency on a real
  `seller.yaml`; it is not intended for production use.
- **IMP-003**: Future rule additions should be added to both `seller.example.yaml` (documented)
  and `SellerConfig` (typed); the Pydantic model enforces that new fields are optional with sane
  defaults to avoid breaking existing `seller.yaml` files.
- **IMP-004**: The `variance_alert_pct` field in `PricingConfig` is reserved for future price
  history comparison logic; the validator currently ignores it.

## References

- **REF-001**: ADR-0003 — JSON Payload Publisher (consumer of this validator)
- **REF-002**: `config/seller.example.yaml` — canonical configuration template
- **REF-003**: `mercadolivre_upload/application/validators/seller_policy.py` — implementation
- **REF-004**: `tests/test_seller_policy.py` — 11 unit tests covering all validation paths
- **REF-005**: Pydantic v2 documentation — `model_validate()`, nested `BaseModel`
