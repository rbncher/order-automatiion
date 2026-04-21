"""Simple session-based authentication for the dashboard."""
import hashlib
import hmac
import os
import secrets
from functools import wraps

from fastapi import Request, Response, HTTPException
from fastapi.responses import RedirectResponse

# Simple user store — in production, move to DB
# Format: {"username": "password_hash"}
# Generate hash: python -c "import hashlib; print(hashlib.sha256(b'yourpassword').hexdigest())"
USERS: dict[str, str] = {}

# Load users from env: DASHBOARD_USERS="admin:sha256hash,viewer:sha256hash"
_users_str = os.environ.get("DASHBOARD_USERS", "")
if _users_str:
    for pair in _users_str.split(","):
        if ":" in pair:
            user, pw_hash = pair.split(":", 1)
            USERS[user.strip()] = pw_hash.strip()

# Default admin user if none configured (hash of "changeme")
if not USERS:
    USERS["admin"] = hashlib.sha256(b"changeme").hexdigest()

# Session secret
SESSION_SECRET = os.environ.get("SESSION_SECRET", secrets.token_hex(32))

# Active sessions: {session_id: username}
_sessions: dict[str, str] = {}


def verify_password(username: str, password: str) -> bool:
    """Check username/password against store."""
    stored_hash = USERS.get(username)
    if not stored_hash:
        return False
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    return hmac.compare_digest(pw_hash, stored_hash)


def create_session(username: str) -> str:
    """Create a new session and return the session ID."""
    session_id = secrets.token_hex(32)
    _sessions[session_id] = username
    return session_id


def get_current_user(request: Request) -> str | None:
    """Get the current user from session cookie."""
    session_id = request.cookies.get("session_id")
    if not session_id:
        return None
    return _sessions.get(session_id)


def require_auth(request: Request) -> str:
    """Check auth and return username, or redirect to login."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401)
    return user


def logout(session_id: str):
    """Remove a session."""
    _sessions.pop(session_id, None)
