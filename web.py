"""Render web entrypoint. Tokens are configured only in Environment variables."""
import asyncio
import hmac
import json
import logging
import os
from urllib.parse import urlsplit

from aiohttp import web
from telegram import Update

import db
import main

log = logging.getLogger(__name__)
STATE = web.AppKey('state', dict)
BOT = web.AppKey('bot', object)
SECRET = web.AppKey('secret', str)
WAKE = web.AppKey('wake', asyncio.Event)


async def health(request):
    return web.json_response(request.app[STATE])


async def index(request):
    state = request.app[STATE]['status']
    message = ('Bot serveri ishlayapti.' if state == 'running' else
               'Server tayyor. Botni ulash uchun Render Environment sozlamalarini to‘ldiring.')
    return web.Response(text=message, content_type='text/plain')


async def webhook(request):
    if request.app[STATE]['status'] != 'running':
        raise web.HTTPServiceUnavailable(text='Bot setup incomplete')
    supplied = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
    if not hmac.compare_digest(supplied, request.app[SECRET]):
        raise web.HTTPForbidden(text='Invalid webhook secret')
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or type(payload.get('update_id')) is not int:
            raise ValueError('Invalid update')
        Update.de_json(payload, request.app[BOT].bot)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise web.HTTPBadRequest(text='Invalid Telegram update') from None
    # Acknowledge only AFTER committing to durable storage. A restart can replay it.
    db.enqueue_update(payload['update_id'], payload)
    request.app[WAKE].set()
    return web.Response(text='OK')


async def consume_updates(app):
    while True:
        app[WAKE].clear()
        row = db.next_update()
        if row is None:
            await app[WAKE].wait()
            continue
        try:
            update = Update.de_json(json.loads(row['payload']), app[BOT].bot)
            await app[BOT].process_update(update)
            await app[BOT].update_persistence()
            db.complete_update(row['id'])
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('Update processing failed; retained for retry')
            await asyncio.sleep(3)


async def lifecycle(app):
    db.configure(main.DB_FILE)
    base_url = os.environ.get('WEBHOOK_BASE_URL', os.environ.get('RENDER_EXTERNAL_URL', '')).rstrip('/')
    secret = os.environ.get('WEBHOOK_SECRET', '')
    missing = []
    database_ready = False
    if os.environ.get('RENDER') and not db.DATABASE_URL:
        missing.append('DATABASE_URL')
    else:
        db.init_db()
        database_ready = True
    if not main.TOKEN or main.TOKEN == 'YOUR_TELEGRAM_BOT_TOKEN':
        missing.append('BOT_TOKEN')
    if not main.ADMIN_IDS:
        missing.append('ADMIN_IDS')
    if not secret:
        missing.append('WEBHOOK_SECRET')
    if not base_url:
        missing.append('WEBHOOK_BASE_URL or RENDER_EXTERNAL_URL')
    if missing:
        app[STATE].update(status='setup_required',
                          database='ready' if database_ready else 'not_configured', missing=missing)
        log.warning('Hosting ready; missing settings: %s', ', '.join(missing))
        yield
        return
    if urlsplit(base_url).scheme != 'https':
        raise RuntimeError('Webhook base URL must use HTTPS')
    app[SECRET] = secret
    bot_app = main.build_application(webhook=True)
    app[BOT] = bot_app
    async with bot_app:
        await main.post_init(bot_app)
        await bot_app.start()
        worker = asyncio.create_task(consume_updates(app))
        try:
            await bot_app.bot.set_webhook(
                url=f'{base_url}/telegram', secret_token=secret,
                allowed_updates=['message', 'callback_query', 'poll_answer'],
                max_connections=1, drop_pending_updates=False)
            app[STATE].update(status='running', database='ready', missing=[])
            log.info('Telegram webhook connected')
            yield
        finally:
            app[STATE]['status'] = 'stopping'
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
            await bot_app.stop()
            # Keep Telegram's webhook registered so the next message wakes Render.


def create_app():
    app = web.Application(client_max_size=1024 * 1024)
    app[STATE] = {'status': 'starting'}
    app[WAKE] = asyncio.Event()
    app.cleanup_ctx.append(lifecycle)
    app.add_routes([web.get('/', index), web.get('/health', health),
                    web.post('/telegram', webhook)])
    return app


if __name__ == '__main__':
    web.run_app(create_app(), host='0.0.0.0', port=int(os.environ.get('PORT', '10000')),
                access_log=None, print=None)
