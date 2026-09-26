"""Regression test: commands must go to PATCH /me/commands, not PATCH /me.

Max split bot commands out of the generic bot-info PATCH in its July 2026
API revision. Sending `commands` inside the `PATCH /me` body is now rejected
by the platform with `method.not.found: Path /me is not recognized`.
"""

import aiomax


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    async def json(self):
        return self._data


def _make_bot():
    bot = aiomax.Bot(access_token="token")
    bot.id = 1
    return bot


def test_commands_are_sent_to_dedicated_endpoint():
    calls = []

    async def fake_patch(url, *args, **kwargs):
        calls.append((url, kwargs.get("json")))
        sent = kwargs.get("json", {}).get("commands", [])
        return _FakeResponse({"commands": sent})

    bot = _make_bot()
    bot.patch = fake_patch

    async def fake_get_me():
        return None

    bot.get_me = fake_get_me

    import asyncio

    commands = [aiomax.BotCommand("balance", "Текущий баланс")]
    asyncio.run(bot.patch_me(commands=commands))

    expected = [{"name": "balance", "description": "Текущий баланс"}]
    assert calls == [("me/commands", {"commands": expected})]
    assert bot.bot_commands == expected


def test_name_and_commands_together_hit_both_endpoints():
    calls = []

    async def fake_patch(url, *args, **kwargs):
        calls.append((url, kwargs.get("json")))
        if url == "me":
            return _FakeResponse({
                "user_id": 1,
                "first_name": "Bot",
                "name": "Bot",
                "is_bot": True,
                "last_activity_time": 0,
            })
        sent = kwargs.get("json", {}).get("commands", [])
        return _FakeResponse({"commands": sent})

    bot = _make_bot()
    bot.patch = fake_patch

    import asyncio

    command = aiomax.BotCommand("help", "Помощь")
    asyncio.run(bot.patch_me(name="Bot", commands=[command]))

    urls = [url for url, _ in calls]
    assert urls == ["me", "me/commands"]


def test_empty_command_list_clears_commands():
    calls = []

    async def fake_patch(url, *args, **kwargs):
        calls.append((url, kwargs.get("json")))
        return _FakeResponse({"commands": []})

    bot = _make_bot()
    bot.patch = fake_patch

    async def fake_get_me():
        return None

    bot.get_me = fake_get_me

    import asyncio

    asyncio.run(bot.patch_me(commands=[]))

    assert calls == [("me/commands", {"commands": []})]
    assert bot.bot_commands == []
