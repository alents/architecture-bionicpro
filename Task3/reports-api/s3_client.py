import boto3
import json
import os
from botocore.exceptions import ClientError
from datetime import datetime

# Конфигурация S3 (MinIO)
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://minio:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
S3_BUCKET = os.getenv("S3_BUCKET", "reports")
CDN_BASE_URL = os.getenv("CDN_BASE_URL", "http://cdn:80")

s3_client = None


def init_s3_client():
    """Инициализация S3-клиента для MinIO"""
    global s3_client
    s3_client = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name="us-east-1",
    )
    return s3_client


def _build_report_key(
        report_name: str, user_id: int, start_date: datetime, end_date: datetime
) -> str:
    """
    Формирует ключ объекта в S3.

    Структура: {report_name}/{user_id}/{start_date}_{end_date}.json
    Пример:   sensor_data/42/2024-01-01T000000_2024-03-01T235959.json

    Имя отчёта — первый уровень иерархии. Это позволяет:
    - быстро инвалидировать кеш по типу отчёта (например, при изменении логики формирования)
    - добавлять новые типы отчётов без изменения структуры хранения
    """
    start_str = start_date.strftime("%Y-%m-%dT%H%M%S")
    end_str = end_date.strftime("%Y-%m-%dT%H%M%S")
    return f"{report_name}/{user_id}/{start_str}_{end_str}.json"


def report_exists(
        report_name: str, user_id: int, start_date: datetime, end_date: datetime
) -> bool:
    """Проверяет наличие отчёта в S3 через HEAD-запрос"""
    key = _build_report_key(report_name, user_id, start_date, end_date)
    try:
        s3_client.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        raise


def upload_report(
        report_name: str, user_id: int, start_date: datetime, end_date: datetime,
        report_data: dict
) -> str:
    """
    Сохраняет отчёт в S3 как JSON.

    Returns:
        str: ключ объекта в S3
    """
    key = _build_report_key(report_name, user_id, start_date, end_date)
    json_bytes = json.dumps(report_data, default=str, ensure_ascii=False).encode("utf-8")

    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json_bytes,
        ContentType="application/json",
    )
    print(f"Report uploaded to S3: {key}")
    return key


def get_report_cdn_url(
        report_name: str, user_id: int, start_date: datetime, end_date: datetime
) -> str:
    """
    Формирует URL для доступа к отчёту через CDN (nginx).

    Пример ключа в S3: sensor_data/42/{start}_{end}.json (в бакете "reports")
    URL в CDN:          http://cdn:80/reports/sensor_data/42/{start}_{end}.json
    """
    key = _build_report_key(report_name, user_id, start_date, end_date)
    return f"{CDN_BASE_URL}/{S3_BUCKET}/{key}"


# --- Инвалидация кеша ---

def delete_by_report_name(report_name: str) -> int:
    """
    Удаляет все закешированные отчёты по имени (для всех пользователей и периодов).
    Используется при изменении логики формирования конкретного отчёта.

    Пример: delete_by_report_name("sensor_data") удалит всё в prefix sensor_data/
    """
    return _delete_by_prefix(f"{report_name}/")


def delete_by_user(user_id: int) -> int:
    """
    Удаляет все закешированные отчёты конкретного пользователя (все типы отчётов).
    Используется при удалении данных пользователя (GDPR / 152-ФЗ).

    Так как user_id — второй уровень иерархии, приходится перебирать
    все известные типы отчётов. Альтернатива — полный листинг бакета.
    """
    # Листим весь бакет и фильтруем по user_id в пути
    deleted_count = 0
    paginator = s3_client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=S3_BUCKET):
        objects = page.get("Contents", [])
        if not objects:
            continue

        # Фильтруем: ключ имеет формат {report_name}/{user_id}/...
        user_prefix = f"/{user_id}/"
        to_delete = [
            {"Key": obj["Key"]} for obj in objects
            if user_prefix in obj["Key"]
        ]

        if to_delete:
            s3_client.delete_objects(
                Bucket=S3_BUCKET,
                Delete={"Objects": to_delete}
            )
            deleted_count += len(to_delete)

    print(f"Deleted {deleted_count} objects for user_id={user_id}")
    return deleted_count


def delete_all_reports() -> int:
    """Удаляет все отчёты из бакета."""
    return _delete_by_prefix("")


def _delete_by_prefix(prefix: str) -> int:
    """
    Удаляет все объекты с заданным префиксом.

    Returns:
        int: количество удалённых объектов
    """
    deleted_count = 0
    paginator = s3_client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        objects = page.get("Contents", [])
        if not objects:
            continue

        delete_keys = [{"Key": obj["Key"]} for obj in objects]
        s3_client.delete_objects(
            Bucket=S3_BUCKET,
            Delete={"Objects": delete_keys}
        )
        deleted_count += len(delete_keys)

    print(f"Deleted {deleted_count} objects with prefix '{prefix}'")
    return deleted_count