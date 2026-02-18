from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
from clickhouse_driver import Client
import psycopg2
import os

default_args = {
    'owner': 'airflow',
    'start_date': datetime(2026, 1, 1),
}

BATCH_SIZE = 1000


def get_clickhouse_client():
    return Client(
        host=os.getenv('CLICKHOUSE_HOST', 'clickhouse'),
        port=int(os.getenv('CLICKHOUSE_PORT', '9000')),
        user=os.getenv('CLICKHOUSE_USER', 'clickhouse_user'),
        password=os.getenv('CLICKHOUSE_PASSWORD', 'clickhouse_password'),
        database=os.getenv('CLICKHOUSE_DATABASE', 'bionicpro')
    )


def get_postgres_connection():
    return psycopg2.connect(
        host=os.getenv('CRM_DB_HOST', 'crm_db'),
        port=int(os.getenv('CRM_DB_PORT', '5432')),
        dbname=os.getenv('CRM_DB_NAME', 'bionicpro_crm'),
        user=os.getenv('CRM_DB_USER', 'crm_user'),
        password=os.getenv('CRM_DB_PASSWORD', 'crm_password'),
    )


def load_emg_sensor_data():
    """Извлекает emg_sensor_data из PostgreSQL и загружает в ClickHouse."""
    pg_conn = get_postgres_connection()
    pg_cursor = pg_conn.cursor()
    ch_client = get_clickhouse_client()

    # Очищаем таблицу перед полной загрузкой
    ch_client.execute("TRUNCATE TABLE IF EXISTS emg_sensor_data")

    pg_cursor.execute("""
                      SELECT user_id, prosthesis_type, muscle_group,
                             signal_frequency, signal_duration, signal_amplitude, signal_time
                      FROM emg_sensor_data
                      """)

    total_inserted = 0
    batch = []
    sql = "INSERT INTO emg_sensor_data VALUES"

    for row in pg_cursor:
        batch.append(row)
        if len(batch) >= BATCH_SIZE:
            ch_client.execute(sql, batch)
            total_inserted += len(batch)
            print(f"✓ emg_sensor_data: вставлено {len(batch)} записей (всего: {total_inserted})")
            batch = []

    if batch:
        ch_client.execute(sql, batch)
        total_inserted += len(batch)

    print(f"✓ emg_sensor_data: всего загружено {total_inserted} записей")

    pg_cursor.close()
    pg_conn.close()
    ch_client.disconnect()


def load_user_profiles():
    """Извлекает user_profiles из PostgreSQL и загружает в ClickHouse."""
    pg_conn = get_postgres_connection()
    pg_cursor = pg_conn.cursor()
    ch_client = get_clickhouse_client()

    # Очищаем таблицу перед полной загрузкой
    ch_client.execute("TRUNCATE TABLE IF EXISTS user_profiles")

    pg_cursor.execute("""
                      SELECT user_id, subject_id, email, first_name, last_name, identity_provider
                      FROM user_profiles
                      """)

    rows = pg_cursor.fetchall()
    if rows:
        sql = "INSERT INTO user_profiles VALUES"
        ch_client.execute(sql, rows)

    print(f"✓ user_profiles: загружено {len(rows)} записей")

    pg_cursor.close()
    pg_conn.close()
    ch_client.disconnect()


def verify_data():
    """Проверяет данные в обеих таблицах и витрине."""
    client = get_clickhouse_client()

    # Проверка emg_sensor_data
    result = client.execute("""
                            SELECT
                                count() as total_records,
                                uniq(user_id) as unique_users,
                                min(signal_time) as earliest_signal,
                                max(signal_time) as latest_signal
                            FROM emg_sensor_data
                            """)
    if result:
        total, unique_users, earliest, latest = result[0]
        print(f"\n{'='*50}")
        print(f"EMG_SENSOR_DATA:")
        print(f"  Всего записей: {total}")
        print(f"  Уникальных пользователей: {unique_users}")
        print(f"  Период: {earliest} — {latest}")

    # Проверка user_profiles
    result = client.execute("SELECT count() FROM user_profiles")
    if result:
        print(f"\nUSER_PROFILES:")
        print(f"  Всего записей: {result[0][0]}")

    # Проверка витрины
    result = client.execute("SELECT count() FROM emg_user_report")
    if result:
        print(f"\nВИТРИНА EMG_USER_REPORT:")
        print(f"  Всего записей: {result[0][0]}")
    print(f"{'='*50}\n")

    client.disconnect()


with DAG(
        'crm_to_clickhouse_dag',
        default_args=default_args,
        schedule_interval='@hourly',
        catchup=False,
        description='Загрузка данных из CRM (PostgreSQL) в ClickHouse'
) as dag:

    load_emg_task = PythonOperator(
        task_id='load_emg_sensor_data',
        python_callable=load_emg_sensor_data
    )

    load_profiles_task = PythonOperator(
        task_id='load_user_profiles',
        python_callable=load_user_profiles
    )

    verify_task = PythonOperator(
        task_id='verify_data',
        python_callable=verify_data
    )

    # Загрузка двух таблиц параллельно, затем верификация
    [load_emg_task, load_profiles_task] >> verify_task