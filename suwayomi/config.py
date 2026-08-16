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

旧版平铺配置迁移：`_conf_schema.json` 中保留了全部旧键（`invisible: true`，
对用户不可见），因此 AstrBot Core 的配置同步不会删除它们，用户旧值得以
保留；插件 `__init__` 中调用 `migrate_legacy_config()` 把旧值迁入分组并
置迁移标记 `_config_migrated_v1`。标记置位后不再迁移，防止 Core 补回的
无意义旧键默认值覆盖分组中的真实配置。
"""
from __future__ import annotations

from typing import Any

# 迁移标记键（_conf_schema.json 中保留，invisible）。置位后跳过迁移。
MIGRATE_FLAG_KEY = "_config_migrated_v1"

# 旧键的"无意义值"（= _conf_schema.json 中 invisible 旧键的 default，
# 与旧版平铺 schema 的默认值一致）。Core 每次加载都会给缺失的 invisible
# 键补回这些默认值，它们不代表用户设置，迁移时直接清理、不得覆盖分组。
_LEGACY_KEY_DEFAULTS: dict[str, Any] = {
    "server_url": "http://localhost:4567",
    "auth_mode": "none",
    "username": "",
    "password": "",
    "result_cards_enabled": False,
    "card_render_timeout_sec": 30,
    "max_pages": 30,
    "send_mode": "image",
    "image_fetch_mode": "download",
    "download_format": "pdf",
    "download_concurrency": 6,
    "download_retries": 3,
    "auto_push_mode": "image",
    "enable_ai_tools": True,
    "allow_ai_send": True,
    "ai_max_sources": 5,
    "ai_results_per_source": 5,
    "ai_tool_timeout_sec": 60,
    "check_interval": 60,
    "chapter_cache_hours": 6,
    "chapter_list_show_cover": True,
    "default_source_id": 0,
    "temp_dir": "",
}

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
    """把旧版平铺配置项迁移到分组结构，返回是否发生了变更（需保存）。

    `_conf_schema.json` 中保留的全部旧键（`invisible: true`）使 AstrBot
    Core 的配置同步不会删除它们，用户旧值得以保留；本函数在插件
    `__init__` 中把旧值迁入分组并删除旧键，置迁移标记后保存。规则：

    - 旧键值**等于默认值**（`_LEGACY_KEY_DEFAULTS`）：视为 Core 补回的
      无意义占位（用户从未设置过），直接清理，**不得覆盖**分组中可能
      存在的真实配置。
    - 旧键值**非默认**：用户确实设置过的旧值，迁入分组（优先于分组内
      刚被 Schema 补的默认值）。
    - 迁移标记已置位：跳过（防止 Core 补回的默认值再次污染分组）。
    """
    if config.get(MIGRATE_FLAG_KEY):
        return False
    for key in list(config):
        if key not in KEY_TO_GROUP:
            continue
        value = config[key]
        if value == _LEGACY_KEY_DEFAULTS.get(key):
            config.pop(key, None)
            continue
        set_config_value(config, key, value)
    config[MIGRATE_FLAG_KEY] = True
    return True
