"""Shipping mode resolver.

Auto-detects user's available shipping modes and selects the best one.
Uses configuration from config/shipping.yaml as the single source of truth.
"""

import logging
from pathlib import Path
from typing import Any, Protocol

from mercadolivre_upload.shared.utils.config_loader import load_yaml_config

logger = logging.getLogger(__name__)


def _load_shipping_config() -> dict[str, Any]:
    """Load shipping configuration from config file.

    Returns:
        Dictionary with mode_priority and default_mode
    """
    try:
        config = load_yaml_config(
            Path("config/shipping.yaml"), Path("config/generic_mappings.yaml")
        )

        shipping_config = config.get("shipping", {})

        return {
            "mode_priority": shipping_config.get("mode_priority", ["me2", "me1"]),
            "default_mode": shipping_config.get("default_mode", "not_specified"),
        }
    except Exception as e:
        logger.warning(f"Could not load shipping config: {e}. Using defaults.")
        return {
            "mode_priority": ["me2", "me1"],
            "default_mode": "not_specified",
        }


class ShippingModeProviderPort(Protocol):
    """Port for shipping mode retrieval."""

    def get_users_me(self) -> dict[str, Any]:
        """Get current user info with shipping modes."""
        ...

    def get_user_shipping_preferences(self, user_id: str) -> dict[str, Any]:
        """Get seller shipping preferences including enabled modes."""
        ...


class ShippingResolver:
    """Resolver for determining best shipping mode.

    Uses configuration from config/shipping.yaml as the single source of truth.
    Prioritizes me2 over me1 based on mode_priority configuration.
    """

    def __init__(self, provider: ShippingModeProviderPort, config: dict[str, Any] | None = None):
        """Initialize resolver.

        Args:
            provider: Shipping mode provider (API adapter)
            config: Optional custom config to override file-based config
        """
        self.provider = provider
        self._cached_modes: list[str] | None = None

        # Load shipping config from config file (single source of truth), allow override
        if config:
            self.mode_priority = config.get("mode_priority", ["me2", "me1"])
            self.default_mode = config.get("default_mode", "not_specified")
        else:
            shipping_config = _load_shipping_config()
            self.mode_priority = shipping_config["mode_priority"]
            self.default_mode = shipping_config["default_mode"]

    def get_best_shipping_mode(self) -> str:
        """Get best available shipping mode for user.

        Queries the ML API to get user's available shipping modes and
        selects the best one based on configured priority.

        Returns:
            Shipping mode: "me1", "me2", or "not_specified"
        """
        available_modes = self._get_available_modes()

        if not available_modes:
            logger.info(f"No shipping modes available, using {self.default_mode}")
            return self.default_mode  # type: ignore[no-any-return]

        # Select best mode based on priority from config
        for mode in self.mode_priority:
            if mode in available_modes:
                logger.info(f"Selected shipping mode: {mode}")
                return mode  # type: ignore[no-any-return]

        # Fallback: return first available mode
        logger.info(f"No priority modes available, using first available: {available_modes[0]}")
        return available_modes[0]

    def _get_available_modes(self) -> list[str]:
        """Fetch and cache user's available shipping modes from ML API.

        Uses /users/{id}/shipping_preferences as the source of truth.
        Falls back to /users/me shipping_modes when preferences are unavailable.

        Returns:
            List of available shipping mode IDs (me1, me2, or empty if none)
        """
        if self._cached_modes is not None:
            return self._cached_modes

        try:
            user_info = self.provider.get_users_me()
            logger.debug(f"User info from ML API: {user_info}")
            user_id = user_info.get("id")

            available_modes: list[str] = []
            if user_id:
                try:
                    shipping_preferences = self.provider.get_user_shipping_preferences(str(user_id))
                    pref_modes = shipping_preferences.get("modes", [])
                    if isinstance(pref_modes, list):
                        available_modes = [mode for mode in pref_modes if mode in ["me1", "me2"]]
                    logger.info(
                        "Available shipping modes from shipping_preferences: " f"{available_modes}"
                    )
                except Exception as e:
                    logger.warning(f"Could not fetch shipping_preferences for user {user_id}: {e}")

            if not available_modes:
                user_shipping_modes = user_info.get("shipping_modes", [])
                if isinstance(user_shipping_modes, list):
                    available_modes = [
                        mode for mode in user_shipping_modes if mode in ["me1", "me2"]
                    ]
                logger.info(f"Available shipping modes from /users/me: {available_modes}")

            # Cache only real discovered modes to avoid pinning transient empty results.
            if available_modes:
                self._cached_modes = available_modes
            else:
                self._cached_modes = None
            logger.info(f"Final available shipping modes: {available_modes}")
            return available_modes

        except Exception as e:
            logger.warning(f"Could not fetch user shipping status: {e}")
            self._cached_modes = None
            logger.info("Using empty available modes due to API error")
            return []

    def clear_cache(self) -> None:
        """Clear cached shipping modes."""
        self._cached_modes = None
