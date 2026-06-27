# Suwayomi 管理 WebUI 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Suwayomi 漫画助手插件添加管理员 WebUI（AstrBot Plugin Pages），提供仪表盘总览、订阅管理和配置编辑功能。

**Architecture:** 后端在 `web/api.py` 中定义独立的 API handler 函数，`main.py` 注册时委托调用。前端通过 AstrBot Bridge SDK 调用。单页面 3 Tab 结构，原生 HTML/CSS/JS，零外部依赖。

**Tech Stack:** Python (quart/aiohttp), HTML5, CSS3, vanilla JS, AstrBot Bridge SDK

---

## 文件结构

```
web/
  __init__.py           — 空文件
  api.py                — 所有 API handler 函数（纯函数，接收依赖注入）
pages/
  dashboard/
    index.html          — 主页面骨架 + 3 Tab 容器
    app.js              — Tab 切换 + API 调用 + DOM 渲染
    style.css           — 样式（light/dark 主题）
main.py                 — __init__ 中注册 API，handler 委托给 web/api.py
tests/
  test_web_api.py       — API handler 单元测试
```

---

### Task 0: 重构 — 提取 API handler 到 web/api.py

**目的:** `main.py` 已有 1136 行，新增 API 会使其更臃肿。将 API 逻辑提取到独立模块。

**Files:**
- Create: `web/__init__.py`
- Create: `web/api.py`
- Modify: `main.py:58-72` (`__init__` 添加注册)
- Modify: `main.py` (添加导入)

- [ ] **Step 1: 创建 `web/__init__.py`**

```bash
mkdir -p web
```

创建空文件 `web/__init__.py`。

- [ ] **Step 2: 创建 `web/api.py`**

所有 API handler 为独立 async 函数，接收 `client`、`sub_mgr`、`config`、`get_kv_data`、`put_kv_data`、`check_updates` 作为参数：

```python
"""WebUI API handlers for Suwayomi plugin.

All handlers are standalone async functions that receive dependencies as parameters.
This keeps main.py clean and makes handlers independently testable.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Awaitable

from astrbot.api import logger

PLUGIN_NAME = "astrbot_suwayomi_server"


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
    except Exception:
        pass

    try:
        mangas = await client.get_library_mangas()
        library_count = len(mangas)
    except Exception:
        pass

    try:
        all_subs = await sub_mgr.get_all_subscriptions()
        subscription_count = len(all_subs)
        for info in all_subs.values():
            subscriber_total += len(info.get("subscribers", []))
    except Exception:
        pass

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
        manga_id = int(manga_id_str)
        source_id = info.get("source_id", 0)
        auto_push = info.get("auto_push", {})
        push_enabled_count = sum(
            1 for v in auto_push.values() if isinstance(v, dict) and v.get("enabled")
        )
        result.append({
            "manga_id": manga_id,
            "title": info.get("title", f"ID:{manga_id}"),
            "source_id": source_id,
            "source_name": source_map.get(str(source_id), f"源{source_id}"),
            "latest_chapter_id": info.get("latest_chapter_id", 0),
            "subscribers": info.get("subscribers", []),
            "subscriber_count": len(info.get("subscribers", [])),
            "push_enabled_count": push_enabled_count,
            "auto_push": auto_push,
        })

    return {"subscriptions": result}


async def api_subscription_delete(
    sub_mgr: Any,
    data: dict,
) -> dict:
    """POST /subscription/delete — 删除订阅者"""
    manga_id = data.get("manga_id")
    umo = data.get("umo")

    if manga_id is None:
        return {"success": False, "message": "缺少 manga_id", "status": 400}

    try:
        if umo:
            await sub_mgr.unsubscribe(int(manga_id), umo)
        else:
            all_data = await sub_mgr._load()
            key = str(manga_id)
            if key in all_data:
                del all_data[key]
                await sub_mgr._save(all_data)
        return {"success": True}
    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] api_subscription_delete error: {e}")
        return {"success": False, "message": str(e), "status": 500}


async def api_subscription_push(
    sub_mgr: Any,
    data: dict,
) -> dict:
    """POST /subscription/push — 切换自动推送开关"""
    manga_id = data.get("manga_id")
    umo = data.get("umo")
    enabled = data.get("enabled")

    if manga_id is None or umo is None or enabled is None:
        return {"success": False, "message": "缺少参数", "status": 400}

    try:
        await sub_mgr.set_auto_push(int(manga_id), umo, bool(enabled))
        return {"success": True}
    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] api_subscription_push error: {e}")
        return {"success": False, "message": str(e), "status": 500}


async def api_config_get(config: Any) -> dict:
    """GET /config — 读取当前插件配置"""
    return dict(config)


async def api_config_post(
    config: Any,
    data: dict,
    rebuild_client: Callable[[dict], Awaitable[None]],
) -> dict:
    """POST /config — 保存插件配置"""
    if not data:
        return {"success": False, "message": "请求体为空", "status": 400}

    server_url = data.get("server_url", "").strip()
    if not server_url:
        return {"success": False, "message": "服务器地址不能为空", "status": 400}

    for key, value in data.items():
        config[key] = value

    try:
        config.save_config()
    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] config save error: {e}")
        return {"success": False, "message": f"保存失败: {e}", "status": 500}

    await rebuild_client(config)

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
```

