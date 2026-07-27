# 开发指南

本文档面向插件开发者，介绍项目架构、开发环境搭建、测试方法和代码规范。

## 项目结构

```
astrbot_suwayomi_server/
├── main.py                    # 插件入口，薄调度层——所有业务逻辑委托给子模块
├── metadata.yaml              # AstrBot 插件元数据
├── _conf_schema.json          # AstrBot 配置 schema（WebUI 自动生成配置表单）
├── requirements.txt           # Python 运行时依赖
├── suwayomi/
│   ├── __init__.py            # PLUGIN_NAME 常量
│   ├── client.py              # Suwayomi GraphQL 异步 HTTP 客户端
│   ├── models.py              # 数据模型定义
│   ├── service.py             # 业务逻辑层（漫画/章节解析、缓存策略、格式化）
│   ├── ai_service.py          # Agent 结构化搜索、章节查询与订阅管理（无发送副作用）
│   ├── ai_tools.py            # AstrBot FunctionTool Schema 与注册工厂
│   └── updater.py             # 更新引擎（check_updates + run_update_loop）
├── utils/
│   ├── __init__.py
│   ├── downloader.py          # 图片下载管道（download_one/download_images/fetch_pages_local）
│   ├── pack.py                # 图片打包工具（ZIP/CBZ/PDF）
│   ├── pusher.py              # 推送投递（push_chapter_images/push_chapter_file）+ schedule_cleanup
│   └── subscription.py        # 订阅管理器（AstrBot KV 存储封装）
├── web/
│   ├── __init__.py
│   └── api.py                 # WebUI API handler 函数（依赖注入，独立可测试）
├── pages/
│   └── dashboard/
│       ├── index.html         # 管理面板页面（3 Tab: 仪表盘/订阅管理/设置）
│       ├── app.js             # 前端逻辑（Tab 切换、API 调用、DOM 渲染）
│       └── style.css          # 样式（支持 light/dark 主题）
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # Mock astrbot 模块（独立运行集成测试）
│   ├── test_pack.py           # 打包功能单元测试
│   ├── test_models.py         # 数据模型单元测试
│   ├── test_client.py         # 客户端单元测试（mocked HTTP）
│   ├── test_subscription.py   # 订阅管理单元测试
│   ├── test_web_api.py        # WebUI API handler 单元测试
│   ├── test_batch_subscribe.py # 批量订阅参数解析单元测试
│   ├── test_push.py           # 自动推送单元测试
│   ├── test_ai_service.py     # Agent Tool 服务层单元测试
│   ├── test_ai_tools.py       # AstrBot Tool call() 调度回归测试
│   ├── test_live_api.py       # Suwayomi 客户端集成测试
│   └── test_live_web_api.py   # WebUI API handler 集成测试
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
│              main.py — SuwayomiPlugin            │
│  ┌────────────┐ ┌────────────┐ ┌──────────────┐ │
│  │ Commands   │ │ Update     │ │ Search Cache │ │
│  │ (薄调度层)  │ │ Loop (后台)│ │ (TTL 10min)  │ │
│  └──────┬─────┘ └─────┬──────┘ └──────┬───────┘ │
│         │             │               │          │
│  ┌──────▼─────────────▼───────────────▼───────┐  │
│  │          suwayomi/service.py               │  │
│  │  resolve_manga / resolve_chapter /         │  │
│  │  get_or_fetch_chapters / fmt helpers       │  │
│  └──────┬─────────────┬───────────────────────┘  │
│         │             │                          │
│  ┌──────▼─────────────▼───────┐                  │
│  │    suwayomi/client.py     │                  │
│  │ SuwayomiClient (GraphQL)  │                  │
│  └──────────┬────────────────┘                  │
│             │                                   │
│  ┌──────────▼────────────────┐                  │
│  │    suwayomi/models.py     │                  │
│  │ Source, Manga, Chapter    │                  │
│  └───────────────────────────┘                  │
│                                                  │
│  ┌───────────┐  ┌────────────┐  ┌────────────┐  │
│  │ utils/    │  │ utils/     │  │ utils/      │  │
│  │download.py│  │ pusher.py  │  │ pack.py     │  │
│  └───────────┘  └────────────┘  └────────────┘  │
│                                                  │
│  ┌───────────────────────────────────────────┐   │
│  │         utils/subscription.py             │   │
│  │  SubscriptionManager (KV Storage)         │   │
│  └───────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
                   │ GraphQL over HTTP
┌──────────────────▼──────────────────────────────┐
│           Suwayomi-Server (:4567)                │
│  /api/graphql  (GraphQL Endpoint)                │
│  /api/v1/...   (REST Legacy)                     │
└─────────────────────────────────────────────────┘
```

