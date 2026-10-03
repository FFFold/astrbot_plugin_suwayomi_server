"""Bangumi 条目解析模块测试（纯逻辑层，网络层 mock）。"""
from unittest.mock import AsyncMock, patch

import pytest
from plugin_pkg.suwayomi import bangumi
from plugin_pkg.suwayomi.bangumi import (
    Resolution,
    best_alias_score,
    confident_aliases,
    parse_search,
    alias_boost,
    build_probes,
    parse_subject,
    resolve_aliases,
)
from plugin_pkg.suwayomi.ranking import STRONG_MATCH_THRESHOLD


def test_parse_search_keeps_order_and_dedupes():
    raw = {"list": [{"id": 3}, {"id": 1}, {"id": 3}, {"id": "bad"}, {"id": 2}]}
    assert parse_search(raw) == [3, 1, 2]
    assert parse_search({}) == []
    assert parse_search(None) == []


def test_parse_subject_names_and_aliases():
    raw = {
        "name": "転生王女と天才令嬢の魔法革命",
        "name_cn": "转生王女与天才千金的魔法革命",
        "infobox": [
            {"key": "中文名", "value": "x"},
            {"key": "别名", "value": [{"v": "転天"}, {"v": "MagiRevo"}, "転天革命"]},
        ],
    }
    names = parse_subject(raw)
    assert names[0] == "转生王女与天才千金的魔法革命"
    assert "転天" in names and "転天革命" in names and "MagiRevo" in names


def _resolution():
    return Resolution(
        by_subject={
            311834: [
                "转生王女与天才千金的魔法革命",
                "転生王女と天才令嬢の魔法革命",
                "転天",
                "MagiRevo",
            ],
            490753: [
                "无力圣女与无能王女～魔力值零却被召唤的圣女异世界救国记～",
                "无用圣女与无能王女～被召唤至异世界的零魔力圣女救国纪～",
            ],
        }
    )


def test_confidence_via_jp_alias_equality():
    r = _resolution()
    r.best_alias_score = best_alias_score("转天", r)
    assert r.best_alias_score == 1000.0  # 転天 归一化后与 转天 相等
    r.confident = True
    assert "転天" in confident_aliases("转天", r)  # 全名因子序列也过线，但 転天 必在列


@pytest.mark.asyncio
async def test_resolve_aliases_network_failure_returns_none():
    with patch.object(bangumi, "_get_json", AsyncMock(side_effect=Exception("boom"))):
        assert await resolve_aliases("转天") is None


@pytest.mark.asyncio
async def test_resolve_aliases_jp_retry_used_when_first_round_weak():
    """第一轮弱命中 → 用日文字形变体再搜一次。"""
    search_responses = {
        "https://api.bgm.tv/search/subject/%E8%BD%AC%E5%A4%A9?type=1&max_results=8": {"list": []},
        "https://api.bgm.tv/search/subject/%E8%BB%A2%E5%A4%A9?type=1&max_results=8": {"list": [{"id": 311834}]},
    }
    subject_response = {
        "name": "転生王女と天才令嬢の魔法革命",
        "name_cn": "转生王女与天才千金的魔法革命",
        "infobox": [{"key": "别名", "value": [{"v": "転天"}]}],
    }

    async def fake_get_json(session, url):
        if url in search_responses:
            return search_responses[url]
        return subject_response

    with patch.object(bangumi, "_get_json", side_effect=fake_get_json):
        resolution = await resolve_aliases("转天")
    assert resolution is not None
    assert 311834 in resolution.by_subject
    assert resolution.confident
    assert resolution.best_alias_score == 1000.0


@pytest.mark.asyncio
async def test_resolve_aliases_skips_jp_retry_when_confident():
    calls = []

    async def fake_get_json(session, url):
        calls.append(url)
        if "/v0/subjects/" in url:
            return {
                "name": "我的首推是恶役大小姐",
                "name_cn": "我的首推是恶役大小姐",
                "infobox": [],
            }
        return {"list": [{"id": 1}]}

    with patch.object(bangumi, "_get_json", side_effect=fake_get_json):
        resolution = await resolve_aliases("我的首推是恶役大小姐")
    assert resolution.confident
    search_calls = [u for u in calls if "search/subject" in u]
    assert len(search_calls) == 1  # 置信则不做日文重试


def test_build_probes_filters_and_ranks():
    r = _resolution()
    probes = build_probes("转天", r, max_probes=3)
    names = [p for p, _ in probes]
    # 英文名被汉字占比过滤；与 query 归一化相同的别名被排除
    assert "MagiRevo" not in names
    assert "転天" not in names
    # 长别名贡献首段（「转生王女与…」→「转生王女」）
    assert any("转生王女" in p for p in names)
    assert len(probes) <= 3


