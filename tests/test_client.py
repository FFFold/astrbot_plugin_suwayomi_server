import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from suwayomi.client import SuwayomiClient


@pytest.fixture
def client():
    return SuwayomiClient("http://localhost:9330", "none", "", "")


@pytest.fixture
def auth_client():
    return SuwayomiClient("http://localhost:9330", "basic", "admin", "pass")


def test_client_init_no_auth(client):
    assert client.server_url == "http://localhost:9330"
    assert client.auth_mode == "none"
    assert client._headers == {"Content-Type": "application/json"}


def test_client_init_basic_auth(auth_client):
    assert "Authorization" in auth_client._headers
    assert auth_client._headers["Authorization"].startswith("Basic ")


def test_build_image_url(client):
    url = client.build_image_url("/api/v1/manga/42/chapter/5/page/0")
    assert url == "http://localhost:9330/api/v1/manga/42/chapter/5/page/0"


def test_build_image_url_strips_trailing_slash():
    c = SuwayomiClient("http://localhost:9330/", "none", "", "")
    url = c.build_image_url("/api/v1/manga/1/chapter/1/page/0")
    assert url == "http://localhost:9330/api/v1/manga/1/chapter/1/page/0"
