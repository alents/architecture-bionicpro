from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
import csv
from clickhouse_driver import Client
import os

# Аргументы по умолчанию
default_args = {
    'owner': 'airflow',
    'start_date': datetime(2026, 1, 1),
}

# Функция для получения клиента ClickHouse из переменных окружения
def get_clickhouse_client():
    return Client(
        host=os.getenv('CLICKHOUSE_HOST', 'clickhouse'),
        port=int(os.getenv('CLICKHOUSE_PORT', '9000')),
        user=os.getenv('CLICKHOUSE_USER', 'clickhouse_user'),
        password=os.getenv('CLICKHOUSE_PASSWORD', 'clickhouse_password'),
        database=os.getenv('CLICKHOUSE_DATABASE', 'bionicpro')
    )


# Функция для создания таблицы
def create_table():
    client = get_clickhouse_client()

    client.execute("""
                   CREATE TABLE IF NOT EXISTS emg_sensor_data (
                                                                  user_id UInt32,
                                                                  prosthesis_type String,
                                                                  muscle_group String,
                                                                  signal_frequency UInt32,
                                                                  signal_duration UInt32,
                                                                  signal_amplitude Decimal(5,2),
                       signal_time DateTime
                       ) ENGINE = MergeTree()
                       ORDER BY (user_id, prosthesis_type, signal_time);
                   """)

    print("✓ Таблица emg_sensor_data создана или уже существует")
    client.disconnect()

# Функция для загрузки данных в ClickHouse
def load_csv_to_clickhouse():
    CSV_FILE_PATH = '/opt/airflow/sample_files/olap.csv'

    BATCH_SIZE = 1000

    client = get_clickhouse_client()

    total_inserted = 0
    batch = []

    print(f"Начинаем загрузку с размером батча: {BATCH_SIZE} записей")

    # Читаем CSV и формируем данные для вставки
    data_to_insert = []
    with open(CSV_FILE_PATH, 'r') as csvfile:
        csvreader = csv.DictReader(csvfile)

        sql = "INSERT INTO emg_sensor_data VALUES"

        for row in csvreader:
            # Добавляем строку в батч
            print(row['user_id'], row['prosthesis_type'], row['muscle_group'], row['signal_frequency'], row['signal_duration'], row['signal_amplitude'], row['signal_time'])
            batch.append((
                int(row['user_id']),
                row['prosthesis_type'],
                row['muscle_group'],
                int(row['signal_frequency']),
                int(row['signal_duration']),
                float(row['signal_amplitude']),
                datetime.strptime(row['signal_time'], '%Y-%m-%d %H:%M:%S')
            ))

            # Когда батч заполнен - вставляем и очищаем
            if len(batch) >= BATCH_SIZE:
                client.execute(sql, batch)
                total_inserted += len(batch)
                print(f"✓ Вставлено {len(batch)} записей (всего: {total_inserted})")
                batch = []  # Очищаем батч для освобождения памяти

        # Вставляем оставшиеся записи (если есть)
        if batch:
            client.execute(sql, batch)
            total_inserted += len(batch)
            print(f"Вставлено {len(batch)} записей (всего: {total_inserted})")

    print(f"Всего успешно загружено {total_inserted} записей в ClickHouse")
    client.disconnect()

# Функция для проверки загруженных данных
def verify_data():
    client = get_clickhouse_client()

    result = client.execute("""
                            SELECT
                                count() as total_records,
                                uniq(user_id) as unique_users,
                                min(signal_time) as earliest_signal,
                                max(signal_time) as latest_signal
                            FROM emg_sensor_data;
                            """)

    if result:
        total, unique_users, earliest, latest = result[0]
        print(f"\n{'='*50}")
        print(f"СТАТИСТИКА ЗАГРУЖЕННЫХ ДАННЫХ:")
        print(f"{'='*50}")
        print(f"Всего записей: {total}")
        print(f"Уникальных пользователей: {unique_users}")
        print(f"Самый ранний сигнал: {earliest}")
        print(f"Самый поздний сигнал: {latest}")
        print(f"{'='*50}\n")

    client.disconnect()

# Определяем DAG
with DAG('csv_to_clickhouse_dag',
         default_args=default_args,
         schedule_interval=None,  # Запускаем каждый час
         catchup=False,
         description='Загрузка данных миодатчиков из CSV в ClickHouse') as dag:

    # Создаем таблицу в ClickHouse
    create_table_task = PythonOperator(
        task_id='create_table',
        python_callable=create_table
    )

    # Загружаем данные из CSV
    load_data_task = PythonOperator(
        task_id='load_csv_to_clickhouse',
        python_callable=load_csv_to_clickhouse
    )

    # Проверяем количество загруженных записей
    verify_data_task = PythonOperator(
        task_id='verify_data_count',
        python_callable=verify_data
    )

    # Определяем порядок выполнения
    create_table_task >> load_data_task >> verify_data_task