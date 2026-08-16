"""Grouped config schema helpers.

配置项按功能分组存储（与 WebUI 设置页、_conf_schema.json 的分组一致）：

- `server`: 服务器连接（server_url / auth_mode / username / password）
- `cards`: 卡片渲染（result_cards_enabled / card_render_timeout_sec）
- `reading`: 阅读体验（max_pages / send_mode / image_fetch_mode）
- `pack`: 下载打包（download_format / download_concurrency / download_retries）
- `push`: 自动推送（auto_push_mode）
- `ai`: AI 漫画工具（enable_ai_tools / allow_ai_send / ai_max_sources / ...）
- `advanced`: 高级（check_interval / chapter_cache_hours / temp_dir 等）

所有读取统一走 `get_config_value()`，写入统一走 `set_config_value()`，
两者均兼容旧版平铺结构（旧键存在于顶层时按旧键读取/写入）。
旧版配置在插件加载时由 `migrate_legacy_config()` 迁移为分组结构。
"""
from __future__ import annotations

from typing import Any

CONFIG_GROUPS: dict[str, list[str]] = {
    "server": ["server_url", "auth_mode", "username", "password"],
    "cards": ["result_cards_enabled", "card_render_timeout_sec"],
    "reading": ["max_pages", "send_mode", "image_fetch_mode"],
    "pack": ["download_format", "download_concurrency", "download_retries"],
    "push": ["auto_push_mode"],
    "ai": [
        "enable_ai_tools",
        "allow_ai_send",
        "ai_max_sources",
        "ai_results_per_source",
        "ai_tool_timeout_sec",
    ],
    "advanced": [
        "check_interval",
        "chapter_cache_hours",
        "chapter_list_show_cover",
        "default_source_id",
        "temp_dir",
    ],
}

KEY_TO_GROUP: dict[str, str] = {
    key: group for group, keys in CONFIG_GROUPS.items() for key in keys
}


def get_config_value(config: dict, key: str, default: Any = None) -> Any:
    """读取配置项，优先读分组，回退到旧版平铺键。"""
    group = KEY_TO_GROUP.get(key)
    if group is not None:
        section = config.get(group)
        if isinstance(section, dict) and key in section:
            return section[key]
    return config.get(key, default)


def set_config_value(config: dict, key: str, value: Any) -> None:
    """写入配置项到所属分组，同时清理旧版平铺键。"""
    group = KEY_TO_GROUP.get(key)
    if group is None:
        return
    section = config.get(group)
    if not isinstance(section, dict):
        section = {}
        config[group] = section
    section[key] = value
    config.pop(key, None)


def flatten_config(config: dict, keys: list[str]) -> dict:
    """将分组配置展开为仅含指定键的平铺 dict（旧版平铺键同样收集）。"""
    flat: dict = {}
    for key in keys:
        group = KEY_TO_GROUP.get(key)
        if group is not None:
            section = config.get(group)
            if isinstance(section, dict) and key in section:
                flat[key] = section[key]
                continue
        if key in config:
            flat[key] = config[key]
    return flat


def migrate_legacy_config(config: dict) -> bool:
    """把旧版平铺配置项迁移到分组结构，返回是否有变更。

    顶层旧值优先于分组内已有值（分组内可能已被 Schema 更新补为默认值），
    迁移完成后删除顶层旧键。
    """
    legacy = [key for key in list(config) if key in KEY_TO_GROUP]
    if not legacy:
        return False
    for key in legacy:
        set_config_value(config, key, config[key])
    return True
