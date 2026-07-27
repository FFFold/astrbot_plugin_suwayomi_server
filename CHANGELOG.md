# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/zh-CN/).

## [Unreleased]

### Added

- **AI 订阅管理工具** — 新增三个 AstrBot Tool：`suwayomi_subscribe_manga`（订阅漫画并可选开启自动推送，已订阅时支持补充开启 `push_enabled`）、`suwayomi_get_subscriptions`（查询当前会话订阅列表，含 `push_enabled` 状态）、`suwayomi_unsubscribe_manga`（取消订阅，已取消时返回友好提示）。新增 `subscribe_manga_for_agent()`、`get_subscriptions_for_agent()`、`unsubscribe_manga_for_agent()` 至 `suwayomi/ai_service.py`。`SubscriptionManager.get_subscriptions()` 返回值新增 `push_enabled` 字段。

### Changed

- **移除无效的章节已读/收藏字段** — `Chapter` 模型中移除 `is_read`、`last_page_read`、`is_bookmarked`（Suwayomi 后端标记对 Bot 用户无意义），同步清理 GraphQL 查询、章节列表显示、AI agent 输出和所有测试。

## [0.5.0] - 2026-07-14

### Added

- **AI Agent 漫画工具** — 注册三个 AstrBot Tool：`suwayomi_search_manga`（自然语言跨源搜索）、`suwayomi_get_chapters`（章节查询，支持 `latest`/`list`/章节号/`ID:数字`）、`suwayomi_send_chapter`（仅明确阅读意图时发送，默认 PDF，支持 ZIP/CBZ/图片；`asyncio.Lock` 防并发，允许失败重试）。新增 `suwayomi/ai_service.py`（无副作用服务层）和 `suwayomi/ai_tools.py`（`SuwayomiFunctionTool` 子类，`call()` 覆写保证配置重载后绑定稳定）。PR #9。
  - **AI 交互状态管理** — `AiInteractionState` 按 `(unified_msg_origin, sender_id)` 隔离章节候选；`asyncio.Lock` 防并发发送；`after_message_sent` 钩子联动 `/reset` 自动清除会话状态。
  - **AI 工具配置项** — `enable_ai_tools`、`allow_ai_send`、`ai_max_sources`、`ai_results_per_source`、`ai_tool_timeout_sec`，完整暴露于配置 Schema、WebUI 和文档。
  - **章节发送重构** — 提取 `_prepare_chapter_delivery`（图片模式）和 `_prepare_chapter_file_delivery`（文件模式）为 `/漫画 阅读` 和 AI Tool 共享。
  - **回归测试** — `tests/test_ai_service.py`（13 个）、`tests/test_ai_tools.py`（4 个）、Web API 配置边界测试。
  - **运行时依赖** — 新增 `pydantic>=2.12.5,<3`。

### Changed

- **下载默认格式改为 PDF** — `download_format` 默认值从 `zip` 改为 `pdf`，与 AI Tool 默认格式统一。同时 `parse_download_args()` 函数参数默认值、`pusher.py` 兜底默认值一并修改。

## [0.4.9] - 2026-07-12

### Fixed

- **JWT 认证无限递归** — `_ensure_jwt` 通过 `_raw_query` 发登录请求形成递归死循环。PR #8 拆分 `_post_graphql()` 无状态 HTTP 层，登录绕过认证路径。
- **GraphQL `Unauthorized` 未触发令牌刷新** — 新增 `_is_unauthorized()` 同时检测 HTTP 401 和 GraphQL errors 中的认证失败。
- **网络连接错误处理** — 捕获 `aiohttp.ClientError` 和 `asyncio.TimeoutError`，明确定义「无法连接到 Suwayomi-Server」。

### Changed

- **`client.py` 架构重构** — 拆分为 `_post_graphql()`（HTTP 层）、`_response_data()`（响应校验）、`_renew_jwt()`（令牌续期中枢，`asyncio.Lock` 防并发）。
- **`_refreshing: bool` → `_jwt_lock: asyncio.Lock`** — 原子化令牌管理。

### Added

- **JWT 认证回归测试** — 7 个异步测试覆盖递归、双重认证失效检测、令牌降级续期和异常响应处理。

## [0.4.8] - 2026-07-10

### Fixed

- **章节标签优先使用章节标题** — 推送、阅读提示、文件名中的「第X话」全部改用章节实际名称（如「07卷附录」）。
- **兼容全角冒号 `ID：xxx`** — `resolve_chapter` 同时接受半角 `:` 和全角 `：`。

