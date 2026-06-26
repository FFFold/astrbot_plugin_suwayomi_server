# 贡献指南

感谢你对 Suwayomi 漫画助手插件的兴趣！本文档将帮助你快速上手开发。

## 目录

- [开发环境](#开发环境)
- [项目结构](#项目结构)
- [开发流程](#开发流程)
- [提交规范](#提交规范)
- [添加新命令](#添加新命令)
- [测试](#测试)
- [常见问题](#常见问题)

## 开发环境

### 前置条件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器
- 可访问的 Suwayomi-Server 实例（用于集成测试）

### 搭建

```bash
# 克隆仓库
git clone https://github.com/FFFold/astrbot_plugin_suwayomi_server.git
cd astrbot_plugin_suwayomi_server

# uv 会自动创建 .venv 并安装依赖
uv sync

# 安装开发依赖
uv add --dev pytest pytest-asyncio
```

### 运行测试

```bash
# 单元测试（无需网络）
uv run pytest tests/test_pack.py tests/test_models.py tests/test_client.py tests/test_subscription.py -v

# 集成测试（需要 Suwayomi-Server）
uv run pytest tests/test_live_api.py -v -s

# 指定服务器地址
SUWAYOMI_URL=http://your-server:9330 uv run pytest tests/test_live_api.py -v -s

# 全部测试
uv run pytest -v
```

### 语法检查

```bash
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
```

## 项目结构

```
astrbot_plugin_suwayomi_server/
├── main.py                    # 插件入口，命令定义和后台更新逻辑
├── metadata.yaml              # AstrBot 插件元数据（名称、版本、平台）
├── _conf_schema.json          # AstrBot 配置 schema（WebUI 自动生成表单）
├── requirements.txt           # Python 运行时依赖
├── suwayomi/
│   ├── __init__.py
│   ├── client.py              # Suwayomi GraphQL 异步 HTTP 客户端
│   └── models.py              # 数据模型（Source, Manga, Chapter, SearchResult）
├── utils/
│   ├── __init__.py
│   ├── pack.py               # 图片打包工具（ZIP/CBZ/PDF）
│   └── subscription.py        # 订阅管理器（AstrBot KV 存储封装）
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # Mock astrbot 模块（独立运行集成测试）
│   ├── test_pack.py           # 打包功能单元测试
│   ├── test_models.py         # 数据模型单元测试
│   ├── test_client.py         # 客户端单元测试（mocked HTTP）
│   ├── test_subscription.py   # 订阅管理单元测试
│   └── test_live_api.py       # 实时 API 集成测试
├── docs/
│   ├── setup.md               # 用户配置教程
│   ├── dev/                   # 开发者文档
│   │   ├── development.md     # 架构详解、设计决策
│   │   └── suwayomi-api.md    # GraphQL API 参考
│   └── superpowers/           # 设计文档和实现计划
├── CHANGELOG.md               # 版本变更日志
├── CONTRIBUTING.md            # 本文档
├── AGENTS.md                  # AI 辅助开发指南
└── README.md                  # 用户文档
```

## 开发流程

### 1. 创建分支

```bash
git checkout -b feature/your-feature-name
# 或
git checkout -b fix/your-bug-fix
```

### 2. 开发

- 遵循现有代码风格
- 新增功能请添加测试
- 修改 API 或配置时更新相关文档

### 3. 测试

```bash
# 确保所有单元测试通过
uv run pytest tests/test_pack.py tests/test_models.py tests/test_client.py tests/test_subscription.py -v

# 语法检查
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
```

### 4. 提交

```bash
git add .
git commit -m "feat: your feature description"
```

### 5. 推送并创建 PR

```bash
git push origin feature/your-feature-name
```

## 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
<type>: <description>

[optional body]
```

### Type 类型

| Type | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档更新 |
| `style` | 代码格式（不影响功能） |
| `refactor` | 重构（不是新功能也不是修复） |
| `test` | 添加或修改测试 |
| `chore` | 构建过程或辅助工具变更 |

### 示例

```bash
feat: 添加漫画收藏功能
fix: 修复重复章节编号显示问题
docs: 更新配置教程
test: 添加订阅管理单元测试
```

## 添加新命令

### 步骤

1. 在 `main.py` 的 `SuwayomiPlugin` 类中添加方法
2. 使用 `@manga_group.command("命令名")` 装饰器
3. 第一个参数必须是 `event: AstrMessageEvent`
4. 使用 `yield event.plain_result(...)` 返回文本
5. 使用 `yield event.chain_result([...])` 返回富媒体
6. 在方法 docstring 中写明用法（AstrBot 展示给用户）
7. 所有用户提示文本使用 `「漫画 命令名」` 格式（带空格）

### 示例

```python
@manga_group.command("收藏")
async def favorite_manga(self, event: AstrMessageEvent, manga_name_or_id: str):
    '''收藏漫画。用法: /漫画 收藏 <漫画名或ID>'''
    try:
        manga, err = await self._resolve_manga(event, manga_name_or_id, "收藏")
        if err or manga is None:
            yield event.plain_result(err or "未找到该漫画。")
            return

        # 实现收藏逻辑
        yield event.plain_result(f"✅ 已收藏「{manga.title}」。")

    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] favorite error: {e}")
        yield event.plain_result("收藏失败，请稍后重试。")
```

### 命令参数

- AstrBot 将所有参数作为原始字符串传递
- 使用 `str` 类型注解，手动进行类型转换
- 可选参数使用默认值：`chapter_num: str = ""`

## 测试

### 单元测试

放在 `tests/` 目录下，使用 `pytest` 框架：

```python
import pytest
from suwayomi.models import Manga

def test_manga_from_dict():
    data = {"id": 42, "title": "One Piece"}
    manga = Manga.from_dict(data)
    assert manga.id == 42
    assert manga.title == "One Piece"
```

### 异步测试

使用 `@pytest.mark.asyncio` 装饰器：

```python
import pytest

@pytest.mark.asyncio
async def test_subscribe():
    # 测试异步逻辑
    pass
### 集成测试

集成测试放在 `tests/test_live_api.py`，默认跳过。需要设置环境变量：

```bash
SUWAYOMI_URL=http://localhost:9330 uv run pytest tests/test_live_api.py -v -s
```

## 文档更新

修改以下内容时，请同步更新文档：

| 修改内容 | 需要更新的文档 |
|---------|---------------|
| 新增/修改命令 | `README.md`, `AGENTS.md`, `main.py` 帮助文本 |
| 新增/修改配置 | `_conf_schema.json`, `docs/setup.md`, `AGENTS.md` |
| 新增/修改 API | `docs/dev/suwayomi-api.md` |
| 架构变更 | `docs/dev/development.md`, `AGENTS.md` |
| 版本发布 | `metadata.yaml`, `CHANGELOG.md` |

> 完整的文件更新清单见 [docs/dev/doc-update-checklist.md](docs/dev/doc-update-checklist.md)。

## 常见问题

### Q: 如何调试 GraphQL 查询？

使用 Suwayomi-Server 的 GraphQL Playground：
1. 打开 `http://localhost:9330/api/graphql`
2. 在浏览器中直接测试查询

### Q: 如何添加新的 GraphQL 查询？

1. 在 `suwayomi/client.py` 中添加方法
2. 使用 `await self._raw_query(query, variables)` 发送请求
3. 在 `suwayomi/models.py` 中添加对应的 `from_dict()` 方法
4. 添加单元测试

### Q: 配置项如何添加？

1. 在 `_conf_schema.json` 中添加配置定义
2. 在 `main.py` 的 `__init__` 或使用处读取配置：`self.config.get("key", default)`
3. 更新 `docs/setup.md` 配置表格

### Q: 版本号在哪里更新？

版本号在 `metadata.yaml` 和 `pyproject.toml` 中，发布时需要同步更新：
1. 更新 `metadata.yaml` 中的 `version`
2. 更新 `README.md` 中的版本 badge
3. 更新 `CHANGELOG.md`
4. 提交并打 tag：`git tag v0.x.x`

## 相关文档

- [开发指南](docs/dev/development.md) — 架构详解、设计决策
- [Suwayomi API 参考](docs/dev/suwayomi-api.md) — GraphQL API 文档
- [配置教程](docs/setup.md) — Suwayomi-Server 部署和插件配置
- [变更日志](CHANGELOG.md) — 版本更新记录
- [文档更新清单](docs/dev/doc-update-checklist.md) — 各类变更需同步更新的文件列表

## 获取帮助

- 提交 [Issue](https://github.com/FFFold/astrbot_plugin_suwayomi_server/issues) 报告 Bug 或建议
- 查看 [AGENTS.md](AGENTS.md) 了解 AI 辅助开发指南
