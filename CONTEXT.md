# scriptml-bot Context

`scriptml-bot` is the Mercado Livre publisher/validator module consumed by the dashboard and root orchestration.

## Dashboard boundary

- The dashboard must call publisher functionality through queued jobs or explicit candidate actions, not by changing publisher internals directly.
- Dry-run/simulation is the default mode exposed to humans.
- Real publication requires the dashboard app policy `automation_mode=full_automation` and explicit user confirmation.
- Seller configuration comes from local config/env files; secrets must not be committed.

## Contracts

- Payload files and `run_manifest.json` remain the handoff contract from builder to publisher.
- Publisher reports are written to dashboard app-data when invoked from dashboard jobs.
- Remote item updates must be dry-run by default and require item-id confirmation for real mutation.
