# Suwayomi-Server 配置教程

本教程指导你部署 Suwayomi-Server 并配置漫画助手插件。

## 目录

- [第一步：部署 Suwayomi-Server](#第一步部署-suwayomi-server)
- [第二步：安装漫画源扩展](#第二步安装漫画源扩展)
- [第三步：配置 AstrBot 插件](#第三步配置-astrbot-插件)
- [第四步：验证](#第四步验证)
- [常见问题](#常见问题)

---

## 第一步：部署 Suwayomi-Server

推荐使用 Docker 部署，简单可靠。

### 方式一：Docker Compose（推荐）

1. 创建目录：
   ```bash
   mkdir -p ~/suwayomi && cd ~/suwayomi
   ```

2. 创建 `docker-compose.yml`：
   ```yaml
   version: "3"
   services:
     suwayomi:
       image: ghcr.io/suwayomi/suwayomi-server:stable
       container_name: suwayomi-server
       volumes:
         - ./data:/home/suwayomi/.local/share/Tachidesk
       ports:
         - "9330:4567"    # 左边的端口可以改，右边必须是 4567
       environment:
         - TZ=Asia/Shanghai
         # 如果需要认证，取消下面的注释并填写：
         # - AUTH_MODE=basic_auth
         # - AUTH_USERNAME=admin
         # - AUTH_PASSWORD=你的密码
       restart: unless-stopped
   ```

3. 启动：
   ```bash
   docker compose up -d
   ```

4. 验证服务运行：
   ```bash
   curl http://localhost:9330/api/v1/settings/about
   ```
   返回 JSON 信息即表示成功。

### 方式二：Docker 命令

```bash
docker run -d \
  --name suwayomi-server \
  -p 9330:4567 \
  -v ~/suwayomi/data:/home/suwayomi/.local/share/Tachidesk \
  -e TZ=Asia/Shanghai \
  --restart unless-stopped \
  ghcr.io/suwayomi/suwayomi-server:stable
```

### 方式三：直接下载

从 [Suwayomi-Server Releases](https://github.com/Suwayomi/Suwayomi-Server/releases) 下载对应系统的包：

- **Windows**: 下载 `win64` 包，解压后双击启动脚本
- **macOS**: 下载 `macOS-arm64`（M 芯片）或 `macOS-x64`（Intel），解压后运行
- **Linux**: 下载 `linux-x64`，解压后运行启动脚本

默认访问地址：`http://localhost:4567`

### 认证配置（可选）

如果你的 Suwayomi-Server 暴露在公网上，建议开启认证。

**通过环境变量配置（Docker）：**

| 环境变量 | 说明 | 示例 |
|---------|------|------|
| `AUTH_MODE` | 认证模式 | `none` / `basic_auth` / `ui_login` |
| `AUTH_USERNAME` | 用户名 | `admin` |
| `AUTH_PASSWORD` | 密码 | `your_password` |

**通过 WebUI 配置：**

1. 打开 `http://你的服务器地址:9330`
2. 进入设置（齿轮图标）
3. 找到「服务器设置」→「认证模式」
4. 选择模式并设置用户名密码

**认证模式说明：**

| 模式 | 说明 | 插件配置对应 |
|------|------|-------------|
| `none` | 无认证 | `auth_mode: none` |
| `basic_auth` | HTTP Basic 认证 | `auth_mode: basic` |
| `ui_login` | JWT 令牌认证 | `auth_mode: jwt` |

> 如果在内网使用，`none` 模式即可。公网部署建议用 `basic_auth` 或 `ui_login`。

### 常用环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BIND_PORT` | `4567` | 服务端口（容器内） |
| `TZ` | `Etc/UTC` | 时区 |
| `WEB_UI_CHANNEL` | `stable` | WebUI 更新渠道 |
| `UPDATE_INTERVAL` | `12` | 书库自动更新间隔（小时） |

完整环境变量列表见 [Suwayomi-Server-docker README](https://github.com/Suwayomi/Suwayomi-Server-docker)。

---

## 第二步：安装漫画源扩展

Suwayomi 本身不包含漫画内容，需要安装「扩展」来连接漫画源网站。

### 操作步骤

1. 打开 Suwayomi WebUI：`http://你的服务器地址:9330`

2. 点击左侧菜单的「扩展」（Extensions）

3. 浏览可用扩展列表，找到你想用的源，点击「安装」：
   - **中文用户推荐**：拷贝漫画、再漫画、Komiic 等
   - **英文用户推荐**：MangaDex、MangaPlus 等

4. 安装完成后，扩展状态变为「已安装」

5. 部分源可能需要额外配置（如语言过滤），点击扩展名称可查看详情

### 添加额外扩展仓库（可选）

如果默认仓库中找不到需要的源，可以添加第三方扩展仓库：

在 Suwayomi WebUI 的设置中找到「扩展仓库」（Extension Repos），添加仓库 URL。

或通过 Docker 环境变量：
```yaml
environment:
  - EXTENSION_REPOS=["https://example.com/repo"]
```

### 验证源安装

安装扩展后，可以通过以下方式验证：

```bash
# 查询已安装的源列表
curl http://localhost:9330/api/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"{ sources { nodes { id name displayName lang } } }"}'
```

返回的 JSON 应包含你安装的源。记住源的 `id`（一串大数字），后面配置插件时可能用到。

---

## 第三步：配置 AstrBot 插件

### 安装插件

```bash
cd AstrBot/data/plugins
git clone https://github.com/FFFold/astrbot_suwayomi_server.git
```

### 配置

在 AstrBot WebUI 的插件管理中找到「Suwayomi 漫画助手」，点击设置：

| 配置项 | 填写 |
|--------|------|
| `server_url` | `http://你的Suwayomi地址:端口`（如 `http://localhost:9330`） |
| `auth_mode` | `none`（如果 Suwayomi 没开认证）/ `basic` / `jwt` |
| `username` | 认证用户名（auth_mode 为 none 时留空） |
| `password` | 认证密码（auth_mode 为 none 时留空） |
| `check_interval` | 更新检查间隔，单位分钟，默认 `60` |
| `max_pages` | 单次阅读最大发送页数，默认 `30` |
| `send_mode` | `image`（直接发图）或 `forward`（合并转发，仅 QQ） |
| `default_source_id` | 默认搜索源 ID，`0` 搜索全部源 |

**网络连通性**：AstrBot 所在机器必须能访问 Suwayomi-Server 地址。如果 AstrBot 和 Suwayomi 都在同一台机器上，用 `http://localhost:9330`。如果 AstrBot 在 Docker 中，需要用宿主机 IP 或 Docker 网络地址。

### 填写示例

**场景 1：同一台机器，无认证**
```
server_url: http://localhost:9330
auth_mode: none
```

**场景 2：Suwayomi 在另一台服务器，Basic 认证**
```
server_url: http://192.168.1.100:9330
auth_mode: basic
username: admin
password: mypassword123
```

**场景 3：Suwayomi 在公网，JWT 认证**
```
server_url: https://manga.example.com
auth_mode: jwt
username: admin
password: mypassword123
```

---

## 第四步：验证

在聊天中发送以下命令逐步验证：

```
# 1. 检查源列表
/漫画 源

# 2. 搜索测试
/漫画 搜索 海贼王

# 3. 订阅测试
/漫画 订阅 1

# 4. 查看订阅
/漫画 我的订阅

# 5. 查看章节
/漫画 章节 海贼王

# 6. 阅读测试
/漫画 阅读 海贼王 1
```

如果第 1 步就失败（返回"漫画服务暂时不可用"），说明 AstrBot 无法连接到 Suwayomi-Server，检查：
- Suwayomi-Server 是否在运行
- `server_url` 是否正确
- 防火墙是否放行了端口
- AstrBot 所在网络是否能访问 Suwayomi 地址

---

## 常见问题

### 搜索返回"未找到相关漫画"

Suwayomi 中没有安装漫画源扩展。去 WebUI 的「扩展」页面安装源。

### 搜索返回"Unknown type 'Long'"

Suwayomi-Server 版本过旧。升级到最新稳定版：
```bash
docker pull ghcr.io/suwayomi/suwayomi-server:stable
docker compose up -d
```

### 图片发送失败

AstrBot 所在机器需要能访问 Suwayomi 的图片 URL。如果 Suwayomi 在内网，确保 AstrBot 也在同一网络中。

### 合并转发模式不生效（QQ）

`send_mode` 设为 `forward` 时，仅在 aiocqhttp（Napcat/Lagrange）平台生效，其他平台自动回退为直接发图。

### 更新推送不工作

- 确认已使用 `/漫画 订阅` 订阅了漫画
- 确认 Suwayomi 的书库中有该漫画（在 WebUI 中能看到）
- 插件默认每 60 分钟检查一次，可通过 `/漫画 更新` 手动触发
- 检查 AstrBot 日志中是否有错误信息

### 连接超时或拒绝连接

```bash
# 从 AstrBot 所在机器测试连通性
curl http://你的Suwayomi地址:端口/api/v1/settings/about
```

如果超时，检查：
- Suwayomi 容器是否在运行：`docker ps | grep suwayomi`
- 端口映射是否正确：`docker port suwayomi-server`
- 防火墙规则

### 认证失败

- 确认 AstrBot 插件的 `auth_mode` 与 Suwayomi 的 `AUTH_MODE` 一致
- `none` 对应 `none`，`basic_auth` 对应 `basic`，`ui_login` 对应 `jwt`
- 确认用户名密码正确
