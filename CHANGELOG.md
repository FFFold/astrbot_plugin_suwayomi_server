# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/zh-CN/).

## [Unreleased]

### Added

- **下载打包发送** — `/漫画 下载` 现在将章节页面打包为 ZIP/PDF/CBZ 文件直接发送到聊天
- **下载格式配置** — 新增 `download_format` 配置项，可选 `zip`（默认）/ `pdf` / `cbz`
- **PDF 打包依赖** — 新增 `img2pdf>=0.5.0` 运行时依赖
- **打包工具模块** — 新增 `utils/pack.py`，提供 ZIP/CBZ/PDF 打包函数
- **共享章节解析** — 抽取 `_resolve_chapter` 和 `_fetch_pages_local` 公共方法供阅读和下载复用

### Changed

- **下载命令重构** — `/漫画 下载` 不再使用 Suwayomi 服务端下载队列，改为本地下载页面图片并打包发送

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
