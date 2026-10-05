"""
Regression tests for three workarounds bots used to carry on top of aiomax.

- ``message_created`` without a ``message``: Max sends one about once a day to
  a busy bot, and ``handle_update`` failed on ``update["message"]``.
- An upload answered with an error body instead of a token surfaced as a bare
  ``KeyError('token')``.
- Code that sends without polling (scripts, workers) had no way to get the
  session ``start_polling`` builds, so it had to rebuild it by hand: token
  header, relative base URL and the Mintsifra CA.
"""

import asyncio
import logging

import pytest

import aiomax
from aiomax import exceptions


def test_message_created_without_message_is_skipped(caplog):
    bot = aiomax.Bot("token")
    received = []

    @bot.on_message()
    async def handler(message):
        received.append(message)

    update = {"update_type": "message_created", "timestamp": 1000}
    with caplog.at_level(logging.WARNING, logger="aiomax.bot"):
        asyncio.run(bot.handle_update(update))

    assert received == []
    assert "without a message" in caplog.text


@pytest.mark.parametrize(
    ("method", "raw"),
    [
        ("upload_video", {"code": "upload.error", "message": "boom"}),
        ("upload_audio", {}),
        ("upload_image", {"photos": {}}),
    ],
)
def test_upload_without_token_raises_a_real_error(method, raw):
    bot = aiomax.Bot("token")

    async def fake_upload(data, type, filename=None):
        return raw

    bot._upload = fake_upload

    with pytest.raises(exceptions.UnknownErrorException) as info:
        asyncio.run(getattr(bot, method)(b"data"))

    assert info.value.text == raw.get("code", "upload.no_token")


def test_upload_file_without_token_raises_a_real_error():
    bot = aiomax.Bot("token")

    async def fake_upload(data, type, filename=None):
        return {"message": "file too big"}

    bot._upload = fake_upload

    with pytest.raises(exceptions.UnknownErrorException) as info:
        asyncio.run(bot.upload_file(b"data", filename="a.txt"))

    assert info.value.description == "file too big"


def test_upload_with_token_still_returns_the_attachment():
    bot = aiomax.Bot("token")

    async def fake_upload(data, type, filename=None):
        return {"photos": {"x": {"token": "tok"}}}

    bot._upload = fake_upload

    attachment = asyncio.run(bot.upload_image(b"data"))
    assert attachment.token == "tok"


def test_context_manager_opens_and_closes_a_ready_session():
    bot = aiomax.Bot("secret", use_certificate=True)

    async def run():
        async with bot as same:
            assert same is bot
            session = bot.session
            assert session is not None and not session.closed
            assert session.headers["Authorization"] == "secret"
            assert str(session._base_url) == bot.api_url
        return session

    session = asyncio.run(run())
    assert session.closed
    assert bot.session is None


def test_context_manager_refuses_a_second_open_session():
    bot = aiomax.Bot("secret")

    async def run():
        async with bot:
            with pytest.raises(RuntimeError):
                async with bot:
                    pass

    asyncio.run(run())


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


@pytest.mark.parametrize(
    "body",
    [
        {"success": False, "code": "message.not.found", "message": "gone"},
        {"success": False},
    ],
)
def test_delete_message_failure_raises_a_typed_error(body):
    bot = aiomax.Bot("token")

    async def fake_delete(url, *args, **kwargs):
        return _FakeResponse(body)

    bot.delete = fake_delete

    with pytest.raises(exceptions.UnknownErrorException) as info:
        asyncio.run(bot.delete_message("mid"))

    assert info.value.text == body.get("code", "")


def test_delete_message_success_returns_quietly():
    bot = aiomax.Bot("token")

    async def fake_delete(url, *args, **kwargs):
        return _FakeResponse({"success": True})

    bot.delete = fake_delete

    assert asyncio.run(bot.delete_message("mid")) is None
