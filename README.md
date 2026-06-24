# Suwayomi 漫画助手

AstrBot 插件 — 将 [Suwayomi-Server](https://github.com/Suwayomi/Suwayomi-Server) 作为漫画后端，为聊天用户提供漫画搜索、阅读、下载和更新推送服务。

## 功能

| 命令 | 说明 |
|------|------|
| `漫画源` | 列出所有已安装的漫画源 |
| `漫画搜索 <关键词> [源名]` | 从多个源搜索漫画 |
| `漫画订阅 <编号>` | 订阅搜索结果中的漫画 |
| `漫画取消订阅 <ID或名称>` | 取消订阅 |
| `漫画我的订阅` | 查看当前会话的订阅列表 |
| `漫画更新` | 手动触发更新检查 |
| `漫画章节 <漫画名或ID>` | 查看章节列表 |
| `漫画阅读 <漫画名或ID> <章节号>` | 阅读章节（发送页面图片） |
| `漫画下载 <漫画名或ID> <章节号>` | 将章节加入下载队列 |

## 更新推送

插件后台定时检查订阅漫画的新章节（默认每 60 分钟），发现更新后自动推送到订阅者的聊天会话。也支持 `漫画更新` 手动触发。

## 安装

1. 将本仓库克隆到 AstrBot 插件目录：
   ```bash
   cd AstrBot/data/plugins
   git clone https://github.com/FFFold/astrbot_suwayomi_server.git
   ```

2. 安装依赖（AstrBot 启动时会自动安装，或手动执行）：
   ```bash
   pip install -r astrbot_suwayomi_server/requirements.txt
   ```

3. 在 AstrBot WebUI 的插件管理中启用插件并配置。

## 配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `server_url` | string | `http://localhost:9330` | Suwayomi-Server 地址 |
| `auth_mode` | string | `none` | 认证模式：`none` / `basic` / `jwt` |
| `username` | string | `""` | 认证用户名 |
| `password` | string | `""` | 认证密码 |
| `check_interval` | int | `60` | 更新检查间隔（分钟） |
| `max_pages` | int | `30` | 单次阅读最大发送页数 |
| `send_mode` | string | `image` | 发图模式：`image`（直接发图）/ `forward`（合并转发） |
| `default_source_id` | int | `0` | 默认搜索源 ID，`0` 表示搜索全部已安装源 |

## 前置要求

- AstrBot >= 4.16
- Suwayomi-Server 已部署并可访问
- Suwayomi 中已安装至少一个漫画源扩展

## 许可证

MIT
