"""SQLite saqlash qatlami. Barcha SQL qiymatlari parametrlangan."""
from __future__ import annotations

import sqlite3
import os
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DB_PATH = Path('data/olimpiada.sqlite3')
DATABASE_URL = ''


def configure(path: str) -> None:
    global DB_PATH, DATABASE_URL
    DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
    DB_PATH = Path(path)
    if not DATABASE_URL:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    if DATABASE_URL:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10) as conn:
            yield PostgresConnection(conn)
        return
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=15000')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _init_sqlite() -> None:
    with connection() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                age INTEGER,
                grade INTEGER CHECK (grade IN (9, 10, 11)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                grade INTEGER NOT NULL CHECK (grade IN (9,10,11)),
                subject TEXT NOT NULL DEFAULT 'Informatika',
                title TEXT NOT NULL,
                year INTEGER NOT NULL,
                duration INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                answer_key TEXT NOT NULL,
                published INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
                answers TEXT NOT NULL,
                current_idx INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                deadline TEXT NOT NULL,
                finished_at TEXT,
                score INTEGER,
                UNIQUE(id, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_attempt_user ON attempts(user_id, finished_at);
            CREATE INDEX IF NOT EXISTS idx_tests_grade ON tests(grade, published);
        ''')
        # Eski bazalarda yangi ustunlar bo'lmasa, ma'lumotni o'chirmasdan qo'shamiz.
        old_columns = {row['name'] for row in c.execute('PRAGMA table_info(tests)')}
        if 'media_kind' not in old_columns:
            c.execute("ALTER TABLE tests ADD COLUMN media_kind TEXT NOT NULL DEFAULT 'document'")
        if 'source_text' not in old_columns:
            c.execute("ALTER TABLE tests ADD COLUMN source_text TEXT NOT NULL DEFAULT ''")
        if 'file_name' not in old_columns:
            c.execute("ALTER TABLE tests ADD COLUMN file_name TEXT NOT NULL DEFAULT ''")
        if 'quiz_questions' not in old_columns:
            c.execute("ALTER TABLE tests ADD COLUMN quiz_questions TEXT NOT NULL DEFAULT ''")
        attempt_columns = {row['name'] for row in c.execute('PRAGMA table_info(attempts)')}
        if 'current_poll_id' not in attempt_columns:
            c.execute("ALTER TABLE attempts ADD COLUMN current_poll_id TEXT NOT NULL DEFAULT ''")
        if 'current_poll_message_id' not in attempt_columns:
            c.execute("ALTER TABLE attempts ADD COLUMN current_poll_message_id INTEGER")
        c.execute('CREATE INDEX IF NOT EXISTS idx_attempt_poll ON attempts(current_poll_id)')


def get_user(user_id: int):
    with connection() as c:
        return c.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()


def upsert_user(user_id: int, name: str):
    with connection() as c:
        c.execute('''INSERT INTO users(id,name) VALUES(?,?)
                     ON CONFLICT(id) DO UPDATE SET name=excluded.name''', (user_id, name[:80]))


def set_age(user_id: int, age: int):
    with connection() as c:
        c.execute('UPDATE users SET age=? WHERE id=?', (age, user_id))


def set_grade(user_id: int, grade: int):
    with connection() as c:
        c.execute('UPDATE users SET grade=? WHERE id=?', (grade, user_id))


def add_test(grade: int, title: str, year: int, duration: int, file_id: str, key: str,
             media_kind: str = 'document', source_text: str = '', file_name: str = '') -> int:
    with connection() as c:
        return insert_id(c, '''INSERT INTO tests(grade,title,year,duration,file_id,answer_key,media_kind,source_text,file_name)
                           VALUES(?,?,?,?,?,?,?,?,?)''',
                        (grade, title, year, duration, file_id, key, media_kind, source_text, file_name))


def get_test(test_id: int):
    with connection() as c:
        return c.execute('SELECT * FROM tests WHERE id=?', (test_id,)).fetchone()


def tests_for_grade(grade: int):
    with connection() as c:
        return c.execute('''SELECT * FROM tests WHERE grade=? AND published=1
                            ORDER BY year DESC, id DESC''', (grade,)).fetchall()


def admin_tests():
    with connection() as c:
        return c.execute('SELECT * FROM tests ORDER BY id DESC').fetchall()


def toggle_test(test_id: int):
    with connection() as c:
        c.execute('UPDATE tests SET published=1-published WHERE id=?', (test_id,))


def delete_test(test_id: int):
    with connection() as c:
        c.execute('DELETE FROM tests WHERE id=?', (test_id,))


def active_attempt(user_id: int):
    with connection() as c:
        return c.execute('''SELECT a.*, t.title, t.grade, t.year, t.duration, t.answer_key, t.file_id, t.media_kind, t.source_text, t.file_name, t.quiz_questions
                            FROM attempts a JOIN tests t ON t.id=a.test_id
                            WHERE a.user_id=? AND a.finished_at IS NULL
                            ORDER BY a.id DESC LIMIT 1''', (user_id,)).fetchone()


def attempt(attempt_id: int):
    with connection() as c:
        return c.execute('''SELECT a.*, t.title, t.grade, t.year, t.duration, t.answer_key, t.file_id, t.media_kind, t.source_text, t.file_name, t.quiz_questions
                            FROM attempts a JOIN tests t ON t.id=a.test_id
                            WHERE a.id=?''', (attempt_id,)).fetchone()


def create_attempt(user_id: int, test_id: int, length: int, started: str, deadline: str) -> int:
    with connection() as c:
        return insert_id(c, '''INSERT INTO attempts(user_id,test_id,answers,started_at,deadline)
                           VALUES(?,?,?,?,?)''', (user_id, test_id, '-' * length, started, deadline))


def set_index(attempt_id: int, index: int) -> None:
    with connection() as c:
        c.execute('UPDATE attempts SET current_idx=? WHERE id=? AND finished_at IS NULL', (index, attempt_id))


def set_answer(attempt_id: int, index: int, letter: str) -> None:
    with connection() as c:
        row = c.execute('SELECT answers FROM attempts WHERE id=? AND finished_at IS NULL', (attempt_id,)).fetchone()
        if row is not None and 0 <= index < len(row['answers']):
            data = row['answers'][:index] + letter + row['answers'][index+1:]
            c.execute('UPDATE attempts SET answers=? WHERE id=? AND finished_at IS NULL', (data, attempt_id))


def finish_attempt(attempt_id: int, finished_at: str):
    """Faqat bir marta yakunlaydi; job va callback parallel kelishi mumkin."""
    with connection() as c:
        row = c.execute('''SELECT a.*,t.answer_key FROM attempts a JOIN tests t ON a.test_id=t.id
                           WHERE a.id=?''', (attempt_id,)).fetchone()
        if row is None or row['finished_at']:
            return None
        score = sum(a == b for a, b in zip(row['answers'], row['answer_key']))
        cur = c.execute('''UPDATE attempts SET finished_at=?, score=?
                           WHERE id=? AND finished_at IS NULL''', (finished_at, score, attempt_id))
        return score if cur.rowcount else None


def recent_results(user_id: int, limit: int = 10):
    with connection() as c:
        return c.execute('''SELECT a.score,a.answers,a.finished_at,t.title,t.answer_key,t.grade,t.year
                            FROM attempts a JOIN tests t ON t.id=a.test_id
                            WHERE a.user_id=? AND a.finished_at IS NOT NULL
                            ORDER BY a.finished_at DESC,a.id DESC LIMIT ?''', (user_id, limit)).fetchall()


def leaderboard(grade: int, limit: int = 10):
    """Har bir testdan eng yaxshi natija, so'ng shu testlar bo'yicha o'rtacha %."""
    with connection() as c:
        return c.execute('''WITH best AS (
                              SELECT a.user_id,a.test_id,
                                     MAX(100.0*a.score/LENGTH(t.answer_key)) AS pct
                              FROM attempts a JOIN tests t ON a.test_id=t.id
                              WHERE a.finished_at IS NOT NULL AND t.grade=? AND t.published=1
                              GROUP BY a.user_id,a.test_id
                            )
                            SELECT u.name,ROUND(AVG(best.pct),1) AS avg_pct, COUNT(*) AS total
                            FROM best JOIN users u ON best.user_id=u.id
                            GROUP BY best.user_id,u.name ORDER BY avg_pct DESC,total DESC LIMIT ?''', (grade, limit)).fetchall()


def dashboard_stats():
    with connection() as c:
        return (
            c.execute('SELECT COUNT(*) AS total FROM users').fetchone()['total'],
            c.execute('SELECT COUNT(*) AS total FROM tests').fetchone()['total'],
            c.execute('SELECT COUNT(*) AS total FROM attempts WHERE finished_at IS NOT NULL').fetchone()['total'],
        )


def unfinished_attempts():
    with connection() as c:
        return c.execute('SELECT id,user_id,deadline FROM attempts WHERE finished_at IS NULL').fetchall()


def save_quiz_questions(test_id: int, questions_json: str) -> None:
    with connection() as c:
        c.execute('UPDATE tests SET quiz_questions=? WHERE id=?', (questions_json, test_id))


def set_current_poll(attempt_id: int, question_index: int, poll_id: str, message_id: int) -> bool:
    with connection() as c:
        result = c.execute("""UPDATE attempts SET current_idx=?, current_poll_id=?, current_poll_message_id=?
                              WHERE id=? AND finished_at IS NULL AND current_poll_id='' """,
                           (question_index, poll_id, message_id, attempt_id))
        return result.rowcount == 1


def quiz_poll_answer(poll_id: str, user_id: int, option_id: int):
    """Only one valid answer per active poll. Returns (attempt_id, poll_message_id)."""
    with connection() as c:
        row = c.execute("""SELECT a.* FROM attempts a
                           WHERE a.current_poll_id=? AND a.user_id=? AND a.finished_at IS NULL""",
                        (poll_id, user_id)).fetchone()
        if not row or not 0 <= option_id <= 3:
            return None
        idx = row['current_idx']
        if idx < 0 or idx >= len(row['answers']) or row['answers'][idx] != '-':
            return None
        new_answers = row['answers'][:idx] + 'ABCD'[option_id] + row['answers'][idx+1:]
        c.execute("""UPDATE attempts
                     SET answers=?, current_poll_id='', current_poll_message_id=NULL,
                         current_idx=?
                     WHERE id=? AND current_poll_id=? AND finished_at IS NULL""",
                  (new_answers, idx+1, row['id'], poll_id))
        return row['id'], row['current_poll_message_id']


def reset_current_poll(attempt_id: int) -> None:
    """Used only when Telegram sent a poll but its local DB registration failed."""
    with connection() as c:
        c.execute("""UPDATE attempts SET current_poll_id='', current_poll_message_id=NULL
                     WHERE id=? AND finished_at IS NULL""", (attempt_id,))


class PostgresConnection:
    """Keep application SQL parameterized on both supported database engines."""
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=()):
        return self.raw.execute(sql.replace('?', '%s'), params)


def insert_id(conn, sql, params):
    if DATABASE_URL:
        return conn.execute(sql + ' RETURNING id', params).fetchone()['id']
    return conn.execute(sql, params).lastrowid


def init_db():
    if DATABASE_URL:
        with connection() as c:
            c.raw.execute(Path(__file__).with_name('postgres_schema.sql').read_text())
    else:
        _init_sqlite()
    with connection() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS bot_sessions (
            user_id BIGINT PRIMARY KEY, data TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS webhook_updates (
            id BIGINT PRIMARY KEY, payload TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_webhook_pending ON webhook_updates(completed,id)')
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        c.execute('DELETE FROM webhook_updates WHERE completed=1 AND created_at<?', (cutoff,))


def load_sessions():
    with connection() as c:
        return {row['user_id']: json.loads(row['data'])
                for row in c.execute('SELECT user_id,data FROM bot_sessions').fetchall()}


def save_session(user_id, data):
    with connection() as c:
        c.execute('''INSERT INTO bot_sessions(user_id,data) VALUES(?,?)
            ON CONFLICT(user_id) DO UPDATE SET data=excluded.data''',
            (user_id, json.dumps(data, ensure_ascii=False)))


def delete_session(user_id):
    with connection() as c:
        c.execute('DELETE FROM bot_sessions WHERE user_id=?', (user_id,))


def enqueue_update(update_id, payload):
    from datetime import datetime, timezone
    with connection() as c:
        c.execute('''INSERT INTO webhook_updates(id,payload,created_at) VALUES(?,?,?)
                     ON CONFLICT(id) DO NOTHING''',
                  (update_id, json.dumps(payload, ensure_ascii=False),
                   datetime.now(timezone.utc).isoformat()))


def next_update():
    with connection() as c:
        return c.execute('SELECT id,payload FROM webhook_updates WHERE completed=0 ORDER BY id LIMIT 1').fetchone()


def complete_update(update_id):
    with connection() as c:
        c.execute("UPDATE webhook_updates SET completed=1,payload='' WHERE id=?", (update_id,))
