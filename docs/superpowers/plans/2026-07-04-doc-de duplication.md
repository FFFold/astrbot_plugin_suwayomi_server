# 文档去重实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除文档中的重复信息（命令列表、配置表、测试计数），建立"唯一维护"责任分层。

**Architecture:** 5 个文档文件需要修改。每个文件独立修改，顺序不影响结果。修改完成后更新 doc-update-checklist.md。

**Tech Stack:** Markdown

---

### Task 1: 修改 AGENTS.md — 去掉测试计数、命令计数、配置选项

**Files:**
- Modify: `AGENTS.md:20` — Commands 段去掉 113 计数
- Modify: `AGENTS.md:46` — Architecture 段去掉 14 个命令计数
- Modify: `AGENTS.md:100-110` — Config Options 段替换为引用

- [ ] **Step 1: Commands 段去掉测试计数**

  修改前：
  ```
  # Unit tests (113 tests, no network needed)
  ```
  修改后：
  ```
  # Unit tests (no network needed)
  ```

- [ ] **Step 2: Architecture 段去掉命令计数**

  修改前：
  ```
  - `main.py`: Plugin entry, all 14 commands under `@filter.command_group("漫画")`, background update loop, WebUI API registration
  ```
  修改后：
  ```
  - `main.py`: Plugin entry, all commands under `@filter.command_group("漫画")`, background update loop, WebUI API registration
  ```

- [ ] **Step 3: Config Options 段替换为引用**

  修改前：
  ```
  ## Config Options

  Key non-obvious config values (in `_conf_schema.json`):
  - `image_fetch_mode`: `url` (direct reference) or `download` (download to temp first, more reliable)
  - `download_concurrency`: Parallel download count (default 6)
  - `download_retries`: Retry count per image with exponential backoff (default 3)
  - `download_format`: `zip` (ZIP archive), `pdf` (PDF document), or `cbz` (comic book archive). Default `zip`.
  - `send_mode`: `image` (direct) or `forward` (QQ merged forward, uses `Comp.Nodes` wrapper)
  - `chapter_cache_hours`: Hours before auto-refreshing chapters from source (default 6). `0` = never auto-refresh, `-1` = always refresh
  - `auto_push_mode`: `image` (inline images, reuses read logic) or `file` (packaged file, reuses download logic). Default `image`.
  - `temp_dir`: Custom temp directory for image downloads. Leave empty for system default. Set to shared directory for Docker environments.
  ```
  修改后：
  ```
  ## Config Options

  完整配置项参考 [README 配置表](../README.md#%E9%85%8D%E7%BD%AE)。
  ```

- [ ] **Step 4: 验证**

  Run: `python -c "import ast; ast.parse(open('AGENTS.md', encoding='utf-8').read()); print('OK')"` — skip (not Python), check visually for removed content

- [ ] **Step 5: Commit**

  ```bash
  git add AGENTS.md
  git commit -m "docs: remove redundant test count, command count, and config options from AGENTS.md"
  ```

---

### Task 2: 修改 docs/dev/development.md — 去掉所有测试计数和命令计数

**Files:**
- Modify: `docs/dev/development.md:32-40` — 项目结构中每个测试文件的计数
- Modify: `docs/dev/development.md:61` — 架构图中 14 个命令计数
- Modify: `docs/dev/development.md:243` — 运行测试命令中的计数

- [ ] **Step 1: 项目结构中去掉测试文件计数**

  修改前 (lines 32-40)：
  ```
  │   ├── test_pack.py           # 打包功能单元测试（19 个）
  │   ├── test_models.py         # 数据模型单元测试（9 个）
  │   ├── test_client.py         # 客户端单元测试（6 个）
  │   ├── test_subscription.py   # 订阅管理单元测试（24 个）
  │   ├── test_web_api.py        # WebUI API handler 单元测试（30 个）
  │   ├── test_batch_subscribe.py # 批量订阅参数解析单元测试（11 个）
  │   ├── test_push.py           # 自动推送单元测试（14 个）
  │   ├── test_live_api.py       # Suwayomi 客户端集成测试（13 个）
  │   └── test_live_web_api.py   # WebUI API handler 集成测试（19 个）
  ```
  修改后：
  ```
  │   ├── test_pack.py           # 打包功能单元测试
  │   ├── test_models.py         # 数据模型单元测试
  │   ├── test_client.py         # 客户端单元测试（mocked HTTP）
  │   ├── test_subscription.py   # 订阅管理单元测试
  │   ├── test_web_api.py        # WebUI API handler 单元测试
  │   ├── test_batch_subscribe.py # 批量订阅参数解析单元测试
  │   ├── test_push.py           # 自动推送单元测试
  │   ├── test_live_api.py       # Suwayomi 客户端集成测试
  │   └── test_live_web_api.py   # WebUI API handler 集成测试
  ```

