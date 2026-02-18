# Mercado Libre Bulk Upload (ml-upload)

A CLI tool to prepare, validate and publish product listings to Mercado Libre from Excel spreadsheets. It handles image uploads, category prediction, attribute mapping, caching, and resilient HTTP uploads to the Mercado Libre API.

## Quick start

- Install (development):

  ```bash
  uv pip install -e ".[dev]"
  # or
  uv pip install -r requirements.txt
  ```

- CLI entrypoint (pyproject): `ml-upload` → `mercadolivre_upload.main:main`

- Common commands:

  ```bash
  ml-upload --help
  ml-upload upload <SPREADSHEET.xlsx> --images <dir> --category "<Cat>" [--dry-run] [--batch-size 5]
  ml-upload validate <SPREADSHEET.xlsx> --images <dir> --category "<Cat>"
  ml-upload doctor
  ml-upload cache --help
  ```

- Legacy fallback paths were removed: both `upload` and `validate` now run only through the new flow.
- Upload runs generate JSON summary reports and, when failures happen, an Excel file with failed rows
  under `cache/reports/` for easier retry.

## Authentication flow

- OAuth2 authorization/code exchange is done manually outside the CLI.
- Store the returned tokens in `tokens.json` (or set `MERCADO_LIVRE_TOKEN_PATH`).
- The app uses `TokenManager` to auto-refresh access tokens when expired.
- After refresh, always persist the newest `refresh_token` returned by Mercado Libre.

## Build, test & lint

- Full test suite:

  ```bash
  uv run pytest
  ```

- Run a single test / file:

  ```bash
  uv run pytest tests/test_cli.py -q
  uv run pytest tests/test_spreadsheet_parser.py::test_parse_row -q
  ```

- Lint & format:

  ```bash
  uv run ruff check .
  uv run black --check .
  uv run mypy mercadolivre_upload/
  uv run pre-commit run --all-files
  ```

## What this project does (overview)

Implements a robust pipeline to publish products on Mercado Libre by transforming spreadsheets into canonical product payloads and publishing them via the Mercado Libre API. Key features:

- Spreadsheet parsing with header detection and resilient row parsing.
- Title-based and ML-based category prediction and attribute mapping.
- Image uploading adapters and payload builders for Mercado Libre.
- Resilient HTTP client with retry/backoff, rate limiting, and `Retry-After` handling.
- Caching of category attributes and prediction results to speed repeated runs.

## High-level architecture

Clean Architecture with dependency inversion via Protocol ports. Main folders:

```
mercadolivre_upload/
├── cli/              # Typer app + commands (upload, validate, doctor, cache)
├── application/      # Use-cases (PublishProductUseCase), builders, validators
│   ├── ports.py      # Protocol interfaces (ImageUploaderPort, ItemPublisherPort, …)
│   └── builders/     # Payload builders: product, attribute, picture, shipping, variation
├── domain/           # Pure models & rules — no I/O
├── api/              # ML API clients (sync/async, adapters)
├── adapters/         # I/O: spreadsheet parsers, image uploaders
├── auth/             # OAuth, TokenManager, secure token storage helpers
├── infrastructure/   # Cache, config (Pydantic), http (ResilientHTTPClient), logging
├── shared/           # Shared utilities
└── utils/            # Text normalization, error helpers
```

### Data flow

Excel → `SpreadsheetParser` → canonical `Product` model → `PublishProductUseCase` (orchestrates `CategoryResolver`, `AttributeBuilderService`, payload `builders/`, `ImageUploaderPort`, `ItemPublisherPort`) → Mercado Libre API.

### Ports & adapters

`application/ports.py` defines Protocol interfaces (`ImageUploaderPort`, `ItemPublisherPort`, `ShippingResolverPort`, `ClipUploaderPort`); infrastructure/adapters implement these ports so use-cases stay infrastructure-agnostic.

### HTTP resilience

`infrastructure/http.py` provides `ResilientHTTPClient` with named retry policies (`SAFE_RETRY`, `NO_RETRY`, `UPLOAD_RETRY`, `NON_IDEMPOTENT`), exponential backoff + jitter, `Retry-After` support, and a `TokenBucketLimiter` used by `MLApiClient`.

### Caching

- `AttributeCache` stores category attribute data under `cache/`.
- `PredictionCache` uses SHA-256 hashed filenames for filesystem safety.
- `CachedAttributeMapper` reads from `AttributeCache` and is passed cache instances from the CLI into use-cases.

### Configuration

Uses `pydantic-settings` (`BaseSettings`) with `.env` support and YAML configuration files in `config/` (e.g., `attribute_rules.yaml`, `fiscal_config.yaml`, `shipping.yaml`, `header_detection.yaml`).

## Conventions

- Line length: 100, target Python: 3.13 (enforced by black + ruff + mypy).
- Commit messages: `<type>(<scope>): <description>` (e.g., `fix(cli): corrected syntax`).
- Centralized text normalization (`utils/text.py`) and validators (`domain/validation/`).
- Async for I/O (image uploads and network calls use `aiohttp`); CPU-bound work remains synchronous.
- Images layout: `anuncios/<SKU>/foto1.jpg` (SKU = folder name).
- Secrets: tokens handled via `tokens.json` / keyring; do not commit secrets.
- Tests: `tests/` with markers `unit`, `integration`, `slow`.

## Project status (standardization summary)

- Standardization run completed phases 1, 2, 3, 4 and 6; Phase 5 (architecture violations refactor) was deferred and requires planned refactoring.
- Production tests reported passing in the standardization run.

## Contributing & notes

- If changing public APIs (domain models, builders, use-cases), update tests and run the full test suite before proposing changes.
- Always verify payloads against the Mercado Libre API documentation when adjusting builders or publishers.

---

If something important was removed by this consolidation, please restore the original markdown files from your branch or commit history.
