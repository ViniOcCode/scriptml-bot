ADR 0001 — Repository architecture: ADRs and agent placement

Status: Accepted
Date: 2026-03-05

Context
- This repository contains the CLI, publishing pipeline, domain logic, infra code, and several agent/instruction documents under .github/agents and top-level AGENTS.md and llms.txt.
- Contributors need a consistent place for Architectural Decision Records (ADRs), an index for operator/developer-facing docs, and a lightweight migration plan that can be reviewed via PRs.

Decision
- Store ADRs in docs/adr/ using sequential numeric prefixes (0001, 0002, ...).
- Keep agent definitions in .github/agents/ and reference them from docs/index.md and AGENTS.md.
- Add docs/index.md as a single entry point for repository documentation and a short repo-architecture-plan.md for migration steps.

Recommended directory tree (high level)
- docs/
  - adr/
    - 0001-repo-architecture.md  # this file
    - 0002-...                   # future ADRs
  - index.md
  - repo-architecture-plan.md
- .github/agents/                 # existing agent definitions
- mercadolivre_upload/            # code
- tests/

Migration steps (short)
1. Add docs/adr and initial ADR (this file) and a small docs/index.md linking existing docs and agent files.
2. Open a PR from branch chore/docs-adr for maintainer review and CI validation.
3. Update AGENTS.md or README in a separate PR to reference docs/index.md if desired.

Rollback and risks
- Risk level: minimal (docs-only change). If the PR introduces an issue, revert the commit or close the PR; rollback is safe and trivial.

Consequences
- Improves discoverability of architecture decisions and agent definitions, reduces ad-hoc docs growth, and provides a stable place for future ADRs and migration notes.
