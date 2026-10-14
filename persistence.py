"""Store registration and admin drafts alongside the quiz database."""
from telegram.ext import BasePersistence, PersistenceInput
import db


class SessionPersistence(BasePersistence):
    def __init__(self):
        super().__init__(store_data=PersistenceInput(
            user_data=True, chat_data=False, bot_data=False, callback_data=False),
            update_interval=5)

    async def get_user_data(self):
        return db.load_sessions()

    async def update_user_data(self, user_id, data):
        db.save_session(user_id, data)

    async def drop_user_data(self, user_id):
        db.delete_session(user_id)

    async def get_chat_data(self):
        return {}

    async def get_bot_data(self):
        return {}

    async def get_callback_data(self):
        return None

    async def get_conversations(self, name):
        return {}

    async def update_chat_data(self, chat_id, data):
        pass

    async def update_bot_data(self, data):
        pass

    async def update_callback_data(self, data):
        pass

    async def update_conversation(self, name, key, new_state):
        pass

    async def drop_chat_data(self, chat_id):
        pass

    async def refresh_user_data(self, user_id, user_data):
        pass

    async def refresh_chat_data(self, chat_id, chat_data):
        pass

    async def refresh_bot_data(self, bot_data):
        pass

    async def flush(self):
        pass
