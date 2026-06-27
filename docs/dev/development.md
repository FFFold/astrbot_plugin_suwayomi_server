# 开发指南

本文档面向插件开发者，介绍项目架构、开发环境搭建、测试方法和代码规范。

## 项目结构

```
astrbot_suwayomi_server/
├── main.py                    # 插件入口，命令定义、后台更新逻辑、WebUI API 注册
├── metadata.yaml              # AstrBot 插件元数据
├── _conf_schema.json          # AstrBot 配置 schema（WebUI 自动生成配置表单）
├── requirements.txt           # Python 运行时依赖
├── suwayomi/
│   ├── __init__.py
│   ├── client.py              # Suwayomi GraphQL 异步 HTTP 客户端
│   └── models.py              # 数据模型定义
├── utils/
│   ├── __init__.py
│   ├── pack.py               # 图片打包工具（ZIP/CBZ/PDF）
│   └── subscription.py        # 订阅管理器（AstrBot KV 存储封装）
├── web/
│   ├── __init__.py
│   └── api.py                # WebUI API handler 函数（依赖注入，独立可测试）
├── pages/
│   └── dashboard/
│       ├── index.html         # 管理面板页面（3 Tab: 仪表盘/订阅管理/设置）
│       ├── app.js             # 前端逻辑（Tab 切换、API 调用、DOM 渲染）
│       └── style.css          # 样式（支持 light/dark 主题）
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # Mock astrbot 模块（独立运行集成测试）
│   ├── test_pack.py           # 打包功能单元测试（19 个）
│   ├── test_models.py         # 数据模型单元测试（9 个）
│   ├── test_client.py         # 客户端单元测试（6 个）
│   ├── test_subscription.py   # 订阅管理单元测试（20 个）
│   ├── test_web_api.py        # WebUI API handler 单元测试（30 个）
│   ├── test_live_api.py       # Suwayomi 客户端集成测试（13 个）
│   └── test_live_web_api.py   # WebUI API handler 集成测试（19 个）
├── docs/
│   ├── dev/                   # 开发者文档（本目录）
│   └── superpowers/           # 设计文档和实现计划
├── CHANGELOG.md
├── LICENSE
└── README.md                  # 用户文档
```

## 架构概览

```
┌─────────────────────────────────────────────────┐
│                  AstrBot Core                    │
│  (Event Bus, Plugin Manager, KV Storage, Chat)  │
└──────────────────┬──────────────────────────────┘
                   │ @filter.command / on_astrbot_loaded
┌──────────────────▼──────────────────────────────┐
│              main.py - SuwayomiPlugin            │
│  ┌────────────┐ ┌────────────┐ ┌──────────────┐ │
│  │ Commands   │ │ Update     │ │ Search Cache │ │
│  │ (13 个命令)│ │ Loop (后台)│ │ (TTL 10min)  │ │
│  └─────┬──────┘ └─────┬──────┘ └──────────────┘ │
│        │              │                          │
│  ┌─────▼──────────────▼──────────────────────┐   │
│  │         suwayomi/client.py                │   │
│  │  SuwayomiClient (async GraphQL HTTP)      │   │
│  └─────────────────┬─────────────────────────┘   │
│                    │                              │
│  ┌─────────────────▼─────────────────────────┐   │
│  │         suwayomi/models.py                │   │
│  │  Source, Manga, Chapter, SearchResult     │   │
│  └───────────────────────────────────────────┘   │
│                                                  │
│  ┌───────────────────────────────────────────┐   │
│  │         utils/subscription.py             │   │
│  │  SubscriptionManager (KV Storage)         │   │
│  └───────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
                   │ GraphQL over HTTP
┌──────────────────▼──────────────────────────────┐
│           Suwayomi-Server (:9330)                │
│  /api/graphql  (GraphQL Endpoint)                │
│  /api/v1/...   (REST Legacy)                     │
└─────────────────────────────────────────────────┘
```

### 核心模块

#### `main.py` — 插件主类

- 继承 `astrbot.api.star.Star`
- 使用 `@filter.command_group("漫画")` 组织命令
- `__init__` 中初始化客户端和订阅管理器
- `@filter.on_astrbot_loaded()` 中启动后台任务（确保事件循环就绪）
- `terminate()` 中取消后台任务并关闭 HTTP 会话
- 搜索缓存使用 `(timestamp, {index: Manga})` 结构，10 分钟 TTL 自动过期

#### `suwayomi/client.py` — GraphQL 客户端

- 基于 `aiohttp.ClientSession` 的异步 HTTP 客户端
- 所有 Suwayomi 交互通过 `POST /api/graphql` 发送 GraphQL 查询/变更
- 支持三种认证模式：无认证、Basic、JWT（自动刷新）
- `_raw_query()` 是核心方法，处理认证头、错误解析、401 重试
- JWT 刷新使用 `_refreshing` 标志防止递归

