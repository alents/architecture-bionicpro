import time
import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import secrets
from config import (
    KEYCLOAK_AUTH_URL, KEYCLOAK_TOKEN_URL, CLIENT_ID, CLIENT_SECRET, CALLBACK_URL,
    FRONTEND_URL, SESSION_MAX_AGE, REPORTS_SERVICE_URL
)
import session_store
import jwt
from database import init_db, async_session
from models import UserProfile
from sqlalchemy import select
from typing import Optional
from urllib.parse import urlencode

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(lifespan=lifespan)

async def save_user_profile(
        subject_id: str,
        email: str = None,
        first_name: str = None,
        last_name: str = None,
        birthday: str = None,
        identity_provider: str = None,
):
    async with async_session() as session:
        result = await session.execute(
            select(UserProfile).where(UserProfile.subject_id == subject_id)
        )
        profile = result.scalar_one_or_none()

        if profile:
            # Обновляем существующий профиль
            if email:
                profile.email = email
            if first_name:
                profile.first_name = first_name
            if last_name:
                profile.last_name = last_name
            if birthday:
                profile.birthday = birthday
            if identity_provider:
                profile.identity_provider = identity_provider
        else:
            # Создаём новый
            profile = UserProfile(
                subject_id=subject_id,
                email=email,
                first_name=first_name,
                last_name=last_name,
                birthday=birthday,
                identity_provider=identity_provider,
            )
            session.add(profile)

        await session.commit()




# CORS — разрешаем фронтенду слать cookie
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

COOKIE_NAME = "SESSION_ID"


def set_session_cookie(response: Response, session_id: str):
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_id,
        httponly=True,
        secure=False,      # на продакшене заменить на True
        samesite="lax",
        max_age=SESSION_MAX_AGE,
        path="/",
    )

# Временное хранилище state (TTL 5 минут)
_pending_states: dict[str, float] = {}

async def get_valid_session(request: Request) -> tuple[Optional[session_store.SessionData], Optional[str]]:

    session_id = request.cookies.get(COOKIE_NAME)
    if not session_id:
        return None, None

    session = session_store.get_session(session_id)
    if not session:
        return None, None

    # Если access_token протух — обновляем через refresh_token
    if session.access_token_expiry <= time.time():
        refresh_token = session_store.get_refresh_token(session_id)
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                KEYCLOAK_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                },
            )
        if token_response.status_code != 200:
            session_store.delete_session(session_id)
            return None, None

        tokens = token_response.json()
        session_store.update_tokens(
            session_id,
            tokens["access_token"],
            tokens["refresh_token"],
            tokens["expires_in"],
        )
        # Получаем обновленную сессию
        session = session_store.get_session(session_id)

    # Ротация сессии
    new_session_id = session_store.rotate_session(session_id)
    if not new_session_id:
        return None, None

    return session, new_session_id

# --- /auth/login ---
@app.get("/auth/login")
def login():
    state = secrets.token_urlsafe(32)
    _pending_states[state] = time.time()

    # Редиректим браузер на Keycloak для авторизации
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": CALLBACK_URL,
        "response_type": "code",
        "scope": "openid",
        "state": state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(url=f"{KEYCLOAK_AUTH_URL}?{query}")


# --- /auth/callback ---
@app.get("/auth/callback")
async def callback(code: str, state: str):
    # Проверяем state
    created_at = _pending_states.pop(state, None)
    if created_at is None or time.time() - created_at > 300:  # 5 минут TTL
        return Response(status_code=400, content="Invalid or expired state")

    # Keycloak редиректит сюда с ?code=..., обмениваем code на токены.
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            KEYCLOAK_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": CALLBACK_URL,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        )

    if token_response.status_code != 200:
        return RedirectResponse(url=f"{FRONTEND_URL}?error=auth_failed")

    tokens = token_response.json()

    # Декодируем access_token для получения базовых данных
    user_info = jwt.decode(
        tokens["access_token"],
        options={"verify_signature": False}
    )


    # Определяем, через какой провайдер пришёл пользователь
    identity_provider = user_info.get("identity_provider", "keycloak")

    # сохраняем профиль
    await save_user_profile(
        subject_id=user_info.get("sub"),
        email=user_info.get("email"),
        first_name=user_info.get("given_name"),
        last_name=user_info.get("family_name"),
        birthday=user_info.get("birthday"),
        identity_provider=identity_provider,
    )

    # Создаем сессию
    session_id = session_store.create_session(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens["expires_in"],
    )

    response = RedirectResponse(url=FRONTEND_URL)
    set_session_cookie(response, session_id)
    return response


# --- /auth/me ---
@app.get("/auth/me")
async def me(request: Request, response: Response):
    session, new_session_id = await get_valid_session(request)
    if not session or not new_session_id:
        return Response(status_code=401)

    resp = Response(content='{"status": "authenticated"}', media_type="application/json")
    set_session_cookie(resp, new_session_id)

    return resp

# --- /auth/report ---
@app.get("/api/report")
async def get_report(
        request: Request,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None
):
    """
    Проксирование запроса на получение отчёта в сервис reports.
    Извлекает access_token из сессии и передаёт его в Authorization header.
    """
    session, new_session_id = await get_valid_session(request)
    if not session or not new_session_id:
        return Response(status_code=401)

    # Получаем актуальный access_token
    access_token = session.access_token
    if not access_token:
        return Response(status_code=401)

    # Формируем query параметры
    params = {}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if limit:
        params["limit"] = limit

    # Проксируем запрос в сервис отчётов
    reports_url = f"{REPORTS_SERVICE_URL}/api/report"
    if params:
        reports_url += f"?{urlencode(params)}"

    async with httpx.AsyncClient() as client:
        try:
            proxy_response = await client.get(
                reports_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                timeout=30.0
            )

            resp = Response(
                content=proxy_response.content,
                status_code=proxy_response.status_code,
                media_type="application/json"
            )
            set_session_cookie(resp, new_session_id)
            return resp
        except Exception:
            return Response(status_code=503)

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=3001)

