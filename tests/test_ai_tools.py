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

from suwayomi.ai_tools import build_ai_tools, effective_tool_timeout  # noqa: E402


class _Plugin:
    last_outer_timeout = None
    last_search_all_sources = False
    last_subscribe_manga_id = None

    async def _ai_search_manga_tool(
        self,
        event,
        query,
        source_hint="",
        search_all_sources=False,
        *,
        _astrbot_tool_timeout=None,
    ):
        self.last_outer_timeout = _astrbot_tool_timeout
        self.last_search_all_sources = search_all_sources
        return event, query, source_hint

    async def _ai_get_chapters_tool(
        self,
        event,
        manga_id,
        selector="latest",
        refresh=False,
        limit=20,
        *,
        _astrbot_tool_timeout=None,
    ):
        self.last_outer_timeout = _astrbot_tool_timeout
        return event, manga_id, selector, refresh, limit

    async def _ai_send_chapter_tool(
        self,
        event,
        manga_id,
        chapter_id,
        confirmed_user_intent,
        format="pdf",
        *,
        _astrbot_tool_timeout=None,
    ):
        self.last_outer_timeout = _astrbot_tool_timeout
        return event, manga_id, chapter_id, confirmed_user_intent, format

    async def _ai_subscribe_manga_tool(
        self,
        event,
        manga_id,
        confirmed_user_intent,
        push_enabled=False,
        *,
        _astrbot_tool_timeout=None,
    ):
        self.last_outer_timeout = _astrbot_tool_timeout
        self.last_subscribe_manga_id = manga_id
        return event, manga_id, confirmed_user_intent, push_enabled

    async def _ai_get_subscriptions_tool(
        self,
        event,
        *,
        _astrbot_tool_timeout=None,
    ):
        self.last_outer_timeout = _astrbot_tool_timeout
        return event, {"subscriptions": []}


@pytest.mark.asyncio
async def test_tool_call_dispatches_without_astrbot_handler_binding():
    plugin = _Plugin()
    tools = build_ai_tools(plugin)

    assert all(tool.handler is None for tool in tools)
    assert all(tool.plugin is plugin for tool in tools)
    assert tools[0].method_name == "_ai_search_manga_tool"
    assert tools[1].method_name == "_ai_get_chapters_tool"
    assert tools[2].method_name == "_ai_send_chapter_tool"
    assert tools[3].method_name == "_ai_subscribe_manga_tool"
    assert tools[4].method_name == "_ai_get_subscriptions_tool"
    assert (
        tools[0].parameters["properties"]["search_all_sources"]["default"]
        is False
    )
    assert tools[2].parameters["properties"]["format"]["default"] == "pdf"
    assert "confirmed_user_intent" in tools[3].parameters["required"]
    assert tools[3].parameters["properties"]["push_enabled"]["default"] is False
    assert tools[4].parameters.get("required", []) == []

    event = object()
    context = SimpleNamespace(context=SimpleNamespace(event=event))
    result = await tools[0].call(context, query="碧蓝之海", source_hint="zh")

    assert result == (event, "碧蓝之海", "zh")

    # Rebuilding the tools after a config save follows the same stable path.
    rebuilt = build_ai_tools(plugin)
    result = await rebuilt[0].call(context, query="ぐらんぶる", source_hint="")
    assert result == (event, "ぐらんぶる", "")


@pytest.mark.asyncio
async def test_tool_call_passes_astrbot_outer_timeout_to_plugin():
    plugin = _Plugin()
    tool = build_ai_tools(plugin)[0]
    event = object()
    context = SimpleNamespace(
        context=SimpleNamespace(event=event),
        tool_call_timeout=90,
    )

    await tool.call(context, query="碧蓝之海")

    assert plugin.last_outer_timeout == 90


def test_effective_tool_timeout_leaves_margin_inside_astrbot_budget():
    assert effective_tool_timeout(60, 120) == 60
    assert effective_tool_timeout(60, 90, preferred_minimum=110) == 85
    assert effective_tool_timeout(300, 120) == 115


@pytest.mark.asyncio
async def test_search_tool_dispatches_single_all_source_request():
    plugin = _Plugin()
    tool = build_ai_tools(plugin)[0]
    context = SimpleNamespace(context=SimpleNamespace(event=object()))

    await tool.call(context, query="碧蓝之海", search_all_sources=True)

    assert plugin.last_search_all_sources is True


@pytest.mark.asyncio
async def test_subscribe_tool_dispatches():
    plugin = _Plugin()
    tools = build_ai_tools(plugin)
    event = object()
    context = SimpleNamespace(context=SimpleNamespace(event=event))

    result = await tools[3].call(context, manga_id=53, confirmed_user_intent=True)

    assert result == (event, 53, True, False)
    assert plugin.last_subscribe_manga_id == 53

    result = await tools[3].call(
        context, manga_id=99, confirmed_user_intent=True, push_enabled=True
    )
    assert result == (event, 99, True, True)


@pytest.mark.asyncio
async def test_get_subscriptions_tool_dispatches():
    plugin = _Plugin()
    tools = build_ai_tools(plugin)
    event = object()
    context = SimpleNamespace(context=SimpleNamespace(event=event))

    result = await tools[4].call(context)

    assert result == (event, {"subscriptions": []})


@pytest.mark.asyncio
async def test_tool_count():
    plugin = _Plugin()
    tools = build_ai_tools(plugin)
    assert len(tools) == 5
