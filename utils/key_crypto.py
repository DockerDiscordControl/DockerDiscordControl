# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Simple key encryption/decryption utility for donation keys.
Uses basic XOR encryption with base64 encoding - not meant for high security,
just to avoid having keys in plain text in the source code.
"""

import base64

def decrypt_key(encrypted_key: str, crypto_key: str = "NothingToEncrypt") -> str:
    """
    Decrypt a donation key using simple XOR encryption.

    Args:
        encrypted_key: Base64 encoded encrypted key
        crypto_key: Encryption key (default: "NothingToEncrypt")

    Returns:
        str: Decrypted donation key
    """
    try:
        key_bytes = crypto_key.encode()
        encrypted_bytes = base64.b64decode(encrypted_key.encode())

        decrypted = []
        for i, byte in enumerate(encrypted_bytes):
            key_byte = key_bytes[i % len(key_bytes)]
            decrypted.append(byte ^ key_byte)

        return bytes(decrypted).decode()
    except (RuntimeError):
        # If decryption fails, return empty string (invalid key)
        return ""

def encrypt_key(plain_key: str, crypto_key: str = "NothingToEncrypt") -> str:
    """
    Encrypt a donation key using simple XOR encryption.

    Args:
        plain_key: Plain text donation key
        crypto_key: Encryption key (default: "NothingToEncrypt")

    Returns:
        str: Base64 encoded encrypted key
    """
    key_bytes = crypto_key.encode()
    text_bytes = plain_key.encode()

    encrypted = []
    for i, byte in enumerate(text_bytes):
        key_byte = key_bytes[i % len(key_bytes)]
        encrypted.append(byte ^ key_byte)

    return base64.b64encode(bytes(encrypted)).decode()

# Encrypted donation keys (use decrypt_key() to get actual keys)
ENCRYPTED_DONATION_KEYS = [
    "Cis3RTk8KHldcSVWX0AoPHlCOVsnP0oNNQAoTkBJQkE=",          # Professional license
    "Cis3RSUnIRE7DCMmX0E2TQ9CRzhbJUpjPgkjTjAxKDdjXURaXA==",    # Lifetime license
    "CiA3Iyw8ShAmFi0sID1dNxo9OEVQKVMWQnA0LSVUICYLIj09JA==",    # Full product name
    "Cis3RSohKhkqFy0qMzVdPwJXMUVdPDMHQnMjMiRUND0dLjYkLA==",    # Commercial license
    "Cis3RVteVWFCACA3NysgJgc8MUVaNy9tQgcjKCpURzIfI1k4OyE=",    # Enterprise edition
    "Cis3RSgsPgc8aFc7OktdQAUjIEVRIzYCQgcgOTRUQkR8Wg==",        # Abyss special edition
]

def get_valid_donation_keys() -> list:
    """
    Get list of valid donation keys (decrypted).

    Returns:
        list: List of valid donation key strings
    """
    return [decrypt_key(encrypted_key) for encrypted_key in ENCRYPTED_DONATION_KEYS]
