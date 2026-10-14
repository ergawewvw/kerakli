CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY, name TEXT NOT NULL, age INTEGER,
    grade INTEGER CHECK (grade IN (9,10,11)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
);
CREATE TABLE IF NOT EXISTS tests (
    id BIGSERIAL PRIMARY KEY,
    grade INTEGER NOT NULL CHECK (grade IN (9,10,11)),
    subject TEXT NOT NULL DEFAULT 'Informatika', title TEXT NOT NULL,
    year INTEGER NOT NULL, duration INTEGER NOT NULL, file_id TEXT NOT NULL,
    answer_key TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
    media_kind TEXT NOT NULL DEFAULT 'document',
    source_text TEXT NOT NULL DEFAULT '', file_name TEXT NOT NULL DEFAULT '',
    quiz_questions TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS attempts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    test_id BIGINT NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    answers TEXT NOT NULL, current_idx INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL, deadline TEXT NOT NULL,
    finished_at TEXT, score INTEGER,
    current_poll_id TEXT NOT NULL DEFAULT '', current_poll_message_id BIGINT,
    UNIQUE(id,user_id)
);
CREATE INDEX IF NOT EXISTS idx_attempt_user ON attempts(user_id,finished_at);
CREATE INDEX IF NOT EXISTS idx_tests_grade ON tests(grade,published);
CREATE INDEX IF NOT EXISTS idx_attempt_poll ON attempts(current_poll_id);
