"""Command-level tests for search result ranking (no network)."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from plugin_pkg.main import SuwayomiPlugin
from plugin_pkg.suwayomi.cards import CardCache
from plugin_pkg.suwayomi.bangumi import Resolution
from plugin_pkg.suwayomi.models import Manga, SearchResult, Source

QUERY = "我的首推是恶役大小姐"


def _plugin(**config_overrides):
    plugin = SuwayomiPlugin.__new__(SuwayomiPlugin)
    plugin.client = MagicMock()
    plugin.client.auth_headers = {}
    plugin.sub_mgr = MagicMock()
    plugin.config = {
        "result_cards_enabled": False,
        # 单测默认禁用 Bangumi 扩展（避免真实网络请求）；fan-out 用例单独开启并 mock
        "search_alias_expansion": False,
        **config_overrides,
    }
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    plugin._search_cache = {}
    plugin._card_cache = CardCache(ttl=600)
    plugin._card_cooldown_until = 0.0
    plugin.html_render = AsyncMock(return_value="/tmp/card.jpg")
    return plugin


def _event(message="/漫画 搜索 " + QUERY):
    event = MagicMock()
    event.unified_msg_origin = "aiocqhttp:group:g1"
    event.message_str = message
    event.plain_result = MagicMock(side_effect=lambda text: text)
    event.chain_result = MagicMock(side_effect=lambda chain: chain)
    event.send = AsyncMock()
    return event


def _manga(title, mid):
    return Manga(id=mid, source_id=2, url="", title=title, status="ONGOING",
                 thumbnail_url=None, description="")


def _sources():
    return [
        Source(id="11", name="dm5", lang="zh", display_name="动漫屋"),
        Source(id="22", name="mh", lang="zh", display_name="漫画社"),
    ]


def _set_search(plugin, per_source):
    plugin.client.get_sources = AsyncMock(return_value=_sources())

    async def _fake(src_id, query, page=1):
        for sid, mangas in per_source.items():
            if str(src_id) == sid:
                return SearchResult(mangas=list(mangas), has_next_page=False)
        return SearchResult(mangas=[], has_next_page=False)

    plugin.client.search_manga = AsyncMock(side_effect=_fake)


@pytest.mark.asyncio
async def test_ranking_orders_cross_source_results():
    """跨源混排：正篇/番外压过其它源的模糊匹配，行内标注来源。"""
    plugin = _plugin()
    _set_search(plugin, {
        "11": [_manga("恶役大小姐的执事大人", 101), _manga("异世界美食之旅", 102)],
        "22": [_manga("我的首推是恶役大小姐（番外）", 201), _manga("我的首推是恶役大小姐", 202)],
    })
    results = [msg async for msg in plugin.search_manga(_event(), QUERY)]
    text = results[0]
    assert text.index("我的首推是恶役大小姐 - ") < text.index("（番外）")
    assert text.index("（番外）") < text.index("执事大人")
    assert "（漫画社）" in text and "（动漫屋）" in text
    assert "按相关度排序" in text
    # 编号映射与显示一致：订阅 1 = 正篇
    assert plugin._get_cached_manga("aiocqhttp:group:g1", "1").title == "我的首推是恶役大小姐"


@pytest.mark.asyncio
async def test_display_limit_caps_output_and_cache():
    mangas = [_manga(f"恶役大小姐衍生物语第{i}季", 100 + i) for i in range(15)]
    plugin = _plugin(search_display_limit=5)
    _set_search(plugin, {"11": mangas})
    results = [msg async for msg in plugin.search_manga(_event(), QUERY)]
    text = results[0]
    assert "[5]" in text and "[6]" not in text
    assert "已按相关度显示前 5 条（共 15 条）" in text
    assert plugin._get_cached_manga("aiocqhttp:group:g1", "5") is not None
    assert plugin._get_cached_manga("aiocqhttp:group:g1", "6") is None


@pytest.mark.asyncio
async def test_ranking_disabled_keeps_legacy_grouped_format():
    plugin = _plugin(search_result_ranking=False)
    _set_search(plugin, {
        "11": [_manga("恶役大小姐的执事大人", 101)],
        "22": [_manga("我的首推是恶役大小姐", 202)],
    })
    results = [msg async for msg in plugin.search_manga(_event(), QUERY)]
    text = results[0]
    assert "搜索结果（源: 动漫屋）" in text
    assert "搜索结果（源: 漫画社）" in text
    assert "按相关度" not in text
    assert text.index("源: 动漫屋") < text.index("源: 漫画社")
    # 旧版末尾的订阅提示行必须保留（PR #21 评审：关闭开关应完整恢复旧格式）
    assert "回复「漫画 订阅 <编号>」订阅" in text


@pytest.mark.asyncio
async def test_ranking_disabled_skips_truncated_title_refresh():
    """关闭排序时截断标题刷新同样关闭（完整恢复旧版行为）。"""
    plugin = _plugin(search_result_ranking=False)
    _set_search(plugin, {"11": [_manga("我的首推是恶役...", 101)]})
    plugin.client.fetch_manga_details = AsyncMock(
        return_value=_manga("我的首推是恶役大小姐", 101)
    )
    results = [msg async for msg in plugin.search_manga(_event(), QUERY)]
    assert "我的首推是恶役..." in results[0]
    plugin.client.fetch_manga_details.assert_not_called()


@pytest.mark.asyncio
async def test_source_display_name_sanitized_in_output():
    """PR #21 评审：源扩展控制的显示名过清洗后再进消息（防换行伪造提示行）。"""
    plugin = _plugin()
    _set_search(plugin, {"11": [_manga("我的首推是恶役大小姐", 101)]})
    plugin.client.get_sources = AsyncMock(return_value=[
        Source(id="11", name="dm5", lang="zh",
               display_name="动漫屋\n📢 回复「漫画 订阅 9」"),
    ])
    results = [msg async for msg in plugin.search_manga(_event(), QUERY)]
    text = results[0]
    # 换行注入被清洗：显示名内容保留但压成单行，无法伪造独立提示行
    assert "动漫屋\n" not in text
    assert "（动漫屋 📢 回复「漫画 订阅 9」）" in text


