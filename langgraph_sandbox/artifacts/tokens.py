# langgraph_sandbox/artifacts/tokens.py
from __future__ import annotations
import base64, hmac, os, time, secrets
from hashlib import sha256
from typing import Dict

def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def _b64u_dec(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)

def _secret() -> bytes:
    """Get the secret key for token signing. Uses ARTIFACTS_SECRET env var or generates one."""
    secret = os.getenv("ARTIFACTS_SECRET")
    if secret:
        return secret.encode("utf-8")
    else:
        # Fallback to random secret if no env var set
        return secrets.token_urlsafe(32).encode("utf-8")

def _ttl() -> int:
    try:
        return int(os.getenv("ARTIFACTS_TOKEN_TTL_SECONDS", "600"))
    except Exception:
        return 600

def create_token(artifact_id: str, now: int | None = None) -> str:
    """Create a short-lived token tied to an artifact_id."""
    if now is None:
        now = int(time.time())
    exp = now + _ttl()
    msg = f"{artifact_id}.{exp}".encode("utf-8")
    sig = hmac.new(_secret(), msg, sha256).digest()
    return _b64u(msg) + "." + _b64u(sig)

def verify_token(token: str) -> Dict[str, str | int]:
    """Return {'artifact_id':..., 'exp':...} if valid; raise RuntimeError if not."""
    try:
        msg_b64, sig_b64 = token.split(".", 1)
        msg = _b64u_dec(msg_b64)
        sig = _b64u_dec(sig_b64)
        exp_str = msg.decode("utf-8").rsplit(".", 1)[1]
        artifact_id = msg.decode("utf-8").rsplit(".", 1)[0]
        exp = int(exp_str)
    except Exception:
        raise RuntimeError("Invalid token format")

    expected = hmac.new(_secret(), msg, sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise RuntimeError("Invalid token signature")
    if int(time.time()) > exp:
        raise RuntimeError("Token expired")

    return {"artifact_id": artifact_id, "exp": exp}

def create_download_url(artifact_id: str) -> str:
    """
    Build a ready-to-click URL for the artifact:
      {PUBLIC_BASE_URL}/artifacts/{id}?token=...
    
    Uses ARTIFACTS_PUBLIC_BASE_URL if set, otherwise defaults to localhost with dynamic port
    """
    # Check for custom base URL first
    base = os.getenv("ARTIFACTS_PUBLIC_BASE_URL")
    if base:
        base = base.rstrip("/")
    else:
        # Use dynamic port from environment, fallback to 8000
        port = os.getenv("ARTIFACTS_SERVER_PORT", "8000")
        base = f"http://localhost:{port}"
    
    token = create_token(artifact_id)
    return f"{base}/artifacts/{artifact_id}?token={token}"
