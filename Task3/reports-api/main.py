from fastapi import FastAPI, HTTPException, Query, Depends, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import clickhouse_connect
import asyncpg
import os
import jwt
from jwt import PyJWKClient
from contextlib import asynccontextmanager
import re

from s3_client import (
    init_s3_client, report_exists, upload_report, get_report_cdn_url,
    delete_by_report_name, delete_by_user, delete_all_reports
)

# Список допустимых имён отчётов.
# При добавлении нового типа отчёта достаточно добавить его сюда
# и реализовать соответствующий генератор.
ALLOWED_REPORT_NAMES = {"sensor_data"}

# Модели данных
class EmgSensorData(BaseModel):
    user_id: int
    prosthesis_type: str
    muscle_group: str
    signal_frequency: int
    signal_duration: int
    signal_amplitude: float
    signal_time: datetime

class ReportUrlResponse(BaseModel):
    """Ответ с CDN-ссылкой на отчёт"""
    cdn_url: str
    cached: bool  # True если отчёт уже был в S3

class UserProfile(BaseModel):
    user_id: int
    subject_id: str
    email: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]

# Глобальные переменные
clickhouse_client = None
pg_pool = None
jwks_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global clickhouse_client, pg_pool, jwks_client

    # ClickHouse подключение
    clickhouse_host = os.getenv("CLICKHOUSE_HOST", "localhost")
    clickhouse_port = int(os.getenv("CLICKHOUSE_PORT", "9000"))
    clickhouse_user = os.getenv("CLICKHOUSE_USER", "default")
    clickhouse_password = os.getenv("CLICKHOUSE_PASSWORD", "")
    clickhouse_database = os.getenv("CLICKHOUSE_DATABASE", "bionicpro")

    try:
        clickhouse_client = clickhouse_connect.get_client(
            host=clickhouse_host,
            port=clickhouse_port,
            username=clickhouse_user,
            password=clickhouse_password,
            database=clickhouse_database
        )
        print(f"Connected to ClickHouse at {clickhouse_host}:{clickhouse_port}")
    except Exception as e:
        print(f"Failed to connect to ClickHouse: {e}")
        clickhouse_client = None

    # PostgreSQL подключение
    auth_db_url = os.getenv("AUTH_DATABASE_URL")

    try:
        pg_pool = await asyncpg.create_pool(auth_db_url, min_size=2, max_size=10)
        print(f"Connected to PostgreSQL (auth DB)")
    except Exception as e:
        print(f"Failed to connect to PostgreSQL: {e}")
        pg_pool = None

    # Keycloak JWKS для валидации токенов
    keycloak_url = os.getenv("KEYCLOAK_URL")
    keycloak_realm = os.getenv("KEYCLOAK_REALM")
    jwks_url = f"{keycloak_url}/realms/{keycloak_realm}/protocol/openid-connect/certs"

    try:
        jwks_client = PyJWKClient(jwks_url)
        print(f"Initialized JWKS client for {jwks_url}")
    except Exception as e:
        print(f"Failed to initialize JWKS client: {e}")
        jwks_client = None

    # Инициализация S3-клиента (MinIO)
    try:
        init_s3_client()
        print("S3 client initialized")
    except Exception as e:
        print(f"Failed to initialize S3 client: {e}")

    yield

    if clickhouse_client:
        clickhouse_client.close()
    if pg_pool:
        await pg_pool.close()

app = FastAPI(
    title="BionicPro Reports Service",
    description="Микросервис для получения отчётов о работе протезов из ClickHouse",
    version="2.0.0",
    lifespan=lifespan
)

security = HTTPBearer()

def get_clickhouse_client():
    """Dependency для получения клиента ClickHouse"""
    if clickhouse_client is None:
        raise HTTPException(status_code=503, detail="ClickHouse connection not available")
    return clickhouse_client