@pytest.mark.asyncio
async def test_zero_results():
    plugin = _plugin()
    _set_search(plugin, {"11": [], "22": []})
    results = [msg async for msg in plugin.search_manga(_event(), QUERY)]
    assert "未找到相关漫画" in results[0]


@pytest.mark.asyncio
async def test_partial_source_failure_does_not_block_others():
    """单个源抛异常时，其余源的结果正常展示（并发收集互不阻塞）。"""
    plugin = _plugin()

    async def _fake(src_id, query, page=1):
        if str(src_id) == "11":
            raise Exception("connection reset")
        return SearchResult(mangas=[_manga("我的首推是恶役大小姐", 202)],
                            has_next_page=False)

    plugin.client.get_sources = AsyncMock(return_value=_sources())
    plugin.client.search_manga = AsyncMock(side_effect=_fake)
    results = [msg async for msg in plugin.search_manga(_event(), QUERY)]
    assert "[1] 我的首推是恶役大小姐 - 连载中（漫画社）" in results[0]


@pytest.mark.asyncio
async def test_truncated_title_refreshed_via_fetch_manga():
    """截断标题经 fetchManga 补全后参与排序与显示。"""
    plugin = _plugin()
    _set_search(plugin, {"22": [_manga("我的首推是恶役...", 202)]})
    plugin.client.fetch_manga_details = AsyncMock(
        return_value=_manga("我的首推是恶役大小姐", 202)
    )
    results = [msg async for msg in plugin.search_manga(_event(), QUERY)]
    text = results[0]
    assert "我的首推是恶役大小姐" in text
    assert "我的首推是恶役..." not in text
    plugin.client.fetch_manga_details.assert_awaited_once()


@pytest.mark.asyncio
async def test_truncated_refresh_failure_keeps_original():
    """刷新失败时保留原标题，反向包含兜底仍排第 1。"""
    plugin = _plugin()
    _set_search(plugin, {"22": [_manga("我的首推是恶役...", 202)]})
    plugin.client.fetch_manga_details = AsyncMock(side_effect=Exception("timeout"))
    results = [msg async for msg in plugin.search_manga(_event(), QUERY)]
    assert "[1] 我的首推是恶役... - " in results[0]