- [ ] **Step 3: 在 `main.py` 中导入并注册 API**

在 `main.py` 的导入区添加：

```python
from .web.api import (
    api_status,
    api_subscriptions,
    api_subscription_delete,
    api_subscription_push,
    api_config_get,
    api_config_post,
    api_sources,
    api_update,
)
```

在 `__init__` 方法末尾（`logger.info(...)` 之后）添加注册：

```python
        # Register WebUI API endpoints
        context.register_web_api(
            f"/{PLUGIN_NAME}/status", self._api_status, ["GET"], "获取服务器状态",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/subscriptions", self._api_subscriptions, ["GET"], "获取全部订阅",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/subscription/delete", self._api_subscription_delete, ["POST"], "删除订阅",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/subscription/push", self._api_subscription_push, ["POST"], "切换推送",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/config", self._api_config, ["GET", "POST"], "插件配置",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/sources", self._api_sources, ["GET"], "获取源列表",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/update", self._api_update, ["POST"], "手动更新",
        )
```

- [ ] **Step 4: 在 `SuwayomiPlugin` 类末尾添加委托方法**

在 `manual_update` 方法之后添加：

```python
    # ── WebUI API delegates ────────────────────────────────────────

    async def _api_status(self):
        from quart import jsonify
        result = await api_status(self.client, self.sub_mgr, self.get_kv_data)
        return jsonify(result)

    async def _api_subscriptions(self):
        from quart import jsonify
        result = await api_subscriptions(self.client, self.sub_mgr)
        return jsonify(result)

    async def _api_subscription_delete(self):
        from quart import jsonify, request
        data = await request.get_json()
        result = await api_subscription_delete(self.sub_mgr, data)
        status = result.pop("status", 200)
        return jsonify(result), status

    async def _api_subscription_push(self):
        from quart import jsonify, request
        data = await request.get_json()
        result = await api_subscription_push(self.sub_mgr, data)
        status = result.pop("status", 200)
        return jsonify(result), status

    async def _api_config(self):
        from quart import jsonify, request
        if request.method == "GET":
            return jsonify(api_config_get(self.config))

        data = await request.get_json()

        async def rebuild_client(cfg):
            try:
                await self.client.close()
            except Exception:
                pass
            self.client = SuwayomiClient(
                server_url=cfg.get("server_url", "http://localhost:9330"),
                auth_mode=cfg.get("auth_mode", "none"),
                username=cfg.get("username", ""),
                password=cfg.get("password", ""),
            )

        result = await api_config_post(self.config, data, rebuild_client)
        status = result.pop("status", 200)
        return jsonify(result), status

    async def _api_sources(self):
        from quart import jsonify
        result = await api_sources(self.client)
        return jsonify(result)

    async def _api_update(self):
        from quart import jsonify
        result = await api_update(self._check_updates, self.put_kv_data)
        return jsonify(result)
```

- [ ] **Step 5: 语法检查**

```bash
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
python -c "import ast; ast.parse(open('web/api.py', encoding='utf-8').read()); print('OK')"
```

- [ ] **Step 6: Commit**

```bash
git add web/ main.py
git commit -m "refactor: extract WebUI API handlers to web/api.py"
```

---

### Task 1: 前端 — HTML 骨架

**Files:**
- Create: `pages/dashboard/index.html`

- [ ] **Step 1: 创建 pages 目录**

```bash
mkdir -p pages/dashboard
```

- [ ] **Step 2: 创建 `index.html`**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Suwayomi 漫画助手</title>
  <link rel="stylesheet" href="./style.css">
