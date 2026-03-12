---
title: "ADR-0002: Remove Legacy Compatibility Shims and Dead Infrastructure Facades"
status: "Accepted"
date: "2026-03-12"
authors: "Architecture / Maintainers"
tags: ["architecture", "cleanup", "compatibility", "infrastructure"]
supersedes: ""
superseded_by: ""
---

# ADR-0002: Remove Legacy Compatibility Shims and Dead Infrastructure Facades

## Status

Proposed | **Accepted** | Rejected | Superseded | Deprecated

## Context

Over time the codebase accumulated three distinct layers of dead or redundant code
that added cognitive overhead and created false signals during audits:

1. **Root-level compatibility shims** — `main.py` (repo root) and `auth/__init__.py` /
   `auth/authenticator.py` were thin redirect modules that simply delegated to the real
   implementations inside the `mercadolivre_upload` package. The installed CLI entry point
   (`ml-upload`) already pointed directly to `mercadolivre_upload.main:main` via
   `pyproject.toml`, making the root `main.py` fully unreachable in normal usage.

2. **`mercadolivre_upload/compat/` package** — Four shim modules
   (`auth_exports.py`, `authenticator.py`, `entrypoints.py`, `__init__.py`) existed to
   bridge the root shims to the real auth implementation. With the root shims present, the
   compat layer was indistinguishable from live code during static analysis.

3. **Dead infrastructure facades** — `infrastructure/migration.py` (727 lines, full
   V1→V2→V3 schema migration framework) and `infrastructure/observability.py` (690 lines,
   `ObservabilityManager`, `Dashboard`, `AlertManager`) had **zero runtime callers**. They
   were re-exported through `infrastructure/__init__.py` and tested in isolation, but no
   CLI command, application service, or use-case ever invoked them. The `infrastructure/__init__.py`
   also maintained a lazy `__getattr__` loader specifically for the observability facade.

The combined dead code totalled approximately **2,400 lines** across 10 source files and
9 test files, with an import chain four levels deep (root shim → compat → real module).

## Decision

Remove all three layers in a single branch (`legacy-cleanup`) using four reversible,
sequentially committed steps, each verified before proceeding:

1. Delete root `main.py` shim and `compat/entrypoints.py`; prune the corresponding
   contract test assertions.
2. Delete `auth/__init__.py`, `auth/authenticator.py`, and `compat/authenticator.py`
   (note: `compat/authenticator.py` is kept because it contains the real `AuthCredentials`,
   `TokenData`, `AuthStatus`, and compatibility `AuthManager` class used by tests).
   Update `tests/test_authenticator.py` to import from `mercadolivre_upload.compat.authenticator`
   directly.
3. Remove `AuthManager` re-export from `cli/__init__.py`, delete `compat/auth_exports.py`
   and `compat/__init__.py`; redirect `_get_auth_manager_cls()` in `cli/app.py` to import
   from `mercadolivre_upload.auth` directly; update `tests/test_cli.py` patch paths.
4. Delete `infrastructure/migration.py`, `infrastructure/observability.py`, and their
   5 test files; prune the migration re-exports and lazy observability loader from
   `infrastructure/__init__.py`.

The live internals (`infrastructure/internals/observability/logger.py`,
`metrics.py`, `helpers.py`) are explicitly **kept** — `StructuredLogger` and
`BusinessMetricsCollector` are imported by `infrastructure/__init__.py` and used at runtime.

## Consequences

### Positive

- **POS-001**: Eliminates ~2,400 lines of dead or redundant code (10 source files, 9 test files), reducing the maintenance surface.
- **POS-002**: Removes a four-level-deep import indirection chain (`root → compat → auth → token_manager`) that was invisible to grep-based audits.
- **POS-003**: Reduces false signals during future dead-code analysis — deleted symbols no longer appear in `__all__` exports or `infrastructure/__init__.py` re-exports.
- **POS-004**: Improves cold-import performance by removing the lazy `__getattr__` observability loader from `infrastructure/__init__.py`.
- **POS-005**: Each step is a standalone, reversible commit, making the PR easy to review incrementally and trivially revertable.

### Negative

- **NEG-001**: Any external code that imported from `auth.*`, `mercadolivre_upload.cli.AuthManager`, or the migration/observability facades will break. No known external consumers exist, but this is a public API surface change.
- **NEG-002**: `compat/authenticator.py` is retained (it is implementation, not a shim), meaning the `compat/` directory still exists with a single file — this may be surprising until a future cleanup moves or renames it.
- **NEG-003**: The migration framework (`V1ToV2Migration`, `V2ToV3Migration`, etc.) is removed. If spreadsheet schema versioning is needed in the future it must be rebuilt or the commit reverted.

## Alternatives Considered

### Deprecation with Warnings

- **ALT-001**: **Description**: Keep all shim files but add `DeprecationWarning` on import to give consumers a migration window before removal.
- **ALT-002**: **Rejection Reason**: No external consumers were identified; adding warnings for internal-only code creates noise without benefit and delays the actual cleanup indefinitely.

### Stub/Raise Shims

- **ALT-003**: **Description**: Replace shim bodies with `raise ImportError("removed in X.Y")` stubs to produce clear error messages.
- **ALT-004**: **Rejection Reason**: Same as ALT-002 — no external consumers. Stubs still appear in grep results and static analysis, negating the audit-clarity benefit.

### Keep Dead Infrastructure as Optional Plugin

- **ALT-005**: **Description**: Move `migration.py` and `observability.py` to an optional extras package (`pip install mercadolivre-upload[observability]`).
- **ALT-006**: **Rejection Reason**: The modules have no documented users and no test coverage from the publish flow. Packaging them as extras would add CI complexity without demonstrated value. They can be reintroduced with proper integration if needed.

## Implementation Notes

- **IMP-001**: The removal was executed on branch `legacy-cleanup` (4 commits: `296b7ea`, `41e6793`, `3d1ffef`, `e92ba7a`). To revert any single step use `git revert <hash>`.
- **IMP-002**: `mercadolivre_upload/compat/authenticator.py` is intentionally retained — it is the real implementation of `AuthCredentials`, `TokenData`, `AuthStatus`, the compat `AuthManager` constructor, `create_auth_manager`, and `get_auth_url`. It should be migrated to `mercadolivre_upload/auth/` in a future step.
- **IMP-003**: Full quality gate passes post-removal: `pytest -q` (591 passed, 76.89% coverage), `ruff check` (clean), `black --check` (clean), `mypy` (clean), `bandit` (clean), `ml-upload validate` smoke test (10 products validated).
- **IMP-004**: `infrastructure/internals/migration/` and `infrastructure/internals/observability/` are **kept**. These internal modules are still imported by `infrastructure/__init__.py` (`Field`, `FieldType`, `SchemaVersion`, `Version`, `StructuredLogger`, `BusinessMetricsCollector`, `HourlyStats`).

## References

- **REF-001**: ADR-0001 — Repository architecture and ADR placement (`docs/adr/0001-repo-architecture.md`)
- **REF-002**: Implementation plan — `plans/legacy-cleanup/plan.md` and `plans/legacy-cleanup/implementation.md` (gitignored)
- **REF-003**: Branch `legacy-cleanup` — commits `296b7ea` through `e92ba7a`