def get_pg_pool():
    """Dependency для получения пула PostgreSQL"""
    if pg_pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL connection not available")
    return pg_pool

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Проверка и декодирование JWT токена из Keycloak"""
    token = credentials.credentials

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        decoded_token = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_exp": True, "verify_aud": False}
        )
        return decoded_token
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token verification failed: {str(e)}")

async def get_current_user(
        token_data: dict = Depends(verify_token),
        pool = Depends(get_pg_pool)
) -> UserProfile:
    """Получить профиль текущего пользователя по subject_id из токена"""
    subject_id = token_data.get("sub")
    if not subject_id:
        raise HTTPException(status_code=401, detail="Subject ID not found in token")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, subject_id, email, first_name, last_name FROM user_profiles WHERE subject_id = $1",
            subject_id
        )

    if not row:
        raise HTTPException(status_code=404, detail="User profile not found")

    return UserProfile(
        user_id=row['user_id'],
        subject_id=row['subject_id'],
        email=row['email'],
        first_name=row['first_name'],
        last_name=row['last_name']
    )


def _generate_report_from_clickhouse(
        client, user_id: int, start_date: datetime, end_date: datetime
) -> dict:
    """Генерирует отчёт sensor_data из ClickHouse и возвращает его как dict."""
    query = """
            SELECT
                user_id, prosthesis_type, muscle_group,
                signal_frequency, signal_duration, signal_amplitude, signal_time
            FROM bionicpro.emg_sensor_data
            WHERE user_id = {user_id:UInt32}
              AND signal_time >= {start_date:DateTime}
              AND signal_time <= {end_date:DateTime}
            ORDER BY signal_time DESC                
            """

    result = client.query(
        query,
        parameters={
            'user_id': user_id, 'start_date': start_date,
            'end_date': end_date
        }
    )

    stats_query = """
                  SELECT
                      count() as total_records,
                      avg(signal_amplitude) as avg_amplitude,
                      max(signal_amplitude) as max_amplitude,
                      min(signal_amplitude) as min_amplitude,
                      avg(signal_frequency) as avg_frequency,
                      avg(signal_duration) as avg_duration,
                      uniq(prosthesis_type) as unique_prosthesis_types,
                      uniq(muscle_group) as unique_muscle_groups
                  FROM bionicpro.emg_sensor_data
                  WHERE user_id = {user_id:UInt32}
                    AND signal_time >= {start_date:DateTime}
                    AND signal_time <= {end_date:DateTime}
                  """

    stats_result = client.query(
        stats_query,
        parameters={
            'user_id': user_id, 'start_date': start_date, 'end_date': end_date
        }
    )

    data = []
    for row in result.result_rows:
        data.append({
            "user_id": row[0], "prosthesis_type": row[1], "muscle_group": row[2],
            "signal_frequency": row[3], "signal_duration": row[4],
            "signal_amplitude": float(row[5]),
            "signal_time": row[6].isoformat() if isinstance(row[6], datetime) else str(row[6])
        })

    stats_row = stats_result.result_rows[0] if stats_result.result_rows else None
    statistics = {
        "total_records": stats_row[0] if stats_row else 0,
        "avg_amplitude": round(float(stats_row[1]), 2) if stats_row and stats_row[1] else 0.0,
        "max_amplitude": round(float(stats_row[2]), 2) if stats_row and stats_row[2] else 0.0,
        "min_amplitude": round(float(stats_row[3]), 2) if stats_row and stats_row[3] else 0.0,
        "avg_frequency": round(float(stats_row[4]), 2) if stats_row and stats_row[4] else 0.0,
        "avg_duration": round(float(stats_row[5]), 2) if stats_row and stats_row[5] else 0.0,
        "unique_prosthesis_types": stats_row[6] if stats_row else 0,
        "unique_muscle_groups": stats_row[7] if stats_row else 0
    }

    return {
        "user_id": user_id,
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "total_records": statistics["total_records"],
        "data": data,
        "statistics": statistics
    }


# --- Эндпоинт получения отчёта ---

@app.get("/api/report/{report_name}", response_model=ReportUrlResponse)
async def get_user_report(
        report_name: str,
        start_date: datetime = Query(
            ..., description="Начало периода в формате ISO 8601 (например: 2024-01-01T00:00:00)"
        ),
        end_date: datetime = Query(
            ..., description="Конец периода в формате ISO 8601 (например: 2024-12-31T23:59:59)"
        ),
        current_user: UserProfile = Depends(get_current_user),
        client = Depends(get_clickhouse_client)
):
    """
    Получить отчёт для текущего авторизованного пользователя.

    report_name определяет тип отчёта (например: sensor_data).
    Логика:
    1. Проверяем, есть ли отчёт в S3 (MinIO)
    2. Если есть — возвращаем CDN-ссылку (cached=True)
    3. Если нет — генерируем из ClickHouse, сохраняем в S3, возвращаем CDN-ссылку (cached=False)
    """
    if report_name not in ALLOWED_REPORT_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown report type: {report_name}")

    user_id = current_user.user_id

    try:
        if start_date >= end_date:
            raise HTTPException(status_code=400, detail="start_date должна быть меньше end_date")

        cached = report_exists(report_name, user_id, start_date, end_date)

        if not cached:
            report_data = _generate_report_from_clickhouse(
                client, user_id, start_date, end_date
            )
            upload_report(report_name, user_id, start_date, end_date, report_data)

        cdn_url = get_report_cdn_url(report_name, user_id, start_date, end_date)

        return ReportUrlResponse(cdn_url=cdn_url, cached=cached)

    except HTTPException:
        raise
    except Exception as e:
        print(f"Ошибка при получении отчёта: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка при получении отчёта: {str(e)}")


# --- Эндпоинт авторизации для nginx ---

@app.get("/auth/verify")
async def verify_cdn_access(
        request: Request,
        token_data: dict = Depends(verify_token),
        pool = Depends(get_pg_pool)
):
    """
    Эндпоинт для nginx auth_request.

    Nginx передаёт оригинальный URI в заголовке X-Original-URI.
    URI имеет формат: /reports/{report_name}/{user_id}/{dates}.json
    Проверяем, что user_id из токена совпадает с user_id в пути.
    """
    original_uri = request.headers.get("X-Original-URI", "")

    # Извлекаем user_id из пути: /reports/{report_name}/{user_id}/...
    # report_name — строка из букв, цифр и подчёркиваний
    match = re.search(r"/reports/[a-zA-Z0-9_]+/(\d+)/", original_uri)
    if not match:
        raise HTTPException(status_code=403, detail="Invalid report path")

    requested_user_id = int(match.group(1))

    subject_id = token_data.get("sub")
    if not subject_id:
        raise HTTPException(status_code=401, detail="Subject ID not found in token")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM user_profiles WHERE subject_id = $1",
            subject_id
        )

    if not row:
        raise HTTPException(status_code=403, detail="User not found")

    if row["user_id"] != requested_user_id:
        raise HTTPException(status_code=403, detail="Access denied: you can only access your own reports")

    return {"status": "ok"}


# --- Админские эндпоинты инвалидации кеша ---

async def _require_admin(token_data: dict = Depends(verify_token)) -> dict:
    """Dependency: проверяет наличие роли admin в токене"""
    realm_roles = token_data.get("realm_access", {}).get("roles", [])
    if "admin" not in realm_roles:
        raise HTTPException(status_code=403, detail="Admin role required")
    return token_data


@app.delete("/api/admin/cache/report/{report_name}")
async def invalidate_cache_by_report(
        report_name: str,
        token_data: dict = Depends(_require_admin),
):
    """
    Удаляет все закешированные экземпляры конкретного отчёта из S3
    (для всех пользователей и периодов).

    Пример: DELETE /api/admin/cache/report/sensor_data
    Используется при изменении логики формирования отчёта или исправлении ошибок.
    """
    deleted_count = delete_by_report_name(report_name)
    return {
        "report_name": report_name,
        "deleted_count": deleted_count,
        "message": f"Deleted {deleted_count} cached reports of type '{report_name}'"
    }


@app.delete("/api/admin/cache/user/{user_id}")
async def invalidate_cache_by_user(
        user_id: int,
        token_data: dict = Depends(_require_admin),
):
    """
    Удаляет все закешированные отчёты конкретного пользователя из S3
    (все типы отчётов).

    Пример: DELETE /api/admin/cache/user/42
    Используется при удалении данных пользователя (GDPR / 152-ФЗ).
    """
    deleted_count = delete_by_user(user_id)
    return {
        "user_id": user_id,
        "deleted_count": deleted_count,
        "message": f"Deleted {deleted_count} cached reports for user {user_id}"
    }


@app.delete("/api/admin/cache")
async def invalidate_all_cache(
        token_data: dict = Depends(_require_admin),
):
    """
    Удаляет ВСЕ закешированные отчёты из S3 (все типы, все пользователи).

    Пример: DELETE /api/admin/cache
    Используется для полного сброса кеша.
    """
    deleted_count = delete_all_reports()
    return {
        "deleted_count": deleted_count,
        "message": f"Deleted {deleted_count} cached reports (all)"
    }