"""Shipping mode resolver.

Auto-detects user's available shipping modes and selects the best one.
Uses configuration from config/shipping.yaml as the single source of truth.
"""

import logging
from pathlib import Path
from typing import Any, Protocol

from mercadolivre_upload.shared.utils.config_loader import load_merged_yaml_config

logger = logging.getLogger(__name__)
_SUPPORTED_SHIPPING_MODES = {"me1", "me2", "custom", "not_specified"}


def _load_shipping_config() -> dict[str, Any]:
    """Load shipping configuration from config file.

    Returns:
        Dictionary with mode_priority and default_mode
    """
    try:
        config = load_merged_yaml_config(
            Path("config/shipping.yaml"), fallback=Path("config/generic_mappings.yaml")
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
        self._cached_shipping_preferences: dict[str, Any] | None = None
        self._cached_logistic_type_by_mode: dict[str, str] = {}
        self._cached_runtime_policy_by_mode: dict[str, dict[str, Any]] = {}

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
        selection = self.get_best_shipping_selection()
        selected_mode = selection.get("mode")
        if not isinstance(selected_mode, str) or not selected_mode:
            return self.default_mode  # type: ignore[no-any-return]
        return selected_mode

    def get_best_shipping_selection(self) -> dict[str, Any]:
        """Get best shipping selection including optional logistic type.

        Returns:
            Dictionary containing:
            - mode: selected mode ("me1", "me2", "not_specified")
            - logistic_type: optional preferred logistic type from seller preferences
            - tags/free_shipping/constraints: optional runtime policy hints from logistics payload
        """
        available_modes = self._get_available_modes()

        if not available_modes:
            logger.info(f"No shipping modes available, using {self.default_mode}")
            return {"mode": self.default_mode, "logistic_type": None}

        selected_mode: str | None = None

        # Select best mode based on priority from config
        for mode in self.mode_priority:
            if mode in available_modes:
                selected_mode = mode
                break

        # Fallback: return first available mode
        if selected_mode is None:
            selected_mode = available_modes[0]
            logger.info(f"No priority modes available, using first available: {selected_mode}")
        else:
            logger.info(f"Selected shipping mode: {selected_mode}")

        logistic_type = self._cached_logistic_type_by_mode.get(selected_mode)
        selection: dict[str, Any] = {
            "mode": selected_mode,
            "logistic_type": logistic_type,
            "available_modes": list(available_modes),
            "logistic_type_by_mode": dict(self._cached_logistic_type_by_mode),
        }
        runtime_policy_by_mode: dict[str, dict[str, Any]] = {}
        for mode, raw_policy in self._cached_runtime_policy_by_mode.items():
            if not isinstance(raw_policy, dict):
                continue
            normalized_policy = dict(raw_policy)
            tags = normalized_policy.get("tags")
            if isinstance(tags, list):
                normalized_policy["tags"] = list(tags)
            constraints = normalized_policy.get("constraints")
            if isinstance(constraints, dict):
                normalized_policy["constraints"] = dict(constraints)
            runtime_policy_by_mode[str(mode)] = normalized_policy
        if runtime_policy_by_mode:
            selection["runtime_policy_by_mode"] = runtime_policy_by_mode
        runtime_policy = self._cached_runtime_policy_by_mode.get(selected_mode, {})
        if isinstance(runtime_policy, dict):
            runtime_tags = runtime_policy.get("tags")
            if isinstance(runtime_tags, list):
                selection["tags"] = list(runtime_tags)
            runtime_free_shipping = runtime_policy.get("free_shipping")
            if isinstance(runtime_free_shipping, bool):
                selection["free_shipping"] = runtime_free_shipping
            runtime_constraints = runtime_policy.get("constraints")
            if isinstance(runtime_constraints, dict):
                selection["constraints"] = dict(runtime_constraints)
        return selection

    @staticmethod
    def _normalize_runtime_tags(raw_tags: Any) -> list[str]:
        """Normalize logistics tags payload into lowercase stable names."""
        normalized_tags: list[str] = []
        if isinstance(raw_tags, (list, tuple, set)):
            for raw_tag in raw_tags:
                tag_name = str(raw_tag).strip().lower()
                if tag_name:
                    normalized_tags.append(tag_name)
        elif isinstance(raw_tags, dict):
            for tag, enabled in raw_tags.items():
                if not enabled:
                    continue
                tag_name = str(tag).strip().lower()
                if tag_name:
                    normalized_tags.append(tag_name)
        return list(dict.fromkeys(normalized_tags))

    @staticmethod
    def _extract_runtime_free_shipping(raw_free_shipping: Any) -> bool | None:
        """Extract runtime free-shipping hint from logistics payload."""
        if isinstance(raw_free_shipping, bool):
            return raw_free_shipping
        if isinstance(raw_free_shipping, dict):
            for key in ("required", "mandatory", "enabled", "free_shipping"):
                value = raw_free_shipping.get(key)
                if isinstance(value, bool):
                    return value
        return None

    @classmethod
    def _extract_runtime_policy_from_logistic(cls, logistic: dict[str, Any]) -> dict[str, Any]:
        """Extract optional runtime policy hints from one logistics row."""
        runtime_policy: dict[str, Any] = {}

        runtime_tags = cls._normalize_runtime_tags(logistic.get("tags"))
        if runtime_tags:
            runtime_policy["tags"] = runtime_tags

        free_shipping_hint = cls._extract_runtime_free_shipping(logistic.get("free_shipping"))
        if free_shipping_hint is not None:
            runtime_policy["free_shipping"] = free_shipping_hint

        raw_constraints = logistic.get("constraints")
        if isinstance(raw_constraints, dict):
            constraints = {
                str(key).strip(): value
                for key, value in raw_constraints.items()
                if str(key).strip()
            }
            if constraints:
                runtime_policy["constraints"] = constraints

        return runtime_policy

    @staticmethod
    def _merge_runtime_policy(
        current_policy: dict[str, Any],
        runtime_policy: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge mode runtime policy hints preserving deterministic behavior."""
        merged = dict(current_policy)

        current_tags = merged.get("tags")
        existing_tags = current_tags if isinstance(current_tags, list) else []
        new_tags_raw = runtime_policy.get("tags")
        new_tags = new_tags_raw if isinstance(new_tags_raw, list) else []
        merged_tags = list(dict.fromkeys([*existing_tags, *new_tags]))
        if merged_tags:
            merged["tags"] = merged_tags

        free_shipping_hint = runtime_policy.get("free_shipping")
        if isinstance(free_shipping_hint, bool):
            existing_free_shipping = merged.get("free_shipping")
            if isinstance(existing_free_shipping, bool):
                merged["free_shipping"] = existing_free_shipping or free_shipping_hint
            else:
                merged["free_shipping"] = free_shipping_hint

        current_constraints = merged.get("constraints")
        merged_constraints = (
            dict(current_constraints) if isinstance(current_constraints, dict) else {}
        )
        runtime_constraints = runtime_policy.get("constraints")
        if isinstance(runtime_constraints, dict):
            merged_constraints.update(runtime_constraints)
        if merged_constraints:
            merged["constraints"] = merged_constraints

        return merged

    @staticmethod
    def _extract_default_logistic_type(logistic_types: Any) -> str | None:
        """Extract preferred logistic type from shipping preferences.types payload."""
        if not isinstance(logistic_types, list):
            return None

        # Prefer entries explicitly marked as default.
        for logistic_type in logistic_types:
            if not isinstance(logistic_type, dict):
                continue
            type_name = logistic_type.get("type")
            if logistic_type.get("default") and isinstance(type_name, str) and type_name:
                return type_name

        # Fallback to first available type.
        for logistic_type in logistic_types:
            if not isinstance(logistic_type, dict):
                continue
            type_name = logistic_type.get("type")
            if isinstance(type_name, str) and type_name:
                return type_name
        return None

    def _get_shipping_preferences(self, user_id: str) -> dict[str, Any]:
        """Get shipping preferences with per-instance caching."""
        if self._cached_shipping_preferences is not None:
            return self._cached_shipping_preferences

        shipping_preferences = self.provider.get_user_shipping_preferences(user_id)
        if isinstance(shipping_preferences, dict):
            self._cached_shipping_preferences = shipping_preferences
            return shipping_preferences
        return {}

    def _get_available_modes(self) -> list[str]:
        """Fetch and cache user's available shipping modes from ML API.

        Uses /users/{id}/shipping_preferences as the source of truth.
        Falls back to /users/me shipping_modes when preferences are unavailable.

        Returns:
            List of available shipping mode IDs (me1/me2/custom/not_specified or empty)
        """
        if self._cached_modes is not None:
            return self._cached_modes

        try:
            self._cached_logistic_type_by_mode = {}
            self._cached_runtime_policy_by_mode = {}
            user_info = self.provider.get_users_me()
            logger.debug(f"User info from ML API: {user_info}")
            user_id = user_info.get("id")

            available_modes: list[str] = []
            if user_id:
                try:
                    shipping_preferences = self._get_shipping_preferences(str(user_id))
                    pref_modes = shipping_preferences.get("modes", [])
                    if isinstance(pref_modes, list):
                        available_modes = [
                            mode for mode in pref_modes if mode in _SUPPORTED_SHIPPING_MODES
                        ]

                    # Some sellers only expose mode/type combinations under logistics.
                    logistics = shipping_preferences.get("logistics", [])
                    if isinstance(logistics, list):
                        for logistic in logistics:
                            if not isinstance(logistic, dict):
                                continue
                            mode = logistic.get("mode")
                            if not isinstance(mode, str) or mode not in _SUPPORTED_SHIPPING_MODES:
                                continue
                            if mode not in available_modes:
                                available_modes.append(mode)
                            preferred_type = self._extract_default_logistic_type(
                                logistic.get("types", [])
                            )
                            if preferred_type:
                                self._cached_logistic_type_by_mode[mode] = preferred_type
                            runtime_policy = self._extract_runtime_policy_from_logistic(logistic)
                            if runtime_policy:
                                cached_policy = self._cached_runtime_policy_by_mode.get(mode, {})
                                self._cached_runtime_policy_by_mode[mode] = (
                                    self._merge_runtime_policy(cached_policy, runtime_policy)
                                )
                    logger.info(
                        "Available shipping modes from shipping_preferences: " f"{available_modes}"
                    )
                except Exception as e:
                    logger.warning(f"Could not fetch shipping_preferences for user {user_id}: {e}")

            if not available_modes:
                user_shipping_modes = user_info.get("shipping_modes", [])
                if isinstance(user_shipping_modes, list):
                    available_modes = [
                        mode for mode in user_shipping_modes if mode in _SUPPORTED_SHIPPING_MODES
                    ]
                logger.info(f"Available shipping modes from /users/me: {available_modes}")

            available_modes = list(dict.fromkeys(available_modes))

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
        self._cached_shipping_preferences = None
        self._cached_logistic_type_by_mode = {}
        self._cached_runtime_policy_by_mode = {}