### 核心模块

#### `main.py` — 插件主类（薄调度层）

- 继承 `astrbot.api.star.Star`
- 使用 `@filter.command_group("漫画")` 组织命令
- `__init__` 中初始化客户端、订阅管理器、搜索缓存，注册 7 个 WebUI API 端点，并尝试启动后台循环（热重载时事件循环已运行则立即启动）
- `@filter.on_astrbot_loaded()` 中构建更新检查闭包并启动后台任务（作为首次启动的兜底）
- `terminate()` 中取消后台任务并关闭 HTTP 会话
- WebUI 保存配置时 (`rebuild_client`) 取消旧后台任务、按新间隔重启循环，并清除搜索缓存
- 搜索缓存使用 `(timestamp, {index: Manga})` 结构，10 分钟 TTL 自动过期
- 所有业务逻辑委托给 `suwayomi/service.py`、`suwayomi/updater.py`、`utils/downloader.py`、`utils/pusher.py`

#### `suwayomi/service.py` — 业务逻辑层

- 独立 async 函数，依赖注入参数（`client`、`sub_mgr`、`get_kv_data` 等）
- `resolve_manga(client, sub_mgr, umo, name_or_id, cmd)` — 按 ID 或名称模糊解析漫画
- `resolve_chapter(chapters, chapter_num, manga_name_or_id, cmd)` — 按编号或 ID 解析章节（支持重复编号检测）
- `get_or_fetch_chapters(client, get_kv_data, put_kv_data, config, manga_id, force)` — 智能缓存/拉取章节
- `search_best_match(client, config, name, source_filter)` — 跨源搜索最佳匹配
- 格式化工具：`fmt_chapter_num`、`fmt_chapter_label`、`normalize_zh`
- 缓存管理：`get_chapter_timestamp` / `set_chapter_timestamp`
- 常量：`STATUS_EMOJI`、`KV_CHAPTER_TS`

#### `suwayomi/ai_service.py` / `suwayomi/ai_tools.py` — Agent Tool 层

- `ai_tools.py` 使用显式 JSON Schema 定义并注册六个 Tool：`suwayomi_search_manga`、`suwayomi_get_chapters`、`suwayomi_send_chapter`、`suwayomi_subscribe_manga`、`suwayomi_get_subscriptions`、`suwayomi_unsubscribe_manga`
- Tool 子类覆写 `call()` 并从 Agent `ContextWrapper` 取得当前事件，不依赖 `star_manager` 只执行一次的 handler partial 绑定，因此保存配置后重新注册仍可正常调用
- `ai_service.py` 负责跨源并行搜索、漫画元数据序列化、章节选择和重复章节候选返回、订阅/取消订阅/订阅列表查询，不发送消息
- 搜索与章节 Tool 返回稳定 `manga_id` / `chapter_id`，不依赖命令模式的数字编号缓存
- 阅读发送候选按 `(unified_msg_origin, sender_id)` 隔离 10 分钟，同一时间仅允许一个发送任务（`asyncio.Lock` 防止并发）
- AstrBot 成功执行 `/reset` 后，`after_message_sent` 钩子按 `unified_msg_origin` 清除搜索缓存、AI 章节候选和发送锁；权限拒绝或重置失败不清理
- `suwayomi_send_chapter` 只有在 `allow_ai_send=true`、用户意图已确认且章节来自当前发送者最近查询结果时才发送；默认打包 PDF，用户可明确指定 ZIP、CBZ 或图片
- 订阅 Tool 均含 `confirmed_user_intent` 守卫，防止 Agent 未确认即执行有副作用的 KV 写入；`suwayomi_subscribe_manga` 支持可选 `push_enabled` 参数同时开启自动推送，已订阅时仍可补充开启推送

#### `suwayomi/updater.py` — 更新引擎

- `check_updates(client, sub_mgr, context, config, get_kv_data, put_kv_data, update_lock, push_chapter_images_fn, push_chapter_file_fn, force)` — 全部订阅检查，同步标题，检测新章节，推送通知，自动推送内容。`update_library()` 调用有 30 秒超时，避免挂死。
- `run_update_loop(interval, check_fn)` — 后台循环包装器，被 `main.py` 的 `_start_bg_task` 启动。正确处理 `CancelledError`，Task 异常退出时有日志记录。
- 所有依赖通过参数注入，`push_chapter_images_fn` 和 `push_chapter_file_fn` 在 `main.py` 的 `_build_check_updates_fn` 中预绑定