#### `suwayomi/models.py` — 数据模型

- 纯数据类（`@dataclass`），无副作用
- `from_dict()` 工厂方法处理 API 返回的 JSON，强制类型转换（API 返回字符串数字）
- `Source.id` 为 `str` 类型（Suwayomi 的 `LongString` 标量）

#### `utils/subscription.py` — 订阅管理

- 通过 AstrBot 的 `get_kv_data()` / `put_kv_data()` 持久化
- 数据结构：`{manga_id: {title, source_id, latest_chapter_id, subscribers: [umo, ...], auto_push: {umo: {enabled: bool}}}}`
- `umo`（`unified_msg_origin`）是 AstrBot 的会话唯一标识
- `delete_manga(manga_id)` — 删除漫画的全部订阅者（公开方法）

#### `web/api.py` — WebUI API handlers

- 独立 async 函数，通过参数注入依赖（`client`、`sub_mgr`、`config`），便于单元测试
- 8 个 handler：`api_status`、`api_subscriptions`、`api_subscription_delete`、`api_subscription_push`、`api_config_get`、`api_config_post`、`api_sources`、`api_update`
- 成功返回 `dict`（HTTP 200），错误返回 `(dict, int)` 元组（HTTP 4xx/5xx）
- `main.py` 中通过 `_json_response()` 辅助方法统一处理返回格式

#### `pages/dashboard/` — 管理面板前端

- AstrBot Plugin Pages，通过 Bridge SDK 的 `postMessage` 机制与后端通信
- 单页面 3 Tab 结构：仪表盘（状态卡片 + 订阅总览 + 更新检查）、订阅管理（五维筛选 + 删除单条订阅）、设置（配置表单）
- 订阅表按（漫画 + UMO）展开为独立行，每行可单独删除
- 原生 HTML/CSS/JS，零外部依赖
- 支持 light/dark 主题（CSS 变量，由 AstrBot 自动设置 `data-theme` 属性）
- 事件委托模式处理按钮点击，避免 XSS 风险
- 使用自定义 DOM 弹窗（`showConfirm()`）替代原生 `confirm()`，兼容 sandbox iframe（无 `allow-modals`）

### 数据流

**搜索流程：**
```
用户输入 → search_manga() → 遍历目标源 → client.search_manga() → GraphQL fetchSourceManga
         → 合并结果 → 缓存到 _search_cache → 返回列表
```

**订阅更新流程：**
```
_update_loop (定时) → _check_updates(force=True) → client.update_library() (触发书库更新)
                   → 遍历订阅 → 同步标题 + 拉取章节 + 对比 latest_chapter_id
                   → 发现新章节 → context.send_message() 推送到各订阅者
```

**更新机制核心方法：**

| 方法 | 职责 | 调用者 |
|------|------|--------|
| `_check_updates(force)` | 主更新逻辑：同步标题、拉取章节、检测新章节、推送通知 | `/漫画 更新`（force=True）、后台定时更新（force=True） |
| `_get_or_fetch_chapters(manga_id, force)` | 章节获取：读缓存或从源拉取 | `_check_updates`、`/漫画 章节`、`/漫画 阅读`、`/漫画 下载` |
| `_get_chapter_timestamp(manga_id)` / `_set_chapter_timestamp(manga_id)` | 管理每个漫画的章节缓存时间戳 | `_get_or_fetch_chapters`、`_check_updates` |
| `SubscriptionManager.update_latest_chapter(manga_id, chapter_id)` | 更新水位线（已通知到的最大章节 ID） | `_check_updates` |
| `SubscriptionManager.update_title(manga_id, new_title)` | 同步漫画标题（仅在变化时写入） | `_check_updates` |

**更新判断逻辑：**

```
latest_chapter_id = 当前水位线（按 manga_id 存储，不是章节编号）
for ch in chapters:
    if ch.id > latest_chapter_id:   ← 比较数据库自增 ID，不是章节编号
        标记为新章节
        更新水位线为 max(ch.id)
```

- 水位线是全局共享的（按 manga_id），不是按 UMO 隔离
- A 手动触发更新后，B 的下次更新不会重复推送已通知的章节
- 章节编号可能重复或不连续（如番外、附录），但数据库 ID 唯一递增

**各入口的缓存行为：**

| 入口 | force | 标题同步 | 章节来源 | 水位线更新 |
|------|-------|---------|---------|-----------|
| `/漫画 章节` | False | 否 | 缓存（过期才拉取） | 否 |
| `/漫画 章节 --刷新` | True | 否 | 源站 | 否 |
| `/漫画 更新` | True | 是 | 源站 | 是 |
| 后台定时更新 | True | 是 | 源站 | 是 |
| `/漫画 阅读` / `/漫画 下载` | False | 否 | 缓存 | 否 |

