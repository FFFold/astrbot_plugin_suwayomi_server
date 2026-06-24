# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/zh-CN/).

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
