# Suwayomi 漫画助手

AstrBot 插件 — 将 [Suwayomi-Server](https://github.com/Suwayomi/Suwayomi-Server) 作为漫画后端，为聊天用户提供漫画搜索、阅读、下载和订阅更新推送服务。

## 命令一览

| 命令 | 说明 |
|------|------|
| `/漫画 源` | 列出所有已安装的漫画源 |
| `/漫画 搜索 <关键词> [源名]` | 从多个源搜索漫画 |
| `/漫画 订阅 <编号>` | 订阅搜索结果中的漫画 |
| `/漫画 取消订阅 <ID或名称>` | 取消订阅 |
| `/漫画 我的订阅` | 查看当前会话的订阅列表 |
| `/漫画 更新` | 手动触发更新检查 |
| `/漫画 章节 <漫画名或ID>` | 查看章节列表 |
| `/漫画 阅读 <漫画名或ID> <章节号>` | 阅读章节（发送页面图片） |
| `/漫画 下载 <漫画名或ID> <章节号>` | 将章节加入下载队列 |

## 使用示例

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
Bot:  [发送该章节所有页面图片]

用户: /漫画 下载 一拳超人 199
Bot:  ✅ 已将「一拳超人 #199」加入下载队列，可在 WebUI 查看进度。
```

## 更新推送

插件后台定时检查订阅漫画的新章节（默认每 60 分钟），发现更新后自动推送到订阅者的聊天会话：

```
📢「一拳超人」更新了！
新增章节：#201, #202, #203
发送「漫画 阅读 一拳超人 201」开始阅读
```

也支持 `/漫画 更新` 手动触发检查。

## 重复章节处理

部分漫画存在编号相同的章节（如附录、特别篇）。插件会在章节列表中标记重复项，并在阅读/下载时提示用户通过章节 ID 精确选择：

```
📖「安達與島村」章节列表（共 67 话）:
  ✅ #7 07卷附录 (ID:456)
  ✅ #7 第7话 (ID:789)

用户: /漫画 阅读 安達與島村 7
Bot:  找到多个第 7 话，请使用 ID 指定:
        ID:456 - 07卷附录
        ID:789 - 第7话
      发送「漫画 阅读 安達與島村 id:456」选择
```

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

在 AstrBot WebUI 的插件设置页面中配置以下选项：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `server_url` | string | `http://localhost:9330` | Suwayomi-Server 地址 |
| `auth_mode` | string | `none` | 认证模式：`none` / `basic` / `jwt` |
| `username` | string | `""` | 认证用户名（basic/jwt 模式） |
| `password` | string | `""` | 认证密码（basic/jwt 模式） |
| `check_interval` | int | `60` | 更新检查间隔（分钟） |
| `max_pages` | int | `30` | 单次阅读最大发送页数 |
| `send_mode` | string | `image` | 发图模式：`image`（直接发图）/ `forward`（合并转发，仅 QQ） |
| `default_source_id` | int | `0` | 默认搜索源 ID，`0` 表示搜索全部已安装源 |

### 认证模式

- `none`：Suwayomi-Server 未开启认证（默认）
- `basic`：HTTP Basic 认证
- `jwt`：JWT 令牌认证（Suwayomi UI_LOGIN 模式）

### 发图模式

- `image`：将章节页面作为独立图片逐张发送（通用，支持所有平台）
- `forward`：使用合并转发消息发送（仅 aiocqhttp/QQ 平台支持，其他平台自动回退为 `image` 模式）

## 前置要求

- AstrBot >= 4.16
- Suwayomi-Server 已部署并可访问
- Suwayomi 中已安装至少一个漫画源扩展

## 许可证

MIT