### Added

- **`fmt_chapter_display(ch)`** — 章节显示标签工具函数。
- **`tests/test_service.py`** — 19 个单元测试。

## [0.4.7] - 2026-07-07

### Changed

- **项目结构重构** — `main.py` 拆分为 4 个模块（`suwayomi/service.py`、`suwayomi/updater.py`、`utils/downloader.py`、`utils/pusher.py`），各模块遵循依赖注入模式；`PLUGIN_NAME` 统一到 `suwayomi/__init__.py`

### Fixed

- **后台更新循环静默失败** — `update_library` 添加 30s 超时；`run_update_loop` 补全兜底日志和 Task 异常回调；无订阅时不再静默返回。
- **热重载后后台循环不启动** — `on_astrbot_loaded` 在热重载时不触发，改为 `__init__` 中检测事件循环状态，已运行时直接启动。
- **WebUI 改配置后间隔不生效** — `rebuild_client` 现取消旧后台任务并按新间隔重启循环，同时清除搜索缓存。
- **`_build_check_updates_fn` 中的参数顺序和闭包问题** — push callbacks 与数据参数顺序不匹配；后台 lambda 未延迟解析导致 `rebuild_client` 后仍引用旧客户端；手动/Web API 更新缺 None guard
- **`resolve_chapter` 错误消息** — 区分 ID 格式无效与 ID 未找到
- **临时目录清理遗漏** — `download_chapter` 和 `push_chapter_file` 在早期 return 路径中缺少清理

### Removed

- **移除 UIN 获取逻辑** — 删除 `_get_bot_uin()`、`_uin_cache` 及相关代码。此前 SnowLuma 对 forward 节点 `uin="0"` 报错，故引入 `get_login_info` API 获取 bot 真实 QQ 号作为 workaround。SnowLuma 已在上游 commit `b6107e38` 修复：`user_id="0"` 或缺失时自动 fallback 到 `selfId`，与 NapCat/LLBot 行为对齐。现所有已知 OneBot 实现均接受 `uin="0"`，因此移除该冗余逻辑。两个 forward 分支（`_push_chapter_images` 自动推送、`漫画 阅读` 命令）统一使用 `uin="0"`。同时修复了 `漫画 阅读` 命令误用 `event.get_sender_id()`（用户 QQ 而非 bot QQ）的问题。
- **内联方法** — `_push_chapter_images/file`、`_download_one/images/fetch_pages_local`、`_resolve_manga/chapter`、`_fmt_*`、`_check_updates/update_loop`、`_normalize_zh`、`STATUS_EMOJI` 等移至对应模块；`push_chapter_file` 未使用的 `client` 参数移除；测试 fixture 弃用 `asyncio.get_event_loop().run_until_complete()`

## [0.4.6] - 2026-07-05

### Fixed

- **`updateLibrary` GraphQL 字段错误** — `update_library()` 查询了 `{updateStatus{state}}`，但 `LibraryUpdateStatus` 类型没有 `state` 字段——`isRunning` 存在于 `jobsInfo` 子字段中。修复为 `{updateStatus{jobsInfo{isRunning}}}`。此前错误被 `_check_updates()` 中的 `except` 静默吞掉，导致"检查更新"返回假成功。同时给 `api_status()` 中的三个 `except Exception: pass` 添加了日志输出，避免未来连接问题无法排查。

### Changed

- **配置教程更新** — `docs/setup.md` 简化验证步骤，补充扩展库添加说明。
- **API 文档更新** — `docs/dev/suwayomi-api.md` 中 `updateLibrary` mutation 更正为 `updateStatus { jobsInfo { isRunning } }`。
- **`api_status()` 错误日志** — `get_sources()`、`get_library_mangas()`、`get_all_subscriptions()` 三个调用的异常从静默忽略改为记录 `logger.warning()`。

## [0.4.5] - 2026-07-04

### Changed

- **订阅数据结构重构** — 将 `subscribers` 从 `list[str]` 改为 `dict[str, dict]`，`auto_push` 字段合并到 `subscribers` 中，消除订阅人数 vs 推送开启人数不一致的 bug。
  - 新结构：`subscribers: {umo: {push_enabled: bool}}`，存在即订阅
  - 取消订阅时自动清除所有关联状态
  - 自动迁移旧格式（list → dict），无需手动干预
  - `set_auto_push` 和 `is_auto_push_enabled` 等公开方法接口不变

