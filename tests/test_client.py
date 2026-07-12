from unittest.mock import AsyncMock

import pytest

from suwayomi.client import SuwayomiClient


@pytest.fixture
def client():
    return SuwayomiClient("http://localhost:4567", "none", "", "")


@pytest.fixture
def auth_client():
    return SuwayomiClient("http://localhost:4567", "basic", "admin", "pass")


def test_client_init_no_auth(client):
    assert client.server_url == "http://localhost:4567"
    assert client.auth_mode == "none"
    assert client._headers == {"Content-Type": "application/json"}


def test_client_init_basic_auth(auth_client):
    assert "Authorization" in auth_client._headers
    assert auth_client._headers["Authorization"].startswith("Basic ")


def test_build_image_url(client):
    url = client.build_image_url("/api/v1/manga/42/chapter/5/page/0")
    assert url == "http://localhost:4567/api/v1/manga/42/chapter/5/page/0"


def test_build_image_url_strips_trailing_slash():
    c = SuwayomiClient("http://localhost:4567/", "none", "", "")
    url = c.build_image_url("/api/v1/manga/1/chapter/1/page/0")
    assert url == "http://localhost:4567/api/v1/manga/1/chapter/1/page/0"


def test_jwt_client_init():
    c = SuwayomiClient("http://localhost:4567", "jwt", "admin", "secret")
    assert c.auth_mode == "jwt"
    assert c._jwt_access_token is None
    assert c._jwt_refresh_token is None
    assert c._username == "admin"
    assert c._password == "secret"
    assert "Authorization" not in c._headers


def test_basic_auth_header_content():
    import base64
    c = SuwayomiClient("http://localhost:4567", "basic", "user", "pass123")
    expected_cred = base64.b64encode(b"user:pass123").decode()
    assert c._headers["Authorization"] == f"Basic {expected_cred}"


@pytest.mark.asyncio
async def test_jwt_first_request_logs_in_without_recursion():
    client = SuwayomiClient("http://localhost:4567", "jwt", "admin", "secret")
    client._post_graphql = AsyncMock(side_effect=[
        (200, {"data": {"login": {
            "accessToken": "access-token",
            "refreshToken": "refresh-token",
        }}}),
        (200, {"data": {"sources": {"nodes": []}}}),
    ])

    sources = await client.get_sources()

    assert sources == []
    assert client._jwt_access_token == "access-token"
    assert client._jwt_refresh_token == "refresh-token"
    assert client._post_graphql.await_count == 2
    assert client._post_graphql.await_args_list[0].args[2:] == ()
    assert client._post_graphql.await_args_list[1].args[2] == "access-token"


@pytest.mark.asyncio
async def test_jwt_refreshes_on_graphql_unauthorized_error():
    client = SuwayomiClient("http://localhost:4567", "jwt", "admin", "secret")
    client._jwt_access_token = "expired-token"
    client._jwt_refresh_token = "refresh-token"
    client._post_graphql = AsyncMock(side_effect=[
        (200, {"errors": [{"message": "Unauthorized\r\nserver stack"}]}),
        (200, {"data": {"refreshToken": {"accessToken": "fresh-token"}}}),
        (200, {"data": {"sources": {"nodes": []}}}),
    ])

    sources = await client.get_sources()

    assert sources == []
    assert client._jwt_access_token == "fresh-token"
    assert client._post_graphql.await_count == 3
    assert client._post_graphql.await_args_list[0].args[2] == "expired-token"
    assert client._post_graphql.await_args_list[1].args[2:] == ()
    assert client._post_graphql.await_args_list[2].args[2] == "fresh-token"


@pytest.mark.asyncio
async def test_jwt_refreshes_on_http_401():
    client = SuwayomiClient("http://localhost:4567", "jwt", "admin", "secret")
    client._jwt_access_token = "expired-token"
    client._jwt_refresh_token = "refresh-token"
    client._post_graphql = AsyncMock(side_effect=[
        (401, {}),
        (200, {"data": {"refreshToken": {"accessToken": "fresh-token"}}}),
        (200, {"data": {"sources": {"nodes": []}}}),
    ])

    sources = await client.get_sources()

    assert sources == []
    assert client._jwt_access_token == "fresh-token"


@pytest.mark.asyncio
async def test_jwt_logs_in_again_when_refresh_token_is_invalid():
    client = SuwayomiClient("http://localhost:4567", "jwt", "admin", "secret")
    client._jwt_access_token = "expired-token"
    client._jwt_refresh_token = "invalid-refresh-token"
    client._post_graphql = AsyncMock(side_effect=[
        (401, {}),
        (200, {"errors": [{"message": "Invalid refresh token"}]}),
        (200, {"data": {"login": {
            "accessToken": "new-access-token",
            "refreshToken": "new-refresh-token",
        }}}),
        (200, {"data": {"sources": {"nodes": []}}}),
    ])

    sources = await client.get_sources()

    assert sources == []
    assert client._jwt_access_token == "new-access-token"
    assert client._jwt_refresh_token == "new-refresh-token"
    assert client._post_graphql.await_count == 4
    assert client._post_graphql.await_args_list[0].args[2] == "expired-token"
    assert client._post_graphql.await_args_list[1].args[2:] == ()
    assert client._post_graphql.await_args_list[2].args[2:] == ()
    assert client._post_graphql.await_args_list[3].args[2] == "new-access-token"