</head>
<body>
  <div class="container">
    <header class="header">
      <h1>Suwayomi 漫画助手</h1>
      <nav class="tabs">
        <button class="tab-btn active" data-tab="dashboard">仪表盘</button>
        <button class="tab-btn" data-tab="subscriptions">订阅管理</button>
        <button class="tab-btn" data-tab="settings">设置</button>
      </nav>
    </header>

    <!-- Tab 1: Dashboard -->
    <section id="tab-dashboard" class="tab-content active">
      <div class="status-cards" id="status-cards">
        <div class="card" id="card-connected">
          <div class="card-label">连接状态</div>
          <div class="card-value" id="val-connected">--</div>
        </div>
        <div class="card">
          <div class="card-label">漫画源</div>
          <div class="card-value" id="val-sources">--</div>
        </div>
        <div class="card">
          <div class="card-label">书库漫画</div>
          <div class="card-value" id="val-library">--</div>
        </div>
        <div class="card">
          <div class="card-label">订阅</div>
          <div class="card-value" id="val-subs">--</div>
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          <h2>订阅总览</h2>
          <button class="btn btn-primary" id="btn-check-update">检查更新</button>
        </div>
        <div id="update-result" class="update-result hidden"></div>
        <table class="table" id="overview-table">
          <thead>
            <tr>
              <th>漫画名</th>
              <th>源</th>
              <th>最新章节 ID</th>
              <th>订阅人数</th>
              <th>推送开启</th>
            </tr>
          </thead>
          <tbody id="overview-tbody"></tbody>
        </table>
        <div class="empty-state hidden" id="overview-empty">暂无订阅</div>
      </div>
    </section>

    <!-- Tab 2: Subscriptions -->
    <section id="tab-subscriptions" class="tab-content">
      <div class="section">
        <div class="filters">
          <input type="text" class="input" id="filter-umo" placeholder="按 UMO 过滤（如 aiocqhttp:group_123）">
          <input type="text" class="input" id="filter-title" placeholder="按漫画名搜索">
        </div>
        <table class="table" id="subs-table">
          <thead>
            <tr>
              <th>漫画 ID</th>
              <th>漫画名</th>
              <th>源</th>
              <th>订阅者</th>
              <th>推送状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody id="subs-tbody"></tbody>
        </table>
        <div class="empty-state hidden" id="subs-empty">暂无订阅数据</div>
      </div>
    </section>

    <!-- Tab 3: Settings -->
    <section id="tab-settings" class="tab-content">
      <form id="config-form" class="config-form">
        <fieldset>
          <legend>服务器连接</legend>
          <div class="form-group">
            <label for="cfg-server_url">Suwayomi-Server 地址</label>
            <input type="text" id="cfg-server_url" name="server_url" placeholder="http://localhost:9330">
          </div>
          <div class="form-group">
            <label for="cfg-auth_mode">认证模式</label>
            <select id="cfg-auth_mode" name="auth_mode">
              <option value="none">无认证</option>
              <option value="basic">Basic 认证</option>
              <option value="jwt">JWT 认证</option>
            </select>
          </div>
          <div class="form-group">
            <label for="cfg-username">用户名</label>
            <input type="text" id="cfg-username" name="username">
          </div>
          <div class="form-group">
            <label for="cfg-password">密码</label>
            <input type="password" id="cfg-password" name="password">
          </div>
        </fieldset>

        <fieldset>
          <legend>阅读体验</legend>
          <div class="form-group">
            <label for="cfg-max_pages">单次最大发送页数</label>
            <input type="number" id="cfg-max_pages" name="max_pages" min="1" max="200">
          </div>
          <div class="form-group">
            <label for="cfg-send_mode">图片发送模式</label>
            <select id="cfg-send_mode" name="send_mode">
              <option value="image">直接发图</option>
              <option value="forward">合并转发</option>
            </select>
          </div>
          <div class="form-group">
            <label for="cfg-image_fetch_mode">图片获取方式</label>
            <select id="cfg-image_fetch_mode" name="image_fetch_mode">
              <option value="url">URL 直接引用</option>
              <option value="download">先下载到本地</option>
            </select>
          </div>
        </fieldset>

        <fieldset>
          <legend>下载打包</legend>
          <div class="form-group">
            <label for="cfg-download_format">默认打包格式</label>
            <select id="cfg-download_format" name="download_format">
              <option value="zip">ZIP 压缩包</option>
              <option value="pdf">PDF 文档</option>
              <option value="cbz">CBZ 漫画</option>
            </select>
          </div>
          <div class="form-group">
            <label for="cfg-download_concurrency">并行下载数</label>
            <input type="number" id="cfg-download_concurrency" name="download_concurrency" min="1" max="20">
          </div>
          <div class="form-group">
            <label for="cfg-download_retries">下载重试次数</label>
            <input type="number" id="cfg-download_retries" name="download_retries" min="0" max="10">
          </div>
        </fieldset>

        <fieldset>
          <legend>自动推送</legend>
          <div class="form-group">
            <label for="cfg-auto_push_mode">推送模式</label>
            <select id="cfg-auto_push_mode" name="auto_push_mode">
              <option value="image">图片（复用阅读）</option>
              <option value="file">文件（复用下载）</option>
            </select>
          </div>
        </fieldset>

        <fieldset>
          <legend>高级</legend>
          <div class="form-group">
            <label for="cfg-check_interval">更新检查间隔（分钟）</label>
            <input type="number" id="cfg-check_interval" name="check_interval" min="1">
          </div>
          <div class="form-group">
            <label for="cfg-chapter_cache_hours">章节缓存时间（小时）</label>
            <input type="number" id="cfg-chapter_cache_hours" name="chapter_cache_hours" min="-1">
          </div>
          <div class="form-group">
            <label for="cfg-default_source_id">默认搜索源 ID</label>
            <input type="number" id="cfg-default_source_id" name="default_source_id" min="0">
          </div>
          <div class="form-group">
            <label for="cfg-temp_dir">临时文件目录</label>
            <input type="text" id="cfg-temp_dir" name="temp_dir" placeholder="留空使用系统默认">
          </div>
        </fieldset>

        <div class="form-actions">
          <button type="submit" class="btn btn-primary">保存配置</button>
          <span id="config-msg" class="form-msg"></span>
        </div>
      </form>
    </section>
  </div>

  <div id="toast" class="toast hidden"></div>

  <script type="module" src="./app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Commit**

