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
import os
import json

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
    created_at = _pending_states.pop(state, None)
    if created_at is None or time.time() - created_at > 300:
        return Response(status_code=400, content="Invalid or expired state")

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

    user_info = jwt.decode(
        tokens["access_token"],
        options={"verify_signature": False}
    )

    identity_provider = user_info.get("identity_provider", "keycloak")

    await save_user_profile(
        subject_id=user_info.get("sub"),
        email=user_info.get("email"),
        first_name=user_info.get("given_name"),
        last_name=user_info.get("family_name"),
        birthday=user_info.get("birthday"),
        identity_provider=identity_provider,
    )

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

# --- /api/report/{report_name} ---
@app.get("/api/report/{report_name}")
async def get_report(
        report_name: str,
        request: Request,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
):
    """
    Получение отчёта: двухшаговый процесс.

    Шаг 1: Запрос к reports-api → получаем CDN-ссылку (reports-api сам решает,
            нужно ли генерировать отчёт или он уже есть в S3).
    Шаг 2: Gateway идёт по CDN-ссылке с access_token → nginx проверяет токен
            через auth_request к reports-api и отдаёт файл из кеша/MinIO.
    Шаг 3: Gateway возвращает JSON-содержимое файла клиенту.
    """
    session, new_session_id = await get_valid_session(request)
    if not session or not new_session_id:
        return Response(status_code=401)

    access_token = session.access_token
    if not access_token:
        return Response(status_code=401)

    # Формируем query параметры
    params = {}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    async with httpx.AsyncClient() as client:
        try:
            # Шаг 1: Получаем CDN-ссылку от reports-api
            reports_url = f"{REPORTS_SERVICE_URL}/api/report/{report_name}"
            if params:
                reports_url += f"?{urlencode(params)}"

            report_response = await client.get(
                reports_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                timeout=30.0
            )

            if report_response.status_code != 200:
                resp = Response(
                    content=report_response.content,
                    status_code=report_response.status_code,
                    media_type="application/json"
                )
                set_session_cookie(resp, new_session_id)
                return resp

            # Парсим ответ — получаем cdn_url
            report_data = report_response.json()
            cdn_url = report_data.get("cdn_url")

            if not cdn_url:
                return Response(
                    content=json.dumps({"error": "CDN URL not received from reports service"}),
                    status_code=502,
                    media_type="application/json"
                )

            # Шаг 2: Забираем файл с CDN (nginx) с access_token
            cdn_response = await client.get(
                cdn_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                },
                timeout=30.0
            )

            if cdn_response.status_code != 200:
                return Response(
                    content=json.dumps({
                        "error": "Failed to fetch report from CDN",
                        "cdn_status": cdn_response.status_code
                    }),
                    status_code=502,
                    media_type="application/json"
                )

            # Шаг 3: Возвращаем содержимое файла клиенту
            resp = Response(
                content=cdn_response.content,
                status_code=200,
                media_type="application/json"
            )
            set_session_cookie(resp, new_session_id)
            return resp

        except httpx.TimeoutException:
            return Response(
                content=json.dumps({"error": "Request timeout"}),
                status_code=504,
                media_type="application/json"
            )
        except Exception as e:
            return Response(
                content=json.dumps({"error": f"Internal error: {str(e)}"}),
                status_code=503,
                media_type="application/json"
            )