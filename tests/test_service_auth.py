# ABOUTME: Tests for API key generation, hashing, and credential encryption.
# ABOUTME: Validates the auth module's cryptographic operations.

import pytest

from tablebuilder.service.auth import (
    generate_api_key,
    hash_api_key,
    encrypt_credentials,
    decrypt_credentials,
    generate_encryption_key,
)


class TestApiKeyGeneration:
    def test_generate_api_key_returns_string(self):
        key = generate_api_key()
        assert isinstance(key, str)
        assert len(key) > 20

    def test_generate_api_key_unique(self):
        keys = {generate_api_key() for _ in range(100)}
        assert len(keys) == 100

    def test_hash_api_key_deterministic(self):
        key = "test-key-123"
        h1 = hash_api_key(key)
        h2 = hash_api_key(key)
        assert h1 == h2

    def test_hash_api_key_different_inputs(self):
        h1 = hash_api_key("key1")
        h2 = hash_api_key("key2")
        assert h1 != h2


class TestCredentialEncryption:
    def test_roundtrip(self):
        key = generate_encryption_key()
        user_id = "testuser@abs.gov.au"
        password = "s3cret!pass"
        encrypted = encrypt_credentials(key, user_id, password)
        dec_user, dec_pass = decrypt_credentials(key, encrypted)
        assert dec_user == user_id
        assert dec_pass == password

    def test_encrypted_is_not_plaintext(self):
        key = generate_encryption_key()
        encrypted = encrypt_credentials(key, "user", "pass")
        assert "user" not in encrypted
        assert "pass" not in encrypted

    def test_wrong_key_fails(self):
        key1 = generate_encryption_key()
        key2 = generate_encryption_key()
        encrypted = encrypt_credentials(key1, "user", "pass")
        with pytest.raises(Exception):
            decrypt_credentials(key2, encrypted)
