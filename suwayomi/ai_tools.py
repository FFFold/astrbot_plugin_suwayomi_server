from __future__ import annotations

from typing import Any

from astrbot.core.agent.tool import FunctionTool
from pydantic.dataclasses import dataclass


AI_TOOL_NAMES = (
    "suwayomi_search_manga",
    "suwayomi_get_chapters",
    "suwayomi_send_chapter",
)


@dataclass
class SuwayomiFunctionTool(FunctionTool):
    """A plugin-owned tool that is safe across initial load and later re-sync."""

    plugin: Any = None
    method_name: str = ""

    async def call(self, context, **kwargs):
        """Dispatch without relying on star_manager's one-time handler binding."""
        event = context.context.event
        method = getattr(self.plugin, self.method_name)
        return await method(event, **kwargs)


def build_ai_tools(plugin: Any) -> list[FunctionTool]:
    return [
        SuwayomiFunctionTool(
            name=AI_TOOL_NAMES[0],
            description=(
                "在 Suwayomi 已安装的漫画源中搜索漫画。适合用户使用简称、别名、"
                "剧情描述或模糊说法找漫画。返回稳定的 manga_id 和候选元数据；"
                "有多个合理候选时必须先询问用户，不能直接取第一项。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "用于搜索的漫画标题或关键词；可根据用户描述推断并多次改写。",
                    },
                    "source_hint": {
                        "type": "string",
                        "description": "可选的漫画源名称、语言代码或来源提示，例如 zh、拷贝漫画。",
                        "default": "",
                    },
                },
                "required": ["query"],
            },
            handler=None,
            plugin=plugin,
            method_name="_ai_search_manga_tool",
        ),
        SuwayomiFunctionTool(
            name=AI_TOOL_NAMES[1],
            description=(
                "根据稳定 manga_id 获取漫画详情和章节。selector 可为 latest、list、"
                "章节号或 ID:数字。结果会返回稳定 chapter_id；同号章节有歧义时必须让用户确认。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "manga_id": {
                        "type": "integer",
                        "description": "suwayomi_search_manga 返回的漫画 ID。",
                    },
                    "selector": {
                        "type": "string",
                        "description": "latest、list、章节号（如 38.5）或 ID:123。",
                        "default": "latest",
                    },
                    "refresh": {
                        "type": "boolean",
                        "description": "是否绕过章节缓存从漫画源刷新；只有用户明确要求最新数据时设为 true。",
                        "default": False,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "selector=list 时最多返回的章节数，范围 1-50。",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 20,
                    },
                },
                "required": ["manga_id"],
            },
            handler=None,
            plugin=plugin,
            method_name="_ai_get_chapters_tool",
        ),
        SuwayomiFunctionTool(
            name=AI_TOOL_NAMES[2],
            description=(
                "把已经通过 suwayomi_get_chapters 明确选定的章节发送到当前聊天。"
                "默认打包为 PDF 文件；如果用户明确指定 ZIP、CBZ 或图片，则通过 format 服从用户。"
                "这是有副作用的工具：仅当用户在当前对话中明确要求看、阅读或发送漫画时调用；"
                "只是在查找或询问时禁止调用。同一回合成功后不得重复调用。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "manga_id": {
                        "type": "integer",
                        "description": "suwayomi_get_chapters 结果中的漫画 ID。",
                    },
                    "chapter_id": {
                        "type": "integer",
                        "description": "suwayomi_get_chapters 结果中的明确章节 ID。",
                    },
                    "confirmed_user_intent": {
                        "type": "boolean",
                        "description": "仅当用户明确要求阅读或发送该章节时为 true。",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["pdf", "zip", "cbz", "image"],
                        "description": "发送格式。默认 pdf；仅在用户明确指定其他格式时改用 zip、cbz 或 image。",
                        "default": "pdf",
                    },
                },
                "required": ["manga_id", "chapter_id", "confirmed_user_intent"],
            },
            handler=None,
            plugin=plugin,
            method_name="_ai_send_chapter_tool",
        ),
    ]
