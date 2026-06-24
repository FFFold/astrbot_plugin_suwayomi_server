import pytest
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


def test_jwt_client_init():
    c = SuwayomiClient("http://localhost:9330", "jwt", "admin", "secret")
    assert c.auth_mode == "jwt"
    assert c._jwt_access_token is None
    assert c._jwt_refresh_token is None
    assert c._username == "admin"
    assert c._password == "secret"
    assert "Authorization" not in c._headers


def test_basic_auth_header_content():
    import base64
    c = SuwayomiClient("http://localhost:9330", "basic", "user", "pass123")
    expected_cred = base64.b64encode(b"user:pass123").decode()
    assert c._headers["Authorization"] == f"Basic {expected_cred}"
