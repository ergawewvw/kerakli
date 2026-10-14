# Olimpiada bot — Render

This branch contains the olympiad bot. The repository's `main` branch contains
an unrelated channel bot and is not part of this deployment.

## Service settings

- Runtime: Python 3.12
- Plan: Free
- Branch: `olimpiada-render`
- Build: `pip install -r requirements.txt`
- Start: `python web.py`
- HTTP port: Render's `PORT`; the app binds `0.0.0.0`
- Health endpoint: `/health`
- Telegram endpoint: `/telegram`, with a secret header
- Keep one service instance and stop the old local polling process before activation.

## Private environment settings

| Variable | Value |
|---|---|
| `BOT_TOKEN` | Token from BotFather; never commit it |
| `ADMIN_IDS` | Your numeric Telegram user ID, or comma-separated IDs |
| `DATABASE_URL` | Internal PostgreSQL URL for the same Render region/workspace |
| `GROQ_API_KEY` | Needed only for AI import; manual tests work without it |
| `WEBHOOK_SECRET` | A generated random secret; supplied when creating the service |

`RENDER_EXTERNAL_URL` is supplied automatically. No manual Telegram webhook call
is needed. Saving the environment and redeploying registers the webhook.
With missing settings the HTTP server reports `setup_required`; this does **not**
mean the Telegram bot is running. `/health` reports `running` after registration.
The setup page never displays secret values.

## Storage and restart behavior

On Render, missing `DATABASE_URL` blocks bot activation: SQLite is never silently
used on its temporary filesystem. Users, tests, results, admin drafts, and accepted
webhook payloads are stored in PostgreSQL. Telegram file IDs remain in the database;
uploaded source files are retrieved from Telegram when needed.

The webhook acknowledges only after storing its payload. Pending updates resume
after restart; repeated completed update IDs are ignored. Processing is at least
once: a crash after sending a Telegram message and before recording completion may
produce a repeated message. Completed webhook payloads are erased; their IDs are
kept for seven days and pruned on startup.

Free Render services sleep after 15 idle minutes. The next Telegram request wakes
the service, so replies can be delayed. Test deadlines remain in the database;
automatic timeout notices can be delayed while the service sleeps.

**Render's free PostgreSQL database expires after 30 days.** The database created
for this deployment expires on **2026-11-13**. Before expiry, export/migrate it to
another PostgreSQL provider and update `DATABASE_URL`. Do not rely on the free tier
as a permanent archive. No paid plan was selected.

Official limits: https://render.com/docs/free

## Existing local data

The initial deployment has a new database. It does not contain your computer's
`data/olimpiada.sqlite3`. Stop both bot instances and back up that file first.
Set `DATABASE_URL` locally to your PostgreSQL external TLS URL and run:

```sh
python migrate_sqlite.py data/olimpiada.sqlite3
```

The script refuses a nonempty destination and leaves the source file unchanged.
Keep the same Telegram bot token if migrating existing Telegram file IDs.

## Verification

`test_deployment.py` covers quiz scoring, large Telegram IDs, restarts, admin
session retention, webhook duplicates, secret checks, and setup-mode behavior.
Run `pytest -q`. PostgreSQL cases additionally require `TEST_DATABASE_URL` pointing
to a **disposable test database**: these tests clear their tables.