- [ ] **Step 2: 架构图去掉命令计数**

  修改前 (line 61)：
  ```
  │ Commands   │ Update     │ Search Cache │ │
  │ (14 个命令)│ Loop (后台)│ (TTL 10min)  │
  ```
  修改后：
  ```
  │ Commands   │ Update     │ Search Cache │ │
  │ (所有命令) │ Loop (后台)│ (TTL 10min)  │
  ```

- [ ] **Step 3: 运行测试命令中去掉计数**

  修改前 (line 243)：
  ```
  # 全部单元测试（113 个，无需网络）
  ```
  修改后：
  ```
  # 全部单元测试（无需网络）
  ```

- [ ] **Step 4: 验证**

  Run: `python -c "import ast; ast.parse(open('docs/dev/development.md', encoding='utf-8').read()); print('OK')"` — visual check only

- [ ] **Step 5: Commit**

  ```bash
  git add docs/dev/development.md
  git commit -m "docs: remove test counts and command count from development guide"
  ```

---

### Task 3: 修改 CONTRIBUTING.md — 去掉测试计数、更新文档引用

**Files:**
- Modify: `CONTRIBUTING.md:92` — 项目结构中 test_push.py 的计数
- Modify: `CONTRIBUTING.md:251-265` — 文档更新表格改为引用 README
- Modify: `CONTRIBUTING.md:285` — FAQ 配置添加步骤中的引用

- [ ] **Step 1: 项目结构中去掉测试计数**

  修改前 (line 92)：
  ```
  │   ├── test_push.py           # 自动推送单元测试（14 个）
  ```
  修改后：
  ```
  │   ├── test_push.py           # 自动推送单元测试
  ```

- [ ] **Step 2: 文档更新表格改为引用 README**

  修改前 (lines 253-265)：
  ```
  ## 文档更新

  修改以下内容时，请同步更新文档：

  | 修改内容 | 需要更新的文档 |
  |---------|---------------|
  | 新增/修改命令 | `README.md`, `AGENTS.md`, `main.py` 帮助文本 |
  | 新增/修改配置 | `_conf_schema.json`, `docs/setup.md`, `AGENTS.md` |
  | 新增/修改 API | `docs/dev/suwayomi-api.md` |
  | 新增/修改 WebUI | `web/api.py`, `pages/dashboard/`, `AGENTS.md`, `docs/dev/development.md` |
  | 架构变更 | `docs/dev/development.md`, `AGENTS.md` |
  | 版本发布 | `metadata.yaml`, `CHANGELOG.md` |

  > 完整的文件更新清单见 [docs/dev/doc-update-checklist.md](docs/dev/doc-update-checklist.md)。
  ```
  修改后：
  ```
  ## 文档更新

  本项目采用文档责任分层，同一信息只在一个地方维护：

  | 修改内容 | 唯一需要更新的文档 |
  |---------|------------------|
  | 新增/修改命令 | `main.py` docstring + `README.md` 命令表 |
  | 新增/修改配置 | `_conf_schema.json` + `README.md` 配置表 |
  | 新增/修改 API | `suwayomi/client.py` + `docs/dev/suwayomi-api.md` |
  | 新增/修改 WebUI | `web/api.py` + `pages/dashboard/` + `AGENTS.md` + `docs/dev/development.md` |
  | 架构变更 | `AGENTS.md` |
  | 版本发布 | `metadata.yaml` + `CHANGELOG.md` + `README.md` badge |

  > 完整清单见 [docs/dev/doc-update-checklist.md](docs/dev/doc-update-checklist.md)。
  ```

- [ ] **Step 3: FAQ 配置添加步骤中的引用**

  修改前 (line 285)：
  ```
  3. 更新 `docs/setup.md` 配置表格
  ```
  修改后：
  ```
  3. 更新 `README.md` 配置表
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add CONTRIBUTING.md
  git commit -m "docs: remove test counts and update doc references in contributing guide"
  ```

---

### Task 4: 修改 docs/setup.md — 配置表替换为引用

**Files:**
- Modify: `docs/setup.md:179-193` — 配置表替换为引用 README