**章节缓存机制：**
- `_get_or_fetch_chapters(manga_id, force=False)` 管理章节数据的缓存
- 缓存时间由 `chapter_cache_hours` 配置控制（默认 6 小时）
- `0` = 仅在 DB 为空时拉取，`-1` = 每次都从源刷新
- `force=True` 可绕过缓存（通过 `--刷新` 参数或更新检查触发）
- 每个漫画的最后拉取时间戳存储在 KV key `suwayomi_chapter_timestamps`

**阅读流程：**
```
用户输入 → read_chapter() → _resolve_manga() (ID/名称/模糊匹配)
         → _get_or_fetch_chapters() → 匹配章节号（支持 ID:xxx 语法）
         → event.send(loading hint)
         → client.fetch_chapter_pages() → 获取页面 URL 列表
         → url 模式: Comp.Image.fromURL() / download 模式: _download_images() + fromFileSystem()
         → 逐页发送 / Comp.Node 合并转发
```

**下载流程：**
```
用户输入 → download_chapter() → _resolve_manga() → _get_or_fetch_chapters()
         → 匹配章节号（支持 ID:xxx 语法）
         → event.send(loading hint)
         → _fetch_pages_local() → 下载所有页面到临时目录
         → pack_zip/pack_pdf/pack_cbz() → 打包为文件
         → Comp.File() 发送文件 → 延迟清理临时目录
```

## 开发环境

### 前置条件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器
- 可访问的 Suwayomi-Server 实例（用于集成测试）

### 搭建

```bash
cd AstrBot/data/plugins/astrbot_suwayomi_server

# uv 会自动创建 .venv 并安装依赖
uv sync

# 安装开发依赖
uv add --dev pytest pytest-asyncio
```

### 运行测试

```bash
# 全部单元测试（84 个，无需网络）
uv run pytest tests/test_pack.py tests/test_models.py tests/test_client.py tests/test_subscription.py tests/test_web_api.py -v

# 实时 API 集成测试（需要 Suwayomi-Server 可访问）
uv run pytest tests/test_live_api.py tests/test_live_web_api.py -v -s

# 指定自定义服务器地址
SUWAYOMI_URL=http://your-server:9330 uv run pytest tests/test_live_api.py tests/test_live_web_api.py -v -s

# 全部测试
uv run pytest -v
```

### 语法检查

```bash
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
```

## 关键设计决策

### 为什么用 GraphQL 而不是 REST？

Suwayomi-Server 同时提供 GraphQL 和 REST API，但 GraphQL 是功能完整的主接口：
- `fetchSourceManga`（搜索）仅 GraphQL 可用
- `fetchChapterPages`（获取页面 URL）仅 GraphQL 可用
- REST 是遗留接口，功能不全

### 为什么 source ID 是字符串？

Suwayomi 的 `source` 字段类型是 `LongString`（自定义标量），不是 `Long`。GraphQL 变量声明必须用 `$sid:LongString!`，JSON 传值也必须是字符串 `"524579092615598717"` 而非数字。

### 为什么用 `filter:{title:{includes:...}}` 而不是 `condition`？

该 Suwayomi 版本的 `mangas` 查询：
- `condition: {title: "..."}` — 精确匹配，不适合模糊搜索
- `filter: {title: {includes: "..."}}` — 子串匹配，适合按标题搜索

### 为什么 `@filter.on_astrbot_loaded()` 而不是在 `__init__` 中启动后台任务？

AstrBot 加载插件时调用 `__init__`，此时事件循环可能尚未运行。`asyncio.create_task()` 需要一个运行中的事件循环。`on_astrbot_loaded` 钩子在 AstrBot 完全启动后触发，确保事件循环就绪。

### 为什么 AstrBot 命令参数都是字符串？

AstrBot 的命令分发器将所有参数作为原始字符串传递，不做类型转换。类型注解 `int` / `float` 仅用于文档目的。插件需要在入口处显式 `float()` / `int()` 转换。

## 添加新命令

1. 在 `SuwayomiPlugin` 类中添加方法
2. 使用 `@manga_group.command("命令名")` 装饰器
3. 第一个参数必须是 `event: AstrMessageEvent`
4. 使用 `yield event.plain_result(...)` 返回文本
5. 使用 `yield event.chain_result([...])` 返回富媒体
6. 在方法 docstring 中写明用法（AstrBot 展示给用户）
7. 所有用户提示文本使用 `「漫画 命令名」` 格式（带空格）

## Suwayomi GraphQL API 参考

详见 [Suwayomi API 参考](suwayomi-api.md)。
