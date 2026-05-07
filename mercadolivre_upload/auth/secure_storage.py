"""Secure storage for sensitive tokens and credentials.

Uses AES-256 encryption with key derived from system keyring or environment variable.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any
from ml_workflow_contracts.file_safety import atomic_write_bytes, file_lock
from ml_workflow_contracts.runtime_paths import resolve_ml_bot_paths

try:
    import keyring
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

logger = logging.getLogger(__name__)


class SecureStorageError(Exception):
    """Raised when secure storage cannot encrypt/decrypt token data safely."""


class SecureTokenStorage:
    """Secure storage for OAuth tokens using AES-256 encryption.

    The encryption key is derived from:
    1. System keyring (preferred) - keyring service specific to this app
    2. Environment variable ENCRYPTION_KEY (fallback for CI/automation)
    3. Generated key stored in keyring (if neither above exists)

    Usage:
        storage = SecureTokenStorage()
        storage.save_tokens({"access_token": "...", "refresh_token": "..."})
        tokens = storage.load_tokens()
    """

    KEYRING_SERVICE = "mercado-livre-bulk-upload"
    KEYRING_USERNAME = "encryption-key"
    SALT_FILE = ".salt"

    def __init__(self, token_path: Path | None = None):
        """Initialize secure storage.

        Args:
            token_path: Path to encrypted token file. Defaults to tokens.json.enc
        """
        canonical = resolve_ml_bot_paths().mercadolivre_tokens_enc
        self.token_path = token_path or canonical
        self._lock_path = resolve_ml_bot_paths().mercadolivre_auth_lock
        self._cipher = None

    def _get_or_create_key(self) -> bytes:
        """Get or create encryption key.

        Priority:
        1. Environment variable ENCRYPTION_KEY
        2. System keyring
        3. Generate new key and store in keyring

        Returns:
            32-byte encryption key
        """
        # Priority 1: Environment variable
        env_key = os.environ.get("ENCRYPTION_KEY")
        if env_key:
            logger.debug("Using encryption key from environment variable")
            env_key_bytes = env_key.encode()
            # Allow passing a full Fernet key directly.
            if len(env_key_bytes) == 44:
                return env_key_bytes
            return env_key_bytes[:32].ljust(32, b"\0")

        # Priority 2: System keyring
        if KEYRING_AVAILABLE:
            try:
                stored_key = keyring.get_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME)
                if stored_key:
                    logger.debug("Using encryption key from keyring")
                    return stored_key.encode()
            except Exception as e:
                logger.warning(f"Failed to get key from keyring: {e}")

        # Priority 3: Generate new key
        logger.info("Generating new encryption key...")
        key = Fernet.generate_key()

        # Store in keyring if available
        if KEYRING_AVAILABLE:
            try:
                keyring.set_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME, key.decode())
                logger.info("Encryption key stored in system keyring")
            except Exception as e:
                raise SecureStorageError(
                    "Failed to persist encryption key in keyring. "
                    "Set ENCRYPTION_KEY or configure a working keyring backend."
                ) from e
        else:
            raise SecureStorageError(
                "Secure storage requires ENCRYPTION_KEY when keyring is unavailable."
            )

        return key

    def _get_or_create_salt(self) -> bytes:
        """Get a stable KDF salt for non-Fernet keys."""
        salt_path = self.token_path.parent / self.SALT_FILE
        if salt_path.exists():
            salt = salt_path.read_bytes()
            if len(salt) == 16:
                return salt
            logger.warning(f"Invalid salt file size at {salt_path}; regenerating salt.")

        salt = os.urandom(16)
        salt_path.parent.mkdir(parents=True, exist_ok=True)
        salt_path.write_bytes(salt)
        os.chmod(salt_path, 0o600)
        return salt

    def _get_fernet(self) -> Fernet:
        """Get or create Fernet cipher instance."""
        if self._cipher is None:
            key = self._get_or_create_key()
            # Ensure key is valid for Fernet (32 bytes, base64 encoded)
            if len(key) == 44:  # Already Fernet key
                self._cipher = Fernet(key)  # type: ignore[assignment]
            else:
                # Derive Fernet key from password-like key
                import base64

                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=self._get_or_create_salt(),
                    iterations=100000,
                )
                fernet_key = base64.urlsafe_b64encode(kdf.derive(key))
                self._cipher = Fernet(fernet_key)  # type: ignore[assignment]

        return self._cipher  # type: ignore[return-value]

    def save_tokens(self, tokens: dict[str, Any]) -> None:
        """Encrypt and save tokens to file.

        Args:
            tokens: Dictionary with token data
        """
        try:
            fernet = self._get_fernet()
            json_data = json.dumps(tokens, indent=2)
            encrypted = fernet.encrypt(json_data.encode())

            with file_lock(self._lock_path):
                atomic_write_bytes(self.token_path, encrypted)
            logger.info(f"Tokens saved securely to {self.token_path}")

            # Set restrictive permissions (owner read/write only)
            os.chmod(self.token_path, 0o600)

        except Exception as e:
            logger.error(f"Failed to save tokens: {e}")
            raise SecureStorageError("Unable to save encrypted token file") from e

    def load_tokens(self) -> dict[str, Any] | None:
        """Load and decrypt tokens from file.

        Returns:
            Dictionary with token data or None if file doesn't exist
        """
        if not self.token_path.exists():
            logger.debug(f"Token file {self.token_path} not found")
            return None

        try:
            fernet = self._get_fernet()
            encrypted = self.token_path.read_bytes()
            decrypted = fernet.decrypt(encrypted)

            return json.loads(decrypted.decode())  # type: ignore[no-any-return]

        except Exception as e:
            logger.error(f"Failed to load tokens: {e}")
            raise SecureStorageError("Unable to load or decrypt secure token file") from e

    def delete_tokens(self) -> None:
        """Delete encrypted token file."""
        if self.token_path.exists():
            self.token_path.unlink()
            logger.info(f"Token file {self.token_path} deleted")
