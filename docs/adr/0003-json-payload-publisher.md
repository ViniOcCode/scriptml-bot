---
title: "ADR-0003: JSON Payload Publisher — New Entry Point for ml-builder Output"
status: "Accepted"
date: "2026-03-24"
authors: "Architecture / Maintainers"
tags: ["architecture", "decision", "cli", "publishing"]
supersedes: ""
superseded_by: ""
---

# ADR-0003: JSON Payload Publisher — New Entry Point for ml-builder Output

## Status

Proposed | **Accepted** | Rejected | Superseded | Deprecated

## Context

The `scriptml` CLI (`ml-upload`) previously accepted only Excel spreadsheets as input for product
publishing to Mercado Livre. An external tool (`ml-builder`) now produces fully self-contained
`payload.json` files that include real CDN picture IDs, `buying_mode`, and a `_meta` block
containing plain-text description and category metadata.

Key constraints and drivers:
- The Excel upload flow (`ml-upload upload`) must remain completely unchanged — zero regression risk.
- `ml-builder` produces payloads that are ready for direct POST to the ML Items API, except for
  seller-specific policy enforcement (listing type, price ranges, blocked categories).
- The new flow must reuse the existing `MLApiClient`, `AuthManager`, and `ItemPublisherPort`
  infrastructure without duplication.
- `_meta` fields (description, SKU, AI-suggestion flag) must be stripped before the payload reaches
  the API; they are internal metadata, not API fields.
- A batch directory structure (`batches/{category_id}/{sku}/payload.json`) must be walkable to
  support category-level bulk publishing.

## Decision

Introduce two new Typer commands (`publish-json`, `publish-batch`) backed by a dedicated adapter,
use-case, and CLI module — completely separate from the existing Excel pipeline:

- **`mercadolivre_upload/adapters/json_payload_reader.py`** — reads and validates a single
  `payload.json`, strips `_meta` before returning a typed `ReadPayloadResult`, raises
  `InvalidPayloadError` for missing required fields or empty `pictures`.
- **`mercadolivre_upload/application/publish_json_use_case.py`** — orchestrates
  read → seller-policy override → seller-policy validation → publish → description post.
  Reuses `MLApiClient.create_item()` and `MLApiClient.create_item_description()` (already present).
- **`mercadolivre_upload/cli/commands/publish_json.py`** — Typer commands with `--dry-run`,
  `--report-dir`, and `--all` flags; reads `batch_manifest.json` for failed-SKU skipping and
  AI-review gating.
- Commands registered in `app.py` using the existing `import_module` lazy-load pattern.

The `_meta` block is consumed (stripped) by the reader adapter before the payload reaches the
use-case or API layer. `description_plain_text` is posted separately via the ML description
endpoint after the item is created.

## Consequences

### Positive

- **POS-001**: Zero changes to the Excel pipeline (`upload` command, `PublishProductUseCase`,
  `SpreadsheetParser`) — existing behavior is fully preserved.
- **POS-002**: Clean separation of concerns: reader (schema), use-case (orchestration), validator
  (business rules), CLI (UX) — each layer is independently testable.
- **POS-003**: `_meta` stripping at the adapter boundary ensures the API layer never receives
  internal metadata; the contract is enforced structurally.
- **POS-004**: `--dry-run` mode validates policy without any API calls, enabling safe CI-level
  pre-flight checks before publishing.
- **POS-005**: Reuses existing `MLApiClient` and `AuthManager` — no new HTTP or auth code
  introduced.
- **POS-006**: 39 new tests added; existing 499 tests remain intact (538 total, 78% coverage).

### Negative

- **NEG-001**: `publish-json` and `publish-batch` are synchronous despite the `MLApiClient`
  supporting async patterns; batch throughput is limited to sequential item publishing.
- **NEG-002**: `batch_manifest.json` format is defined implicitly by convention (not via a schema);
  schema drift between `ml-builder` and `scriptml` is a future risk.
- **NEG-003**: `seller.yaml` is per-tenant and git-ignored; operators must copy from
  `seller.example.yaml` manually — no automatic provisioning.
- **NEG-004**: Report output in `cache/reports/` is not cleaned up automatically; operators must
  manage disk usage.

## Alternatives Considered

### Extend the existing `upload` command with a `--json` flag

- **ALT-001**: **Description**: Detect whether the input is `.xlsx` or `.json` and branch inside
  the existing `upload` command.
- **ALT-002**: **Rejection Reason**: Would couple two fundamentally different input models in one
  command, increasing risk of regression in the Excel path and making the code harder to reason
  about. The Excel path involves `SpreadsheetParser`, column normalization, and category resolution
  which are irrelevant for pre-built payloads.

### Reuse `PublishProductUseCase` for JSON payloads

- **ALT-003**: **Description**: Convert `payload.json` to the internal `Product` domain model and
  pass it through the existing use-case.
- **ALT-004**: **Rejection Reason**: `PublishProductUseCase` tightly couples category resolution,
  attribute building, and image uploading — steps that are unnecessary when `ml-builder` has
  already produced a complete payload with real picture IDs. Forcing JSON payloads through this
  pipeline would add latency and fragility with no benefit.

### Async batch publishing with `asyncio.gather`

- **ALT-005**: **Description**: Run multiple `create_item()` calls concurrently using
  `asyncio.gather` for higher throughput.
- **ALT-006**: **Rejection Reason**: The codebase is fully synchronous; introducing async at the
  use-case layer would require changes to `MLApiClient`, `AuthManager`, and all test infrastructure.
  The Mercado Livre API also enforces rate limits that make parallelism a risk without a proven
  token-bucket strategy. Deferred to a future ADR once the synchronous baseline is validated.

## Implementation Notes

- **IMP-001**: The `import_module` lazy-load pattern (`mercadolivre_upload.cli.commands.publish_json`)
  is used in `app.py` consistent with other commands — avoids circular imports and keeps startup
  fast.
- **IMP-002**: `config/seller.yaml` is git-ignored; `config/seller.example.yaml` is versioned as
  the canonical template. Operators must copy and customize before running `publish-json`.
- **IMP-003**: Smoke test: `uv run ml-upload publish-json --help` and
  `uv run ml-upload publish-batch --help` must show both commands after any `app.py` change.
- **IMP-004**: Success criteria — `uv run pytest -q` passes with ≥ 60% coverage and all four
  quality gates (`ruff`, `black --check`, `mypy`, `pytest`) exit 0.

## References

- **REF-001**: ADR-0001 — Repository architecture (ADR placement convention)
- **REF-002**: `plans/json-payload-publisher/implementation.md` — full 5-step implementation spec
- **REF-003**: `mercadolivre_upload/application/ports.py` — `ItemPublisherPort` protocol reused
  by `publish_json_use_case.py`
- **REF-004**: Mercado Livre Items API — `POST /items`, `POST /items/{id}/description`
- **REF-005**: ADR-0004 (this session) — Seller Policy Validation Layer
- **REF-006**: ADR-0005 (this session) — Synchronous-Only Execution Model