- [ ] **Step 1: 配置表替换为引用**

  修改前 (lines 177-193)：
  ```
  ### 配置

  在 AstrBot WebUI 的插件管理中找到「Suwayomi 漫画助手」，点击设置：

  | 配置项 | 填写 |
  |--------|------|
  | `server_url` | `http://你的Suwayomi地址:端口`（如 `http://localhost:4567`） |
  | `auth_mode` | `none`（如果 Suwayomi 没开认证）/ `basic` / `jwt` |
  | `username` | 认证用户名（auth_mode 为 none 时留空） |
  | `password` | 认证密码（auth_mode 为 none 时留空） |
  | `check_interval` | 更新检查间隔，单位分钟，默认 `60` |
  | `max_pages` | 单次阅读最大发送页数，默认 `30` |
  | `send_mode` | `image`（直接发图）或 `forward`（合并转发，仅 QQ） |
  | `default_source_id` | 默认搜索源 ID，`0` 搜索全部源 |
  | `chapter_cache_hours` | 章节缓存时间（小时），默认 `6`。`0` 不自动刷新，`-1` 每次都刷新 |
  | `download_format` | 下载打包格式，`zip`（ZIP 压缩包）/ `pdf`（PDF 文档）/ `cbz`（CBZ 漫画），默认 `zip` |
  | `temp_dir` | 临时文件目录，留空使用系统默认。Docker 环境请设置为 AstrBot 和聊天平台容器共享的目录，例如 `/AstrBot/data/temp` |
  | `auto_push_mode` | 自动推送模式，`image`（图片，复用阅读逻辑）/ `file`（文件，复用下载逻辑），默认 `image` |
  ```
  修改后：
  ```
  ### 配置

  在 AstrBot WebUI 的插件管理中找到「Suwayomi 漫画助手」，点击设置。完整配置项说明见 [README 配置表](../README.md#%E9%85%8D%E7%BD%AE)。
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add docs/setup.md
  git commit -m "docs: replace redundant config table with reference to README"
  ```

---

### Task 5: 更新 doc-update-checklist.md 反映新责任分层

**Files:**
- Modify: `docs/dev/doc-update-checklist.md` — 所有变更分类的文件列表

- [ ] **Step 1: 更新"新增/修改命令"**

  修改前：
  ```
  ## 新增/修改命令

  | 文件 | 更新内容 |
  |------|---------|
  | `main.py` | 命令方法 + docstring（用户帮助文本） |
  | `main.py` | `/漫画 帮助` 命令的完整帮助文本 |
  | `README.md` | 命令表格 |
  | `README.md` | 使用示例（如有新交互流程） |
  | `AGENTS.md` | 架构描述中的命令数量 |
  | `CONTRIBUTING.md` | 添加新命令章节（如适用） |
  ```
  修改后：
  ```
  ## 新增/修改命令

  | 文件 | 更新内容 |
  |------|---------|
  | `main.py` | 命令方法 + docstring（用户帮助文本，唯一来源） |
  | `main.py` | `/漫画 帮助` 命令的完整帮助文本 |
  | `README.md` | 命令表格（唯一权威来源） |
  ```

- [ ] **Step 2: 更新"新增/修改配置项"**

  修改前：
  ```
  ## 新增/修改配置项

  | 文件 | 更新内容 |
  |------|---------|
  | `_conf_schema.json` | 配置字段定义（name, description, hint, default） |
  | `main.py` | `self.config.get()` 读取逻辑 |
  | `README.md` | 配置表格（基本设置 / 阅读设置） |
  | `docs/setup.md` | 配置参考表格 |
  | `AGENTS.md` | Config Options 段落 |
  ```
  修改后：
  ```
  ## 新增/修改配置项

  | 文件 | 更新内容 |
  |------|---------|
  | `_conf_schema.json` | 配置字段定义（name, description, hint, default） |
  | `main.py` | `self.config.get()` 读取逻辑 |
  | `README.md` | 配置表格（唯一权威来源） |
  ```

- [ ] **Step 3: 更新"架构变更"**

  去掉 `AGENTS.md` 中的 Key Helper Methods/Config Options（已移除）：
  修改前：
  ```
  ## 架构变更

  | 文件 | 更新内容 |
  |------|---------|
  | `AGENTS.md` | Architecture 段落 |
  | `AGENTS.md` | Key Helper Methods 段落 |
  | `docs/dev/development.md` | 架构图、模块说明、数据流、项目结构 |
  | `CONTRIBUTING.md` | 项目结构 |
  | `AGENTS.md` | Critical Quirks（如有新的陷阱） |
  ```
  修改后：
  ```
  ## 架构变更

  | 文件 | 更新内容 |
  |------|---------|
  | `AGENTS.md` | Architecture、Key Helper Methods、Critical Quirks |
  | `docs/dev/development.md` | 架构图、模块说明、数据流、项目结构 |
  | `CONTRIBUTING.md` | 项目结构 |
  ```

- [ ] **Step 4: 更新"测试变更"**

  去掉测试计数相关的条目：
  修改前：
  ```
  | `AGENTS.md` | 单元测试数量、测试命令 |
  ```
  修改后：
  ```
  | `AGENTS.md` | 测试运行命令 |
  ```

- [ ] **Step 5: 更新"快速参考"表**

  修改以下行：
  - `AGENTS.md` — 去掉"新命令"触发场景（已不再有命令列表）
  - `docs/setup.md` — 去掉"新增/修改配置"触发场景

  修改前：
  ```
  | `AGENTS.md` | 架构变更、新命令、新配置、测试变更、依赖变更 |
  ```
  修改后：
  ```
  | `AGENTS.md` | 架构变更、测试变更、依赖变更 |
  ```

  修改前：
  ```
  | `docs/setup.md` | 新增/修改配置 |
  ```
  修改后：
  ```
  | `docs/setup.md` | 部署流程或认证配置变更 |
  ```

- [ ] **Step 6: Commit**

  ```bash
  git add docs/dev/doc-update-checklist.md
  git commit -m "docs: update doc-update-checklist to reflect new single-source model"
  ```
