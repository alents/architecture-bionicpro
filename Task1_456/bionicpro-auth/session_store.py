import uuid
import time
from typing import Optional
from dataclasses import dataclass
from crypto import encrypt, decrypt
from config import SESSION_MAX_AGE


@dataclass
class SessionData:
    access_token: str
    encrypted_refresh_token: str  # хранится зашифрованным
    access_token_expiry: float    # timestamp
    created_at: float


# In-memory хранилище
_sessions: dict[str, SessionData] = {}


def create_session(access_token: str, refresh_token: str, expires_in: int) -> str:
    session_id = uuid.uuid4().hex
    _sessions[session_id] = SessionData(
        access_token=access_token,
        encrypted_refresh_token=encrypt(refresh_token),
        access_token_expiry=time.time() + expires_in,
        created_at=time.time(),
    )
    return session_id


def get_session(session_id: str) -> Optional[SessionData]:
    session = _sessions.get(session_id)
    if session is None:
        return None
    # Проверяем, не истекла ли сессия целиком
    if time.time() - session.created_at > SESSION_MAX_AGE:
        delete_session(session_id)
        return None
    return session


def get_refresh_token(session_id: str) -> Optional[str]:
    session = get_session(session_id)
    if session is None:
        return None
    return decrypt(session.encrypted_refresh_token)


def update_tokens(session_id: str, access_token: str, refresh_token: str, expires_in: int):
    session = _sessions.get(session_id)
    if session:
        session.access_token = access_token
        session.encrypted_refresh_token = encrypt(refresh_token)
        session.access_token_expiry = time.time() + expires_in


def rotate_session(old_session_id: str) -> Optional[str]:
    """Ротация: переносим данные на новый session_id, удаляем старый."""
    session = _sessions.pop(old_session_id, None)
    if session is None:
        return None
    new_session_id = uuid.uuid4().hex
    _sessions[new_session_id] = session
    return new_session_id


def delete_session(session_id: str):
    _sessions.pop(session_id, None)