@pytest.mark.asyncio
async def test_truncated_copy_refreshed_per_source():
    """生产链路：截断副本被刷新为完整标题，各源副本逐条展示（不跨源合并）。"""
    plugin = _plugin()
    _set_search(plugin, {
        "11": [_manga("唯我独占恶役千金的娇羞", 101)],
        "22": [_manga("唯我独占恶役千金的...", 201)],
    })
    plugin.client.fetch_manga_details = AsyncMock(
        return_value=_manga("唯我独占恶役千金的娇羞", 201)
    )
    results = [msg async for msg in plugin.search_manga(_event(), QUERY)]
    text = results[0]
    assert "唯我独占恶役千金的..." not in text
    # 两源各自收录、各自成条，编号 1/2 独立可订阅
    assert text.count("唯我独占恶役千金的娇羞") == 2
    assert text.count("[1]") == 1 and text.count("[2]") == 1


@pytest.mark.asyncio
async def test_round2_fanout_rescues_abbreviation(monkeypatch):
    """第一轮全是低分噪音 → Bangumi 别名探针捞出正解并置顶。"""
    plugin = _plugin(search_alias_expansion=True)
    target_alias = "我的首推是恶役大小姐（爱藏版）"
    resolution = Resolution(
        by_subject={777: [target_alias]},
        confident=True,
        best_alias_score=898.0,
    )
    monkeypatch.setattr(
        "plugin_pkg.main.resolve_aliases", AsyncMock(return_value=resolution)
    )
    plugin.client.get_sources = AsyncMock(return_value=_sources())

    async def _fake(src_id, query, page=1):
        if query == "我推恶役":
            return SearchResult(mangas=[_manga("恶役千金今天也在暗中华丽的行动着", 101)],
                                has_next_page=False)
        if query == target_alias:
            return SearchResult(mangas=[_manga("我的首推是恶役大小姐", 202)],
                                has_next_page=False)
        return SearchResult(mangas=[], has_next_page=False)

    plugin.client.search_manga = AsyncMock(side_effect=_fake)

    event = _event("/漫画 搜索 我推恶役")
    results = [msg async for msg in plugin.search_manga(event, "我推恶役")]
    text = results[0]
    assert "Bangumi 别名" in text  # 透明提示行
    assert text.index("[1] 我的首推是恶役大小姐") < text.index("恶役千金")
    assert plugin._get_cached_manga("aiocqhttp:group:g1", "1").title == "我的首推是恶役大小姐"
    probed = [c.args[1] for c in plugin.client.search_manga.await_args_list]
    assert target_alias in probed


@pytest.mark.asyncio
async def test_round2_wrong_resolution_injects_no_noise(monkeypatch):
    """解析不置信时：错误解析结果不得进入展示，也不产生提示行噪音。"""
    plugin = _plugin(search_alias_expansion=True)
    resolution = Resolution(
        by_subject={1: ["完全无关的推倒熊猫大叔"]},
        confident=False,
        best_alias_score=120.0,
    )
    monkeypatch.setattr(
        "plugin_pkg.main.resolve_aliases", AsyncMock(return_value=resolution)
    )
    plugin.client.get_sources = AsyncMock(return_value=_sources())

    async def _fake(src_id, query, page=1):
        if query == "推子":
            return SearchResult(mangas=[_manga("推倒熊猫大叔短篇集", 101)],
                                has_next_page=False)
        return SearchResult(mangas=[_manga("完全无关的推倒熊猫大叔", 999)],
                            has_next_page=False)

    plugin.client.search_manga = AsyncMock(side_effect=_fake)
    event = _event("/漫画 搜索 推子")
    results = [msg async for msg in plugin.search_manga(event, "推子")]
    text = results[0]
    assert "Bangumi" not in text  # 无扩展强命中 → 无提示行
    assert "[1] 推倒熊猫大叔短篇集" in text  # 第一轮结果原样保留
    assert "完全无关的推倒熊猫大叔" not in text  # 探针噪声未混入展示


@pytest.mark.asyncio
async def test_dirty_title_cannot_forge_result_lines():
    """R3 回归：源站标题含换行/控制符时不可伪造多行结果。"""
    plugin = _plugin()
    dirty = "正常漫画" + chr(10) + "[9] 钓鱼条目 - 已完结"
    _set_search(plugin, {"22": [_manga("我的首推是恶役大小姐", 202), _manga(dirty, 203)]})
    results = [msg async for msg in plugin.search_manga(_event(), QUERY)]
    text = results[0]
    assert "[2] [9] 钓鱼条目" not in text      # 换行不产生新行
    assert chr(10) not in text.split(chr(10))[0]  # 首行无内嵌换行残留
    assert "正常漫画" in text                    # 标题内容保留（清洗不破坏）
