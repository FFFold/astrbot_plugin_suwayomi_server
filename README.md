<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="logo.png">
    <img src="https://raw.githubusercontent.com/FFFold/astrbot_plugin_suwayomi_server/main/logo.png" alt="Suwayomi 漫画助手" width="128" height="128">
  </picture>
  <br>
  <h1 align="center"><b>📖 Suwayomi 漫画助手</b></h1>
  <p align="center">
    基于 <a href="https://github.com/Suwayomi/Suwayomi-Server">Suwayomi-Server</a> 的 AstrBot 漫画插件
    <br>
    搜索 · 阅读 · 下载 · 订阅更新 · 多平台
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/AstrBot-%3E%3D4.16-blue?style=flat-square" alt="AstrBot >= 4.16">
    <img src="https://img.shields.io/badge/Python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
    <img src="https://img.shields.io/badge/license-AGPL--3.0-orange?style=flat-square" alt="License AGPL-3.0">
    <img src="https://img.shields.io/badge/version-0.4.2-8A2BE2?style=flat-square" alt="Version 0.4.1">
    <img src="https://img.shields.io/badge/support-8%20platforms-green?style=flat-square" alt="8 platforms">
  </p>
</p>

---

将 [Suwayomi-Server](https://github.com/Suwayomi/Suwayomi-Server) 作为漫画后端，为聊天平台（QQ / Telegram / Discord 等）提供漫画搜索、在线阅读、批量下载和订阅更新推送服务。

> 🚀 **首次使用？** 查看 [Suwayomi-Server 部署教程](docs/setup.md) 快速上手。

---

## ✨ 特性

| | 功能 | 说明 |
|---|---|---|
| 🔍 | **多源搜索** | 跨多个已安装漫画源全局搜索，智能合并结果 |
| 📖 | **在线阅读** | 直接在聊天中阅读漫画章节，支持逐页发送或合并转发 |
| ⬇️ | **章节下载** | 下载章节页面并打包为 ZIP/PDF/CBZ 文件发送到聊天 |
| 🔔 | **订阅更新** | 订阅漫画后自动推送新章节通知，支持自定义检查间隔 |
| 🔄 | **章节缓存** | 章节数据自动缓存可配置时长（默认 6h），也支持强制刷新 |
| 🏷️ | **重复章节处理** | 智能识别重复章节号，通过 ID 精确选择 |
| 🔐 | **多种认证** | 支持无认证 / Basic / JWT 三种 Suwayomi 认证模式 |
| 🖼️ | **灵活发图** | 直接引用 URL 或先下载到本地再发送，适配不同网络环境 |
| 🌐 | **多平台** | 支持 aiocqhttp / Telegram / QQ官方 / 企业微信 / 飞书 / Discord / Slack / KOOK |
| 🖥️ | **管理面板** | AstrBot WebUI 内嵌仪表盘：连接状态总览、订阅管理、配置编辑 |

---

## 📋 命令

| 命令 | 说明 |
|---|---|
| `/漫画 源` | 列出所有已安装的漫画源 |
| `/漫画 搜索 <关键词> [源名]` | 从多个源搜索漫画 |
| `/漫画 订阅 <编号>` | 订阅搜索结果中的漫画 |
| `/漫画 批量订阅 <名称1>, <名称2>, ... [源名]` | 批量订阅多部漫画（逗号分隔） |
| `/漫画 取消订阅 <ID或名称>` | 取消订阅指定漫画 |
| `/漫画 我的订阅` | 查看当前会话的订阅列表 |
| `/漫画 更新` | 手动触发更新检查（全局推送） |
| `/漫画 章节 <漫画名或ID> [--刷新]` | 查看章节列表，`--刷新` 强制从源拉取最新数据 |
| `/漫画 阅读 <漫画名或ID> <章节号>` | 阅读指定章节（发送页面图片） |
| `/漫画 下载 <漫画名或ID> <章节号> [格式]` | 下载章节并打包发送（格式: zip/pdf/cbz） |
| `/漫画 推送 开/关/状态` | 控制自动推送（有更新时自动发送漫画内容） |
| `/漫画 帮助` | 显示完整用法说明 |

---

## 💬 使用示例

### 基本流程

```
用户: /漫画 搜索 一拳超人
Bot:  🔍 搜索结果（源: 拷贝漫画 (ZH)）:
        [1] 一拳超人 - 连载中
        [2] 一拳超人 重制版 - 连载中
      回复「漫画 订阅 <编号>」订阅，如「漫画 订阅 1」

用户: /漫画 订阅 1
Bot:  ✅ 已订阅「一拳超人」，有新章节时会推送。

用户: /漫画 章节 一拳超人
Bot:  📖「一拳超人」章节列表（共 200 话）:
        ✅ #200 第200话
        ✅ #199 第199话
        ...

用户: /漫画 阅读 一拳超人 200
Bot:  📖 正在加载「一拳超人」第 200 话，请稍后...
      [图片] [图片] [图片] ...

用户: /漫画 下载 一拳超人 199
Bot:  ⏳ 正在下载「一拳超人」第 199 话，请稍候...
      [文件: 一拳超人_第199话.zip]
```

### 批量订阅

一次性订阅多部漫画，用逗号分隔名称：

```
用户: /漫画 批量订阅 咒术回战, 鬼灭之刃, 电锯人
Bot:  📚 开始批量订阅 3 部漫画...
      正在处理 [1/3] 咒术回战...
      正在处理 [2/3] 鬼灭之刃...
      正在处理 [3/3] 电锯人...
      📚 批量订阅完成 (2 新增, 0 已存在, 1 失败):
        ✅ 咒術廻戦 - 连载中 - 拷贝漫画 (ZH)
        ✅ 鬼滅の刃 - 已完结 - 禁漫天堂 (JM)
        ❌ 电锯人 - 未找到匹配结果
```

也可指定源：`/漫画 批量订阅 咒术回战, 鬼灭之刃 jm`

### 强制刷新章节缓存

章节数据默认缓存 **6 小时**（可配置）。如需获取最新章节，添加 `--刷新` 参数：

```
用户: /漫画 章节 一拳超人 --刷新
Bot:  📖「一拳超人」章节列表（共 205 话）:
        ✅ #205 第205话  ← 新章节
        ...
```

### 重复章节选择

部分漫画存在编号相同的章节（如附录、特别篇），可通过 **章节 ID** 精确选择：

```
用户: /漫画 阅读 安達與島村 7
Bot:  找到多个第 7 话，请使用 ID 指定:
        ID:456 - 07卷附录
        ID:789 - 第7话
      发送「漫画 阅读 安達與島村 ID:456」选择
```

---

## 🔔 更新推送

插件后台定时检查已订阅漫画的新章节（默认每 **60 分钟**），发现更新后自动推送到对应聊天会话：

```
📢「一拳超人」更新了！
新增章节：#201 第201话, #202 第202话, #203 第203话
发送「漫画 阅读 一拳超人 203」开始阅读
```

也可通过 `/漫画 更新` 命令手动触发检查（会全局推送，所有订阅该漫画的用户都会收到通知）。

### 自动推送

默认只发送文本通知。开启自动推送后，发现更新时会自动发送漫画内容：

```
用户: /漫画 推送 开
Bot:  ✅ 已开启自动推送，共 3 部漫画。有更新时将自动推送内容。

用户: /漫画 推送 状态
Bot:  📡 自动推送状态:
        • 一拳超人 — ✅ 开启
        • 海贼王 — ✅ 开启
```

推送模式通过 `auto_push_mode` 配置：`image` 直接发送图片，`file` 发送 ZIP/PDF/CBZ 文件包。

---

## 📦 安装

### 前置要求

- Python 3.12+
- AstrBot >= 4.16
- 已部署并运行的 [Suwayomi-Server](https://github.com/Suwayomi/Suwayomi-Server)
- Suwayomi 中已安装至少一个漫画源扩展

### 安装步骤

**方式一：Git 克隆**

```bash
cd AstrBot/data/plugins
git clone https://github.com/FFFold/astrbot_plugin_suwayomi_server.git astrbot_suwayomi_server
uv pip install -r astrbot_suwayomi_server/requirements.txt
```

**方式二：AstrBot WebUI（推荐）**

在 AstrBot 管理面板的插件市场中搜索并安装。

> 安装完成后在 AstrBot WebUI 中启用插件并完成配置即可使用。

---

## ⚙️ 配置

在 AstrBot WebUI 的插件设置页面中配置。

### 基本设置

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `server_url` | string | `http://localhost:9330` | Suwayomi-Server 地址 |
| `auth_mode` | string | `none` | 认证模式：`none` / `basic` / `jwt` |
| `username` | string | `""` | 认证用户名（basic / jwt 模式） |
| `password` | string | `""` | 认证密码（basic / jwt 模式） |
| `check_interval` | int | `60` | 更新检查间隔（分钟） |
| `default_source_id` | int | `0` | 默认搜索源 ID，`0` 搜索全部已安装源 |

### 阅读设置

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `send_mode` | string | `image` | 发图模式：`image`（逐张发送）/ `forward`（合并转发，仅 QQ） |
| `image_fetch_mode` | string | `url` | 图源获取：`url`（直接引用）/ `download`（先下载到本地） |
| `max_pages` | int | `30` | 单次阅读最大发送页数 |
| `download_concurrency` | int | `6` | 并行下载图片数（仅 `download` 模式） |
| `download_retries` | int | `3` | 图片下载失败重试次数（指数退避） |
| `chapter_cache_hours` | int | `6` | 章节缓存时长（小时）。`0` = 不自动刷新，`-1` = 总是从源刷新 |
| `download_format` | string | `zip` | 下载打包格式：`zip` / `pdf` / `cbz` |
| `temp_dir` | string | `""` | 临时文件目录。留空用系统默认，Docker 环境设置共享目录如 `/AstrBot/data/temp` |
| `auto_push_mode` | string | `image` | 自动推送模式：`image`（图片）/ `file`（文件） |

### 认证模式说明

| 模式 | 说明 |
|---|---|
| `none` | Suwayomi-Server 未开启认证（默认） |
| `basic` | HTTP Basic 认证 |
| `jwt` | JWT 令牌认证（Suwayomi UI_LOGIN 模式） |

### 发图模式说明

| 模式 | 说明 |
|---|---|
| `image` | 将章节页面作为独立图片逐张发送，通用性强，支持所有平台 |
| `forward` | 使用合并转发消息发送章节页面，仅 aiocqhttp / QQ 平台支持，其他平台自动回退为 `image` |

### 图片获取方式

| 方式 | 说明 |
|---|---|
| `url` | 直接引用 Suwayomi 图片 URL，速度快但网络不稳定时易失败 |
| `download` | 先下载到本地临时文件再发送，更可靠，发送后 60 秒自动清理 |

## 📚 文档

| 文档 | 说明 |
|---|---|
| [Suwayomi-Server 配置教程](docs/setup.md) | Docker 部署、漫画源安装、插件配置 |
| [开发指南](docs/dev/development.md) | 架构详解、设计决策、数据流 |
| [Suwayomi API 参考](docs/dev/suwayomi-api.md) | GraphQL API 文档 |
| [贡献指南](CONTRIBUTING.md) | 开发环境搭建、提交规范 |
| [变更日志](CHANGELOG.md) | 版本更新记录 |

---

## 📄 许可证

[AGPL-3.0](LICENSE) © Fold

---

<p align="center">
  <sub>由 <a href="https://github.com/Suwayomi/Suwayomi-Server">Suwayomi-Server</a> 提供漫画数据支持 · 为 <a href="https://github.com/Soulter/AstrBot">AstrBot</a> 量身打造</sub>
</p>
