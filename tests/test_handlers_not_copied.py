"""
Router.handlers / Router.commands deep-copied every handler on every update.
A bound-method handler then ran on a fresh copy of its object each time
(state silently lost), and an object holding anything unpicklable — a
Future, a lock, a session — made handle_update raise TypeError.
"""

import asyncio

import aiomax


def _update(text: str) -> dict:
    return {
        "update_type": "message_created",
        "timestamp": 1,
        "message": {
            "sender": {"user_id": 1, "first_name": "A", "is_bot": False},
            "recipient": {"chat_id": 5, "chat_type": "dialog"},
            "timestamp": 1,
            "body": {"mid": "m", "seq": 1, "text": text, "attachments": []},
        },
    }


async def _dispatch(bot, text):
    await bot.handle_update(_update(text))
    await asyncio.gather(*bot._handler_tasks)


class Counter:
    def __init__(self):
        self.seen = 0
        self.lock = asyncio.Lock()
        self.future = None

    async def on_message(self, message):
        self.seen += 1

    async def on_ping(self, ctx):
        self.seen += 1


def test_bound_method_handlers_keep_their_object():
    async def run():
        counter = Counter()
        counter.future = asyncio.get_running_loop().create_future()
        bot = aiomax.Bot("token")
        child = aiomax.Router()
        bot.add_router(child)
        child.on_message()(counter.on_message)
        child.on_command("ping")(counter.on_ping)

        for text in ("a", "b", "/ping"):
            await _dispatch(bot, text)
        return counter.seen

    # Two plain messages plus the command; /ping is not a plain message.
    assert asyncio.run(run()) == 3


def test_reading_handlers_does_not_mutate_the_router():
    bot = aiomax.Bot("token")
    child = aiomax.Router()
    bot.add_router(child)

    @child.on_message()
    async def on_message(message):
        pass

    before = len(bot._handlers["message_created"])
    for _ in range(3):
        bot.handlers
        bot.commands
    assert len(bot._handlers["message_created"]) == before
    assert len(bot.handlers["message_created"]) == before + 1
