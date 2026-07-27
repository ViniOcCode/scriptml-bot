# scriptml-bot AI context

## Role

This app is the publisher/validator boundary consumed by the current `mlbot`
dashboard. Builder payloads and `run_manifest.json` are immutable evidence; the
publisher must not reinterpret product truth or bypass dashboard ownership.

## Current runtime

- Configuration: `publisher_config` from `ml_app_settings_core` in SQLite, or
  an immutable per-process `MLBOT_PUBLISHER_CONFIG_SNAPSHOT`.
- Secrets: Bitwarden materialized files referenced by the exact `*_FILE`
  catalog.
- OAuth tokens: Fernet-encrypted SQLite rows in
  `OAuthCredentialRepository`.
- Identity: one active integration profile, seller confirmed through
  `/users/me`, expected seller ID and expected taxpayer document type.
- Publication: paused by default, duplicate-protected and bound to the current
  candidate/snapshot/hash/attempt chain.
- Failure semantics: confirmed rejection is `failed` with no side effect;
  ambiguous transport or response is `unknown` and requires reconciliation.

There is no production fallback to OpenBao, Vault, local token files,
plaintext environment secrets or operational YAML.

## Supported surfaces

- `mercadolivre_upload.application.dashboard_api`
- `ml-upload publish-payload`
- `ml-upload publish-manifest`
- `ml-upload reconcile`

The old spreadsheet publisher, local OAuth-token command, cache command and
doctor command are not production surfaces.

## Required safety behavior

- Use allowlisted update fields and explicit lifecycle operations.
- Validate item, profile, seller, candidate, execution, snapshot, attempt and
  payload hash relationships before remote mutation.
- Preserve structured per-item outcomes for `legacy_items` and
  `user_products`.
- Keep fiscal states explicit: `completed`, `not_applicable`, `pending`,
  `failed` or `unknown`.
- Never infer “no effect” from a transport failure.
- Never leak local metadata into Mercado Livre payloads.
- Reject workspace traversal and symlink escape.

## Verification

```bash
uv sync --frozen --extra dev
uv run pytest -q tests
uv run ruff check mercadolivre_upload
```
