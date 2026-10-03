"""WebUI API handlers for Suwayomi plugin.

All handlers are standalone async functions that receive dependencies as parameters.
This keeps main.py clean and makes handlers independently testable.

Handlers return:
  - dict on success (HTTP 200)
  - (dict, int) tuple on error, where int is the HTTP status code
"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from astrbot.api import logger

try:
    from ..suwayomi.config import flatten_config, set_config_value
except ImportError:
    # 真正以包内模块导入（__package__ 含至少两级，如 astrbot_suwayomi_server.web）
    # 时，相对导入失败意味着 suwayomi.config 内部出错，不应掩盖；
    # 测试把 web 当作顶层包导入时层级不足，回退绝对导入。
    if __package__ and __package__.count(".") >= 1:
        raise
    from suwayomi.config import flatten_config, set_config_value

PLUGIN_NAME = "astrbot_plugin_suwayomi_server"

# Whitelist of known config keys — shared by api_config_get and api_config_post
ALLOWED_CONFIG_KEYS = {
    "server_url", "auth_mode", "username", "password",
    "result_cards_enabled", "card_render_timeout_sec",
    "t2i_source", "t2i_endpoint",
    "check_interval", "max_pages", "send_mode", "image_fetch_mode",
    "download_concurrency", "download_retries", "default_source_id",
    "chapter_cache_hours", "chapter_list_show_cover", "download_format",
    "temp_dir", "auto_push_mode",
    "enable_ai_tools", "allow_ai_send", "ai_max_sources",
    "ai_results_per_source", "ai_tool_timeout_sec",
    "search_result_ranking", "search_display_limit",
    "search_refresh_truncated_titles", "search_alias_expansion",
    "bangumi_mirror", "bangumi_mirror_url",
    "file_delivery_max_pages",
}

# Numeric config keys with their minimum allowed values
NUMERIC_CONFIG_KEYS = {
    "check_interval": 1,
    "max_pages": 1,
    "download_concurrency": 1,
    "download_retries": 0,
    "default_source_id": 0,
    "chapter_cache_hours": -1,
    "card_render_timeout_sec": 5,
    "ai_max_sources": 1,
    "ai_results_per_source": 1,
    "ai_tool_timeout_sec": 10,
    "search_display_limit": 1,
    "file_delivery_max_pages": 1,
}

MAX_NUMERIC_CONFIG_KEYS = {
    "card_render_timeout_sec": 120,
    "ai_max_sources": 10,
    "ai_results_per_source": 20,
    "ai_tool_timeout_sec": 300,
    "search_display_limit": 50,
    "file_delivery_max_pages": 2000,
}

BOOLEAN_CONFIG_KEYS = {
    "enable_ai_tools", "allow_ai_send",
    "result_cards_enabled", "chapter_list_show_cover",
    "search_result_ranking", "search_refresh_truncated_titles",
    "search_alias_expansion", "bangumi_mirror",
}

ENUM_CONFIG_KEYS = {
    "send_mode": {"image", "forward"},
    "image_fetch_mode": {"url", "download"},
    "auto_push_mode": {"image", "file"},
    "download_format": {"zip", "pdf", "cbz"},
    "t2i_source": {"system", "custom"},
    "auth_mode": {"none", "basic", "jwt"},
}

# Free-form string keys: non-string payloads (JSON numbers/objects) are dropped
# instead of being stored, so downstream helpers never see unexpected types.
STRING_CONFIG_KEYS = {
    "t2i_endpoint",
    "username",
    "password",
    "temp_dir",
    "bangumi_mirror_url",
}


async def api_status(
    client: Any,
    sub_mgr: Any,
    get_kv_data: Callable[[str, Any], Awaitable[Any]],
) -> dict:
    """GET /status — 服务器状态摘要"""
    connected = False
    source_count = 0
    library_count = 0
    subscription_count = 0
    subscriber_total = 0

    try:
        sources = await client.get_sources()
        source_count = len(sources)
        connected = True
    except Exception as e:
        logger.warning(f"[{PLUGIN_NAME}] api_status: get_sources() 失败: {e}")

    try:
        mangas = await client.get_library_mangas()
        library_count = len(mangas)
    except Exception as e:
        logger.warning(f"[{PLUGIN_NAME}] api_status: get_library_mangas() 失败: {e}")

    try:
        all_subs = await sub_mgr.get_all_subscriptions()
        subscription_count = len(all_subs)
        for info in all_subs.values():
            subscriber_total += len(info.get("subscribers", {}))
    except Exception as e:
        logger.warning(f"[{PLUGIN_NAME}] api_status: get_all_subscriptions() 失败: {e}")

    last_ts = await get_kv_data("suwayomi_last_update_check", 0)

    return {
        "connected": connected,
        "source_count": source_count,
        "library_count": library_count,
        "subscription_count": subscription_count,
        "subscriber_total": subscriber_total,
        "last_update_check": last_ts,
    }


async def api_subscriptions(
    client: Any,
    sub_mgr: Any,
) -> dict:
    """GET /subscriptions — 全部订阅列表（跨所有用户）"""
    all_subs = await sub_mgr.get_all_subscriptions()

    source_map: dict[str, str] = {}
    try:
        sources = await client.get_sources()
        source_map = {str(s.id): s.display_name for s in sources}
    except Exception:
        pass

    result = []
    for manga_id_str, info in all_subs.items():
        try:
            manga_id = int(manga_id_str)
        except (TypeError, ValueError):
            # 与更新引擎一致：外部损坏的非数字键跳过而非让整个列表 500
            logger.debug(
                f"[{PLUGIN_NAME}] 订阅列表跳过损坏的非数字键 {manga_id_str!r}"
            )
            continue
        source_id = info.get("source_id", 0)
        subscribers = info.get("subscribers", {})
        push_enabled_count = sum(
            1 for s in subscribers.values() if s.get("push_enabled")
        )
        result.append({
            "manga_id": manga_id,
            "title": info.get("title", f"ID:{manga_id}"),
            "source_id": source_id,
            "source_name": source_map.get(str(source_id), f"源{source_id}"),
            "latest_chapter_id": info.get("latest_chapter_id", 0),
            "subscribers": subscribers,
            "subscriber_count": len(subscribers),
            "push_enabled_count": push_enabled_count,
        })

    return {"subscriptions": result}


async def api_subscription_delete(
    sub_mgr: Any,
    data: dict,
) -> dict | tuple[dict, int]:
    """POST /subscription/delete — 删除订阅者"""
    manga_id = data.get("manga_id")
    umo = data.get("umo")

    if manga_id is None:
        return {"success": False, "message": "缺少 manga_id"}, 400

    try:
        manga_id = int(manga_id)
    except (ValueError, TypeError):
        return {"success": False, "message": "manga_id 必须是有效的整数"}, 400

    try:
        if umo:
            await sub_mgr.unsubscribe(manga_id, umo)
        else:
            await sub_mgr.delete_manga(manga_id)
        return {"success": True}
    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] api_subscription_delete error: {e}")
        return {"success": False, "message": str(e)}, 500


async def api_subscription_push(
    sub_mgr: Any,
    data: dict,
) -> dict | tuple[dict, int]:
    """POST /subscription/push — 切换自动推送开关"""
    manga_id = data.get("manga_id")
    umo = data.get("umo")
    enabled = data.get("enabled")

    if manga_id is None or umo is None or enabled is None:
        return {"success": False, "message": "缺少参数"}, 400

    try:
        manga_id = int(manga_id)
    except (ValueError, TypeError):
        return {"success": False, "message": "manga_id 必须是有效的整数"}, 400

    try:
        await sub_mgr.set_auto_push(manga_id, umo, bool(enabled))
        return {"success": True}
    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] api_subscription_push error: {e}")
        return {"success": False, "message": str(e)}, 500


def api_config_get(config: Any) -> dict:
    """GET /config — 读取当前插件配置，仅返回白名单字段，掩码敏感字段"""
    cfg = flatten_config(config, sorted(ALLOWED_CONFIG_KEYS))
    if cfg.get("password"):
        cfg["password"] = "***"
    return cfg


async def api_config_post(
    config: Any,
    data: dict,
    rebuild_client: Callable[[Any], Awaitable[None]],
) -> dict | tuple[dict, int]:
    """POST /config — 保存插件配置"""
    if not data:
        return {"success": False, "message": "请求体为空"}, 400

    raw_server_url = data.get("server_url", "")
    if not isinstance(raw_server_url, str):
        return {"success": False, "message": "服务器地址必须是字符串"}, 400
    server_url = raw_server_url.strip()
    if not server_url:
        return {"success": False, "message": "服务器地址不能为空"}, 400

    # Whitelist of known config keys to prevent overwriting internal attributes
    allowed_keys = ALLOWED_CONFIG_KEYS

    for key, value in data.items():
        if key not in allowed_keys:
            continue
        # Skip masked password from GET response
        if key == "password" and value == "***":
            continue
        # Validate and coerce numeric fields
        if key in NUMERIC_CONFIG_KEYS:
            try:
                value = int(value)
                if value < NUMERIC_CONFIG_KEYS[key]:
                    value = NUMERIC_CONFIG_KEYS[key]
                if key in MAX_NUMERIC_CONFIG_KEYS:
                    value = min(value, MAX_NUMERIC_CONFIG_KEYS[key])
            except (ValueError, TypeError):
                logger.debug(
                    f"[{PLUGIN_NAME}] 配置 {key} 数值非法，忽略: {value!r}"
                )
                continue
        if key in BOOLEAN_CONFIG_KEYS:
            if isinstance(value, str):
                value = value.strip().lower() in {"1", "true", "yes", "on"}
            else:
                value = bool(value)
        if key in ENUM_CONFIG_KEYS:
            if not isinstance(value, str) or value not in ENUM_CONFIG_KEYS[key]:
                logger.debug(
                    f"[{PLUGIN_NAME}] 配置 {key} 枚举值非法，忽略: {value!r}"
                )
                continue
        if key in STRING_CONFIG_KEYS and not isinstance(value, str):
            logger.debug(
                f"[{PLUGIN_NAME}] 配置 {key} 应为字符串，忽略: {value!r}"
            )
            continue
        set_config_value(config, key, value)

    try:
        config.save_config()
    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] config save error: {e}")
        return {"success": False, "message": f"保存失败: {e}"}, 500

    try:
        await rebuild_client(config)
    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] client rebuild error: {e}")
        return {"success": True, "message": "配置已保存，但连接重建失败，请手动重载插件"}

    return {"success": True, "message": "配置已保存"}


async def api_sources(client: Any) -> dict:
    """GET /sources — 已安装的源列表"""
    try:
        sources = await client.get_sources()
        return {
            "sources": [
                {
                    "id": s.id,
                    "name": s.name,
                    "lang": s.lang,
                    "display_name": s.display_name,
                }
                for s in sources
            ]
        }
    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] api_sources error: {e}")
        return {"sources": [], "error": str(e)}


async def api_update(
    check_updates: Callable[[bool], Awaitable[str]],
    put_kv_data: Callable[[str, Any], Awaitable[None]],
) -> dict:
    """POST /update — 手动触发更新检查"""
    try:
        summary = await check_updates(force=True)
        await put_kv_data("suwayomi_last_update_check", time.time())
        return {"success": True, "summary": summary}
    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] api_update error: {e}")
        return {"success": False, "summary": f"更新检查失败: {e}"}
