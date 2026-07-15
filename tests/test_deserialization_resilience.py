"""Regression tests for deserialization robustness of untrusted API payloads.

Covers medium-severity findings:

* M2  - message_removed must not crash when the cache is disabled.
* M6  - an unknown attachment/button type must not crash the whole update.
* M7  - a new/unexpected field from the server must not raise on `**data`.
* M8  - Chat.from_json must deserialize nested icon/pinned_message/dialog.
* M11 - Button.from_json must tolerate missing optional fields.
"""

import aiomax
from aiomax import buttons, types


def _user(uid=1):
    return {
        "user_id": uid,
        "first_name": "Test",
        "name": "Test",
        "is_bot": False,
        "last_activity_time": 1000,
    }


# --- M2 -------------------------------------------------------------------

def test_message_removed_with_cache_disabled_does_not_crash():
    bot = aiomax.Bot("token", max_messages_cached=0)
    assert bot.cache is None

    payload = types.MessageDeletePayload.from_json(
        {"timestamp": 1000, "message_id": "m1", "chat_id": 5, "user_id": 7},
        bot,
    )
    assert payload.message is None
    assert payload.message_id == "m1"


# --- M6 -------------------------------------------------------------------

def test_unknown_attachment_type_returns_base_instead_of_raising():
    att = types.Attachment.from_json({"type": "future_type", "payload": {}})
    assert att is not None
    assert att.type == "future_type"


def test_unknown_button_type_returns_base_instead_of_raising():
    btn = buttons.Button.from_json({"type": "future_button", "text": "x"})
    assert btn is not None
    assert btn.type == "future_button"
    assert btn.text == "x"


# --- M7 -------------------------------------------------------------------

def test_user_from_json_tolerates_unexpected_field():
    user = types.User.from_json({**_user(), "new_field_from_2027": "value"})
    assert user.user_id == 1


def test_chat_from_json_tolerates_unexpected_field():
    chat = types.Chat.from_json(
        {
            "chat_id": 5,
            "type": "chat",
            "status": "active",
            "last_event_time": 1000,
            "participants_count": 2,
            "is_public": True,
            "brand_new_field": 123,
        }
    )
    assert chat.chat_id == 5


def test_image_from_json_tolerates_unexpected_field():
    image = types.Image.from_json({"url": "http://x", "extra": 1})
    assert image.url == "http://x"


# --- M8 -------------------------------------------------------------------

def test_chat_from_json_deserializes_nested_objects():
    chat = types.Chat.from_json(
        {
            "chat_id": 5,
            "type": "dialog",
            "status": "active",
            "last_event_time": 1000,
            "participants_count": 2,
            "is_public": False,
            "icon": {"url": "http://img"},
            "dialog_with_user": _user(9),
            "pinned_message": {
                "body": {"mid": "mid-1", "seq": 1, "text": "pinned"},
                "recipient": {"chat_id": 5, "chat_type": "dialog"},
                "sender": _user(9),
                "timestamp": 1000,
            },
        }
    )
    assert isinstance(chat.icon, types.Image)
    assert chat.icon.url == "http://img"
    assert isinstance(chat.dialog_with_user, types.User)
    assert chat.dialog_with_user.user_id == 9
    assert isinstance(chat.pinned_message, types.Message)
    assert chat.pinned_message.body.text == "pinned"


# --- M11 ------------------------------------------------------------------

def test_link_button_without_url_does_not_crash():
    btn = buttons.Button.from_json({"type": "link", "text": "go"})
    assert isinstance(btn, buttons.LinkButton)
    assert btn.url == ""


def test_geolocation_button_without_quick_does_not_crash():
    btn = buttons.Button.from_json(
        {"type": "request_geo_location", "text": "geo"}
    )
    assert isinstance(btn, buttons.GeolocationButton)
    assert btn.quick is False
