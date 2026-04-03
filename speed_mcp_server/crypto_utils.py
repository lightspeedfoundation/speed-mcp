"""
Encrypt env payload so only the client with the matching private key can read it.
Hybrid: AES-256-GCM for payload, RSA-OAEP for the AES key.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _load_public_key(pem: str) -> RSAPublicKey:
    if isinstance(pem, bytes):
        pem = pem.decode("utf-8")
    return serialization.load_pem_public_key(pem.encode("utf-8"))


def encrypt_env_for_client(env: dict[str, str], client_public_key_pem: str) -> dict[str, Any]:
    """
    Encrypt env dict so only the holder of the private key can decrypt.
    Returns dict with base64-encoded: encrypted_key (RSA-OAEP), nonce, ciphertext (AES-GCM).

    Plaintext is a flat JSON object ``{"ALCHEMY_API_KEY": "...", ...}`` (same as legacy speed-mcp).
    Lightspeed-CLI ``decryptMcpEnv`` accepts this (legacy branch) or ``{"env": {...}}`` (wrapped).
    """
    public_key = _load_public_key(client_public_key_pem)
    payload_bytes = json.dumps(env, sort_keys=True).encode("utf-8")

    # AES-256-GCM for payload; 96-bit nonce for GCM
    aes_key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    aesgcm = AESGCM(aes_key)
    ciphertext = aesgcm.encrypt(nonce, payload_bytes, None)

    # RSA-OAEP for the AES key (so only client can recover it)
    encrypted_aes_key = public_key.encrypt(
        aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    return {
        "encrypted": True,
        "algorithm": "RSA-OAEP-AES256GCM",
        "encrypted_key_b64": base64.standard_b64encode(encrypted_aes_key).decode("ascii"),
        "nonce_b64": base64.standard_b64encode(nonce).decode("ascii"),
        "ciphertext_b64": base64.standard_b64encode(ciphertext).decode("ascii"),
    }


def decrypt_env_from_server(
    encrypted_key_b64: str,
    nonce_b64: str,
    ciphertext_b64: str,
    private_key_pem: str,
) -> dict[str, str]:
    """
    Decrypt env dict (for use in Speed-CLI). Requires the client's RSA private key.
    """
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

    def load_private_key(pem: str) -> RSAPrivateKey:
        if isinstance(pem, bytes):
            pem = pem.decode("utf-8")
        return serialization.load_pem_private_key(pem.encode("utf-8"), password=None)

    private_key = load_private_key(private_key_pem)
    encrypted_aes_key = base64.standard_b64decode(encrypted_key_b64)
    nonce = base64.standard_b64decode(nonce_b64)
    ciphertext = base64.standard_b64decode(ciphertext_b64)

    aes_key = private_key.decrypt(
        encrypted_aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    aesgcm = AESGCM(aes_key)
    payload_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    data = json.loads(payload_bytes.decode("utf-8"))
    if isinstance(data, dict) and "env" in data and isinstance(data["env"], dict):
        return data["env"]
    if isinstance(data, dict):
        return data  # legacy: flat env map
    return {}
