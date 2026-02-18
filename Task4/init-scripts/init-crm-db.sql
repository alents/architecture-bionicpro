CREATE TABLE IF NOT EXISTS user_profiles (
                                             user_id SERIAL PRIMARY KEY,
                                             subject_id VARCHAR NOT NULL UNIQUE,
                                             email VARCHAR,
                                             first_name VARCHAR,
                                             last_name VARCHAR,
                                             birthday VARCHAR,
                                             identity_provider VARCHAR,
                                             created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

CREATE INDEX IF NOT EXISTS idx_user_profiles_subject_id ON user_profiles(subject_id);

-- =============================================================
-- Настройка CDC (Change Data Capture) для Debezium
-- =============================================================

-- Даём пользователю crm_db_user право на логическую репликацию.
-- Это позволяет Debezium подключаться по протоколу репликации
-- и читать WAL (Write-Ahead Log).
ALTER ROLE crm_db_user REPLICATION;

-- Публикация определяет, какие таблицы доступны для логической репликации.
-- Debezium подпишется на эту публикацию и будет получать события
-- INSERT/UPDATE/DELETE по таблице user_profiles.
CREATE PUBLICATION debezium_pub FOR TABLE user_profiles;






