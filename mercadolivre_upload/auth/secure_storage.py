"""Secure storage for sensitive tokens and credentials.

Uses AES-256 encryption with key derived from system keyring or environment variable.
"""

import json
import logging
import os
from pathlib import Path

try:
    import keyring
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

logger = logging.getLogger(__name__)


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
        self.token_path = token_path or Path("tokens.json.enc")
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
            return env_key.encode()[:32].ljust(32, b"\0")

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
                logger.warning(
                    f"Failed to store key in keyring: {e}. "
                    "Set ENCRYPTION_KEY environment variable for persistence."
                )

        return key

    def _get_fernet(self) -> Fernet:
        """Get or create Fernet cipher instance."""
        if self._cipher is None:
            key = self._get_or_create_key()
            # Ensure key is valid for Fernet (32 bytes, base64 encoded)
            if len(key) == 44:  # Already Fernet key
                self._cipher = Fernet(key)
            else:
                # Derive Fernet key from password-like key
                import base64

                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=os.urandom(16),
                    iterations=100000,
                )
                fernet_key = base64.urlsafe_b64encode(kdf.derive(key))
                self._cipher = Fernet(fernet_key)

        return self._cipher

    def save_tokens(self, tokens: dict) -> None:
        """Encrypt and save tokens to file.

        Args:
            tokens: Dictionary with token data
        """
        try:
            fernet = self._get_fernet()
            json_data = json.dumps(tokens, indent=2)
            encrypted = fernet.encrypt(json_data.encode())

            self.token_path.write_bytes(encrypted)
            logger.info(f"Tokens saved securely to {self.token_path}")

            # Set restrictive permissions (owner read/write only)
            os.chmod(self.token_path, 0o600)

        except Exception as e:
            logger.error(f"Failed to save tokens: {e}")
            raise

    def load_tokens(self) -> dict | None:
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

            return json.loads(decrypted.decode())

        except Exception as e:
            logger.error(f"Failed to load tokens: {e}")
            logger.warning("You may need to re-authenticate")
            return None

    def delete_tokens(self) -> None:
        """Delete encrypted token file."""
        if self.token_path.exists():
            self.token_path.unlink()
            logger.info(f"Token file {self.token_path} deleted")


def migrate_plaintext_tokens(
    plaintext_path: Path = Path("tokens.json"),
    encrypted_path: Path = Path("tokens.json.enc"),
) -> bool:
    """Migrate tokens from plaintext to encrypted storage.

    Args:
        plaintext_path: Path to old plaintext tokens.json
        encrypted_path: Path to new encrypted tokens.json.enc

    Returns:
        True if migration successful, False otherwise
    """
    if not plaintext_path.exists():
        return False

    try:
        logger.info(f"Migrating tokens from {plaintext_path} to encrypted storage...")
        tokens = json.loads(plaintext_path.read_text())

        storage = SecureTokenStorage(encrypted_path)
        storage.save_tokens(tokens)

        # Backup and remove old plaintext file
        backup_path = plaintext_path.with_suffix(".json.backup")
        plaintext_path.rename(backup_path)
        logger.info(f"Plaintext tokens backed up to {backup_path}")
        logger.info("Migration complete. Please delete the backup file manually.")

        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False
