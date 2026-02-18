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


-- Таблица профилей пользователей
CREATE TABLE IF NOT EXISTS bionicpro.user_profiles (
                                                       user_id UInt32,
                                                       subject_id String,
                                                       email String,
                                                       first_name String,
                                                       last_name String,
                                                       identity_provider String
) ENGINE = MergeTree()
    ORDER BY (user_id);


-- Витрина: данные сенсоров с информацией о пользователе
CREATE OR REPLACE VIEW bionicpro.emg_user_report AS
SELECT
    e.user_id,
    u.email,
    u.first_name,
    u.last_name,
    e.prosthesis_type,
    e.muscle_group,
    e.signal_frequency,
    e.signal_duration,
    e.signal_amplitude,
    e.signal_time
FROM bionicpro.emg_sensor_data AS e
         INNER JOIN bionicpro.user_profiles AS u
                    ON e.user_id = u.user_id;