"""Tests for the live-server probe helper (offline, uses a local HTTP server)."""
import pytest
import pytest_asyncio
from aiohttp import web

from tests.helpers import server_reachable


@pytest_asyncio.fixture
async def local_graphql_server():
    app = web.Application()

    async def handler(request):
        return web.json_response({"data": {"__typename": "Query"}})

    app.router.add_post("/api/graphql", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    await runner.cleanup()


@pytest.mark.asyncio
async def test_server_reachable_true(local_graphql_server):
    assert await server_reachable(local_graphql_server) is True


@pytest.mark.asyncio
async def test_server_reachable_false_on_unreachable_port():
    assert await server_reachable("http://127.0.0.1:1", timeout=1.0) is False
