"""Guards the user-facing help text for chapter selectors (no network)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_HELP_BLOCK_RE = re.compile(r'async def help_cmd.*?text = """(.*?)"""', re.S)


def _help_text() -> str:
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    match = _HELP_BLOCK_RE.search(text)
    assert match is not None, "help command text block not found"
    return match.group(1)


def test_help_mentions_all_selector_forms():
    help_text = _help_text()
    assert "📖 Suwayomi 漫画助手" in help_text
    assert "第5话" in help_text
    assert "第01卷" in help_text
    assert "章节名" in help_text
    assert "ID:123" in help_text


def test_ai_tool_selector_description_stays_id_based():
    text = (ROOT / "suwayomi" / "ai_tools.py").read_text(encoding="utf-8")
    match = re.search(r'"selector":\s*\{.*?"description":\s*"([^"]*)"', text, re.S)
    assert match is not None, "selector parameter schema not found"
    description = match.group(1)
    assert "ID:数字" in description
    assert "章节名" not in description
    assert "第01卷" not in description
