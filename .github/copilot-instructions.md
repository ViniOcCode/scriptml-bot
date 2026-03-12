# Copilot Instructions

## Test-Driven Generation (TDG) — required pattern

Always write tests before implementation. The sequence is:
1. Write the type signature (the contract)
2. Write failing tests that define correct behavior
3. Confirm tests fail for the right reason
4. Implement to make tests pass
5. Run the full quality gate (`ruff`, `black --check`, `mypy`, `pytest`)

Never paste implementation before the tests exist. If a `SKILL.md` exists under `skills/<domain>/` for the area being changed, read it first — it contains the domain model, invariants, state machines, and what NOT to do.

## Build, test, and lint commands

- Install dependencies (dev): `uv pip install -e ".[dev]"`
- Run full tests: `uv run pytest -q`
- Run a single test file: `uv run pytest tests/test_cli.py -q`
- Run a single test node: `uv run pytest tests/test_cli.py::TestUploadCommand::test_upload_success -q`
- Lint: `uv run ruff check .`
- Format check: `uv run black --check --diff .`
- Type check: `uv run mypy mercadolivre_upload/`
- Security check: `uv run bandit -q -c pyproject.toml -r mercadolivre_upload`
- Run hooks: `uv run pre-commit run --all-files`
- Build package (CI path): `python -m build` (CI installs `build` first)

## High-level architecture

- CLI entrypoint is `ml-upload` (`pyproject.toml`) -> `mercadolivre_upload.main:main` -> Typer app in `mercadolivre_upload/cli/app.py`.
- `cli.app.upload` is hybrid:
  - new flow when `--images` and `--category` are provided (delegates to `mercadolivre_upload.cli.commands.upload`)
  - legacy compatibility flow otherwise (uses `PublishProductService`).
- Composition root for publishing is `mercadolivre_upload/cli/commands/upload.py`, which wires:
  - infra/adapters: `AuthManager`, `MLApiClient`, `ImageUploader`, `ClipUploader`, `AttributeCache`, `PredictionCache`
  - domain/application services: `CategoryResolver`, `ShippingResolver`, `FiscalService`, `PublishProductUseCase`.
- Publishing pipeline (high level):
  1. `SpreadsheetParser` reads Excel and normalizes columns.
  2. `PublishProductUseCase.execute` resolves category (name match -> title predictor -> per-title fallback), resolves to leaf category, and converts row dicts to `Product`.
  3. Attribute building combines resolver metadata plus optional `CachedAttributeMapper`.
  4. Images/clips are uploaded and payload is published via `ItemPublisherPort`.
- Ports/protocols are in `mercadolivre_upload/application/ports.py`; use-cases depend on these Protocols, while API/adapters provide implementations.
- HTTP resilience is centralized in `mercadolivre_upload/infrastructure/http.py` and used by `MLApiClient` (`mercadolivre_upload/api/client.py`): retry policies, backoff+jitter, token-bucket limiter, `Retry-After`.
- Caching is file-based:
  - `AttributeCache` (`cache/categories/.attribute_cache.json`) stores category attributes with TTL.
  - `PredictionCache` stores domain-discovery results in SHA-256-hashed filenames.

## Key repository-specific conventions

- Preserve CLI compatibility exports in `mercadolivre_upload/cli/__init__.py` (`PublishProductService`, `AuthManager`); tests patch these import paths.
- Keep Portuguese-normalized matching behavior: header/category/attribute matching consistently uses `PortugueseTextNormalizer`/`TextNormalizer` and supports accented/unaccented variants.
- In the publish flow, pass an `AttributeCache` instance via `PublishProductUseCase(attribute_cache=...)`; cache mapper initialization is per category and intentionally optional/fallback-safe.
- `ImageUploader` expects images under `<images>/<SKU>/` first, then falls back to the base images directory if SKU folder is missing.
- `cli/commands/upload.py` merges split YAML configs (`standard_fields`, `shipping`, `attribute_rules`) as the runtime source of truth.

## Reusable agents

For Mercado Livre publish-flow changes, run these reusable sub-agents:

1. Docs agent: `.github/agents/mercadolivre-docs-agent.md`
2. Code review agent: `.github/agents/code-review-agent.md`
3. PR engineer agent: `.github/agents/pr-engineer-agent.md`

Recommended order:
- Run docs agent first to validate API behavior.
- Implement changes and tests.
- Run code review agent on diff.
- Run PR engineer agent to prepare commit and PR summary.
