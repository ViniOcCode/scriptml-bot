# Mercado Livre publisher (`ml-upload`)

`scriptml-bot` validates and publishes immutable builder payloads and
`run_manifest.json` artifacts. The dashboard and worker are the supported
production control plane.

## Production contract

- Operational publisher configuration comes from the versioned
  `publisher_config` document in the dashboard SQLite database.
- The worker may pass an immutable `MLBOT_PUBLISHER_CONFIG_SNAPSHOT` for one
  child process.
- Secrets are materialized by the Bitwarden init container and consumed only
  through the catalogued `*_FILE` variables.
- OAuth access and refresh tokens are encrypted in SQLite by
  `OAuthCredentialRepository` using `OAUTH_TOKEN_ENCRYPTION_KEY`.
- Real publication is bound to the active integration profile, authenticated
  seller and taxpayer identity.
- New listings are created paused. Ambiguous remote effects return `unknown`
  and require reconciliation.

OpenBao/Vault, plaintext tokens, `.ml_token.enc`, `tokens.json` and operational
YAML are not production fallbacks.

## Supported CLI

The packaged entrypoint is:

```bash
ml-upload --help
```

Supported commands are:

- `publish-payload`
- `publish-manifest`
- `reconcile`

All require an explicit `--workspace`. Production also requires
`MLBOT_SETTINGS_DB`, a complete secret-file snapshot and the active encrypted
OAuth credential. Spreadsheet `upload`/`validate` and local `auth` commands are
intentionally absent because they bypass the current publication chain.

Safe validation example (the default):

```bash
ml-upload publish-manifest workspace/runs/RUN_ID/run_manifest.json \
  --workspace workspace \
  --publish-inactive
```

Real publication additionally requires both explicit intent and the exact
confirmation literal:

```bash
ml-upload publish-manifest workspace/runs/RUN_ID/run_manifest.json \
  --workspace workspace \
  --execute \
  --confirm PUBLICAR \
  --publish-inactive
```

The exported `PublishProductUseCase` follows the same boundary: it defaults to
`dry_run=True`; callers that deliberately select `dry_run=False` must also pass
`execute=True` and `confirmation="PUBLICAR"`.

The dashboard remains the preferred interface because it owns candidate,
snapshot, attempt, identity and audit relationships.

## Development

From this repository inside the `mlbot` workspace:

```bash
uv sync --frozen --extra dev
uv run pytest -q tests
uv run ruff check mercadolivre_upload
```

Development and tests may pass an explicit YAML fixture with `--config`; the
runtime loader accepts it only when `APP_ENV` is `development` or `test`.
Production never falls back to that file.

## Security invariants

- Do not commit secrets, SQLite databases, generated artifacts or customer
  payloads.
- Do not retry a mutation after an ambiguous transport outcome.
- Do not publish across profiles or sellers.
- Do not accept payload or report paths outside the configured workspace and
  app-data roots.
- Do not turn reconciliation-required outcomes into success.
