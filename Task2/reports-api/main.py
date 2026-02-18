from fastapi import FastAPI, HTTPException, Query, Depends
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

# Модели данных
class EmgSensorData(BaseModel):
    user_id: int
    prosthesis_type: str
    muscle_group: str
    signal_frequency: int
    signal_duration: int
    signal_amplitude: float
    signal_time: datetime

class ReportResponse(BaseModel):
    user_id: int
    period_start: datetime
    period_end: datetime
    total_records: int
    data: List[EmgSensorData]
    statistics: dict

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
    # Инициализация при запуске
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

    yield

    # Очистка при завершении
    if clickhouse_client:
        clickhouse_client.close()
    if pg_pool:
        await pg_pool.close()

app = FastAPI(
    title="BionicPro Reports Service",
    description="Микросервис для получения отчетов о работе протезов из ClickHouse",
    version="1.0.0",
    lifespan=lifespan
)

security = HTTPBearer()

def get_clickhouse_client():
    """Dependency для получения клиента ClickHouse"""
    if clickhouse_client is None:
        print("ClickHouse connection not available")
        raise HTTPException(
            status_code=503,
            detail="ClickHouse connection not available"
        )
    return clickhouse_client

def get_pg_pool():
    """Dependency для получения пула PostgreSQL"""
    if pg_pool is None:
        print("PostgreSQL connection not available")
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL connection not available"
        )
    return pg_pool

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    Проверка и декодирование JWT токена из Keycloak

    Returns:
        dict: Декодированные claims из токена (включая subject_id)
    """

    token = credentials.credentials

    try:
        # Получаем публичный ключ для проверки подписи из JWKS
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        # Декодируем и валидируем токен
        decoded_token = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={
                "verify_exp": True,
                "verify_aud": False
            }
        )

        return decoded_token

    except jwt.ExpiredSignatureError as e:
        print(f"jwt.ExpiredSignatureError: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError as e:
        print(f"jwt.InvalidTokenError: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail=f"Invalid token: {str(e)}"
        )
    except Exception as e:
        print(f"Exception: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail=f"Token verification failed: {str(e)}"
        )

async def get_current_user(
        token_data: dict = Depends(verify_token),
        pool = Depends(get_pg_pool)
) -> UserProfile:
    """
    Получить профиль текущего пользователя по subject_id из токена

    Returns:
        UserProfile: Профиль пользователя из БД
    """
    subject_id = token_data.get("sub")

    if not subject_id:
        raise HTTPException(
            status_code=401,
            detail="Subject ID not found in token"
        )

    # Запрос профиля из БД
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id, subject_id, email, first_name, last_name
            FROM user_profiles
            WHERE subject_id = $1
            """,
            subject_id
        )

    if not row:
        raise HTTPException(
            status_code=404,
            detail="User profile not found"
        )

    return UserProfile(
        user_id=row['user_id'],
        subject_id=row['subject_id'],
        email=row['email'],
        first_name=row['first_name'],
        last_name=row['last_name']
    )

@app.get("/api/report", response_model=ReportResponse)
async def get_user_report(
        start_date: datetime = Query(
            ...,
            description="Начало периода в формате ISO 8601 (например: 2024-01-01T00:00:00)"
        ),
        end_date: datetime = Query(
            ...,
            description="Конец периода в формате ISO 8601 (например: 2024-12-31T23:59:59)"
        ),
        limit: int = Query(
            default=1000,
            ge=1,
            le=10000,
            description="Максимальное количество записей в ответе"
        ),
        current_user: UserProfile = Depends(get_current_user),
        client = Depends(get_clickhouse_client)
):
    """
    Получить отчет о работе протеза для текущего авторизованного пользователя.

    Требует авторизации через Bearer token.
    User ID автоматически извлекается из токена.

    Args:
        start_date: Начало периода
        end_date: Конец периода
        limit: Максимальное количество записей

    Returns:
        Отчет с данными сигналов и статистикой
    """
    user_id = current_user.user_id

    try:
        # Валидация периода
        if start_date >= end_date:
            raise HTTPException(
                status_code=400,
                detail="start_date должна быть меньше end_date"
            )

        # Запрос основных данных
        query = """
                SELECT
                    user_id,
                    prosthesis_type,
                    muscle_group,
                    signal_frequency,
                    signal_duration,
                    signal_amplitude,
                    signal_time
                FROM bionicpro.emg_user_report
                WHERE user_id = {user_id:UInt32}
                  AND signal_time >= {start_date:DateTime}
                  AND signal_time <= {end_date:DateTime}
                ORDER BY signal_time DESC
                    LIMIT {limit:UInt32} \
                """

        result = client.query(
            query,
            parameters={
                'user_id': user_id,
                'start_date': start_date,
                'end_date': end_date,
                'limit': limit
            }
        )

        # Запрос статистики
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
                      FROM bionicpro.emg_user_report
                      WHERE user_id = {user_id:UInt32}
                        AND signal_time >= {start_date:DateTime}
                        AND signal_time <= {end_date:DateTime} \
                      """

        stats_result = client.query(
            stats_query,
            parameters={
                'user_id': user_id,
                'start_date': start_date,
                'end_date': end_date
            }
        )

        # Преобразование результатов
        data = []
        for row in result.result_rows:
            data.append(EmgSensorData(
                user_id=row[0],
                prosthesis_type=row[1],
                muscle_group=row[2],
                signal_frequency=row[3],
                signal_duration=row[4],
                signal_amplitude=float(row[5]),
                signal_time=row[6]
            ))

        # Формирование статистики
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

        return ReportResponse(
            user_id=user_id,
            period_start=start_date,
            period_end=end_date,
            total_records=statistics["total_records"],
            data=data,
            statistics=statistics
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при получении отчета: {str(e)}"
        )