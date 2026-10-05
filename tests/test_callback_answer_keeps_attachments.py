"""
Callback.answer copied the message's inline keyboard into every answer, so a
bare notification (or a text-only edit) went out as an edit with
attachments=[keyboard]. Max treats a non-empty attachments list as a full
replacement, so the message lost its photo or file — ClearTranscriptBot's
users watched a paid transcript vanish on every button press.
"""

import asyncio

import aiomax
from aiomax import types

MESSAGE = {
    "sender": {"user_id": 9, "first_name": "Bot", "is_bot": True},
    "recipient": {"chat_id": 5, "chat_type": "dialog"},
    "timestamp": 1,
    "body": {
        "mid": "m",
        "seq": 1,
        "text": "Invoice #42",
        "attachments": [
            {
                "type": "image",
                "payload": {"photo_id": 1, "token": "ph", "url": "http://x"},
            },
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [
                        [{"type": "callback", "text": "Pay", "payload": "p"}]
                    ]
                },
            },
        ],
    },
}
CALLBACK = {
    "timestamp": 1,
    "callback_id": "cb1",
    "payload": "p",
    "user": {"user_id": 1, "first_name": "A", "is_bot": False},
}


class _Response:
    async def json(self):
        return {"success": True}


def _answer(**kwargs) -> dict:
    bot = aiomax.Bot("token")
    sent = {}

    async def post(url, **kw):
        sent["body"] = kw["json"]
        return _Response()

    bot.post = post
    callback = types.Callback.from_json(CALLBACK, MESSAGE, bot=bot)
    asyncio.run(callback.answer(**kwargs))
    return sent["body"]


def test_notification_alone_does_not_edit_the_message():
    body = _answer(notification="Payment received")
    assert body == {"notification": "Payment received", "message": None}


def test_text_edit_leaves_the_attachments_alone():
    message = _answer(text="Paid")["message"]
    assert message["text"] == "Paid"
    assert "attachments" not in message


def test_new_attachments_keep_the_current_keyboard():
    photo = types.PhotoAttachment(token="new")
    attachments = _answer(attachments=[photo])["message"]["attachments"]
    kinds = [a["type"] for a in attachments]
    assert kinds == ["inline_keyboard", "image"]


def test_explicit_keyboard_still_wins():
    keyboard = [[{"type": "callback", "text": "Done", "payload": "d"}]]
    attachments = _answer(text="Paid", keyboard=keyboard)["message"][
        "attachments"
    ]
    assert attachments[0]["payload"]["buttons"][0][0]["text"] == "Done"
