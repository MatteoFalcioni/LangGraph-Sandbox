# langgraph_sandbox/artifacts/tokens.py
"""
Token-based security system for artifact access.

This module implements a secure token system that allows controlled access to artifacts
without exposing direct file paths. Each artifact gets a unique ID and requires a 
signed token to access.

Token Structure: <base64_message>.<base64_signature>
- message: "artifact_id.expiration_timestamp"
- signature: HMAC-SHA256 of the message using a secret key

Security features:
- Time-based expiration (default 24 hours)
- HMAC signature prevents tampering
- Artifact ID must match the token
- No direct file path exposure
"""

from __future__ import annotations
import base64, hmac, os, time, secrets
from hashlib import sha256
from typing import Dict

def _b64u(data: bytes) -> str:
    """
    Convert bytes to URL-safe base64 string (no padding).
    Used for encoding the token message and signature.
    """
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def _b64u_dec(s: str) -> bytes:
    """
    Convert URL-safe base64 string back to bytes.
    Handles missing padding by adding it back.
    """
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)

def _secret() -> bytes:
    """
    Get the secret key for token signing.
    
    Priority:
    1. ARTIFACTS_SECRET environment variable (for production)
    2. Generate random secret (for development)
    
    This secret is used to sign all tokens, ensuring they can't be forged.
    """
    # Try to use the fixed secret from environment first
    env_secret = os.getenv("ARTIFACTS_SECRET")
    if env_secret:
        return env_secret.encode("utf-8")
    
    # Fall back to generating a random secret
    return secrets.token_urlsafe(32).encode("utf-8")

def _ttl() -> int:
    """
    Get token time-to-live in seconds.
    Default: 600 seconds (10 minutes), but can be overridden via environment.
    In this project, it's set to 24 hours (86400 seconds) in docker-compose.yml
    """
    try:
        return int(os.getenv("ARTIFACTS_TOKEN_TTL_SECONDS", "600"))
    except Exception:
        return 600

def create_token(artifact_id: str, now: int | None = None) -> str:
    """
    Create a short-lived token tied to an artifact_id.
    
    Token format: <base64_message>.<base64_signature>
    - message: "artifact_id.expiration_timestamp"
    - signature: HMAC-SHA256(message, secret_key)
    
    Args:
        artifact_id: The unique identifier for the artifact (e.g., "art_abc123")
        now: Current timestamp (for testing), defaults to current time
    
    Returns:
        A signed token string that can be used to access the artifact
    """
    if now is None:
        now = int(time.time())
    
    # Calculate expiration time
    exp = now + _ttl()
    
    # Create the message: "artifact_id.expiration_timestamp"
    msg = f"{artifact_id}.{exp}".encode("utf-8")
    
    # Sign the message with HMAC-SHA256 using our secret key
    sig = hmac.new(_secret(), msg, sha256).digest()
    
    # Encode both message and signature as URL-safe base64
    return _b64u(msg) + "." + _b64u(sig)

def verify_token(token: str) -> Dict[str, str | int]:
    """
    Verify a token and return its contents if valid.
    
    Steps:
    1. Split token into message and signature parts
    2. Decode both from base64
    3. Extract artifact_id and expiration from message
    4. Verify the signature matches what we expect
    5. Check if token has expired
    
    Args:
        token: The token string to verify
    
    Returns:
        Dictionary with 'artifact_id' and 'exp' (expiration timestamp)
    
    Raises:
        RuntimeError: If token is malformed, signature is invalid, or expired
    """
    try:
        # Split token into message and signature parts
        msg_b64, sig_b64 = token.split(".", 1)
        
        # Decode from base64
        msg = _b64u_dec(msg_b64)
        sig = _b64u_dec(sig_b64)
        
        # Extract artifact_id and expiration from message
        exp_str = msg.decode("utf-8").rsplit(".", 1)[1]
        artifact_id = msg.decode("utf-8").rsplit(".", 1)[0]
        exp = int(exp_str)
    except Exception:
        raise RuntimeError("Invalid token format")

    # Verify the signature matches what we expect
    expected = hmac.new(_secret(), msg, sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise RuntimeError("Invalid token signature")
    
    # Check if token has expired
    if int(time.time()) > exp:
        raise RuntimeError("Token expired")

    return {"artifact_id": artifact_id, "exp": exp}

def create_download_url(artifact_id: str) -> str:
    """
    Build a ready-to-click URL for the artifact.
    
    Creates a complete URL that can be used to download the artifact:
    {PUBLIC_BASE_URL}/artifacts/{id}?token=...
    
    The URL includes:
    - Base URL (from environment or localhost)
    - Artifact ID in the path
    - Signed token as query parameter
    
    Args:
        artifact_id: The unique identifier for the artifact
    
    Returns:
        Complete URL string (e.g., "http://localhost:8002/artifacts/art_abc123?token=xyz789")
    """
    # Check for custom base URL first (set in docker-compose.yml)
    base = os.getenv("ARTIFACTS_PUBLIC_BASE_URL")
    if base:
        base = base.rstrip("/")
    else:
        # Use dynamic port from environment, fallback to 8000
        port = os.getenv("ARTIFACTS_SERVER_PORT", "8000")
        base = f"http://localhost:{port}"
    
    # Create a signed token for this artifact
    token = create_token(artifact_id)
    
    # Combine everything into a complete URL
    return f"{base}/artifacts/{artifact_id}?token={token}"
