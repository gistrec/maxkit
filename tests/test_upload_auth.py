"""
The upload URL Max returns points at a separate upload host. The bot token
must not travel there: before the fix _upload posted through the API session,
whose default Authorization header carried the token to that host.
"""

import asyncio

import aiohttp

from aiohttp import web

import aiomax


async def _serve(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, site._server.sockets[0].getsockname()[1]


def test_upload_host_does_not_receive_the_bot_token():
    seen = {}

    async def run():
        upload_port = {}

        async def uploads(request):
            assert request.headers.get("Authorization") == "SECRET"
            return web.json_response(
                {"url": f"http://127.0.0.1:{upload_port['p']}/up"}
            )

        async def up(request):
            seen["auth"] = request.headers.get("Authorization")
            await request.read()
            return web.json_response({"token": "file-token"})

        api = web.Application()
        api.router.add_post("/uploads", uploads)
        cdn = web.Application()
        cdn.router.add_post("/up", up)
        api_runner, api_port = await _serve(api)
        cdn_runner, upload_port["p"] = await _serve(cdn)
        try:
            bot = aiomax.Bot("SECRET", api_url=f"http://127.0.0.1:{api_port}/")
            async with bot:
                attachment = await bot.upload_file(b"hello", filename="a.txt")
                # The API session is still usable after the upload.
                assert not bot.session.closed
            return attachment
        finally:
            await api_runner.cleanup()
            await cdn_runner.cleanup()

    attachment = asyncio.run(run())
    assert attachment.token == "file-token"
    assert seen["auth"] is None


def test_upload_goes_through_the_custom_session_proxy():
    """
    Proxy settings live on the session, not the connector. A bot started
    with ClientSession(proxy=...) (docs/Примеры.md) must upload through
    that proxy too, still without the token.
    """
    seen = []

    async def run():
        async def proxy(request):
            seen.append(
                (request.path, request.headers.get("Authorization"))
            )
            if request.path.endswith("/uploads"):
                return web.json_response({"url": "http://upload.invalid/up"})
            await request.read()
            return web.json_response({"token": "file-token"})

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", proxy)
        runner, port = await _serve(app)
        bot = aiomax.Bot("SECRET", api_url="http://api.invalid/")
        bot.session = aiohttp.ClientSession(
            headers={"Authorization": "SECRET"},
            base_url=bot.api_url,
            proxy=f"http://127.0.0.1:{port}",
        )
        try:
            return await bot.upload_file(b"hello", filename="a.txt")
        finally:
            await bot.session.close()
            await runner.cleanup()

    attachment = asyncio.run(run())
    assert attachment.token == "file-token"
    assert seen == [("/uploads", "SECRET"), ("/up", None)]