```bash
git add pages/dashboard/index.html
git commit -m "feat(webui): add HTML skeleton with 3-tab layout"
```

---

### Task 2: 前端 — CSS 样式

**Files:**
- Create: `pages/dashboard/style.css`

- [ ] **Step 1: 创建 `style.css`**

```css
:root {
  --bg: #f5f5f5;
  --bg-card: #ffffff;
  --bg-input: #ffffff;
  --border: #e0e0e0;
  --text: #1a1a1a;
  --text-secondary: #666;
  --primary: #4a90d9;
  --primary-hover: #357abd;
  --danger: #e74c3c;
  --danger-hover: #c0392b;
  --success: #27ae60;
  --warning: #f39c12;
  --radius: 8px;
  --shadow: 0 1px 3px rgba(0,0,0,0.1);
}

[data-theme="dark"] {
  --bg: #1a1a2e;
  --bg-card: #16213e;
  --bg-input: #0f3460;
  --border: #2a2a4a;
  --text: #e0e0e0;
  --text-secondary: #999;
  --primary: #5dade2;
  --primary-hover: #3498db;
  --danger: #e74c3c;
  --danger-hover: #c0392b;
  --success: #2ecc71;
  --warning: #f1c40f;
  --shadow: 0 1px 3px rgba(0,0,0,0.3);
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
}

.container {
  max-width: 1100px;
  margin: 0 auto;
  padding: 20px;
}

/* Header & Tabs */
.header {
  margin-bottom: 24px;
}

.header h1 {
  font-size: 1.5rem;
  margin-bottom: 12px;
}

.tabs {
  display: flex;
  gap: 4px;
  border-bottom: 2px solid var(--border);
}

.tab-btn {
  padding: 8px 20px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 0.95rem;
  transition: all 0.2s;
  margin-bottom: -2px;
}

.tab-btn:hover { color: var(--text); }
.tab-btn.active {
  color: var(--primary);
  border-bottom-color: var(--primary);
}

.tab-content { display: none; }
.tab-content.active { display: block; }

/* Status Cards */
.status-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  box-shadow: var(--shadow);
}

.card-label {
  font-size: 0.85rem;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.card-value {
  font-size: 1.8rem;
  font-weight: 700;
}

.card-value.status-ok { color: var(--success); }
.card-value.status-err { color: var(--danger); }

/* Section */
.section {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  box-shadow: var(--shadow);
  margin-bottom: 20px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.section-header h2 {
  font-size: 1.1rem;
}

/* Table */
.table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}

.table th, .table td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}

.table th {
  font-weight: 600;
  color: var(--text-secondary);
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.table tr:hover td {
  background: rgba(0,0,0,0.02);
}

[data-theme="dark"] .table tr:hover td {
  background: rgba(255,255,255,0.03);
}

/* Buttons */
.btn {
  padding: 6px 16px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.85rem;
  transition: background 0.2s;
}

.btn-primary {
  background: var(--primary);
  color: #fff;
}
.btn-primary:hover { background: var(--primary-hover); }

.btn-danger {
  background: var(--danger);
  color: #fff;
  font-size: 0.8rem;
  padding: 4px 10px;
}
.btn-danger:hover { background: var(--danger-hover); }

.btn-sm {
  font-size: 0.8rem;
  padding: 3px 8px;
}

/* Inputs */
.input, .config-form input, .config-form select {
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-input);
  color: var(--text);
  font-size: 0.9rem;
}

.input:focus, .config-form input:focus, .config-form select:focus {
  outline: none;
  border-color: var(--primary);
}

.filters {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.filters .input { flex: 1; }

/* Config Form */
.config-form fieldset {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  margin-bottom: 16px;
}

.config-form legend {
  font-weight: 600;
  padding: 0 8px;
  color: var(--primary);
}

.form-group {
  margin-bottom: 12px;
}

.form-group label {
  display: block;
  font-size: 0.85rem;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.form-group input, .form-group select {
  width: 100%;
  max-width: 400px;
}

.form-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.form-msg {
  font-size: 0.85rem;
}
.form-msg.success { color: var(--success); }
.form-msg.error { color: var(--danger); }

/* Update Result */
.update-result {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 12px;
  margin-bottom: 16px;
  white-space: pre-wrap;
  font-size: 0.9rem;
}

/* Empty State */
.empty-state {
  text-align: center;
  padding: 40px;
  color: var(--text-secondary);
}

/* Toast */
.toast {
  position: fixed;
  bottom: 20px;
  right: 20px;
  padding: 12px 20px;
  border-radius: var(--radius);
  color: #fff;
  font-size: 0.9rem;
  z-index: 1000;
  transition: opacity 0.3s;
}
.toast.success { background: var(--success); }
.toast.error { background: var(--danger); }

/* Subscriber tags */
.sub-tag {
  display: inline-block;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 8px;
  margin: 2px;
  font-size: 0.8rem;
  font-family: monospace;
}

.push-on { color: var(--success); }
.push-off { color: var(--text-secondary); }

/* Utility */
.hidden { display: none; }
```

