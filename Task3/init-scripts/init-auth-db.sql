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

INSERT INTO user_profiles (subject_id, email, first_name, last_name, identity_provider, created_at, updated_at)
VALUES
    ('b0b0e90c-a6c0-4813-9a0f-e9ab46aae95c', 'prothetic1@example.com', 'Prothetic', 'One', 'keycloak', '2026-02-14 10:39:45.097133+00', '2026-02-14 10:39:45.097133+00'),
    ('5f635e86-3013-4502-b683-535487ffdf30', 'prothetic2@example.com', 'Prothetic', 'Two', 'keycloak', '2026-02-14 10:40:58.766963+00', '2026-02-14 10:40:58.766963+00'),
    ('863fc098-0e5d-49bf-91b7-e7a7d999d937', 'prothetic3@example.com', 'Prothetic', 'Three', 'keycloak', '2026-02-14 10:43:53.443978+00', '2026-02-14 10:43:53.443978+00')
    ON CONFLICT (subject_id) DO NOTHING;