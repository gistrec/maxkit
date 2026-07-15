"""Smoke tests: the package imports and basic objects construct.

Guarantees the suite has at least one always-present test so ``pytest`` (and
CI) collect successfully even before feature-specific tests land.
"""

import aiomax
from aiomax import filters


def test_package_exposes_bot():
    assert hasattr(aiomax, "Bot")


def test_bot_constructs_with_defaults():
    bot = aiomax.Bot("token")
    assert bot.access_token == "token"
    assert bot.session is None
    assert bot.command_prefixes == "/"


def test_equals_filter_matches_content():
    class Obj:
        content = "ping"

    assert filters.equals("ping")(Obj()) is True
    assert filters.equals("pong")(Obj()) is False