- [ ] **Step 2: Commit**

```bash
git add pages/dashboard/style.css
git commit -m "feat(webui): add CSS styles with light/dark theme support"
```

---

### Task 3: 前端 — JavaScript 逻辑

**Files:**
- Create: `pages/dashboard/app.js`

- [ ] **Step 1: 创建 `app.js`**

```javascript
const bridge = window.AstrBotPluginPage;

// ── State ──────────────────────────────────────────────
let allSubscriptions = [];
let allSources = [];

// ── Init ───────────────────────────────────────────────
const context = await bridge.ready();
initTabs();
await loadDashboard();

// ── Tab switching ──────────────────────────────────────
function initTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('tab-' + btn.dataset.tab).classList.add('active');

      if (btn.dataset.tab === 'dashboard') loadDashboard();
      if (btn.dataset.tab === 'subscriptions') loadSubscriptions();
      if (btn.dataset.tab === 'settings') loadConfig();
    });
  });
}

// ── Dashboard ──────────────────────────────────────────
async function loadDashboard() {
  const statusEl = document.getElementById('val-connected');
  statusEl.textContent = '加载中...';

  try {
    const [statusRes, subsRes] = await Promise.all([
      bridge.apiGet('status'),
      bridge.apiGet('subscriptions'),
    ]);

    // Status cards
    const connected = statusRes.connected;
    statusEl.textContent = connected ? '已连接' : '断开';
    statusEl.className = 'card-value ' + (connected ? 'status-ok' : 'status-err');
    document.getElementById('val-sources').textContent = statusRes.source_count;
    document.getElementById('val-library').textContent = statusRes.library_count;
    document.getElementById('val-subs').textContent =
      statusRes.subscription_count + ' 部 / ' + statusRes.subscriber_total + ' 人';

    // Overview table
    allSubscriptions = subsRes.subscriptions || [];
    renderOverviewTable(allSubscriptions);
  } catch (e) {
    statusEl.textContent = '错误';
    statusEl.className = 'card-value status-err';
  }

  // Check update button
  const btnUpdate = document.getElementById('btn-check-update');
  btnUpdate.onclick = async () => {
    btnUpdate.disabled = true;
    btnUpdate.textContent = '检查中...';
    const resultEl = document.getElementById('update-result');
    resultEl.classList.remove('hidden');
    try {
      const res = await bridge.apiPost('update');
      resultEl.textContent = res.summary || '检查完成';
    } catch (e) {
      resultEl.textContent = '更新检查失败: ' + e.message;
    }
    btnUpdate.disabled = false;
    btnUpdate.textContent = '检查更新';
  };
}

function renderOverviewTable(subs) {
  const tbody = document.getElementById('overview-tbody');
  const emptyEl = document.getElementById('overview-empty');

  if (!subs.length) {
    tbody.innerHTML = '';
    emptyEl.classList.remove('hidden');
    return;
  }
  emptyEl.classList.add('hidden');

  tbody.innerHTML = subs.map(s => `
    <tr>
      <td>${esc(s.title)}</td>
      <td>${esc(s.source_name)}</td>
      <td>${s.latest_chapter_id}</td>
      <td>${s.subscriber_count}</td>
      <td>${s.push_enabled_count}</td>
    </tr>
  `).join('');
}

// ── Subscriptions ──────────────────────────────────────
async function loadSubscriptions() {
  try {
    const res = await bridge.apiGet('subscriptions');
    allSubscriptions = res.subscriptions || [];
    allSources = (await bridge.apiGet('sources')).sources || [];
    renderSubsTable(allSubscriptions);
  } catch (e) {
    showToast('加载订阅失败', 'error');
  }

  // Filters
  document.getElementById('filter-umo').oninput = applySubsFilter;
  document.getElementById('filter-title').oninput = applySubsFilter;
}

function applySubsFilter() {
  const umoFilter = document.getElementById('filter-umo').value.toLowerCase();
  const titleFilter = document.getElementById('filter-title').value.toLowerCase();

  let filtered = allSubscriptions;
  if (umoFilter) {
    filtered = filtered.filter(s =>
      s.subscribers.some(u => u.toLowerCase().includes(umoFilter))
    );
  }
  if (titleFilter) {
    filtered = filtered.filter(s => s.title.toLowerCase().includes(titleFilter));
  }
  renderSubsTable(filtered);
}

function renderSubsTable(subs) {
  const tbody = document.getElementById('subs-tbody');
  const emptyEl = document.getElementById('subs-empty');

  if (!subs.length) {
    tbody.innerHTML = '';
    emptyEl.classList.remove('hidden');
    return;
  }
  emptyEl.classList.add('hidden');

  tbody.innerHTML = subs.map(s => {
    const subTags = s.subscribers.map(u => {
      const ap = s.auto_push[u];
      const enabled = ap && ap.enabled;
      return `<span class="sub-tag" title="${esc(u)}">${esc(formatUmo(u))} <span class="${enabled ? 'push-on' : 'push-off'}">${enabled ? 'ON' : 'OFF'}</span></span>`;
    }).join(' ');

    return `
      <tr>
        <td>${s.manga_id}</td>
        <td>${esc(s.title)}</td>
        <td>${esc(s.source_name)}</td>
        <td>${subTags}</td>
        <td>${s.push_enabled_count}/${s.subscriber_count}</td>
        <td>
          <button class="btn btn-danger btn-sm" onclick="deleteAllSubs(${s.manga_id}, '${esc(s.title)}')">删除全部</button>
        </td>
      </tr>
    `;
  }).join('');
}

async function deleteAllSubs(mangaId, title) {
  if (!confirm(`确认删除「${title}」的所有订阅？`)) return;
  try {
    await bridge.apiPost('subscription/delete', { manga_id: mangaId });
    showToast('已删除', 'success');
    await loadSubscriptions();
  } catch (e) {
    showToast('删除失败', 'error');
  }
}

// ── Settings ───────────────────────────────────────────
async function loadConfig() {
  try {
    const config = await bridge.apiGet('config');
    for (const [key, value] of Object.entries(config)) {
      const el = document.getElementById('cfg-' + key);
      if (!el) continue;
      el.value = value;
    }
  } catch (e) {
    showToast('加载配置失败', 'error');
  }

  const form = document.getElementById('config-form');
  form.onsubmit = async (e) => {
    e.preventDefault();
    const msgEl = document.getElementById('config-msg');
    const data = {};
    const inputs = form.querySelectorAll('input, select');
    inputs.forEach(el => {
      if (!el.name) return;
      if (el.type === 'number') {
        data[el.name] = Number(el.value);
      } else {
        data[el.name] = el.value;
      }
    });

    try {
      const res = await bridge.apiPost('config', data);
      if (res.success) {
        msgEl.textContent = '保存成功';
        msgEl.className = 'form-msg success';
      } else {
        msgEl.textContent = res.message || '保存失败';
        msgEl.className = 'form-msg error';
      }
    } catch (err) {
      msgEl.textContent = '保存失败: ' + err.message;
      msgEl.className = 'form-msg error';
    }

    setTimeout(() => { msgEl.textContent = ''; }, 3000);
  };
}

// ── Helpers ────────────────────────────────────────────
function esc(str) {
  if (!str) return '';
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

function formatUmo(umo) {
  return umo;
}

function showToast(msg, type) {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.className = 'toast ' + type;
  setTimeout(() => { toast.className = 'toast hidden'; }, 3000);
}
```