## [0.4.4] - 2026-07-04

### Fixed

- **自动推送 TypeError** — 修复 `_push_chapter_images` 和 `_push_chapter_file` 中调用 `MessageChain().chain(chain)` 导致的 `TypeError: 'list' object is not callable` 错误。`chain` 是 `MessageChain` 的列表字段而非方法，应使用 `MessageChain(chain=chain)` 构造。此 bug 导致所有启用自动推送的订阅在更新时都抛出异常，降级为"图片发送失败"文本提示。
- **自动推送忽略合并转发配置** — 修复 `_push_chapter_images` 不检查 `send_mode` 配置，始终以单条内联消息发送全部图片的问题。当群聊有 30+ 页时，QQ NT 拒绝单条消息中的过多图片元素（`result: 34` / `retcode 1200`）。现在自动推送复用阅读指令的发送逻辑：`send_mode=forward` 时在 aiocqhttp 平台用 `Comp.Nodes`（合并转发）发送；非 QQ 平台或 `send_mode=image` 时回退为内联发图。
- **合并转发节点缺少真实 user_id** — 修复 forward 节点中 `uin="0"` 被新版 Napcat 拒绝的问题（`forward node user_id/uin is required`）。新增 `_get_bot_uin()` 通过 `get_login_info` API 获取机器人真实 QQ 号并缓存，用于 forward 节点的 `user_id`。

## [0.4.1] - 2026-06-27

### Added

- **批量订阅** — 新增 `「漫画 批量订阅」` 命令，支持一次订阅多部漫画，逗号/分号分隔名称，自动搜索最佳匹配，逐个反馈进度，汇总报告（新增/已存在/失败），支持指定源，最多 20 部
- **批量订阅单元测试** — 新增 `tests/test_batch_subscribe.py`（11 个测试），覆盖参数解析：中英文逗号、分号、混合分隔符、源名过滤、空白处理

### Fixed

- **`default_source_id` 类型比较** — 修复 `Source.id`（str）与配置值（int）比较永远不匹配的 bug，影响 `search_manga` 和新增的 `_search_best_match`
- **我的订阅格式统一** — 改为 `标题 - 源名 - ID: xxx` 格式，源名获取失败时降级显示
- **章节列表标题格式** — 统一为 `标题 - 源名 章节列表`，续行消息同步修复
- **批量订阅源名查找** — 修复 `src.id`（str）与 `manga.source_id`（int）类型不匹配导致源名始终为空的问题

## [0.4.0] - 2026-06-27

### Added

- **管理员 WebUI** — 新增 AstrBot Plugin Pages 管理界面，包含 3 个 Tab：
  - **仪表盘** — Suwayomi 连接状态、源数量、书库漫画数、订阅统计、订阅总览表、手动检查更新
  - **订阅管理** — 跨所有用户的订阅列表，支持按漫画 ID、漫画名、源、订阅者（UMO）、推送状态五个维度同时筛选，删除单条订阅、自定义确认弹窗
  - **设置** — 可视化编辑全部插件配置（服务器连接、阅读体验、下载打包、自动推送、高级选项）
- **WebUI API 模块** — 新增 `web/api.py`，7 个独立 API handler（status, subscriptions CRUD, config, sources, update），依赖注入便于测试
- **SubscriptionManager.delete_manga()** — 新增公开方法删除漫画的全部订阅者，替代直接访问私有 `_load`/`_save`
- **API 集成测试** — 新增 `tests/test_live_web_api.py`（19 个测试），覆盖所有 WebUI API handler 的端到端调用
- **多维筛选** — 订阅管理支持漫画 ID / 漫画名 / 源 / 订阅者 / 推送状态五个筛选条件同时生效，带计数显示和一键清除

### Changed

- **项目结构重构** — API handler 从 `main.py` 提取到 `web/api.py`，`main.py` 仅负责注册和委托
- **测试扩充** — 单元测试从 51 个增加到 95 个，集成测试新增 19 个 WebUI API 测试

## [0.3.2] - 2026-06-26

### Fixed

- **漫画标题同步** — 订阅的漫画在源站改名后，更新检查时自动同步最新标题到本地存储
- **空搜索防护** — `/漫画 搜索` 不带关键词时返回用法提示，不再触发空搜索请求
- **手动更新强制刷新** — `/漫画 更新` 现在绕过缓存，强制从源拉取章节并同步标题
- **后台更新强制刷新** — 后台定时更新检查也绕过缓存，确保及时发现新章节；缓存仅用于 `/漫画 章节` 浏览