#### `utils/downloader.py` — 图片下载管道

- `download_one(session, url, dest, retries)` — 单图下载，指数退避重试
- `download_images(urls, concurrency, custom_tmp, retries)` — 并行批量下载，返回 `(paths, tmp_dir)`
- `fetch_pages_local(client, chapter_id, max_pages, concurrency, custom_tmp, retries)` — 获取页面列表并下载到临时目录，返回 `(total_pages, page_urls, local_paths, tmp_dir)`

#### `utils/pusher.py` — 推送投递

- `push_chapter_images(client, context, config, umo, title, chapter, fetch_pages_local_fn, fmt_chapter_num_fn)` — 推送章节为图片（支持 `send_mode=forward` 合并转发）
- `push_chapter_file(context, config, umo, title, chapter, fetch_pages_local_fn, fmt_chapter_num_fn)` — 推送章节为打包文件（ZIP/CBZ/PDF）
- `schedule_cleanup(tmp_dir, delay)` — 延迟清理临时目录（消除 4 处重复的 asyncio 任务）
- `is_aiocqhttp_target(context, umo)` — 检测平台是否为 aiocqhttp（用于 forward 模式判断）

#### `suwayomi/client.py` — GraphQL 客户端

- 基于 `aiohttp.ClientSession` 的异步 HTTP 客户端
- 所有 Suwayomi 交互通过 `POST /api/graphql` 发送 GraphQL 查询/变更
- 支持三种认证模式：无认证、Basic、JWT（自动刷新）
- `_post_graphql()` — 底层 HTTP POST，处理 JSON 解析、错误归一化、网络异常捕获
- `_raw_query()` — 上层认证查询，调用 `_ensure_jwt()`，通过 `_response_data()` 统一校验响应
- JWT 认证使用 `asyncio.Lock` 保护，`_is_unauthorized()` 检测 HTTP 401 / GraphQL Unauthorized 两种失效，`_renew_jwt()` 自动执行 refresh → re-login 降级续期

#### `suwayomi/models.py` — 数据模型

- 纯数据类（`@dataclass`），无副作用
- `from_dict()` 工厂方法处理 API 返回的 JSON，强制类型转换（API 返回字符串数字）
- `Source.id` 为 `str` 类型（Suwayomi 的 `LongString` 标量）

#### `utils/subscription.py` — 订阅管理

- 通过 AstrBot 的 `get_kv_data()` / `put_kv_data()` 持久化
- 数据结构：`{manga_id: {title, source_id, latest_chapter_id, subscribers: {umo: {push_enabled: bool}}}}`
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

**批量订阅流程：**
```
用户输入 → batch_subscribe() → 按逗号/分号分割名称列表
          → 逐个 suwayomi.service.search_best_match() → client.search_manga() → 取第一个结果
          → 检查是否已订阅 → sub_mgr.subscribe() + 快照章节水位线
          → 汇总报告（✅ 新增 / ⏭ 已存在 / ❌ 失败）
```

**订阅更新流程：**
```
updater.run_update_loop (定时) → updater.check_updates(force=True)
                              → client.update_library() (30s 超时) (触发书库更新)
                              → 遍历订阅 → 同步标题 + service.get_or_fetch_chapters() + 对比 latest_chapter_id
                              → 发现新章节 → context.send_message() 推送到各订阅者
                              → 对开启自动推送的订阅者: pusher.push_chapter_images() / pusher.push_chapter_file()
```

**后台循环生命周期：**
```
fresh startup: __init__ → asyncio.get_running_loop() 无运行中循环 → 跳过
             → on_astrbot_loaded() → _start_bg_task() 启动
hot reload:   __init__ → asyncio.get_running_loop() 已运行 → _try_start_bg_loop() → _start_bg_task()
config save:  rebuild_client() → 取消旧 bg_task → _try_start_bg_loop() → 按新间隔重启
terminate:    _bg_task.cancel() → 清理
```
`_bg_task is None` 守卫防止重复启动。

**更新机制核心方法：**

