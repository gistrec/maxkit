"""
Posts made on behalf of a channel arrive without ``sender``. handle_update
built the FSM cursor from ``message.sender.user_id`` and raised
AttributeError, so no handler ever ran for a channel post or its edit.
"""

import asyncio

import aiomax


def _channel_message(text: str) -> dict:
    return {
        "recipient": {"chat_id": -5, "chat_type": "channel"},
        "timestamp": 1,
        "body": {"mid": "m1", "seq": 1, "text": text, "attachments": []},
    }


async def _dispatch(bot, update):
    await bot.handle_update(update)
    # Handlers run as tasks; let them finish.
    await asyncio.gather(*bot._handler_tasks)


def test_channel_post_reaches_message_and_edit_handlers():
    bot = aiomax.Bot("token")
    seen = []

    @bot.on_message()
    async def on_message(message, cursor):
        seen.append(("message", message.body.text, cursor))

    @bot.on_message_edit()
    async def on_edit(old, new):
        seen.append(("edit", new.body.text))

    async def run():
        for update_type in ("message_created", "message_edited"):
            await _dispatch(
                bot,
                {
                    "update_type": update_type,
                    "message": _channel_message("post"),
                    "timestamp": 1,
                },
            )

    asyncio.run(run())
    assert seen == [("message", "post", None), ("edit", "post")]


def test_channel_post_reaches_a_command_handler():
    bot = aiomax.Bot("token")
    seen = []

    @bot.on_command("ping")
    async def ping(ctx):
        seen.append(ctx.message.body.text)

    asyncio.run(
        _dispatch(
            bot,
            {
                "update_type": "message_created",
                "message": _channel_message("/ping"),
                "timestamp": 1,
            },
        )
    )
    assert seen == ["/ping"]


def test_channel_post_with_a_state_filter_registered():
    """
    filters.state reads message.user_id, which dereferenced the missing
    sender and raised — aborting dispatch for every handler, not just the
    stateful one.
    """
    bot = aiomax.Bot("token")
    seen = []

    @bot.on_message(aiomax.filters.state("waiting"))
    async def stateful(message):
        seen.append("stateful")

    @bot.on_message()
    async def plain(message):
        seen.append("plain")

    asyncio.run(
        _dispatch(
            bot,
            {
                "update_type": "message_created",
                "message": _channel_message("post"),
                "timestamp": 1,
            },
        )
    )
    assert seen == ["plain"]
