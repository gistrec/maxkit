"""
Regression tests for handling media-only messages (body.text=None).

MAX delivers ``message_created`` updates with ``body.text`` set to ``null``
for messages that carry only an attachment (a sticker, or a photo/file sent
without a caption). Before the fix the command-detection loop in
``Bot.handle_update`` called ``len(message.body.text)`` unconditionally and
crashed the whole update with ``TypeError`` (and, because the polling marker
is committed before processing, the update and the rest of the batch were
lost).
"""

import asyncio

import aiomax


def _sender() -> dict:
    return {
        "user_id": 1,
        "first_name": "Test",
        "name": "Test",
        "is_bot": False,
        "last_activity_time": 1000,
    }


def _textless_update() -> dict:
    """A ``message_created`` update for a sticker (no text)."""
    return {
        "update_type": "message_created",
        "message": {
            "sender": _sender(),
            "recipient": {"chat_id": 10, "chat_type": "chat"},
            "timestamp": 1000,
            "body": {
                "mid": "mid-1",
                "seq": 1,
                "text": None,
                "attachments": [
                    {"type": "sticker", "payload": {"code": "sticker-code"}}
                ],
            },
        },
    }


def test_textless_message_does_not_crash():
    bot = aiomax.Bot("token")

    # Must not raise TypeError from len(None) in the command parser.
    asyncio.run(bot.handle_update(_textless_update()))


def test_textless_message_still_reaches_message_handlers():
    bot = aiomax.Bot("token")
    received = []

    @bot.on_message()
    async def handler(message):
        received.append(message)

    async def run():
        await bot.handle_update(_textless_update())
        # handlers are dispatched as background tasks; wait for them
        if bot._handler_tasks:
            await asyncio.gather(*bot._handler_tasks)

    asyncio.run(run())

    assert len(received) == 1
    assert received[0].body.text is None
