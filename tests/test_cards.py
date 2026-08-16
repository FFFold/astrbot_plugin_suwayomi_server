"""Unit tests for suwayomi/cards.py (no network)."""
import math

import pytest

from suwayomi.cards import (
    CHAPTER_LINES_PER_CARD,
    MAX_CHAPTER_CARDS,
    build_batch_card,
    build_chapter_cards,
    build_search_card,
    build_subscribe_confirm_card,
    build_update_card,
)


def _manga(title="咒术回战", status="ONGOING", thumbnail="/api/v1/manga/1/thumbnail"):
    return {"title": title, "status": status, "thumbnail_url": thumbnail}


def test_build_search_card_escapes_and_numbers_rows():
    data = build_search_card(
        [
            {"index": 1, "title": "咒术回战", "status": "ONGOING", "source": "拷贝漫画", "thumbnail_url": "/a"},
            {"index": 2, "title": "鬼灭<之刃", "status": "COMPLETED", "source": "拷贝漫画", "thumbnail_url": "/b"},
        ],
        subtitle="拷贝漫画 · 2 条",
        footer="回复「漫画 订阅 <编号>」订阅",
    )
    assert data["card_type"] == "search"
    assert data["rows"][0]["index"] == 1
    assert data["rows"][0]["detail"] == "连载中 · 拷贝漫画"
    assert data["rows"][1]["title"] == "鬼灭&lt;之刃"
    assert data["footer"] == "回复「漫画 订阅 &lt;编号&gt;」订阅"
    # thumbnail_url 原样保留供 embed_covers 使用
    assert data["rows"][0]["thumbnail_url"] == "/a"


def test_build_subscribe_confirm_card():
    data = build_subscribe_confirm_card(
        {"title": "鬼灭之刃", "status": "COMPLETED", "thumbnail_url": "/c"},
        source_name="拷贝漫画",
        footer="有新章节时会推送通知",
    )
    assert data["card_type"] == "confirm"
    assert data["title"] == "鬼灭之刃"
    assert data["status"] == "已完结"
    assert data["status_class"] == "status-completed"
    assert "ID" in data["meta"] and "拷贝漫画" in data["meta"]


def test_build_update_card_multi():
    data = build_update_card(
        [
            {"title": "咒术回战", "status": "ONGOING", "chapters": ["#251 新的一页", "#252 决战"],
             "read_hint": "「漫画 阅读 咒术回战 252」", "thumbnail_url": "/d"},
            {"title": "鬼灭之刃", "status": "COMPLETED", "chapters": ["#205"],
             "read_hint": "「漫画 阅读 鬼灭之刃 205」", "thumbnail_url": "/e"},
        ],
        heading="📢 2 部漫画更新了",
    )
    assert data["heading"] == "📢 2 部漫画更新了"
    assert data["items"][0]["status"] == "连载中"
    assert data["items"][1]["status_class"] == "status-completed"
    assert data["items"][0]["chapters"][0] == "#251 新的一页"


def test_build_batch_card_marks():
    data = build_batch_card(
        [
            {"status": "ok", "title": "咒术回战", "detail": "连载中 - 拷贝漫画", "thumbnail_url": "/f"},
            {"status": "exists", "title": "鬼灭之刃", "detail": "已完结 - 拷贝漫画（已订阅）", "thumbnail_url": "/g"},
            {"status": "fail", "title": "海贼王", "detail": "未找到匹配结果", "thumbnail_url": None},
        ],
        summary="1 新增, 1 已存在, 1 失败",
    )
    icons = {row["icon"] for row in data["rows"]}
    assert icons == {"✓", "⏭", "✕"}
    assert {row["mark_class"] for row in data["rows"]} == {"mark-ok", "mark-skip", "mark-fail"}
    assert data["rows"][2]["thumbnail_url"] is None


def test_build_chapter_cards_single_header_only():
    cards, tail = build_chapter_cards(
        {"title": "咒术回战", "cover_data_url": None, "meta": "拷贝漫画 · 3 话",
         "tags": ["连载中"], "hint": "「漫画 章节 咒术回战 --刷新」"},
        ["#1", "#2", "#3"],
    )
    assert len(cards) == 1
    assert tail == []
    assert cards[0]["is_continuation"] is False
    # 三列
    assert len(cards[0]["chunks"]) == 3
    assert sum(len(c) for c in cards[0]["chunks"]) == 3
    # 标题保留
    assert cards[0]["title"] == "咒术回战"


def test_build_chapter_cards_chunks_by_constant():
    lines = [f"#{i} 章" for i in range(1, CHAPTER_LINES_PER_CARD * 2 + 1)]
    cards, tail = build_chapter_cards({"title": "X", "cover_data_url": None}, lines)
    assert len(cards) == 2
    assert tail == []
    assert cards[1]["is_continuation"] is True
    assert cards[1]["continuation"] == "章节续 (2/2)"
    # 每张卡的行数不超过 per-card 常量
    for card in cards:
        total = sum(len(c) for c in card["chunks"])
        assert total <= CHAPTER_LINES_PER_CARD


def test_build_chapter_cards_tail_and_cap():
    lines = [f"#{i}" for i in range(1, CHAPTER_LINES_PER_CARD * (MAX_CHAPTER_CARDS + 1) + 10)]
    cards, tail = build_chapter_cards({"title": "X", "cover_data_url": None}, lines)
    assert len(cards) == MAX_CHAPTER_CARDS
    assert len(tail) == len(lines) - CHAPTER_LINES_PER_CARD * MAX_CHAPTER_CARDS


def test_build_chapter_cards_escapes_lines():
    lines = ["#1 章 & 节", "#2 <b>x</b>"]
    cards, tail = build_chapter_cards({"title": "X", "cover_data_url": None}, lines)
    flat = [line for col in cards[0]["chunks"] for line in col]
    assert "章 &amp; 节" in flat[0]
    assert "<b>" not in "".join(flat)
    # tail 返回原始行（用于纯文本，不转义）
    cards2, tail2 = build_chapter_cards({"title": "X", "cover_data_url": None}, ["#1 & x"] * 600)
    assert tail2 == ["#1 & x"] * (600 - CHAPTER_LINES_PER_CARD * MAX_CHAPTER_CARDS)


def test_build_chapter_cards_empty_lines_returns_header():
    cards, tail = build_chapter_cards({"title": "X", "cover_data_url": None}, [])
    assert len(cards) == 1
    assert tail == []
