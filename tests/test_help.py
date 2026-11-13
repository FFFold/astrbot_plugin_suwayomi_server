"""Guards the user-facing help text for chapter selectors (no network)."""

from pathlib import Path


def test_help_mentions_all_selector_forms():
    text = Path("main.py").read_text(encoding="utf-8")
    assert "第5话" in text
    assert "第01卷" in text
    assert "章节名" in text
    assert "列表里重号会标注 ID" in text


def test_ai_tool_selector_description_mentions_volume_and_name():
    text = Path("suwayomi/ai_tools.py").read_text(encoding="utf-8")
    assert "第5话" in text
    assert "第01卷" in text
    assert "章节名" in text
