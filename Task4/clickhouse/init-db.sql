CREATE DATABASE IF NOT EXISTS bionicpro;

CREATE TABLE IF NOT EXISTS bionicpro.emg_sensor_data (
                                                         user_id UInt32,
                                                         prosthesis_type String,
                                                         muscle_group String,
                                                         signal_frequency UInt32,
                                                         signal_duration UInt32,
                                                         signal_amplitude Decimal(5,2),
    signal_time DateTime
    ) ENGINE = MergeTree()
    ORDER BY (user_id, prosthesis_type, signal_time);

INSERT INTO bionicpro.emg_sensor_data
SELECT *
FROM file('olap.csv', 'CSV');

--  Kafka-таблица: читает CDC-события из топика Kafka.
--      Это «виртуальный поток» — данные здесь не хранятся.
--      ClickHouse подключается как Kafka consumer и вычитывает
--      сообщения, которые Debezium отправил после трансформации
--      ExtractNewRecordState (плоский JSON без вложенности).
CREATE TABLE IF NOT EXISTS bionicpro.user_profiles_kafka (
                                                             user_id           UInt32,
                                                             subject_id        String,
                                                             email             Nullable(String),
    first_name        Nullable(String),
    last_name         Nullable(String),
    birthday          Nullable(String),
    identity_provider Nullable(String),
    created_at        Nullable(String),
    updated_at        Nullable(String),
    __op              String,
    __deleted         String
    ) ENGINE = Kafka
    SETTINGS
    kafka_broker_list = 'kafka:29092',
    kafka_topic_list = 'bionicpro_cdc.public.user_profiles',
    kafka_group_name = 'clickhouse_consumer',
    kafka_format = 'JSONEachRow',
    kafka_skip_broken_messages = 1;

--  Целевая таблица: хранит актуальное состояние профилей.
--      ReplacingMergeTree при фоновых merge оставляет только строку
--      с максимальным значением version для каждого user_id.
--      Поле is_deleted позволяет обрабатывать DELETE-операции:
--      вместо физического удаления мы помечаем строку флагом.
CREATE TABLE IF NOT EXISTS bionicpro.user_profiles (
                                                       user_id           UInt32,
                                                       subject_id        String,
                                                       email             Nullable(String),
    first_name        Nullable(String),
    last_name         Nullable(String),
    birthday          Nullable(String),
    identity_provider Nullable(String),
    created_at        Nullable(String),
    updated_at        Nullable(String),
    is_deleted        UInt8 DEFAULT 0,
    version           UInt64
    ) ENGINE = ReplacingMergeTree(version)
    ORDER BY user_id;

--  Materialized View: связывает Kafka-таблицу с целевой.
--      Выполняет две функции:
--      a) Триггер: без MV ClickHouse не начнёт читать из Kafka
--      b) Трансформация: преобразует __deleted в числовой флаг
--         и добавляет версию (now64) для ReplacingMergeTree.
CREATE MATERIALIZED VIEW IF NOT EXISTS bionicpro.user_profiles_mv
TO bionicpro.user_profiles AS
SELECT
    user_id,
    subject_id,
    email,
    first_name,
    last_name,
    birthday,
    identity_provider,
    created_at,
    updated_at,
    if(__deleted = 'true', 1, 0)        AS is_deleted,
    toUnixTimestamp64Milli(now64())      AS version
FROM bionicpro.user_profiles_kafka;

-- =============================================================
-- 3. Витрина для отчётности
-- =============================================================
-- Обычный VIEW (не Materialized) — выполняет JOIN при каждом запросе.
-- Это гарантирует актуальность данных: профили могут меняться через CDC.
-- FINAL в JOIN заставляет ReplacingMergeTree отдать только последнюю
-- версию каждого профиля (дедупликация «на лету»).
-- Фильтр is_deleted = 0 исключает удалённых пользователей.

CREATE VIEW IF NOT EXISTS bionicpro.user_sensor_report AS
SELECT
    e.user_id        AS user_id,
    u.email          AS email,
    u.first_name     AS first_name,
    u.last_name      AS last_name,
    e.prosthesis_type  AS prosthesis_type,
    e.muscle_group     AS muscle_group,
    e.signal_frequency AS signal_frequency,
    e.signal_duration  AS signal_duration,
    e.signal_amplitude AS signal_amplitude,
    e.signal_time      AS signal_time
FROM bionicpro.emg_sensor_data AS e
         LEFT JOIN (
    SELECT * FROM bionicpro.user_profiles FINAL WHERE is_deleted = 0
) AS u ON e.user_id = u.user_id;