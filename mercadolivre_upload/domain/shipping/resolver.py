"""Shipping mode resolver.

Auto-detects user's available shipping modes and selects the best one.
Uses configuration from config/generic_mappings.yaml as the single source of truth.
"""

import logging
from pathlib import Path
from typing import Protocol

import yaml

logger = logging.getLogger(__name__)


def _load_shipping_config() -> dict:
    """Load shipping configuration from config file.
    
    Returns:
        Dictionary with mode_priority and default_mode
    """
    try:
        config_path = Path("config/generic_mappings.yaml")
        with open(config_path, encoding='utf-8') as f:
            config = yaml.safe_load(f)

        shipping_config = config.get('shipping', {})

        return {
            'mode_priority': shipping_config.get('mode_priority', ['me1', 'me2']),
            'default_mode': shipping_config.get('default_mode', 'not_specified'),
        }
    except Exception as e:
        logger.warning(f"Could not load shipping config: {e}. Using defaults.")
        return {
            'mode_priority': ['me1', 'me2'],
            'default_mode': 'not_specified',
        }


class ShippingModeProviderPort(Protocol):
    """Port for shipping mode retrieval."""

    def get_users_me(self) -> dict:
        """Get current user info with shipping modes."""
        ...


class ShippingResolver:
    """Resolver for determining best shipping mode.
    
    Uses configuration from config/generic_mappings.yaml as the single source of truth.
    Prioritizes me1 over me2 based on mode_priority configuration.
    """

    def __init__(self, provider: ShippingModeProviderPort, config: dict | None = None):
        """Initialize resolver.

        Args:
            provider: Shipping mode provider (API adapter)
            config: Optional custom config to override file-based config
        """
        self.provider = provider
        self._cached_modes: list[str] | None = None

        # Load shipping config from config file (single source of truth), allow override
        if config:
            self.mode_priority = config.get('mode_priority', ['me1', 'me2'])
            self.default_mode = config.get('default_mode', 'not_specified')
        else:
            shipping_config = _load_shipping_config()
            self.mode_priority = shipping_config['mode_priority']
            self.default_mode = shipping_config['default_mode']

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
            return self.default_mode

        # Select best mode based on priority from config (me1 is prioritized over me2)
        for mode in self.mode_priority:
            if mode in available_modes:
                logger.info(f"Selected shipping mode: {mode}")
                return mode

        # Fallback: return first available mode
        logger.info(f"No priority modes available, using first available: {available_modes[0]}")
        return available_modes[0]

    def _get_available_modes(self) -> list[str]:
        """Fetch and cache user's available shipping modes from ML API.

        Calls /users/me endpoint to determine which shipping modes the user
        has access to based on their Mercado Envios status and shipping settings.

        Returns:
            List of available shipping mode IDs (me1, me2, or empty if none)
        """
        if self._cached_modes is not None:
            return self._cached_modes

        try:
            user_info = self.provider.get_users_me()
            logger.debug(f"User info from ML API: {user_info}")

            available_modes: list[str] = []

            # Check if user has accepted Mercado Envios terms
            mercadoenvios_status = user_info.get("status", {}).get("mercadoenvios")
            logger.info(f"Mercado Envios status: {mercadoenvios_status}")

            # Get user's shipping modes from the API response
            # The user can have multiple shipping modes available
            user_shipping_modes = user_info.get("shipping_modes", [])

            if user_shipping_modes:
                # Use the shipping modes returned by the API
                available_modes = [mode for mode in user_shipping_modes if mode in ["me1", "me2"]]
                logger.info(f"Available shipping modes from API: {available_modes}")
            elif mercadoenvios_status == "accepted":
                # User has accepted Mercado Envios but no explicit modes listed
                # Default to both me1 and me2 being available
                available_modes = ["me1", "me2"]
                logger.info("Mercado Envios accepted, defaulting to me1 and me2")
            else:
                # Check if user has any shipping configuration that indicates mode availability
                seller_reputation = user_info.get("seller_reputation", {})
                power_seller_status = seller_reputation.get("power_seller_status")

                # Power sellers typically have access to me2
                if power_seller_status:
                    available_modes = ["me2"]
                    logger.info(f"Power seller status: {power_seller_status}, enabling me2")
                else:
                    # For non-power sellers, try me1 first
                    available_modes = ["me1"]
                    logger.info("Non-power seller, defaulting to me1")

            self._cached_modes = available_modes if available_modes else ["me1", "me2"]
            logger.info(f"Final available shipping modes: {self._cached_modes}")
            return self._cached_modes

        except Exception as e:
            logger.warning(f"Could not fetch user shipping status: {e}")
            # Default to trying me1 first, then me2
            self._cached_modes = ["me1", "me2"]
            logger.info(f"Using default shipping modes due to API error: {self._cached_modes}")
            return self._cached_modes

    def clear_cache(self) -> None:
        """Clear cached shipping modes."""
        self._cached_modes = None
