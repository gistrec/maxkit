"""
Regression tests for content filters against ``content=None``.

Objects passed to filters may expose ``content=None`` — a Message whose
``body.text`` is ``None`` (media-only message) or a Callback with an empty
``payload``. Before the fix ``has``/``startswith``/``endswith``/``regex`` and
``papaya`` dereferenced ``obj.content`` directly and crashed with
``AttributeError``/``TypeError``. They must now treat a ``None`` content as a
non-match instead of raising.
"""

from aiomax import filters


class _Obj:
    def __init__(self, content):
        self.content = content


def test_filters_do_not_crash_on_none_content():
    obj = _Obj(None)

    assert filters.has("x")(obj) is False
    assert filters.startswith("x")(obj) is False
    assert filters.endswith("x")(obj) is False
    assert filters.regex(".*")(obj) is None  # falsy -> treated as no match
    assert filters.papaya(obj) is False
    # equals was already safe (None == "x") but assert it stays a non-match
    assert filters.equals("x")(obj) is False


def test_filters_still_match_real_content():
    obj = _Obj("hello папайя world")

    assert filters.has("llo")(obj) is True
    assert filters.startswith("hello")(obj) is True
    assert filters.endswith("world")(obj) is True
    assert filters.regex("hello.*")(obj) is not None
    assert filters.papaya(obj) is True
    assert filters.equals("hello папайя world")(obj) is True


def test_filters_still_raise_without_content_attr():
    class NoContent:
        pass

    for f in (
        filters.has("x"),
        filters.startswith("x"),
        filters.endswith("x"),
        filters.regex(".*"),
    ):
        try:
            f(NoContent())
        except Exception:
            pass
        else:
            raise AssertionError("expected filter to raise without content")
