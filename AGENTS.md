# AGENTS.md

## Project overview

This repository provides a Python CLI and publishing pipeline for Mercado Livre product uploads (package: `mercadolivre_upload`). The CLI entrypoint is `ml-upload` (pyproject.toml -> `mercadolivre_upload.main:main`) and commands live under `mercadolivre_upload/cli` (notably `cli/app.py` and `cli/commands/upload.py`). The codebase is Python 3.13-oriented and organized into `cli/`, `application/`, `domain/`, `infrastructure/`, `adapters/`, and `tests/`.

---

## Agent-focused quick start

- Install dev dependencies (preferred wrapper used in local docs):

```bash
uv pip install -e "[dev]"
```

- Run the CLI help:

```bash
uv run ml-upload --help
```

- Validate a sample spreadsheet (safe, read-only validation):

```bash
uv run ml-upload validate anuncios/2.xlsx -i anuncios/ -c "quadros decorativos"
```

- Run the full test suite (may enforce coverage gates):

```bash
uv run pytest -q
```

- Run a single test file or node (avoid full coverage gate when iterating):

```bash
uv run pytest tests/test_cli.py -q
# or, to avoid the coverage gate during focused runs:
uv run pytest tests/test_spreadsheet_parser.py --override-ini addopts='' -q
```

---

## Key commands and developer tooling

- Lint with Ruff:

```bash
uv run ruff check .
```

- Format check with Black:

```bash
uv run black --check --diff .
```

- Type checking:

```bash
uv run mypy mercadolivre_upload/
```

- Security scan:

```bash
uv run bandit -q -c pyproject.toml -r mercadolivre_upload
```

- Run pre-commit hooks locally:

```bash
uv run pre-commit run --all-files
```

- Build package (CI path):

```bash
python -m build
```

---

## Where to look (high-value files)

- CLI entry & composition: `mercadolivre_upload/cli/app.py`, `mercadolivre_upload/cli/commands/upload.py`
- Publish use-case orchestration: `mercadolivre_upload/application/publish_product.py`
- HTTP resilience & client: `mercadolivre_upload/infrastructure/http.py` and `mercadolivre_upload/api/client.py`
- Caches: `cache/` (attribute and prediction caches)
- Runtime config: `config/standard_fields.yaml`, `config/shipping.yaml`, `config/attribute_rules.yaml`, `config/fiscal_config.yaml`
- Tests: `tests/` (unit and integration scenarios). Many tests assume the CLI exports and compatibility shims remain present.
- Top-level scripts: `main.py`, `README.md`, `pyproject.toml`.

---

## Testing & CI notes (agent-relevant)

- Pyproject enforces coverage (`--cov-fail-under=60`) for the package; when running targeted tests during development use `--override-ini addopts=''` or run single-file commands to avoid unrelated coverage failures.
- The test suite contains integration-style scenarios; adding or changing behavior in the publish flow typically requires updating/adding tests near the affected use-case files (see tests referencing `PublishProductUseCase`).
- Before opening PRs, run the quality gates: `ruff`, `black --check`, `mypy`, `pytest` (or targeted tests during iteration), and `bandit` if security-sensitive changes were made.

---

## Code style & conventions

- Python 3.13, 4-space indentation, max line length ~100. Format with Black; lint with Ruff. Keep module names snake_case and classes PascalCase.
- Follow existing typing and strict mypy expectations for public interfaces.
- Commit messages follow Conventional Commits. When making automated commits from an agent, prefer the Conventional Commit format and include the required Co-authored-by trailer: `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`.

---

## Safe agent actions (allowed)

- Run tests, linters, formatters, static analyzers, and security scans.
- Create or update documentation, README, and AGENTS.md contents.
- Make small, well-tested code changes that include unit tests and follow the repo's conventions.
- Open PRs using Conventional Commits and include test evidence in PR description.

---

## Restricted actions (ask a human)

- Do not run `ml-upload upload` against real Mercado Livre accounts or use real API credentials without an explicit human-provided test environment and approval.
- Do not commit API keys, tokens, or other secrets into the repository. If a change requires secret handling, request guidance and use environment-based injection / vaults.
- Structural changes that alter the publishing flow, release process, or external API contracts should be reviewed by a maintainer.

---

## PR and review guidance for agents

- Title: use Conventional Commit format: `feat(upload): <short description>`
- Ensure all added behavior has tests; run `uv run pytest -q` and `uv run ruff check .` locally before creating a PR.
- Include a short validation section in the PR description showing commands run and outcomes (test commands and sample CLI output or report paths).

---

## Helpful shortcuts & tips

- Use `uv run ml-upload validate <file> -i <images_dir> -c "<category name>"` for quick validation checks on example spreadsheets.
- Use the `anuncios/` fixtures under repository root to reproduce common validation scenarios.
- When editing mapping/config YAML, check `config/` split files: `standard_fields.yaml`, `attribute_rules.yaml`, and `shipping.yaml`.

---

## Contact / escalation

If unsure about a change's safety (credentials, publish flow, or backwards-compatibility), create an issue and ping a human maintainer rather than merging the change.

---

## File provenance

This AGENTS.md is machine-readable guidance for coding agents operating on this repository. Keep it up to date when the build, test, or release processes change.
