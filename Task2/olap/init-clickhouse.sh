#!/bin/bash

echo "Инициализация базы данных ClickHouse..."

# Создаем базу данных
docker compose exec -it clickhouse clickhouse-client \
  --user clickhouse_user \
  --password clickhouse_password \
  --query "CREATE DATABASE IF NOT EXISTS bionicpro"

echo "База данных bionicpro создана"

# Создаем таблицу
docker compose exec -it clickhouse clickhouse-client \
  --user clickhouse_user \
  --password clickhouse_password \
  --database bionicpro \
  --query "CREATE TABLE IF NOT EXISTS emg_sensor_data (
    user_id UInt32,
    prosthesis_type String,
    muscle_group String,
    signal_frequency UInt32,
    signal_duration UInt32,
    signal_amplitude Decimal(5,2),
    signal_time DateTime
) ENGINE = MergeTree()
ORDER BY (user_id, prosthesis_type, signal_time);"

echo "Таблица emg_sensor_data создана"

# Проверяем результат
echo ""
echo "Проверка созданных объектов:"
docker exec -it clickhouse clickhouse-client \
  --user clickhouse_user \
  --password clickhouse_password \
  --query "SHOW DATABASES"

echo ""
docker compose exec -it clickhouse clickhouse-client \
  --user clickhouse_user \
  --password clickhouse_password \
  --database bionicpro \
  --query "SHOW TABLES"

echo ""
echo "Инициализация завершена!"


