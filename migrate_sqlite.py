"""Copy an existing local quiz database to an EMPTY PostgreSQL database.

Set DATABASE_URL to the external TLS database URL in your local environment.
Stop the bot first. Run: python migrate_sqlite.py data/olimpiada.sqlite3
Never commit the database or its connection URL to Git.
"""
import argparse
import os
import sqlite3

import psycopg
from psycopg import sql

import db


def migrate(source_path):
    url = os.environ.get('DATABASE_URL', '')
    if not url:
        raise SystemExit('DATABASE_URL is required')
    source = sqlite3.connect(f'file:{source_path}?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    db.configure(source_path)
    db.init_db()
    tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    try:
        with psycopg.connect(url, connect_timeout=15) as target:
            for table in ('users', 'tests', 'attempts', 'bot_sessions'):
                if target.execute(sql.SQL('SELECT COUNT(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]:
                    raise RuntimeError('Target database is not empty; migration stopped safely')
            for table in ('users', 'tests', 'attempts', 'bot_sessions'):
                if table not in tables:
                    continue
                rows = source.execute(f'SELECT * FROM {table}').fetchall()
                for row in rows:
                    columns = list(row.keys())
                    statement = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
                        sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, columns)),
                        sql.SQL(',').join(sql.Placeholder() for _ in columns))
                    target.execute(statement, tuple(row))
            for table in ('tests', 'attempts'):
                target.execute(sql.SQL("SELECT setval(pg_get_serial_sequence(%s,'id'), "
                                       "COALESCE((SELECT MAX(id) FROM {}),0)+1,false)").format(
                                           sql.Identifier(table)), (table,))
        print('Migration complete. Source SQLite file was not changed.')
    finally:
        source.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    migrate(parser.parse_args().source)
