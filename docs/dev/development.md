# 开发指南

本文档面向插件开发者，介绍项目架构、开发环境搭建、测试方法和代码规范。

## 项目结构

```
astrbot_suwayomi_server/
├── main.py                    # 插件入口，所有命令定义和后台更新逻辑
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
├── tests/
│   ├── __init__.py
│   ├── test_models.py         # 数据模型单元测试（9 个）
│   ├── test_client.py         # 客户端单元测试（6 个）
│   ├── test_subscription.py   # 订阅管理单元测试（11 个）
│   └── test_live_api.py       # 实时 API 集成测试（11 个）
├── docs/
│   ├── dev/                   # 开发者文档（本目录）
│   ├── superpowers/           # 设计文档和实现计划
│   └── CHANGELOG.md           # 版本变更日志
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
│  │ (10 个命令)│ │ Loop (后台)│ │ (TTL 10min)  │ │
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
- 数据结构：`{manga_id: {title, source_id, latest_chapter_id, subscribers: [umo, ...]}}`
- `umo`（`unified_msg_origin`）是 AstrBot 的会话唯一标识

### 数据流

**搜索流程：**
```
用户输入 → search_manga() → 遍历目标源 → client.search_manga() → GraphQL fetchSourceManga
         → 合并结果 → 缓存到 _search_cache → 返回列表
```

**订阅更新流程：**
```
_update_loop (定时) → _check_updates() → client.update_library() (触发书库更新)
                   → 遍历订阅 → _get_or_fetch_chapters() → 对比 latest_chapter_id
                   → 发现新章节 → context.send_message() 推送到各订阅者
```

**章节缓存机制：**
- `_get_or_fetch_chapters(manga_id, force=False)` 管理章节数据的缓存
- 缓存时间由 `chapter_cache_hours` 配置控制（默认 6 小时）
- `0` = 仅在 DB 为空时拉取，`-1` = 每次都从源刷新
- `force=True` 可绕过缓存（通过 `--刷新` 参数触发）
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
# 全部单元测试（26 个，无需网络）
uv run pytest tests/test_models.py tests/test_client.py tests/test_subscription.py -v

# 实时 API 集成测试（需要 Suwayomi-Server 可访问）
uv run pytest tests/test_live_api.py -v -s

# 指定自定义服务器地址
SUWAYOMI_URL=http://your-server:9330 uv run pytest tests/test_live_api.py -v -s

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
