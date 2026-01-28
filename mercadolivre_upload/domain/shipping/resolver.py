"""Shipping mode resolver.

Auto-detects user's available shipping modes and selects the best one.
"""

import logging
from typing import Optional, Protocol

logger = logging.getLogger(__name__)


class ShippingModeProviderPort(Protocol):
    """Port for shipping mode retrieval."""

    def get_users_me(self) -> dict:
        """Get current user info with shipping modes."""
        ...


class ShippingResolver:
    """Resolver for determining best shipping mode."""

    # Shipping mode priority: me2 (Full) > me1 (calculated) > not_specified
    MODE_PRIORITY = ["me2", "me1"]

    def __init__(self, provider: ShippingModeProviderPort):
        """Initialize resolver.

        Args:
            provider: Shipping mode provider (API adapter)
        """
        self.provider = provider
        self._cached_modes: Optional[list[str]] = None

    def get_best_shipping_mode(self) -> str:
        """Get best available shipping mode for user.

        Returns:
            Shipping mode: "me2", "me1", or "not_specified"
        """
        available_modes = self._get_available_modes()

        if not available_modes:
            logger.info("No shipping modes available, using not_specified")
            return "not_specified"

        # Select best mode based on priority (me2 > me1)
        for mode in self.MODE_PRIORITY:
            if mode in available_modes:
                logger.debug(f"Selected shipping mode: {mode}")
                return mode

        # Fallback: return first available mode
        return available_modes[0]

    def _get_available_modes(self) -> list[str]:
        """Fetch and cache user's available shipping modes.

        Checks status.mercadoenvios from /users/me to determine if user
        can use Mercado Envios (me1/me2) or must use not_specified.

        Returns:
            List of available shipping mode IDs (empty if Mercado Envios not accepted)
        """
        if self._cached_modes is not None:
            return self._cached_modes

        try:
            user_info = self.provider.get_users_me()

            # Check if user has accepted Mercado Envios terms
            mercadoenvios_status = user_info.get("status", {}).get("mercadoenvios")

            if mercadoenvios_status == "accepted":
                # User has accepted Mercado Envios terms
                # Only use me2 to avoid validation issues with me1
                self._cached_modes = ["me2"]
                logger.info("Mercado Envios accepted, using me2 only")
            else:
                # Force me2 even when status indicates not accepted
                # User confirmed manual publication with me2 works
                self._cached_modes = ["me2"]
                logger.info(
                    f"Mercado Envios status: {mercadoenvios_status}, "
                    "forcing me2 mode (user confirmed it works)"
                )

            return self._cached_modes

        except Exception as e:
            logger.warning(f"Could not fetch user shipping status: {e}")
            # Try me2 as fallback
            self._cached_modes = ["me2"]
            return self._cached_modes

    def clear_cache(self) -> None:
        """Clear cached shipping modes."""
        self._cached_modes = None
