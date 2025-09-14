import os
import sys
from pathlib import Path

import pytest

# Make project importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.artifacts.tokens import create_token, verify_token, create_download_url


def test_artifact_token_secret_required():
    """Test that ARTIFACTS_TOKEN_SECRET is required for token operations."""
    # Clear environment
    if "ARTIFACTS_TOKEN_SECRET" in os.environ:
        del os.environ["ARTIFACTS_TOKEN_SECRET"]
    
    with pytest.raises(RuntimeError, match="ARTIFACTS_TOKEN_SECRET not set"):
        create_token("test_artifact")


def test_artifact_public_base_url_required():
    """Test that ARTIFACTS_PUBLIC_BASE_URL is required for download URLs."""
    # Set token secret but not base URL
    os.environ["ARTIFACTS_TOKEN_SECRET"] = "test-secret-key"
    if "ARTIFACTS_PUBLIC_BASE_URL" in os.environ:
        del os.environ["ARTIFACTS_PUBLIC_BASE_URL"]
    
    with pytest.raises(RuntimeError, match="ARTIFACTS_PUBLIC_BASE_URL not set"):
        create_download_url("test_artifact")


def test_artifact_token_creation_and_verification():
    """Test token creation and verification with proper environment variables."""
    os.environ["ARTIFACTS_TOKEN_SECRET"] = "test-secret-key-12345"
    os.environ["ARTIFACTS_PUBLIC_BASE_URL"] = "http://localhost:8000"
    
    artifact_id = "test_artifact_123"
    
    # Create token
    token = create_token(artifact_id)
    assert token is not None
    assert "." in token  # Should have format: payload.signature
    
    # Verify token
    result = verify_token(token)
    assert result["artifact_id"] == artifact_id
    assert "exp" in result
    assert result["exp"] > 0


def test_artifact_download_url_creation():
    """Test download URL creation with proper environment variables."""
    os.environ["ARTIFACTS_TOKEN_SECRET"] = "test-secret-key-12345"
    os.environ["ARTIFACTS_PUBLIC_BASE_URL"] = "http://localhost:8000"
    
    artifact_id = "test_artifact_456"
    
    # Create download URL
    url = create_download_url(artifact_id)
    assert url.startswith("http://localhost:8000/artifacts/")
    assert artifact_id in url
    assert "token=" in url
    
    # Extract token from URL and verify it
    token = url.split("token=")[1]
    result = verify_token(token)
    assert result["artifact_id"] == artifact_id


def test_artifact_token_ttl_override():
    """Test that ARTIFACTS_TOKEN_TTL_SECONDS can be overridden."""
    os.environ["ARTIFACTS_TOKEN_SECRET"] = "test-secret-key-12345"
    os.environ["ARTIFACTS_TOKEN_TTL_SECONDS"] = "300"  # 5 minutes
    
    artifact_id = "test_artifact_ttl"
    token = create_token(artifact_id)
    result = verify_token(token)
    
    # Check that expiration is approximately 5 minutes from now
    import time
    current_time = int(time.time())
    expected_exp = current_time + 300
    assert abs(result["exp"] - expected_exp) < 5  # Allow 5 second tolerance


def test_artifact_token_expiration():
    """Test that expired tokens are rejected."""
    os.environ["ARTIFACTS_TOKEN_SECRET"] = "test-secret-key-12345"
    
    artifact_id = "test_artifact_expired"
    
    # Create token with past expiration
    import time
    past_time = int(time.time()) - 3600  # 1 hour ago
    token = create_token(artifact_id, now=past_time)
    
    # Verify token should fail due to expiration
    with pytest.raises(RuntimeError, match="Token expired"):
        verify_token(token)


def test_artifact_token_invalid_format():
    """Test that malformed tokens are rejected."""
    os.environ["ARTIFACTS_TOKEN_SECRET"] = "test-secret-key-12345"
    
    # Test various invalid token formats
    invalid_tokens = [
        "invalid",
        "invalid.token",
        "invalid.token.extra",
        "",
        "invalid..token",
    ]
    
    for token in invalid_tokens:
        with pytest.raises(RuntimeError, match="Invalid token format"):
            verify_token(token)


def test_artifact_token_invalid_signature():
    """Test that tokens with invalid signatures are rejected."""
    os.environ["ARTIFACTS_TOKEN_SECRET"] = "test-secret-key-12345"
    
    artifact_id = "test_artifact_invalid"
    valid_token = create_token(artifact_id)
    
    # Modify the signature part to make it invalid
    parts = valid_token.split(".")
    invalid_token = parts[0] + "." + "invalid_signature"
    
    with pytest.raises(RuntimeError):
        verify_token(invalid_token)


def test_artifact_download_url_with_trailing_slash():
    """Test that download URL handles base URL with trailing slash correctly."""
    os.environ["ARTIFACTS_TOKEN_SECRET"] = "test-secret-key-12345"
    os.environ["ARTIFACTS_PUBLIC_BASE_URL"] = "http://localhost:8000/"
    
    artifact_id = "test_artifact_slash"
    url = create_download_url(artifact_id)
    
    # Should not have double slashes in the path part
    assert "//" not in url.split("://")[1]  # Check only the path part after protocol
    assert url.startswith("http://localhost:8000/artifacts/")
    assert artifact_id in url
