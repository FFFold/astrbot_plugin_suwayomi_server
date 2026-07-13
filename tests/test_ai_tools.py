"""Regression tests for AstrBot's plugin-instance binding of FunctionTool handlers."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from pydantic.dataclasses import dataclass


@dataclass
class _FakeFunctionTool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Any] | None = None
    handler_module_path: str | None = None

    async def call(self, context, **kwargs):
        raise NotImplementedError


tool_module = types.ModuleType("astrbot.core.agent.tool")
tool_module.FunctionTool = _FakeFunctionTool
sys.modules.setdefault("astrbot.core", types.ModuleType("astrbot.core"))
sys.modules.setdefault("astrbot.core.agent", types.ModuleType("astrbot.core.agent"))
sys.modules["astrbot.core.agent.tool"] = tool_module

from suwayomi.ai_tools import build_ai_tools  # noqa: E402


class _Plugin:
    async def _ai_search_manga_tool(self, event, query, source_hint=""):
        return event, query, source_hint

    async def _ai_get_chapters_tool(
        self, event, manga_id, selector="latest", refresh=False, limit=20
    ):
        return event, manga_id, selector, refresh, limit

    async def _ai_send_chapter_tool(
        self, event, manga_id, chapter_id, confirmed_user_intent, format="pdf"
    ):
        return event, manga_id, chapter_id, confirmed_user_intent, format


@pytest.mark.asyncio
async def test_tool_call_dispatches_without_astrbot_handler_binding():
    plugin = _Plugin()
    tools = build_ai_tools(plugin)

    assert all(tool.handler is None for tool in tools)
    assert all(tool.plugin is plugin for tool in tools)
    assert tools[0].method_name == "_ai_search_manga_tool"
    assert tools[1].method_name == "_ai_get_chapters_tool"
    assert tools[2].method_name == "_ai_send_chapter_tool"
    assert tools[2].parameters["properties"]["format"]["default"] == "pdf"

    event = object()
    context = SimpleNamespace(context=SimpleNamespace(event=event))
    result = await tools[0].call(context, query="碧蓝之海", source_hint="zh")

    assert result == (event, "碧蓝之海", "zh")

    # Rebuilding the tools after a config save follows the same stable path.
    rebuilt = build_ai_tools(plugin)
    result = await rebuilt[0].call(context, query="ぐらんぶる", source_hint="")
    assert result == (event, "ぐらんぶる", "")
