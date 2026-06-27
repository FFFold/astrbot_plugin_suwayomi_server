# Suwayomi 插件管理 WebUI 设计文档

## 概述

为 Suwayomi 漫画助手插件添加管理员 WebUI（AstrBot Plugin Pages），提供仪表盘总览、订阅管理和配置编辑功能。不包含漫画阅读器（Suwayomi 自有 WebUI 负责）。

## 技术方案

- **前端**: 原生 HTML + CSS + vanilla JS，零外部依赖
- **通信**: AstrBot Bridge SDK（`apiGet` / `apiPost`）
- **结构**: 单页面 3 Tab，`pages/dashboard/index.html` + `app.js` + `style.css`
- **主题**: CSS 变量适配 `data-theme="dark"/"light"`

## 页面结构

### Tab 1 — 仪表盘

**状态卡片（顶部 4 卡片）：**

| 卡片 | 数据来源 | 展示 |
|------|----------|------|
| 连接状态 | `client.get_sources()` 成功/失败 | 🟢 已连接 / 🔴 断开 |
| 源数量 | `len(sources)` | 数字 |
| 书库漫画数 | `len(get_library_mangas())` | 数字 |
| 订阅数 | `len(all_subs)` 部漫画，N 个订阅者 | 数字 |

**订阅总览表：**

| 列 | 说明 |
|----|------|
| 漫画名 | `title` |
| 源 | `source_display_name`（从 sources map 查） |
| 最新章节 ID | `latest_chapter_id` |
| 订阅人数 | `len(subscribers)` |
| 推送开启数 | 统计 auto_push enabled 的人数 |

**操作区：**
- 「检查更新」按钮 → 调用 `apiPost("update")` → 展示结果
- 更新结果文本区域

### Tab 2 — 订阅管理

**过滤器：**
- UMO 过滤输入框（支持模糊匹配，解析为可读格式：`平台:群组ID:用户ID`）
- 漫画名搜索框

**订阅表格：**

| 列 | 说明 |
|----|------|
| 漫画 ID | `manga_id` |
| 漫画名 | `title` |
| 源 | `source_display_name` |
| 订阅者 | UMO 列表（可读格式） |
| 推送状态 | 每个订阅者的 auto_push 开关 |
| 操作 | 删除订阅者、切换推送 |

**操作：**
- 点击订阅者可展开该 UMO 的所有订阅
- 删除订阅者：二次确认后调用 `apiPost("subscription/delete", {manga_id, umo})`
- 切换推送：调用 `apiPost("subscription/push", {manga_id, umo, enabled})`

### Tab 3 — 设置

**表单分组：**

| 分组 | 字段 |
|------|------|
| 服务器连接 | `server_url`, `auth_mode`, `username`, `password` |
| 阅读体验 | `max_pages`, `send_mode`, `image_fetch_mode` |
| 下载打包 | `download_format`, `download_concurrency`, `download_retries` |
| 自动推送 | `auto_push_mode` |
| 高级 | `chapter_cache_hours`, `default_source_id`, `temp_dir`, `check_interval` |

**行为：**
- 页面加载时 `apiGet("config")` 填充表单
- 保存时 `apiPost("config", {...})` → 后端校验 + `config.save_config()` + 重建 SuwayomiClient
- 保存成功/失败显示 toast 提示

## 后端 API

所有 endpoint 前缀: `/api/plug/astrbot_plugin_suwayomi_server/`

### `GET status`

测试 Suwayomi 连接，返回状态摘要。

```json
{
  "connected": true,
  "source_count": 5,
  "library_count": 42,
  "subscription_count": 12,
  "subscriber_total": 35,
  "last_update_check": "2026-06-26T10:30:00"
}
```

实现：并发调用 `get_sources()` + `get_library_mangas()` + `get_all_subscriptions()`，连接失败时 `connected: false`，其他字段为 0。

### `GET subscriptions`

返回全部订阅数据（跨所有用户），附带源显示名。

```json
{
  "subscriptions": [
    {
      "manga_id": 123,
      "title": "一拳超人",
      "source_id": 524579092615598717,
      "source_name": "拷贝漫画",
      "latest_chapter_id": 4567,
      "subscribers": ["aiocqhttp:group_123:456", "telegram:user_789"],
      "auto_push": {
        "aiocqhttp:group_123:456": true,
        "telegram:user_789": false
      }
    }
  ]
}
```

实现：读取 `sub_mgr.get_all_subscriptions()`，构建 sources map 补充源名称。

### `POST subscription/delete`

删除订阅者。

```json
// 请求
{ "manga_id": 123, "umo": "aiocqhttp:group_123:456" }
// umo 为空则删除该漫画全部订阅者

// 响应
{ "success": true }
```

实现：调用 `sub_mgr.unsubscribe(manga_id, umo)` 或遍历所有 subscribers 逐个删除。

### `POST subscription/push`

切换自动推送开关。

```json
// 请求
{ "manga_id": 123, "umo": "aiocqhttp:group_123:456", "enabled": true }

// 响应
{ "success": true }
```

实现：调用 `sub_mgr.set_auto_push(manga_id, umo, enabled)`。

### `GET config`

返回当前插件配置 dict（直接 `self.config`）。

### `POST config`

保存配置。

```json
// 请求
{ "server_url": "http://192.168.1.100:9330", "auth_mode": "none", ... }

// 响应
{ "success": true, "message": "配置已保存" }
```

实现：校验必填字段 → 更新 `self.config` → `self.config.save_config()` → 重建 `SuwayomiClient`（关闭旧 session）。

### `GET sources`

返回已安装源列表。

```json
{
  "sources": [
    { "id": "524579092615598717", "name": "copymanga", "lang": "zh", "display_name": "拷贝漫画" }
  ]
}
```

### `POST update`

手动触发更新检查。

```json
// 响应
{ "summary": "✅ 发现 2 部漫画更新：..." }
```

实现：调用 `self._check_updates(force=True)`，同步等待返回 summary。

## 文件结构

```
pages/
  dashboard/
    index.html    — 主页面骨架 + 3 Tab 容器
    app.js        — Tab 切换 + API 调用 + DOM 渲染
    style.css     — 样式（light/dark 主题）
```

## 边界情况

- **Suwayomi 连接失败**: 状态卡片显示红色，订阅管理和配置仍可用
- **漫画已删除**: 订阅中标记为「不可用」，仍可删除订阅
- **配置保存后**: 关闭旧 `SuwayomiClient` session，创建新实例
- **UMO 格式**: 解析为 `平台:群组:用户` 可读格式，原始 UMO 作为 tooltip

## 不做的事

- 不做漫画阅读器（Suwayomi WebUI 负责）
- 不做用户认证（复用 AstrBot Dashboard 的认证）
- 不做实时推送/WebSocket（管理员手动刷新即可）
- 不做 i18n（管理员界面统一中文）
