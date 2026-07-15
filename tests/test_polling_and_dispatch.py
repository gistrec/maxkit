"""Regression tests for polling loop, command dispatch and error handling.

Covers medium-severity findings:

* M1  - a bad update must not drop the rest of an already-committed batch.
* M3  - send/edit must raise a real exception on 2xx + {"success": false}
        instead of `raise None` (TypeError).
* M4  - a whitespace-only command ("/ ") must not raise IndexError.
* M5  - shutdown must not block forever on a hung handler.
* M9  - a command name defined in two routers keeps both handlers.
* M10 - updates from the same user are serialised (no FSM race).
"""

import asyncio

import aiomax
from aiomax import exceptions
from aiomax.router import Router


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _sender(uid=1):
    return {
        "user_id": uid,
        "first_name": "Test",
        "name": "Test",
        "is_bot": False,
        "last_activity_time": 1000,
    }


def _message_update(text, uid=1):
    return {
        "update_type": "message_created",
        "message": {
            "sender": _sender(uid),
            "recipient": {"chat_id": 10, "chat_type": "chat"},
            "timestamp": 1000,
            "body": {"mid": "mid-1", "seq": 1, "text": text},
        },
    }


# --- M1 -------------------------------------------------------------------

def test_bad_update_does_not_drop_rest_of_batch():
    processed = []

    class B(aiomax.Bot):
        async def get_me(self):
            return None

        async def get_updates(self, limit=100):
            self.polling = False
            return {
                "updates": [
                    {"update_type": "bad"},
                    {"update_type": "good"},
                ]
            }

        async def handle_update(self, update):
            if update["update_type"] == "bad":
                raise ValueError("boom")
            processed.append(update["update_type"])

    bot = B("token")
    asyncio.run(bot.start_polling(session=FakeSession()))

    # The good update is processed even though the earlier one raised.
    assert processed == ["good"]


# --- M3 -------------------------------------------------------------------

def test_send_message_raises_real_exception_on_success_false():
    class FakeResp:
        status = 200
        content_type = "application/json"

        async def json(self):
            return {
                "success": False,
                "code": "some.error",
                "message": "desc",
            }

    bot = aiomax.Bot("token")

    async def fake_post(url, **kwargs):
        return FakeResp()

    bot.post = fake_post

    async def run():
        await bot.send_message("hi", chat_id=1)

    try:
        asyncio.run(run())
    except exceptions.AiomaxException:
        pass  # a real, meaningful exception (not TypeError from `raise None`)
    else:
        raise AssertionError("expected an AiomaxException")


# --- M4 -------------------------------------------------------------------

def test_whitespace_only_command_does_not_crash():
    bot = aiomax.Bot("token")
    # "/ " passes the length guard but splits to an empty list.
    asyncio.run(bot.handle_update(_message_update("/ ")))


# --- M5 -------------------------------------------------------------------

def test_shutdown_cancels_hung_handler():
    class B(aiomax.Bot):
        async def get_me(self):
            return None

        async def get_updates(self, limit=100):
            self.polling = False
            return {"updates": []}

    bot = B("token", shutdown_timeout=0.05)

    @bot.on_ready()
    async def hung():
        await asyncio.sleep(3600)

    async def run():
        # If the drain blocked forever, wait_for would raise TimeoutError.
        await asyncio.wait_for(
            bot.start_polling(session=FakeSession()), timeout=5
        )

    asyncio.run(run())


# --- M9 -------------------------------------------------------------------

def test_command_collision_keeps_all_handlers():
    parent = Router()
    child = Router()

    @parent.on_command("start")
    async def p(ctx):
        pass

    @child.on_command("start")
    async def c(ctx):
        pass

    parent.add_router(child)

    assert len(parent.commands["start"]) == 2


# --- M10 ------------------------------------------------------------------

def test_same_user_updates_are_serialised():
    order = []

    bot = aiomax.Bot("token")

    @bot.on_message()
    async def handler(message):
        order.append(("start", message.body.text))
        await asyncio.sleep(0.05)
        order.append(("end", message.body.text))

    async def run():
        # Two updates from the same user dispatched back-to-back.
        await bot.handle_update(_message_update("first", uid=1))
        await bot.handle_update(_message_update("second", uid=1))
        await asyncio.gather(*list(bot._handler_tasks))

    asyncio.run(run())

    # Serialised: the first handler fully finishes before the second starts.
    assert order == [
        ("start", "first"),
        ("end", "first"),
        ("start", "second"),
        ("end", "second"),
    ]


def test_different_users_run_concurrently():
    order = []

    bot = aiomax.Bot("token")

    @bot.on_message()
    async def handler(message):
        order.append(("start", message.body.text))
        await asyncio.sleep(0.05)
        order.append(("end", message.body.text))

    async def run():
        await bot.handle_update(_message_update("userA", uid=1))
        await bot.handle_update(_message_update("userB", uid=2))
        await asyncio.gather(*list(bot._handler_tasks))

    asyncio.run(run())

    # Different users are not serialised: both start before either ends.
    assert order[0][0] == "start"
    assert order[1][0] == "start"
