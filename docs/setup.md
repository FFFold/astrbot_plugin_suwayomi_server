# Suwayomi-Server 配置教程

本教程指导你部署 Suwayomi-Server 并配置漫画助手插件。

## 目录

- [第一步：部署 Suwayomi-Server](#第一步部署-suwayomi-server)
- [第二步：安装漫画源扩展](#第二步安装漫画源扩展)
- [第三步：配置 AstrBot 插件](#第三步配置-astrbot-插件)
- [第四步：验证](#第四步验证)
- [可选：优化 T2I 卡片渲染服务](#可选优化-t2i-卡片渲染服务)
- [⚠️ 更换 Suwayomi-Server 实例的注意事项](#️-更换-suwayomi-server-实例的注意事项)
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
   services:
     suwayomi:
       image: ghcr.io/suwayomi/suwayomi-server:stable
       container_name: suwayomi-server
       volumes:
         - ./data:/home/suwayomi/.local/share/Tachidesk
       ports:
         - "4567:4567"    # 左边的端口可以改，右边必须是 4567
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

    浏览器打开 http://localhost:4567/ ，能正常访问WebUI即表示成功。

### 方式二：Docker 命令

```bash
docker run -d \
  --name suwayomi-server \
  -p 4567:4567 \
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

1. 打开 `http://你的服务器地址:4567`
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

Suwayomi 本身不包含漫画内容，需要安装「扩展」来连接漫画源网站。而Suwayomi 本身也不包含扩展库，所以需要先手动添加。

### 操作步骤

1. 打开 Suwayomi WebUI：`http://你的服务器地址:4567`

2. 点击左侧菜单的「设置」→「浏览」→「扩展库」，添加合适的扩展库（如[keiyoushi](https://keiyoushi.github.io/docs/guides/getting-started)中提供的库链接）

3. 点击左侧菜单的「浏览」（Browse），再点击上方「扩展」标签

4. 浏览可用扩展列表，找到你想用的源，点击「安装」：
   - **中文用户推荐**：拷贝漫画、再漫画、Komiic 等
   - **英文用户推荐**：MangaDex、MangaPlus 等

5. 安装完成后，扩展状态变为「已安装」

6. 安装扩展后，可在 Suwayomi-Server 的 WebUI 中调整插件的相关设置，如登录状态、语言过滤等。

---

## 第三步：配置 AstrBot 插件

### 安装插件

在Astrbot 插件市场中点击安装本插件，或Git安装：

```bash
cd AstrBot/data/plugins
git clone https://github.com/FFFold/astrbot_suwayomi_server.git
```

### 配置

在 AstrBot WebUI 的插件管理中找到「Suwayomi 漫画助手」，点击设置。完整配置项说明见 [README 配置表](../README.md#%EF%B8%8F-%E9%85%8D%E7%BD%AE)。

**网络连通性**：AstrBot 所在机器必须能访问 Suwayomi-Server 地址。如果 AstrBot 和 Suwayomi 都在同一台机器上，用 `http://localhost:4567`。如果 AstrBot 运行在 Docker 中，则需要使用宿主机 IP 或 Docker 网桥 IP 确保 Suwayomi-Server 对 Astrbot 可达。

### 填写示例

配置项在 WebUI 插件设置中按分组展示（服务器连接 / 卡片渲染 / 阅读体验 / 下载打包 / 自动推送 / AI 漫画工具 / 高级）。

**场景 1：同一台机器，无认证**
```
server:
  server_url: http://localhost:4567
  auth_mode: none
```

**场景 2：Suwayomi 在另一台服务器，Basic 认证**
```
server:
  server_url: http://192.168.1.100:4567
  auth_mode: basic
  username: admin
  password: mypassword123
```

**场景 3：Suwayomi 在公网，JWT 认证**
```
server:
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

# 6. 强制刷新章节（可选）
/漫画 章节 海贼王 --刷新

# 7. 阅读测试
/漫画 阅读 海贼王 1
```

如果第 1 步就失败（返回"漫画服务暂时不可用"），说明 AstrBot 无法连接到 Suwayomi-Server，检查：
- Suwayomi-Server 是否在运行
- `server_url` 是否正确
- 防火墙是否放行了端口
- AstrBot 所在网络是否能访问 Suwayomi 地址

---

## 可选：优化 T2I 卡片渲染服务

> 本插件默认状态为纯文本回复。开启 `result_cards_enabled` 后，指令结果会渲染为带封面的卡片，默认使用 **AstrBot 系统 T2I 服务**，无需额外部署。

### 为什么要自建？

AstrBot 框架默认使用**部署在国外的官方 T2I 端点**（`t2i.soulter.top` 及其官方端点池）。国内用户访问时常见两个问题：

- **速度慢** —— 渲染一张卡片动辄数秒，章节列表等多卡片场景更明显
- **失败率高** —— 网络抖动或端点限流会触发渲染失败，插件只能回退纯文本

自建一个本地的 astrbot-t2i-service 可以彻底解决：渲染在局域网/本机完成，速度从数秒降到几百毫秒，且不受官方端点波动影响。

### 方案一：改 AstrBot 全局端点（最省事）

如果你只有本插件需要卡片渲染，直接把 AstrBot 的 T2I 端点指向自建服务即可，**无需修改插件配置**（`t2i_source` 保持默认的「使用 AstrBot 系统配置」）：

1. 按下方「部署方式」先把服务跑起来
2. 打开 AstrBot WebUI → **配置** → 「文本转图像」
3. 将 **文本转图像服务 API 地址** 填为自建地址，例如 `http://127.0.0.1:8999`
4. 保存后重启 AstrBot 生效

> 也可以开启「文本转图像自定义模版」使用 AstrBot 的模板系统；本插件不受此影响，模板由插件自带。

**注意**：AstrBot 全局配置为空的默认值即官方端点 `https://t2i.soulter.top/text2img`，并且会自动从官方端点池中随机选取节点，因此填了自建地址后请确认已生效。

### 方案二：仅本插件单独配置（推荐多实例/多插件共存）

如果其他插件仍想用官方端点，或你想让本插件的卡片渲染与系统设置完全隔离：

1. 按下方「部署方式」把服务跑起来
2. 打开 AstrBot WebUI → 插件管理 → 「Suwayomi 漫画助手」→ 设置
3. 在「卡片渲染」分组中：
   - **T2I 服务来源** → 选择「单独配置（自建 T2I 服务）」
   - **T2I 端点** → 填写服务地址，例如 `http://192.168.1.100:8999`
     - 末尾**无需** `/text2img`，插件会自动补全
   - 确认 **指令结果卡片渲染** 已开启
4. 发送 `/漫画 搜索 海贼王` 验证；渲染失败会自动回退纯文本，不会报错

**方案对比**：

| | 方案一：改全局 | 方案二：插件单独配置 |
|---|---|---|
| 影响范围 | AstrBot 所有用到 T2I 的功能 | 仅本插件卡片渲染 |
| 配置位置 | AstrBot 配置 → 文本转图像 | 插件设置 → 卡片渲染 |
| 适用场景 | 只有本插件用卡片 | 多插件/多实例共存，需隔离 |
| 留空时行为 | — | 回退系统配置并打印警告 |

### 部署方式一：Docker（推荐）

官方镜像由 AstrBot 官方维护并发布在 Docker Hub（`soulter/astrbot-t2i-service`）：

```bash
docker run -d \
  --name astrbot-t2i \
  -p 8999:8999 \
  -e TZ=Asia/Shanghai \
  -e IMAGE_LIFETIME_HOURS=24 \
  --restart unless-stopped \
  soulter/astrbot-t2i-service:latest
```

验证服务运行：

```bash
curl -X POST http://localhost:8999/text2img/generate \
  -H "Content-Type: application/json" \
  -d '{"html":"<h1>hello</h1>","options":{"type":"png"}}' \
  -o test.png
```

能生成 `test.png` 即表示部署成功。

### 部署方式二：从源码运行

需要 Python 3.13+ 与 Playwright 浏览器依赖：

```bash
git clone https://github.com/AstrBotDevs/astrbot-t2i-service.git
cd astrbot-t2i-service
pip install -r requirements.txt
playwright install --with-deps chromium
python main.py
```

默认监听 `0.0.0.0:8999`。

### 常用环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `8999` | 服务端口 |
| `IMAGE_LIFETIME_HOURS` | `24` | 生成图片的保留时长（小时），过期自动清理 |
| `STORAGE_BACKEND` | `local` | 图片存储后端，支持 `local` / `s3` / `r2` |
| `RATE_LIMIT_MAX_REQUESTS` | `0` | 限流窗口内最大请求数，`0` 表示不限流 |
| `RATE_LIMIT_WINDOW_SECONDS` | `0` | 限流窗口秒数 |

> 多副本部署（K8s 等）时，JSON 模式生成的图片可能落在不同实例上导致 404，此时需配置 S3/R2 共享存储。本插件使用**直接返回图片字节**的模式（不落盘），单实例部署即可，无此问题。
>
> 完整环境变量与 API 说明见 [astrbot-t2i-service 仓库](https://github.com/AstrBotDevs/astrbot-t2i-service)。

### 注意事项

- AstrBot 所在机器必须能访问 T2I 端点地址（Docker 部署时注意容器网络）
- 「T2I 服务来源」选择「单独配置」但端点留空时，插件会打印警告并回退使用 AstrBot 系统 T2I 配置，不会静默失败
- 若 T2I 服务不可用，命令会等待 `card_render_timeout_sec`（默认 30 秒）后回退纯文本，并在之后 5 分钟内不再尝试渲染

---

## ⚠️ 更换 Suwayomi-Server 实例的注意事项

**漫画 ID 和章节 ID 由 Suwayomi-Server 数据库自动生成**，每个实例的数据库独立，ID 互不通用。这意味着**不能直接更换后端实例而不做处理**，否则：

- 已有的订阅记录中的 `manga_id` 会指向错误的漫画或不存在
- 自动更新检查会失败或查错漫画
- 阅读/下载命令中使用的章节号可能对应错误内容

### 哪些数据绑定在实例上？

| 数据 | 存储位置 | 是否绑定实例 |
|------|---------|-------------|
| 订阅记录（漫画名、manga_id、source_id） | AstrBot KV 存储 | ✅ 是 |
| 章节缓存时间戳 | AstrBot KV 存储 | ✅ 是（按 manga_id） |
| 漫画元数据（标题、封面等） | Suwayomi 数据库 | ✅ 是 |
| 章节列表 | Suwayomi 数据库 | ✅ 是 |
| 已安装的扩展/源 | Suwayomi 数据库 | ✅ 是 |

### 迁移方案

#### 方案一：复制数据库文件（推荐）

直接复制原实例的数据库文件到新实例，保持 ID 一致：

```bash
# Docker 环境下，数据库文件在挂载卷中
# 例如原实例数据目录为 ~/suwayomi/data
cp ~/suwayomi/data/tachidesk.mv.db /新实例数据目录/tachidesk.mv.db
```

**注意**：复制前需停止原实例，确保数据库文件完整。复制后两个实例的数据库内容完全相同，ID 一致。

#### 方案二：重新订阅

如果无法复制数据库（例如跨版本不兼容），需要在新实例上重新订阅：

1. **确认新实例已安装相同的源扩展**（源 ID 也可能不同）
2. 在聊天中执行 `/漫画 更新 --刷新` 强制刷新所有订阅（会因 ID 不匹配而失败）
3. 逐个取消旧订阅：`/漫画 取消订阅 <漫画名>`
4. 重新搜索并订阅：`/漫画 搜索 <漫画名>` → `/漫画 订阅 <序号>`
5. 通知所有订阅者重新订阅

#### 方案三：仅更换地址（同实例）

如果只是 Suwayomi-Server 换了地址（如迁移服务器但保留了数据库），只需修改插件配置中的 `server_url`，无需其他操作。

### 如何避免此问题？

- **备份数据库**：定期备份 Suwayomi 的数据目录（包含 `tachidesk.mv.db`）
- **使用 Docker 卷**：通过 Docker 卷管理数据，迁移时直接复制卷
- **记录源 ID**：不同实例的源 ID 可能不同，迁移后需确认源 ID 一致

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

### 章节数据不是最新的

插件默认缓存章节数据 6 小时。如需强制刷新：

- 使用 `/漫画 章节 <漫画名> --刷新` 从源重新拉取
- 或在配置中将 `chapter_cache_hours` 设为 `-1`（每次都刷新）或 `0`（永不自动刷新）

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

- 确认 AstrBot 插件的 `auth_mode` 按下表对应 Suwayomi 的 `AUTH_MODE`：`none`→`none`，`basic_auth`→`basic`，`ui_login`→`jwt`
- `none` 对应 `none`，`basic_auth` 对应 `basic`，`ui_login` 对应 `jwt`
- 确认用户名密码正确
