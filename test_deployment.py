"""Deployment regressions; run with pytest, optional TEST_DATABASE_URL for PostgreSQL."""
import asyncio
import os
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

import db
import main
import web as hosting


@pytest.fixture(params=['sqlite', 'postgres'])
def database(request, tmp_path, monkeypatch):
    if request.param == 'postgres':
        url = os.environ.get('TEST_DATABASE_URL')
        if not url:
            pytest.skip('TEST_DATABASE_URL is not set')
        monkeypatch.setenv('DATABASE_URL', url)
    else:
        monkeypatch.delenv('DATABASE_URL', raising=False)
    db.configure(str(tmp_path / 'quiz.sqlite3'))
    db.init_db()
    with db.connection() as c:
        for table in ['attempts', 'tests', 'users', 'bot_sessions', 'webhook_updates']:
            c.execute(f'DELETE FROM {table}')
    yield


def test_quiz_results_and_cascade(database):
    uid = 8_123_456_789
    db.upsert_user(uid, 'Sinov')
    db.set_grade(uid, 9)
    db.set_age(uid, 15)
    tid = db.add_test(9, 'Test', 2026, 15, 'telegram-file', 'AB')
    db.save_quiz_questions(tid, '[{"q":"Question?"}]')
    db.toggle_test(tid)
    assert len(db.tests_for_grade(9)) == 1
    aid = db.create_attempt(uid, tid, 2, '2026-10-14T00:00:00+00:00', '2026-10-14T00:15:00+00:00')
    assert db.set_current_poll(aid, 0, 'poll1', 12)
    assert db.quiz_poll_answer('poll1', uid + 1, 0) is None
    assert db.quiz_poll_answer('poll1', uid, 0) == (aid, 12)
    assert db.quiz_poll_answer('poll1', uid, 0) is None
    db.set_answer(aid, 1, 'B')
    assert db.finish_attempt(aid, '2026-10-14T00:01:00+00:00') == 2
    assert db.finish_attempt(aid, '2026-10-14T00:02:00+00:00') is None
    assert db.dashboard_stats() == (1, 1, 1)
    assert float(db.leaderboard(9)[0]['avg_pct']) == 100
    assert db.recent_results(uid)[0]['score'] == 2
    db.init_db()  # Redeploy/migration must preserve existing records.
    assert db.get_test(tid)['title'] == 'Test'
    db.delete_test(tid)
    assert db.attempt(aid) is None


def test_restart_and_duplicate_webhook(database):
    db.save_session(99, {'flow': 'admin_title', 'draft': {'grade': 9}})
    db.enqueue_update(100, {'update_id': 100})
    db.enqueue_update(100, {'update_id': 100})
    db.init_db()
    assert db.load_sessions()[99]['draft']['grade'] == 9
    assert db.next_update()['id'] == 100
    db.complete_update(100)
    db.enqueue_update(100, {'update_id': 100})
    assert db.next_update() is None


def test_webhook_authentication(database):
    async def run():
        app = hosting.create_app()
        app.cleanup_ctx.clear()
        app[hosting.STATE]['status'] = 'running'
        app[hosting.SECRET] = 'test-webhook-secret'
        app[hosting.BOT] = SimpleNamespace(bot=None)
        async with TestClient(TestServer(app)) as client:
            response = await client.post('/telegram', json={'update_id': 101})
            assert response.status == 403
            assert db.next_update() is None
            response = await client.post('/telegram', json={'update_id': 101}, headers={
                'X-Telegram-Bot-Api-Secret-Token': 'test-webhook-secret'})
            assert response.status == 200
            assert db.next_update()['id'] == 101
            response = await client.post('/telegram', json={'update_id': 'not-integer'}, headers={
                'X-Telegram-Bot-Api-Secret-Token': 'test-webhook-secret'})
            assert response.status == 400
    asyncio.run(run())


def test_setup_mode(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('RENDER', raising=False)
    monkeypatch.setattr(main, 'DB_FILE', str(tmp_path / 'setup.sqlite3'))
    monkeypatch.setattr(main, 'TOKEN', '')
    monkeypatch.setattr(main, 'ADMIN_IDS', set())
    async def run():
        async with TestClient(TestServer(hosting.create_app())) as client:
            response = await client.get('/health')
            result = await response.json()
            assert result['status'] == 'setup_required'
            assert 'BOT_TOKEN' in result['missing']
            assert (await client.post('/telegram', json={'update_id': 1})).status == 503
    asyncio.run(run())


def test_application_uses_persistence(monkeypatch):
    monkeypatch.setattr(main, 'TOKEN', '123456:TEST_TOKEN_NOT_REAL')
    app = main.build_application(webhook=True)
    assert app.updater is None
    assert app.persistence is not None
