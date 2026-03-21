# ABOUTME: API key generation, hashing, and credential encryption for the service.
# ABOUTME: Uses SHA-256 for API key hashing and Fernet for credential encryption.

import hashlib
import json
import secrets

from cryptography.fernet import Fernet


def generate_api_key() -> str:
    """Generate a cryptographically random API key."""
    return f"tb_{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    """SHA-256 hash an API key for storage."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_encryption_key() -> str:
    """Generate a new Fernet encryption key (base64-encoded)."""
    return Fernet.generate_key().decode()


def encrypt_credentials(encryption_key: str, user_id: str, password: str) -> str:
    """Encrypt ABS credentials using Fernet. Returns base64-encoded ciphertext."""
    f = Fernet(encryption_key.encode())
    payload = json.dumps({"user_id": user_id, "password": password})
    return f.encrypt(payload.encode()).decode()


def decrypt_credentials(encryption_key: str, encrypted: str) -> tuple[str, str]:
    """Decrypt ABS credentials. Returns (user_id, password)."""
    f = Fernet(encryption_key.encode())
    payload = json.loads(f.decrypt(encrypted.encode()).decode())
    return payload["user_id"], payload["password"]