def test_build_probes_excludes_query_normalized():
    r = Resolution(by_subject={1: ["我的首推是恶役大小姐", "我的首推是恶役大小姐（番外）"]})
    probes = build_probes("我的首推是恶役大小姐", r)
    names = [p for p, _ in probes]
    assert "我的首推是恶役大小姐" not in names


def test_alias_boost_via_provenance_and_substring():
    r = _resolution()
    r.confident = True
    # ① 溯源-only 关联：结果自身 B''≈846 ≥650 → 继承但封顶 849
    assert alias_boost("转天", "转生王女和天才千金的魔法革命", 311834, r) == 849.0
    # ② 子串关联：标题包含官方别名（海贼王→航海王 场景）
    r2 = Resolution(by_subject={1: ["海贼王", "航海王", "ONE PIECE"]}, confident=True)
    assert alias_boost("海贼王", "航海王 ONE PIECE 第108卷", None, r2) >= STRONG_MATCH_THRESHOLD
    # ③ 未关联的结果不增强：标题与全部别名无交集且无溯源
    r3 = Resolution(by_subject={3: ["间谍过家家", "SPY×FAMILY"]}, confident=True)
    assert alias_boost("海贼王", "航海王之外的无关作品", None, r3) == 0.0


def test_alias_boost_provenance_floor_blocks_noise():
    """溯源-only 且结果自身低分（噪声）→ 不增强。"""
    r = Resolution(
        by_subject={1: ["我推恶役"]}, confident=True, best_alias_score=1000.0
    )
    assert alias_boost("我推恶役", "恶役千金执事大人异闻录", 1, r, base_score=300.0) == 0.0
    assert alias_boost("我推恶役", "我的首推是恶役大小姐", 1, r, base_score=846.0) == 849.0


def test_alias_boost_requires_confidence():
    r = Resolution(by_subject={1: ["海贼王", "航海王"]}, confident=False)
    assert alias_boost("海贼王", "航海王", 1, r) == 0.0


def test_api_bases_priority_chain():
    from plugin_pkg.suwayomi.bangumi import (
        BUILTIN_MIRROR_BASES, OFFICIAL_API_BASE, api_bases,
    )
    assert api_bases(False, "") == [OFFICIAL_API_BASE]
    assert api_bases(False, "https://x.example") == [OFFICIAL_API_BASE]
    assert api_bases(True, "https://my.mirror/") == ["https://my.mirror"]
    assert api_bases(True, "") == BUILTIN_MIRROR_BASES


@pytest.mark.asyncio
async def test_resolve_falls_back_to_next_base():
    """第一个端点网络失败 → 自动尝试第二个内置镜像。"""
    calls = []

    async def fake_get_json(session, url):
        calls.append(url)
        if "api.bangumi.vip" in url and "/search/" in url:
            raise Exception("mirror1 down")
        if "/search/" in url:
            return {"list": [{"id": 311834}]}
        return {"name": "転生王女と天才令嬢の魔法革命", "name_cn": "转生王女与天才千金的魔法革命",
                "infobox": [{"key": "别名", "value": [{"v": "転天"}]}]}

    from plugin_pkg.suwayomi import bangumi as bm
    with patch.object(bm, "_get_json", side_effect=fake_get_json):
        resolution = await bm.resolve_aliases(
            "转天", bases=bm.api_bases(True, "")
        )
    assert resolution is not None and 311834 in resolution.by_subject
    searched = [u for u in calls if "/search/" in u]
    assert any("api.bangumi.vip" in u for u in searched)
    assert any("bgmapi.anibt.net" in u for u in searched)


@pytest.mark.asyncio
async def test_resolve_all_bases_down_returns_none():
    from plugin_pkg.suwayomi import bangumi as bm
    with patch.object(bm, "_get_json", AsyncMock(side_effect=Exception("all down"))):
        assert await bm.resolve_aliases("转天", bases=bm.api_bases(True, "")) is None


def test_keyword_slash_and_plus_are_quoted():
    """含 / 与 + 的关键词不再破坏 URL 路径。"""
    from plugin_pkg.suwayomi.bangumi import _quote_keyword
    q = _quote_keyword("海贼王/航海王")
    assert "/" not in q
    assert _quote_keyword("间谍+过家家") == "%E9%97%B4%E8%B0%8D%20%E8%BF%87%E5%AE%B6%E5%AE%B6"


