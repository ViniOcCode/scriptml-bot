"""Explicit authorization guard for remote publication mutations."""

from __future__ import annotations


class PublicationIntentError(ValueError):
    """Raised when a real publication was not explicitly authorized."""


def require_publication_intent(
    *,
    dry_run: bool,
    execute: bool,
    confirmation: str | None,
) -> None:
    """Reject any non-dry-run publication without an explicit human intent.

    The guard lives below the CLI so queue workers and direct Python callers
    cannot turn a validation invocation into a remote mutation accidentally.
    """
    if dry_run:
        return
    if not execute:
        raise PublicationIntentError("Real publication requires explicit --execute intent.")
    if confirmation != "PUBLICAR":
        raise PublicationIntentError(
            "Real publication requires the exact confirmation literal PUBLICAR."
        )


__all__ = ["PublicationIntentError", "require_publication_intent"]
