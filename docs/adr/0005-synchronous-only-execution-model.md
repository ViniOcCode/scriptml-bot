---
title: "ADR-0005: Synchronous-Only Execution Model"
status: "Accepted"
date: "2026-03-24"
authors: "Architecture / Maintainers"
tags: ["architecture", "decision", "concurrency", "http"]
supersedes: ""
superseded_by: ""
---

# ADR-0005: Synchronous-Only Execution Model

## Status

Proposed | **Accepted** | Rejected | Superseded | Deprecated

## Context

The `mercadolivre_upload` package orchestrates multi-step I/O-bound operations: reading files,
calling the Mercado Livre API (item creation, image upload, description posting), and writing
reports. The original SDD spec for the JSON Payload Publisher (ADR-0003) proposed an `async def`
use-case interface. Investigation of the existing codebase revealed that:

- All 113 source files in `mercadolivre_upload/` are fully synchronous (`def`, not `async def`).
- `MLApiClient` uses `requests` (synchronous) with `urllib3` retry adapters — no `httpx`,
  `aiohttp`, or `asyncio` primitives anywhere.
- `AuthManager` / `TokenManager` are synchronous.
- Test infrastructure uses `unittest.mock.patch`, `MagicMock`, and `typer.testing.CliRunner` —
  all synchronous; there is no `pytest-asyncio` in `pyproject.toml`.
- The Mercado Livre API enforces rate limits (documented as ~20 req/s for the items endpoint);
  concurrency without a proven token-bucket strategy introduces risk of 429 responses.

Introducing `async def` in the new use-case would require changes to `MLApiClient`, `AuthManager`,
test infrastructure, and the CLI runner — a large blast radius for a speculative throughput gain.

## Decision

The payload publish use-cases and CLI commands (`publish-payload`, `publish-manifest`)
are implemented as synchronous (`def`, not `async def`). Batch publishing in `publish-manifest`
processes items sequentially.

The existing HTTP resilience layer (`infrastructure/http.py` — retry, backoff+jitter, token-bucket
rate limiter, `Retry-After` handling) already handles transient failures gracefully for sequential
requests. No new concurrency primitives are introduced.

This decision is intentionally revisable: when the synchronous baseline is validated in production
and throughput becomes a measured bottleneck, a future ADR may introduce concurrent publishing
(e.g., `httpx` + `asyncio.gather` with the existing token-bucket limiter).

## Consequences

### Positive

- **POS-001**: Zero changes to `MLApiClient`, `AuthManager`, or any existing infrastructure module
  — the new use-case reuses existing synchronous interfaces without adaptation.
- **POS-002**: Test infrastructure remains simple: `MagicMock`, `patch`, `typer.testing.CliRunner`
  — no `pytest-asyncio`, `AsyncMock`, or `anyio` fixtures needed.
- **POS-003**: Synchronous sequential publishing is inherently rate-limit safe — no risk of
  bursting the ML API with concurrent requests.
- **POS-004**: Error handling is straightforward: an exception from `create_item()` surfaces
  immediately to the caller without `asyncio` task cancellation complexity.
- **POS-005**: CLI invocation is simple: `typer` and `CliRunner` handle synchronous commands
  natively; no `asyncio.run()` wrapper needed at the entry point.

### Negative

- **NEG-001**: Batch publishing throughput is proportional to round-trip latency per item;
  for large batches (>50 items) this may be noticeably slow compared to concurrent approaches.
- **NEG-002**: If the ML API introduces long-polling or webhook callbacks in the future, the
  synchronous model will require significant refactoring.
- **NEG-003**: The synchronous model cannot benefit from connection pooling across concurrent
  requests — each sequential request reuses the same `requests.Session` but does not overlap I/O.

## Alternatives Considered

### `async def` use-case with `asyncio.run()` at CLI boundary

- **ALT-001**: **Description**: Define `PublishJsonUseCase.execute()` as `async def` and wrap it
  with `asyncio.run()` in the Typer command function, requiring `MLApiClient` to be ported to
  `httpx` or wrapped in `asyncio.to_thread`.
- **ALT-002**: **Rejection Reason**: Requires changes to `MLApiClient` (synchronous `requests`)
  and `AuthManager` (synchronous token refresh), plus new async test infrastructure
  (`pytest-asyncio`, `AsyncMock`). The blast radius is too large relative to the speculative
  throughput benefit for the initial implementation.

### `concurrent.futures.ThreadPoolExecutor` for parallel batch

- **ALT-003**: **Description**: Run multiple `create_item()` calls in a thread pool inside
  `publish_batch()` for parallel I/O without async/await.
- **ALT-004**: **Rejection Reason**: Thread-based parallelism with shared `requests.Session`
  requires thread-safety analysis of `MLApiClient` and `TokenManager`. Rate-limit handling
  (token-bucket in `infrastructure/http.py`) is not thread-safe as currently implemented.
  Risk outweighs the benefit for the initial release.

### Full port to `httpx` + `asyncio`

- **ALT-005**: **Description**: Replace `requests` with `httpx` throughout `MLApiClient` and
  adopt `async def` as the standard for all I/O-bound methods.
- **ALT-006**: **Rejection Reason**: A full HTTP client migration is a repo-wide breaking change
  requiring updates to all 499 existing tests, retry/backoff logic, and the token-bucket rate
  limiter. This is a significant architectural undertaking that should be planned independently,
  not bundled with a feature addition.

## Implementation Notes

- **IMP-001**: All new use-case and CLI code uses `def` (not `async def`) — no `asyncio` imports
  in the new modules. This is enforced by code review.
- **IMP-002**: When batch throughput becomes a measured production concern, create a new ADR
  proposing a concurrent approach. At that point, the `PublishJsonUseCase` interface can be
  extended without changing the synchronous baseline.
- **IMP-003**: The existing `infrastructure/http.py` rate limiter (token-bucket + `Retry-After`)
  applies automatically to all `MLApiClient` calls, providing resilience for sequential batches.
- **IMP-004**: Success metric: `publish-manifest` of 10 items should complete in under 60 seconds
  on a standard network; measure in production before declaring throughput a bottleneck.

## References

- **REF-001**: ADR-0003 — JSON Payload Publisher (the feature that triggered this decision)
- **REF-002**: `mercadolivre_upload/infrastructure/http.py` — synchronous HTTP resilience layer
- **REF-003**: `mercadolivre_upload/api/client.py` — synchronous `MLApiClient` using `requests`
- **REF-004**: `pyproject.toml` — dependency list (no `httpx`, `aiohttp`, or `pytest-asyncio`)
- **REF-005**: Mercado Livre API rate limit documentation
