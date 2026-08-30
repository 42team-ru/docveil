import pytest
import jwt
from datetime import UTC, datetime, timedelta

from api.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_token,
)
from api.core.config import settings


def test_password_hashing():
    password = "my_secure_password"
    hashed = hash_password(password)
    
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrong_password", hashed) is False


def test_access_token_creation_and_decoding():
    subject = "user-uuid"
    roles = ["user", "admin"]
    
    token = create_access_token(subject, roles)
    assert isinstance(token, str)
    
    payload = decode_access_token(token)
    assert payload["sub"] == subject
    assert payload["roles"] == roles
    assert "exp" in payload


def test_access_token_expired():
    # Patch the settings to make token expire immediately
    old_expire = settings.access_token_expire_minutes
    settings.access_token_expire_minutes = -1  # expires in the past
    
    token = create_access_token("sub", ["user"])
    
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)
        
    settings.access_token_expire_minutes = old_expire


def test_refresh_token_generation_and_hashing():
    token1 = generate_refresh_token()
    token2 = generate_refresh_token()
    
    assert token1 != token2
    assert len(token1) > 20
    
    hashed_token = hash_token(token1)
    assert hashed_token != token1
    assert len(hashed_token) == 64  # sha256 hex length