| 方法 | 职责 | 调用者 |
|------|------|--------|
| `updater.check_updates(force)` | 主更新逻辑：同步标题、拉取章节、检测新章节、推送通知 | `/漫画 更新`（force=True）、后台定时更新（force=True） |
| `service.get_or_fetch_chapters(manga_id, force)` | 章节获取：读缓存或从源拉取 | `check_updates`、`/漫画 章节`、`/漫画 阅读`、`/漫画 下载` |
| `service.get_chapter_timestamp(manga_id)` / `service.set_chapter_timestamp(manga_id)` | 管理每个漫画的章节缓存时间戳 | `get_or_fetch_chapters`、`check_updates` |
| `SubscriptionManager.update_latest_chapter(manga_id, chapter_id)` | 更新水位线（已通知到的最大章节 ID） | `check_updates` |
| `SubscriptionManager.update_title(manga_id, new_title)` | 同步漫画标题（仅在变化时写入） | `check_updates` |

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
| `/漫画 章节` | 使用 `service.get_or_fetch_chapters` 决定 | 否 | 缓存（过期才拉取） | 否 |
| `/漫画 章节 --刷新` | 传递 force=True | 否 | 源站 | 否 |
| `/漫画 更新` | force=True | 是 | 源站 | 是 |
| 后台定时更新 | force=True | 是 | 源站 | 是 |
| `/漫画 阅读` / `/漫画 下载` | 使用 `service.get_or_fetch_chapters` 决定 | 否 | 缓存 | 否 |

**章节缓存机制：**
- `service.get_or_fetch_chapters(client, get_kv_data, put_kv_data, config, manga_id, force=False)` 管理章节数据的缓存
- 缓存时间由 `chapter_cache_hours` 配置控制（默认 6 小时）
- `0` = 仅在 DB 为空时拉取，`-1` = 每次都从源刷新
- `force=True` 可绕过缓存（通过 `--刷新` 参数或更新检查触发）
- 每个漫画的最后拉取时间戳存储在 KV key `suwayomi_chapter_timestamps`

**阅读流程：**
```
用户输入 → read_chapter() → service.resolve_manga() (ID/名称/模糊匹配)
         → service.get_or_fetch_chapters() → service.resolve_chapter()（支持 ID:xxx 语法）
         → event.send(loading hint)
         → client.fetch_chapter_pages() → 获取页面 URL 列表
         → url 模式: Comp.Image.fromURL()
         → download 模式: downloader.fetch_pages_local() + Comp.Image.fromFileSystem()
         → 逐页发送 / Comp.Node 合并转发
         → pusher.schedule_cleanup() 延迟清理临时文件
```

**下载流程：**
```
用户输入 → download_chapter() → service.resolve_manga() → service.get_or_fetch_chapters()
         → service.resolve_chapter()（支持 ID:xxx 语法）
         → event.send(loading hint)
         → downloader.fetch_pages_local() → 下载所有页面到临时目录
         → pack_zip/pack_pdf/pack_cbz() → 打包为文件
         → Comp.File() 发送文件 → pusher.schedule_cleanup() 延迟清理
```

**自动推送流程：**
```
updater.check_updates() 检测到新章节 → 遍历订阅者：
  ├─ pusher.push_chapter_images() — 图片模式
  │   ├─ fetch 页面 URL client.fetch_chapter_pages()
  │   ├─ 或 downloader.fetch_pages_local()（image_fetch_mode=download）
  │   ├─ context.send_message() 发送图片/forward
  │   └─ schedule_cleanup() 清理
  └─ pusher.push_chapter_file() — 文件模式
      ├─ downloader.fetch_pages_local() 下载全部页面
      ├─ pack_zip/pack_pdf/pack_cbz() 打包
      ├─ context.send_message() 发送文件
      └─ schedule_cleanup() 清理
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
# 全部单元测试（无需网络）
uv run pytest tests/test_pack.py tests/test_models.py tests/test_client.py tests/test_subscription.py tests/test_web_api.py tests/test_batch_subscribe.py tests/test_push.py tests/test_service.py tests/test_ai_service.py tests/test_ai_tools.py -v

# 实时 API 集成测试（需要 Suwayomi-Server 可访问）
uv run pytest tests/test_live_api.py tests/test_live_web_api.py -v -s

# 指定自定义服务器地址（推荐：先设置环境变量避免连接默认 :4567 失败）
$env:SUWAYOMI_URL="http://your-server:9330"; uv run pytest tests/test_live_api.py tests/test_live_web_api.py -v -s

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
