"""
Max documents ``last_activity_time`` as optional ("может не возвращаться",
for users who hide their online status) and ``name`` as deprecated. User
required both, so a sender without either raised TypeError in from_json and
the whole message, callback or bot_started update was lost.
"""

import asyncio

import pytest

import aiomax
from aiomax import types

FULL = {
    "user_id": 1,
    "first_name": "Аня",
    "last_name": "Петрова",
    "name": "Аня Петрова",
    "is_bot": False,
    "last_activity_time": 1700000000000,
}


@pytest.mark.parametrize("missing", ["last_activity_time", "name"])
def test_message_from_a_sender_missing_a_field_is_handled(missing):
    sender = {k: v for k, v in FULL.items() if k != missing}
    bot = aiomax.Bot("token")
    seen = []

    @bot.on_message()
    async def on_message(message):
        seen.append(message.sender.user_id)

    update = {
        "update_type": "message_created",
        "timestamp": 1,
        "message": {
            "sender": sender,
            "recipient": {"chat_id": 5, "chat_type": "dialog"},
            "timestamp": 1,
            "body": {"mid": "m", "seq": 1, "text": "hi", "attachments": []},
        },
    }

    async def run():
        await bot.handle_update(update)
        await asyncio.gather(*bot._handler_tasks)

    asyncio.run(run())
    assert seen == [1]


def test_name_falls_back_to_first_and_last_name():
    data = {k: v for k, v in FULL.items() if k != "name"}
    assert types.User.from_json(data).name == "Аня Петрова"

    data.pop("last_name")
    assert types.User.from_json(data).name == "Аня"


def test_name_and_activity_time_still_read_when_present():
    user = types.User.from_json(FULL)
    assert user.name == "Аня Петрова"
    assert user.last_activity_time == 1700000000
    assert types.User.from_json(
        {"user_id": 1, "first_name": "A"}
    ).last_activity_time is None
