# Repository Guidelines

## Project Structure & Module Organization
Core application code lives in `mercadolivre_upload/`, organized by layer:
- `cli/` for Typer commands (`upload`, `validate`, `doctor`, `cache`)
- `application/` for use cases and orchestration
- `domain/` for business rules and models
- `infrastructure/` for HTTP, logging, metrics, migration, and cache
- `adapters/` for spreadsheet/image/clip integrations

Tests are in `tests/` and follow feature-focused files such as `test_publish_product.py` and `test_validate_command.py`. Runtime configs live in `config/*.yaml`. Generated reports and cache artifacts are written under `cache/` (especially `cache/reports/`).

## Build, Test, and Development Commands
- `uv pip install -e ".[dev]"`: install runtime + dev dependencies.
- `uv run ml-upload --help`: inspect CLI entrypoints.
- `uv run pytest -q`: run full test suite with coverage threshold checks.
- `uv run ruff check .`: lint and import-order checks.
- `uv run black --check --diff .`: formatting validation.
- `uv run mypy mercadolivre_upload/`: strict type checking.
- `uv run bandit -q -c pyproject.toml -r mercadolivre_upload`: security scan.
- `uv run pre-commit run --all-files`: execute local quality gates before pushing.

## Coding Style & Naming Conventions
Use Python 3.13, 4-space indentation, and max line length 100. Format with Black and lint with Ruff. Keep module names `snake_case`; classes `PascalCase`; functions/variables/tests `snake_case`. Prefer typed public interfaces; project mypy mode is strict for runtime code.

## Testing Guidelines
Pytest discovers `tests/test_*.py`, `Test*` classes, and `test_*` functions. Coverage is enforced at `>=60%` for `mercadolivre_upload` (`--cov-fail-under=60`). Use markers (`unit`, `integration`, `slow`) when appropriate. Add or update tests in the nearest domain/feature file for every behavioral change.

## Commit & Pull Request Guidelines
Follow Conventional Commit style seen in history: `feat: ...`, `fix: ...`, `refactor(scope): ...`, `docs: ...`, `test: ...`, `cleanup: ...`. Keep subject lines imperative and specific.

For PRs, include:
- concise problem/solution summary
- linked issue (if applicable)
- validation evidence (commands run and outcomes)
- sample CLI output or report-path examples when behavior changes

Ensure CI parity locally by running lint, format, mypy, pytest, and bandit before opening the PR.

Always use the OpenAI developer documentation MCP server if you need to work with the OpenAI API, ChatGPT Apps SDK, Codex,… without me having to explicitly ask.

Always use the Mercado Libre MCP server if you need to work with the mercado libre documentation and doubts about the api, without me having to explicitly ask.

Always use Context7 MCP when I need library/API documentation, code generation, setup or configuration steps without me having to explicitly ask.
