"""Shared helpers for live integration tests."""
from __future__ import annotations

import asyncio

import aiohttp


async def server_reachable(url: str, timeout: float = 3.0) -> bool:
    """Return True if a Suwayomi-Server GraphQL endpoint responds at url."""
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.post(
                f"{url.rstrip('/')}/api/graphql",
                json={"query": "{__typename}"},
            ) as resp:
                return resp.status < 500
    except Exception:
        return False


def server_reachable_sync(url: str, timeout: float = 3.0) -> bool:
    """Sync wrapper for module-level pytest.skipif evaluation."""
    try:
        return asyncio.run(server_reachable(url, timeout))
    except RuntimeError:
        return False