### Added

- **章节列表显示源名** — `/漫画 章节` 回复标题中显示漫画所属源名称（如 `[MangaDex]`）

### Changed

- **文档补充** — 明确说明 `/漫画 更新` 会全局推送通知给所有订阅者

## [0.3.0] - 2026-06-26

### Added

- **自动推送漫画内容** — 发现更新时自动推送章节图片或打包文件到聊天（默认关闭）
- **推送命令组** — `/漫画 推送 开` 开启自动推送、`/漫画 推送 关` 关闭、`/漫画 推送 状态` 查看当前状态
- **推送模式配置** — 新增 `auto_push_mode` 配置项：`image`（图片模式，复用阅读逻辑）/ `file`（文件模式，复用下载逻辑）
- **per-会话控制** — 每个聊天会话独立控制自动推送开关，默认关闭
- **订阅时快照章节** — 订阅时立即记录当前最大章节 ID，避免首次更新推送全部已有章节

### Changed

- `SubscriptionManager` 新增 `set_auto_push`、`get_auto_push`、`is_auto_push_enabled`、`set_auto_push_all` 方法
- 推送失败自动降级为文本提示，章节间 2 秒间隔防刷屏
- 临时文件清理使用 `try/finally` 确保异常时也能正确清理

## [0.2.2] - 2026-06-26

### Fixed

- **章节排序** — 章节列表和更新通知改为按源站顺序（`source_order`）排序，附录/番外等按源站意图排列
- **简繁匹配** — 漫画名匹配（章节/阅读/下载/取消订阅）对简繁中文不敏感，使用 OpenCC 归一化后比较
- **多结果引导** — 匹配到多个漫画时提示具体命令用法（如 `/漫画 章节 151`）

### Changed

- 新增 `opencc-python-reimplemented` 运行时依赖

## [0.2.1] - 2026-06-25

### Fixed

- **多漫画更新推送丢失** — 修复当多部漫画同时更新时，用户只收到第一部漫画的更新通知，其余被跳过的问题。现在同一用户的所有更新合并为一条消息发送

## [0.2.0] - 2026-06-25

### Added

- **下载打包发送** — `/漫画 下载` 现在将章节页面打包为 ZIP/PDF/CBZ 文件直接发送到聊天
- **下载格式配置** — 新增 `download_format` 配置项，可选 `zip`（默认）/ `pdf` / `cbz`
- **临时目录配置** — 新增 `temp_dir` 配置项，Docker 环境可设置共享目录
- **PDF 打包依赖** — 新增 `img2pdf>=0.5.0` 运行时依赖
- **打包工具模块** — 新增 `utils/pack.py`，提供 ZIP/CBZ/PDF 打包函数和 `parse_download_args()` 参数解析
- **共享章节解析** — 抽取 `_resolve_chapter` 和 `_fetch_pages_local` 公共方法供阅读和下载复用

### Changed

- **下载命令重构** — `/漫画 下载` 不再使用 Suwayomi 服务端下载队列，改为本地下载页面图片并打包发送
- **非阻塞打包** — 打包和清理操作改为异步执行，避免阻塞事件循环

### Fixed

- **AstrBot 参数拆分** — 修复 `--刷新` 和下载格式参数因 AstrBot 参数拆分而丢失的问题，改为从原始消息解析
- **Windows 文件名** — 修复章节号为 `?` 时文件名包含非法字符的问题

## [0.1.4] - 2026-06-25

### Added

- **章节缓存机制** — 新增 `chapter_cache_hours` 配置项，控制章节数据自动刷新间隔（默认 6 小时）
- **强制刷新参数** — `/漫画 章节 <漫画名> --刷新` 可绕过缓存，从源重新拉取章节数据
- **缓存时间戳** — 使用 KV 存储记录每个漫画的章节拉取时间，支持按漫画独立缓存

### Changed

- **章节获取逻辑** — `_get_or_fetch_chapters()` 现在根据缓存时间自动决定是否从源刷新，而非仅在 DB 为空时拉取

## [0.1.3] - 2026-06-25

### Added