- [ ] **Step 2: Commit**

```bash
git add pages/dashboard/app.js
git commit -m "feat(webui): add JavaScript logic for dashboard, subscriptions, and settings tabs"
```

---

### Task 4: 单元测试 — 后端 API

**Files:**
- Create: `tests/test_web_api.py`

- [ ] **Step 1: 创建 API 测试文件**

```python
"""Tests for WebUI API handlers in web/api.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from web.api import (
    api_status,
    api_subscriptions,
    api_subscription_delete,
    api_subscription_push,
    api_config_get,
    api_config_post,
    api_sources,
    api_update,
)


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_sources = AsyncMock(return_value=[])
    client.get_library_mangas = AsyncMock(return_value=[])
    client.close = AsyncMock()
    return client


@pytest.fixture
def fake_plugin():
    """FakePlugin mimicking the KV storage interface."""
    class FakePlugin:
        def __init__(self):
            self._store = {}
        async def get_kv_data(self, key, default=None):
            return self._store.get(key, default)
        async def put_kv_data(self, key, value):
            self._store[key] = value
    return FakePlugin()


@pytest.fixture
def sub_mgr(fake_plugin):
    from utils.subscription import SubscriptionManager
    return SubscriptionManager(fake_plugin)


# ── api_status ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_connected(mock_client, sub_mgr, fake_plugin):
    from suwayomi.models import Source
    mock_client.get_sources = AsyncMock(return_value=[
        Source(id="1", name="src", lang="zh", display_name="源"),
    ])

    result = await api_status(mock_client, sub_mgr, fake_plugin.get_kv_data)
    assert result["connected"] is True
    assert result["source_count"] == 1


@pytest.mark.asyncio
async def test_status_disconnected(mock_client, sub_mgr, fake_plugin):
    mock_client.get_sources = AsyncMock(side_effect=Exception("fail"))

    result = await api_status(mock_client, sub_mgr, fake_plugin.get_kv_data)
    assert result["connected"] is False
    assert result["source_count"] == 0


# ── api_subscriptions ───────────────────────────────────

@pytest.mark.asyncio
async def test_subscriptions_empty(mock_client, sub_mgr):
    result = await api_subscriptions(mock_client, sub_mgr)
    assert result["subscriptions"] == []


@pytest.mark.asyncio
async def test_subscriptions_with_data(mock_client, sub_mgr):
    from suwayomi.models import Source

    await sub_mgr.subscribe(42, "One Piece", 100, "user1")
    await sub_mgr.subscribe(42, "One Piece", 100, "user2")
    await sub_mgr.set_auto_push(42, "user1", True)

    mock_client.get_sources = AsyncMock(return_value=[
        Source(id="100", name="src", lang="zh", display_name="测试源"),
    ])

    result = await api_subscriptions(mock_client, sub_mgr)
    subs = result["subscriptions"]
    assert len(subs) == 1
    assert subs[0]["manga_id"] == 42
    assert subs[0]["source_name"] == "测试源"
    assert subs[0]["subscriber_count"] == 2
    assert subs[0]["push_enabled_count"] == 1


# ── api_subscription_delete ─────────────────────────────

@pytest.mark.asyncio
async def test_delete_subscription(sub_mgr):
    await sub_mgr.subscribe(42, "OP", 100, "user1")
    result = await api_subscription_delete(sub_mgr, {"manga_id": 42, "umo": "user1"})
    assert result["success"] is True
    subs = await sub_mgr.get_subscriptions("user1")
    assert len(subs) == 0


@pytest.mark.asyncio
async def test_delete_all_subscriptions(sub_mgr):
    await sub_mgr.subscribe(42, "OP", 100, "user1")
    await sub_mgr.subscribe(42, "OP", 100, "user2")
    result = await api_subscription_delete(sub_mgr, {"manga_id": 42})
    assert result["success"] is True
    all_subs = await sub_mgr.get_all_subscriptions()
    assert "42" not in all_subs


@pytest.mark.asyncio
async def test_delete_missing_manga_id():
    result = await api_subscription_delete(MagicMock(), {})
    assert result["success"] is False
    assert result["status"] == 400


# ── api_subscription_push ───────────────────────────────

@pytest.mark.asyncio
async def test_push_toggle(sub_mgr):
    await sub_mgr.subscribe(42, "OP", 100, "user1")
    result = await api_subscription_push(sub_mgr, {
        "manga_id": 42, "umo": "user1", "enabled": True,
    })
    assert result["success"] is True
    assert await sub_mgr.get_auto_push(42, "user1") is True


@pytest.mark.asyncio
async def test_push_missing_params():
    result = await api_subscription_push(MagicMock(), {"manga_id": 42})
    assert result["success"] is False
    assert result["status"] == 400


# ── api_config ──────────────────────────────────────────

def test_config_get():
    cfg = {"server_url": "http://localhost:9330", "auth_mode": "none"}
    result = api_config_get(cfg)
    assert result == cfg


@pytest.mark.asyncio
async def test_config_post_save():
    cfg = {"server_url": "http://old:9330"}
    cfg.save_config = MagicMock()
    rebuild = AsyncMock()

    result = await api_config_post(cfg, {"server_url": "http://new:9330"}, rebuild)
    assert result["success"] is True
    assert cfg["server_url"] == "http://new:9330"
    cfg.save_config.assert_called_once()
    rebuild.assert_called_once()


@pytest.mark.asyncio
async def test_config_post_empty_url():
    cfg = {"server_url": "http://old:9330"}
    cfg.save_config = MagicMock()

    result = await api_config_post(cfg, {"server_url": ""}, AsyncMock())
    assert result["success"] is False
    assert result["status"] == 400


# ── api_sources ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_sources_list(mock_client):
    from suwayomi.models import Source
    mock_client.get_sources = AsyncMock(return_value=[
        Source(id="1", name="a", lang="zh", display_name="A"),
    ])
    result = await api_sources(mock_client)
    assert len(result["sources"]) == 1
    assert result["sources"][0]["display_name"] == "A"


@pytest.mark.asyncio
async def test_sources_error(mock_client):
    mock_client.get_sources = AsyncMock(side_effect=Exception("fail"))
    result = await api_sources(mock_client)
    assert result["sources"] == []
    assert "error" in result


# ── api_update ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_success(fake_plugin):
    check = AsyncMock(return_value="✅ 无更新")
    result = await api_update(check, fake_plugin.put_kv_data)
    assert result["success"] is True
    check.assert_called_once_with(force=True)


@pytest.mark.asyncio
async def test_update_failure(fake_plugin):
    check = AsyncMock(side_effect=Exception("fail"))
    result = await api_update(check, fake_plugin.put_kv_data)
    assert result["success"] is False
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/test_web_api.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_web_api.py
git commit -m "test(webui): add unit tests for API handlers"
```

---

### Task 5: 验证和收尾

- [ ] **Step 1: 运行全部测试确保无回归**

```bash
uv run pytest tests/test_pack.py tests/test_models.py tests/test_client.py tests/test_subscription.py tests/test_web_api.py -v
```

- [ ] **Step 2: 语法检查**

```bash
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
python -c "import ast; ast.parse(open('web/api.py', encoding='utf-8').read()); print('OK')"
```

- [ ] **Step 3: 更新 AGENTS.md**

在 Architecture 的 `main.py` 行后添加：
```
  │   ├── web/api.py (WebUI API handlers)
  │   └── pages/dashboard/ (WebUI: 仪表盘 + 订阅管理 + 配置)
```

- [ ] **Step 4: 最终 Commit**

```bash
git add -A
git commit -m "docs: update AGENTS.md with WebUI architecture info"
```
