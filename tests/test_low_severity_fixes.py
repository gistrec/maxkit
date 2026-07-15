"""Regression tests for the low-severity audit fixes.

* L1 - send/edit retry AttachmentNotReady a bounded number of times.
* L2 - get_exception tolerates a JSON error body without a "code" field.
* L4 - _upload uses a fixed "data" field name + safe filename metadata.
* L5 - edit_message handles both bare and {"message": ...} responses.
* L6 - AudioAttachment.from_json tolerates a missing payload / fields.
* L7 - Router.bot resolves to the root Bot through deep nesting.
* L8 - Callback.answer targets the configured api_url, not a hardcoded host.
"""

import asyncio

import aiomax
import aiomax.bot as bot_module
from aiomax import exceptions, types, utils
from aiomax.router import Router


def _sender(uid=1):
    return {
        "user_id": uid,
        "first_name": "Test",
        "name": "Test",
        "is_bot": False,
        "last_activity_time": 1000,
    }


# --- L1 -------------------------------------------------------------------

def test_send_message_stops_retrying_attachment_not_ready(monkeypatch):
    async def _no_sleep(*args, **kwargs):
        return None

    monkeypatch.setattr(bot_module.asyncio, "sleep", _no_sleep)

    calls = {"post": 0}
    bot = aiomax.Bot("token", attachment_retries=3)

    async def fake_post(url, **kwargs):
        calls["post"] += 1
        raise exceptions.AttachmentNotReady()

    bot.post = fake_post

    try:
        asyncio.run(bot.send_message("hi", chat_id=1))
    except exceptions.AttachmentNotReady:
        pass
    else:
        raise AssertionError("expected AttachmentNotReady after retries")

    # initial attempt + attachment_retries, not an unbounded recursion.
    assert calls["post"] == 4


# --- L2 -------------------------------------------------------------------

def test_get_exception_without_code_field():
    class FakeResp:
        status = 400
        content_type = "application/json"

        async def json(self):
            return {"message": "error with no code"}

    exc = asyncio.run(utils.get_exception(FakeResp()))
    assert isinstance(exc, exceptions.AiomaxException)


# --- L4 -------------------------------------------------------------------

def test_upload_uses_fixed_field_name_and_filename():
    bot = aiomax.Bot("token")
    captured = {}

    class FakeResp:
        async def json(self):
            return {"url": "http://upload", "token": "t"}

        def raise_for_status(self):
            return None

    async def fake_post(url, **kwargs):
        return FakeResp()

    class FakeSession:
        async def post(self, url, data=None, **kwargs):
            captured["form"] = data
            return FakeResp()

    bot.post = fake_post
    bot.session = FakeSession()

    evil = 'evil"; name="injected'
    asyncio.run(bot._upload(b"filebytes", "file", evil))

    form = captured["form"]
    names = [opts.get("name") for opts, _headers, _value in form._fields]
    filenames = [opts.get("filename") for opts, _headers, _value in form._fields]
    assert names == ["data"]
    # The attacker-controlled name is confined to the filename metadata,
    # which aiohttp encodes safely, and never becomes the field name.
    assert filenames == [evil]


# --- L5 -------------------------------------------------------------------

def _edit_response_message():
    return {
        "body": {"mid": "m1", "seq": 1, "text": "edited"},
        "recipient": {"chat_id": 1, "chat_type": "chat"},
        "sender": _sender(),
        "timestamp": 1000,
    }


def _run_edit(response_payload):
    bot = aiomax.Bot("token")

    class FakeResp:
        status = 200
        content_type = "application/json"

        async def json(self):
            return response_payload

    async def fake_put(url, **kwargs):
        return FakeResp()

    bot.put = fake_put
    return asyncio.run(bot.edit_message("m1", "edited"))


def test_edit_message_handles_enveloped_response():
    result = _run_edit({"message": _edit_response_message()})
    assert result.body.text == "edited"


def test_edit_message_handles_bare_message_response():
    result = _run_edit(_edit_response_message())
    assert result.body.text == "edited"


# --- L6 -------------------------------------------------------------------

def test_audio_attachment_tolerates_missing_fields():
    att = types.AudioAttachment.from_json({"payload": {}})
    assert att.url is None
    assert att.token is None

    att2 = types.AudioAttachment.from_json({})
    assert att2.token is None


# --- L7 -------------------------------------------------------------------

def test_router_bot_resolves_through_deep_nesting():
    bot = aiomax.Bot("token")
    r1, r2, r3 = Router(), Router(), Router()
    bot.add_router(r1)
    r1.add_router(r2)
    r2.add_router(r3)

    assert r3.bot is bot
    assert r2.bot is bot
    assert r1.bot is bot
    assert bot.bot is None


# --- L8 -------------------------------------------------------------------

def test_callback_answer_targets_configured_host():
    bot = aiomax.Bot("token")
    captured = {}

    async def fake_post(url, **kwargs):
        captured["url"] = url

        class R:
            async def json(self):
                return {}

        return R()

    bot.post = fake_post
    callback = types.Callback(
        bot, 1000, "cb1", None, types.User(**_sender()), None, "payload"
    )
    asyncio.run(callback.answer(notification="hi"))

    # Relative path resolved against Bot.api_url, not a hardcoded host.
    assert captured["url"] == "answers"