- **帮助命令** — `/漫画 帮助` 显示完整用法说明
- **阅读加载提示** — 发送 `/漫画 阅读` 后立刻提示「正在加载」，再后台加载图片
- **图片本地缓存** — 新增 `image_fetch_mode` 配置项：`url`（直接引用）/ `download`（先下载到本地再发送，更可靠）
- **并行下载** — 下载模式使用 `asyncio.gather` 并行下载，默认 6 路并发
- **下载重试** — 下载失败自动重试 3 次，指数退避（0.5s → 1s → 2s）
- **可配置并发与重试** — `download_concurrency` 和 `download_retries` 配置项
- **章节列表拆分发送** — 章节过多时自动拆分为多条消息（~1500 字符/条），不再截断
- **更新推送带章节名** — 推送通知显示章节标题，重复编号显示 ID
- **重名漫画区分** — 多个同名漫画显示所属漫画源和连载状态
- **自动拉取章节** — 订阅、章节列表、阅读、下载命令在章节数据为空时自动从源拉取

### Fixed

- **缺失参数提示** — `/漫画 阅读` 和 `/漫画 下载` 不带章节号时显示用法示例
- **ID: 大小写** — `id:123`、`ID:123`、`Id:123` 均可识别
- **源名显示** — 重名漫画区分时显示源名称而非源 ID 数字
- **异常传播** — 章节拉取失败时显示「获取章节失败」而非「暂无章节」
- **加载提示阻断** — 提示消息发送失败不影响图片加载
- **临时文件清理** — 下载的临时图片延迟 60 秒清理，防止平台未读完即删除

## [0.1.2] - 2026-06-24

### Added

- **配置教程** — 新增 `docs/setup.md`，包含 Suwayomi-Server Docker 部署、漫画源安装、插件配置的完整步骤及常见问题解答
- **AGENTS.md** — 新增开发者快速上手指南，记录 GraphQL API 陷阱和 AstrBot 框架注意事项

### Fixed

- 配置教程中移除废弃的 Docker Compose `version` 键、修正 YAML 引号、澄清认证模式映射关系

## [0.1.1] - 2026-06-24

### Fixed

- **QQ 合并转发修复** — 使用 `send_mode: forward` 时，所有页面图片现在正确打包为一条合并转发消息发送，而非每张图片各自一个转发包

### Changed

- **文档重组** — 用户文档（README）与开发者文档（docs/dev/）分离
- 新增 `docs/dev/development.md`：架构概览、开发环境、测试方法、设计决策
- 新增 `docs/dev/suwayomi-api.md`：插件实际使用的 GraphQL API 参考

## [0.1.0] - 2026-06-24

### Added

- **漫画搜索** — 从多个已安装源搜索漫画，支持按源名过滤
- **漫画源列表** — 查看 Suwayomi-Server 中所有已安装的漫画源
- **漫画订阅/取消订阅** — 订阅搜索结果中的漫画，支持按 ID 或名称取消
- **订阅列表** — 查看当前会话的所有订阅
- **章节列表** — 查看漫画的章节列表，标记已读/已下载状态，自动识别重复章节编号
- **章节阅读** — 在聊天中直接发送章节页面图片，支持直接发图和合并转发两种模式
- **章节下载** — 将章节加入 Suwayomi 下载队列
- **更新推送** — 后台定时检查订阅漫画的新章节并推送到聊天会话
- **手动更新** — `/漫画 更新` 命令手动触发更新检查
- **多源搜索** — 默认搜索前 5 个源，可配置默认源 ID，也可在搜索时指定源名
- **漫画名模糊匹配** — 支持按名称模糊查找漫画（库内搜索 + 订阅列表匹配）
- **章节 ID 选择** — 重复章节编号时提示用户通过 `id:xxx` 语法精确选择
- **认证支持** — 支持无认证、Basic 认证、JWT 认证三种模式
- **平台兼容** — 支持 aiocqhttp、Telegram、QQ Official、WeCom、Lark、DingTalk、Discord、Slack、Kook 等平台
- **搜索缓存** — 搜索结果缓存 10 分钟，支持直接通过编号订阅
- **单元测试** — 26 个单元测试覆盖数据模型、客户端、订阅管理
- **集成测试** — 11 个实时 API 集成测试验证与 Suwayomi-Server 的实际交互

### Technical

- 基于 aiohttp 的异步 GraphQL HTTP 客户端
- 使用 AstrBot KV 存储持久化订阅数据
- asyncio.Lock 防止更新检查并发执行
- JWT 令牌自动刷新，带递归保护
- 后台任务通过 `@filter.on_astrbot_loaded()` 延迟启动，确保事件循环就绪
