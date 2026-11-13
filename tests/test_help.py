"""Guards the user-facing help text for chapter selectors (no network)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_help_mentions_all_selector_forms():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "第5话" in text
    assert "第01卷" in text
    assert "章节名" in text
    assert "列表里重号会标注 ID" in text


def test_ai_tool_selector_description_mentions_volume_and_name():
    text = (ROOT / "suwayomi" / "ai_tools.py").read_text(encoding="utf-8")
    match = re.search(r'"selector":\s*\{.*?"description":\s*"([^"]*)"', text, re.S)
    assert match is not None, "selector parameter schema not found"
    description = match.group(1)
    assert "第5话" in description
    assert "第01卷" in description
    assert "章节名" in description