def test_alias_boost_short_alias_poisoning_blocked():
    """R2 回归：社区向条目追加高频短字（如「王」）不得借子串关联操纵排序。"""
    r = Resolution(
        by_subject={1: ["海贼王", "航海王", "王"]}, confident=True, best_alias_score=1000.0
    )
    # 含「王」的无关结果不因短字子串关联获得增强（「王」被长度门槛过滤）
    assert alias_boost("海贼王", "斗破苍穹之王者归来", None, r) == 0.0
    # 长别名「航海王」仍是合法子串关联，但继承分封顶 949（非 1000）
    assert alias_boost("海贼王", "航海王 ONE PIECE", None, r) == 949.0


@pytest.mark.asyncio
async def test_deadline_budget_shared_across_bases():
    """R5 回归：hang 型故障下回退链仍能在共享预算内走到后续端点。

    基1 每请求都挂满超时（慢挂而非快败），共享预算保证基2 仍获
    得可用时间片并成功返回。
    """
    import asyncio as _asyncio

    async def hang_then_fail(session, url):
        await _asyncio.sleep(0.5)  # 模拟慢挂（测试用短超时放大）
        raise Exception("slow hang")

    async def ok(session, url):
        if "/search/" in url:
            return {"list": [{"id": 311834}]}
        return {"name": "転生王女と天才令嬢の魔法革命",
                "name_cn": "转生王女与天才千金的魔法革命",
                "infobox": [{"key": "别名", "value": [{"v": "転天"}]}]}

    side = [hang_then_fail, ok]  # 基1 全部慢挂，基2 正常
    calls = {"n": 0}

    async def routed(session, url):
        idx = 0 if "api.bangumi.vip" in url else 1
        return await side[idx](session, url)

    from plugin_pkg.suwayomi import bangumi as bm
    with patch.object(bm, "_get_json", side_effect=routed):
        resolution = await bm.resolve_aliases(
            "转天", bases=bm.api_bases(True, ""), deadline=0.75, timeout=0.3
        )
    assert resolution is not None and 311834 in resolution.by_subject


@pytest.mark.asyncio
async def test_deadline_zero_skips_all_requests():
    """deadline=0（预算耗尽）应立即放弃，不发任何请求（而非回落默认超时）。"""
    calls = {"n": 0}

    async def counting(session, url):
        calls["n"] += 1
        return {}

    from plugin_pkg.suwayomi import bangumi as bm
    with patch.object(bm, "_get_json", side_effect=counting):
        assert await bm.resolve_aliases(
            "转天", bases=bm.api_bases(True, ""), deadline=0
        ) is None
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_deadline_caps_endpoint_wall_clock():
    """端点内多阶段的墙钟总和不得超过其切片（详情阶段的慢滴被截断）。"""
    import asyncio as _asyncio
    import time as _time

    async def search_ok_subjects_slow(session, url):
        if "/search/" in url:
            return {"list": [{"id": 311834}]}
        await _asyncio.sleep(0.5)  # 慢滴：短于任何单请求超时，但超出端点切片
        return {"name": "x", "name_cn": "转天"}

    from plugin_pkg.suwayomi import bangumi as bm
    with patch.object(bm, "_get_json", side_effect=search_ok_subjects_slow):
        t0 = _time.monotonic()
        resolution = await bm.resolve_aliases(
            "转天", bases=[bm.OFFICIAL_API_BASE], deadline=0.25, timeout=8
        )
        elapsed = _time.monotonic() - t0
    assert resolution is None
    assert elapsed < 0.45


@pytest.mark.asyncio
async def test_deadline_leftover_budget_reaches_next_base():
    """基1 慢滴烧完自己的切片后，剩余预算仍归基2 使用。"""
    import asyncio as _asyncio

    async def base1_slow(session, url):
        await _asyncio.sleep(0.3)  # 超出其切片 0.2
        return {}

    async def base2_ok(session, url):
        if "/search/" in url:
            return {"list": [{"id": 42}]}
        return {"name": "転天", "name_cn": "转天"}

    async def routed(session, url):
        return await (base1_slow if "a.example" in url else base2_ok)(session, url)

    from plugin_pkg.suwayomi import bangumi as bm
    with patch.object(bm, "_get_json", side_effect=routed):
        resolution = await bm.resolve_aliases(
            "转天", bases=["https://a.example", "https://b.example"],
            deadline=0.4, timeout=8,
        )
    assert resolution is not None and 42 in resolution.by_subject
