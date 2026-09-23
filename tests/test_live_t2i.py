"""Integration tests against a live standalone T2I service (astrbot-t2i-service).

Usage:
    uv run pytest tests/test_live_t2i.py -v -s

Set T2I_ENDPOINT env var or it defaults to the LAN instance below.
Auto-skips when the endpoint is unreachable, so plain `uv run pytest` stays
green without a T2I service.
"""
import os
from pathlib import Path

import pytest
from suwayomi.cards import CARD_WIDTH, build_search_card, render_card
from suwayomi.t2i import make_endpoint_renderer, normalize_endpoint

from tests.helpers import t2i_reachable_sync  # noqa: E402

ENDPOINT = os.environ.get("T2I_ENDPOINT", "http://100.87.49.15:9105/")

pytestmark = pytest.mark.skipif(
    not t2i_reachable_sync(ENDPOINT),
    reason="独立 T2I 服务不可达，跳过集成测试（可用 T2I_ENDPOINT 指定地址）",
)


@pytest.mark.asyncio
async def test_live_endpoint_renders_card():
    """A real card template renders to a real JPEG through the live service."""
    tmpldata = build_search_card(
        rows=[
            {
                "index": 1,
                "title": "咒术回战",
                "status": "ONGOING",
                "source": "拷贝漫画",
                "thumbnail_url": None,
            },
        ],
        subtitle="测试源",
        footer="这是独立 T2I 服务的连通性验证",
    )

    path = await render_card(
        make_endpoint_renderer(ENDPOINT),
        tmpldata,
        timeout=60,
    )

    assert path is not None, "独立 T2I 端点渲染失败"
    img = Path(path)
    try:
        assert img.exists()
        assert img.stat().st_size > 1000, "渲染结果不应为空图片"

        from PIL import Image

        with Image.open(img) as im:
            # render_card 请求 880px 视口 × ultra(1.8) 设备像素比 → 约 1584px 宽
            assert im.format == "JPEG"
            expected = round(CARD_WIDTH * 1.8)
            assert abs(im.width - expected) <= 8, (
                f"输出宽度 {im.width}px 与预期 {expected}px 不符"
            )
            im.verify()
    finally:
        img.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_live_endpoint_accepts_bare_host_without_text2img():
    """Users may enter a bare host:port — normalization must still reach /generate."""
    bare = ENDPOINT.rstrip("/").replace("/text2img", "")
    assert normalize_endpoint(bare).endswith("/text2img")

    path = await render_card(
        make_endpoint_renderer(bare),
        build_search_card(rows=[], subtitle="空结果", footer="bare host probe"),
        timeout=60,
    )

    assert path is not None
    Path(path).unlink(missing_ok=True)
