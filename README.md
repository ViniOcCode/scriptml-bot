# Mercado Livre Bulk Upload (`ml-upload`)

CLI application for validating and publishing Mercado Livre listings from Excel spreadsheets, with category/attribute resolution, image handling, and report generation.

## What this app does

- Reads `.xlsx` and `.xls` spreadsheets and normalizes common Portuguese/English headers.
- Resolves categories and required metadata before publish.
- Uploads product images (and optional clips in the publish flow).
- Supports validation-only runs (`validate`) and publish runs (`upload`).
- Writes machine-readable reports in `cache/reports/` for retry and auditing.

## Requirements

- Python `>=3.13`
- [uv](https://docs.astral.sh/uv/)

## Installation

```bash
# Development install (same dependency set used by CI)
uv pip install -e ".[dev]"

# Runtime-only alternative
uv pip install -r requirements.txt
```

Entrypoint: `ml-upload` -> `mercadolivre_upload.main:main`.

## Quick workflow (recommended)

### 1) Configure authentication

- Secure token storage is enabled by default.
- Default token path behavior:
  - if `MERCADO_LIVRE_TOKEN_PATH` is unset, runtime uses `tokens.json.enc`
  - if `MERCADO_LIVRE_TOKEN_PATH=tokens.json`, runtime stores encrypted tokens in
    `tokens.json.enc`
- Persisted token payload stores only:
  - `access_token`
  - `refresh_token`
  - `expires_at`
- Plaintext mode is explicit opt-out only:
  - `MERCADO_LIVRE_USE_SECURE_STORAGE=0`
- Migration behavior:
  - `MERCADO_LIVRE_AUTO_MIGRATE_TOKENS` defaults to enabled in secure mode
  - existing plaintext `tokens.json` is migrated automatically to `.enc` (backup created as
    `tokens.json.backup`)
- Secure mode errors (key setup/decryption/migration) fail explicitly.

#### External secret managers (1Password, Vault, etc.)

No code changes are required. The app already reads sensitive values from environment variables, so
you can inject them at runtime from your secret manager:

- `MERCADO_LIVRE_CLIENT_ID`
- `MERCADO_LIVRE_CLIENT_SECRET`
- `MERCADO_LIVRE_REDIRECT_URI` (if not using the default callback URL)
- `ENCRYPTION_KEY` (recommended for CI/non-interactive environments, required when keyring is
  unavailable)

Example with 1Password CLI:

```bash
# .env.1password (secret references, not plaintext)
MERCADO_LIVRE_CLIENT_ID=op://<vault>/<item>/client_id
MERCADO_LIVRE_CLIENT_SECRET=op://<vault>/<item>/client_secret
ENCRYPTION_KEY=op://<vault>/<item>/encryption_key
MERCADO_LIVRE_REDIRECT_URI=op://<vault>/<item>/redirect_uri
```

```bash
op run --env-file=.env.1password -- \
  uv run ml-upload validate anuncios/2.xlsx -i anuncios/ -c "quadros decorativos"
```

Important behavior to plan for:

- Tokens are still persisted locally in an encrypted file (`tokens.json.enc` by default).
- `ENCRYPTION_KEY` must stay stable to decrypt existing token files.
- Use `MERCADO_LIVRE_TOKEN_PATH` if you want a custom token-file location.

#### Access/refresh token lifecycle in secure mode

- `get_access_token()` reads `access_token`.
- If token is expired and `auto_refresh=True`, the app uses `refresh_token` to request new
  credentials and persists updated `access_token`/`refresh_token`/`expires_at`.
- If `refresh_token` is missing, refresh fails with an explicit auth error.

### 2) Prepare input files

- Spreadsheet: `.xlsx` or `.xls`.
- Images: the uploader searches `<images>/<SKU>/` first; if the SKU folder is missing, it falls back to the base images folder.

Example layout:

```text
anuncios/
├── 12345/
│   ├── foto1.jpg
│   └── foto2.png
└── 67890/
    └── imagem-principal.jpg
```

### 3) Validate first

```bash
uv run ml-upload validate anuncios/2.xlsx -i anuncios/ -c "quadros decorativos"
```

### 4) Publish

```bash
uv run ml-upload upload anuncios/2.xlsx -i anuncios/ -c "quadros decorativos" --batch-size 5
```

### 5) Check generated reports

Default report directory: `cache/reports/`

- Validation run: `validation-summary-<timestamp>.json`
- Upload run: `upload-summary-<timestamp>.json`
- Upload failures (only when failures happen): `failed-items-<timestamp>.xlsx`

## CLI reference

```bash
ml-upload --help
```

| Command | Purpose |
| --- | --- |
| `ml-upload upload` | Publish products |
| `ml-upload validate` | Validate products without publishing |
| `ml-upload auth` | Set/refresh token and inspect auth status |
| `ml-upload cache clear` | Clear attribute cache |
| `ml-upload cache status` | Show cache status |
| `ml-upload doctor` | Run environment health checks |

### Common options

- `upload` and `validate`:
  - `EXCEL` positional argument **or** `--excel/-e`
  - `--images/-i`
  - `--category/-c`
  - `--batch-size` (default: `5`)
  - `--report-dir` (default: `cache/reports`)
  - `--detailed`
- `upload` also supports `--verbose`.

> `--category/-c` must be passed as an option (not as a positional argument).

## Configuration

Runtime YAML configuration is merged from:

- `config/standard_fields.yaml`
- `config/shipping.yaml`
- `config/attribute_rules.yaml`

Config ownership map:

- `standard_fields.yaml`: base field mapping/defaults used by upload flow and `SmartAttributeMapper`.
- `shipping.yaml`: shipping policy toggles consumed by `ShippingResolver`.
- `attribute_rules.yaml`: attribute classification/sanitization/scoring rules.
- `fiscal_config.yaml`: fiscal defaults and value mappings consumed by fiscal domain.

Key behavior controlled there includes:

- explicit/automatic field mapping rules
- shipping and listing behavior
- warning gates and rollout routing
- defaults for sale terms, required core fields, and attribute handling

## Architecture snapshot

- CLI entrypoint: `ml-upload` -> `mercadolivre_upload.main:main` -> Typer app in `mercadolivre_upload/cli/app.py`.
- Composition root for upload/validate wiring: `mercadolivre_upload/cli/commands/upload.py`.
- Publish orchestration: `PublishProductUseCase` (`mercadolivre_upload/application/publish_product.py`).
- Protocol ports (clean boundaries): `mercadolivre_upload/application/ports.py`.
- Resilient HTTP client (retry/backoff/rate limit): `mercadolivre_upload/infrastructure/http.py`.
- Caches:
  - category attributes under `cache/categories/`
  - category predictions under `cache/categories/predictions/`

## Development commands

```bash
# Tests
uv run pytest -q
uv run pytest tests/test_cli.py -q

# Lint, format, typing, security
uv run ruff check .
uv run black --check --diff .
uv run mypy mercadolivre_upload/
uv run bandit -q -c pyproject.toml -r mercadolivre_upload

# Hooks
uv run pre-commit run --all-files
```

## Troubleshooting

- **"Arquivo nao encontrado"**: verify spreadsheet path and extension (`.xlsx`/`.xls`).
- **No images uploaded for SKU**: confirm image names/extensions and folder structure under `--images`.
- **Auth errors**: verify token file path, encryption key/keyring setup, and refresh token validity.
- **Unexpected attribute validation failures**: inspect the generated JSON summary report and adjust mapping rules in `config/standard_fields.yaml` / `config/attribute_rules.yaml`.
