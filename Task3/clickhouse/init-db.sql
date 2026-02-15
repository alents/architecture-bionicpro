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