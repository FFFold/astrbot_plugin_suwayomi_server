"""Ranking scorer tests — 覆盖设计文档中的全部证据等级与真实案例。"""
from plugin_pkg.suwayomi.ranking import (
    STRONG_MATCH_THRESHOLD,
    jp_variant,
    looks_truncated,
    normalize_for_rank,
    rank_items,
    score_title,
)

QUERY = "我的首推是恶役大小姐"


def test_equality_gets_max():
    assert score_title(QUERY, QUERY) == 1000.0


def test_normalization_variants_equal():
    # 繁简 / 全半角+大小写 / 空白与加号 / 日文字形
    assert score_title(QUERY, "我的首推是惡役大小姐") == 1000.0
    assert score_title("one piece", "ONE PIECE") == 1000.0
    assert score_title("海贼王one+piece", "海贼王 ONE PIECE") == 1000.0
    assert score_title("转天", "転天") == 1000.0
    # 日文新字体汉字被转换，假名保留
    assert normalize_for_rank("転生王女と天才令嬢の魔法革命") == "转生王女と天才令娘の魔法革命"


def test_forward_containment_orders_by_extra_length():
    spinoff = score_title(QUERY, "我的首推是恶役大小姐（番外）")
    bloated = score_title(QUERY, "我的首推是恶役大小姐与执事大人的超长日常物语外传")
    assert 850 <= spinoff < 900
    assert bloated < spinoff


def test_reverse_containment_truncated_title():
    # 源站截断标题：覆盖 7/10 → 880 - 9 = 871
    assert score_title(QUERY, "我的首推是恶役...") == 880.0 - 3.0 * 3


def test_reverse_containment_requires_solid_coverage():
    # 短标题且覆盖不足 60% → 不得进入 B' 级（2 字标题只覆盖关键词 2/10）
    assert score_title(QUERY, "我的") < STRONG_MATCH_THRESHOLD
    assert score_title(QUERY, "我的首推") < STRONG_MATCH_THRESHOLD  # 4/10=40%


def test_short_title_does_not_outrank_subsequence_match():
    # 回归：搜「派对孔明」时 2 字标题《派对》恰好覆盖 50%，不得凭反向包含
    # 压过对正解《派对浪客诸葛孔明》的子序列匹配（真实源站数据评测发现）
    assert score_title("派对孔明", "派对浪客诸葛孔明") > score_title("派对孔明", "派对")


def test_subsequence_abbreviation_cases():
    full = "我的首推是恶役大小姐"
    assert score_title("我推恶役", full) >= 840.0
    assert score_title("转天", "转生王女和天才千金的魔法革命") >= 800.0
    assert score_title("无用无能", "无用圣女与无能王女") >= 840.0


def test_subsequence_beats_partial_noise():
    q = "我推恶役"
    target = score_title(q, "我的首推是恶役大小姐")
    noise = score_title(q, "恶役大小姐的执事大人")
    assert target >= STRONG_MATCH_THRESHOLD > noise


def test_unrelated_popular_title_stays_partial():
    # 「我推的孩子」缺 恶/役 二字 → 不构成子序列 → C 级
    assert score_title("我推恶役", "我推的孩子") < STRONG_MATCH_THRESHOLD


def test_partial_band_for_fuzzy_results():
    s = score_title(QUERY, "恶役大小姐的执执事大人")
    assert 250 <= s < STRONG_MATCH_THRESHOLD


def test_multi_token_containment():
    s = score_title("间谍 过家家", "间谍与过家家日常")
    assert s >= 850.0
    s2 = score_title("间谍+过家家", "某间谍过家家")
    assert s2 >= 850.0


def test_empty_inputs_are_safe():
    assert score_title("", "标题") == 0.0
    assert score_title("关键词", "") == 0.0
    assert score_title("...", "...") == 0.0


def test_rank_items_stable_for_equal_scores():
    items = ["甲作品", "乙作品", "丙作品"]
    ranked, scores = rank_items("完全不相关的关键词xyz", items, title_of=lambda x: x)
    assert ranked == items  # 同分保持原顺序
    assert scores == [scores[0]] * 3


def test_rank_items_orders_real_case():
    items = [
        "恶役大小姐的执事大人",
        "我的首推是恶役大小姐",
        "我的首推是恶役大小姐（番外）",
        "异世界美食之旅",
    ]
    ranked, scores = rank_items(QUERY, items, title_of=lambda x: x)
    assert ranked[0] == "我的首推是恶役大小姐"
    assert ranked[1] == "我的首推是恶役大小姐（番外）"
    assert scores[0] == 1000.0
    assert scores == sorted(scores, reverse=True)


def test_looks_truncated():
    assert looks_truncated("我的首推是恶役...")
    assert looks_truncated("我的首推是恶役…")
    assert looks_truncated("完。。")
    assert not looks_truncated("我的首推是恶役大小姐")
    assert not looks_truncated("")
    assert not looks_truncated("第3话.")


def test_jp_variant():
    assert jp_variant("转天") == "転天"
    assert jp_variant("我的首推") == "我的首推"  # 无差异字符时原样返回


def test_jp_variants_dictionary_covers_builtin_misses():
    """PR #21 评审：opencc JPVariants.txt 动态构建补全内置小表缺口。

    「戦争」此前归一化后仍不等于「战争」（戦 不在内置表中），
    动态表覆盖全部 365 组繁→日变体后应满分相等。
    """
    assert score_title("战争", "戦争") == 1000.0
    assert normalize_for_rank("悪") == normalize_for_rank("恶")
    assert normalize_for_rank("亜") == normalize_for_rank("亚")
    assert normalize_for_rank("円") == normalize_for_rank("圆")


def test_jp_kokuji_and_rare_shinjitai_covered():
    """PR #21 复审：JPVariants 未收录的 頬/艶/働 由内置小表兜底。"""
    assert score_title("颊", "頬") == 1000.0
    assert score_title("艳", "艶") == 1000.0
    assert score_title("劳动", "労働") == 1000.0


def test_normalize_falls_back_to_builtin_table_when_dictionary_missing(monkeypatch):
    """JPVariants.txt 不可用时整体回落内置小表（転→转 仍生效，优雅退化）。"""
    from plugin_pkg.suwayomi import ranking

    monkeypatch.setattr(ranking, "_JP_TO_TRAD", None)
    monkeypatch.setattr(ranking, "_TRAD_TO_JP", None)
    monkeypatch.setattr(ranking, "_s2t", None)
    monkeypatch.setattr(ranking, "_JP_EXTRA_TO_CN", ranking._JP_TO_CN)
    ranking._normalize_cached.cache_clear()
    try:
        assert normalize_for_rank("転天") == normalize_for_rank("转天")
        assert jp_variant("转天") == "転天"
    finally:
        ranking._normalize_cached.cache_clear()
