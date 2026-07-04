# 文档去重设计

**日期**: 2026-07-04
**状态**: 待实现

## 问题

项目文档中存在大量重复信息，同一内容（命令列表、配置表、测试数量、架构描述）分散在 5+ 个文件中，每次变更需要同步更新多处，容易遗漏。

## 方案：文档责任分层 + 交叉引用

每份文档划定唯一责任范围，同一信息只在一个地方维护，其余文件通过链接引用。

### 责任分层

| 文件 | 唯一维护内容 | 去掉的重复 |
|------|------------|-----------|
| **`README.md`** | 命令参考表 + 配置参考表（**权威来源**） | —（成为源头） |
| **`AGENTS.md`** | 架构 + 关键方法 + Quirks + 添加命令流程 + 测试运行命令 | 去掉命令列表、配置列表、测试计数 |
| **`docs/setup.md`** | 部署和配置教程 | 去掉独立配置表（引用 README） |
| **`docs/dev/development.md`** | 架构详解 + 数据流 + 设计决策 | 去掉命令/配置/测试列表和计数 |
| **`CONTRIBUTING.md`** | 开发环境搭建 + 提交规范 + 项目结构 | 去掉命令/配置列表、测试计数 |
| **`main.py`** docstring | 命令帮助文本（**唯一来源**） | — |

### 测试计数处理

测试数量的具体数字全部从文档中移除，原因：
- 变化频繁（每加一个测试就要同步改所有文档）
- 实际价值低——用户关心的是怎么跑测试，不是具体数字
- 想查数量可直接运行 `uv run pytest --collect-only`

保留测试运行命令（实用指令）在 `AGENTS.md`，其他文件引用 `AGENTS.md`。

### 变更时的同步规则

| 变更类型 | 只需更新的文件 |
|---------|--------------|
| 新增/修改命令 | `main.py` docstring + `README.md` 命令表 |
| 新增/修改配置 | `_conf_schema.json` + `README.md` 配置表 |
| 架构变更 | `AGENTS.md` |
| 测试变更 | `AGENTS.md`（运行命令）+ 测试文件本身 |
| 版本发布 | `metadata.yaml` + `CHANGELOG.md` + `README.md` badge |
| API 变更 | `suwayomi/client.py` + `docs/dev/suwayomi-api.md` |

## 具体变更

### README.md

不变。直接成为命令表和配置表的唯一权威来源。

### AGENTS.md

1. Architecture 段落：去掉 `(14 个命令)` → 改为 `(所有命令，详见 README)`
2. 去掉 Config Options 整个段落，改为一行引用
3. Commands 段：去掉 `(113 tests, no network needed)` 中的数字 `113`，保留命令
4. 去掉最后 "Documentation Update Checklist" 段落（已有 doc-update-checklist.md 引用）

### docs/dev/development.md

1. 项目结构中的测试文件：去掉 `（19 个）`、`（9 个）` 等计数
2. 架构图中的 `(14 个命令)` → 去掉或改为引用
3. 运行测试命令中的 `（113 个，无需网络）` → 去掉计数，保留说明

### CONTRIBUTING.md

1. 项目结构中的 `test_push.py`：去掉 `（14 个）`
2. 文档更新表格：改为引用 README 和 AGENTS.md 作为权威来源
3. FAQ 中的配置添加步骤：`docs/setup.md 配置表格` → `README.md 配置表`

### doc-update-checklist.md

更新为反映新的责任分层：

- 命令变更：只列 `README.md`（不再是 README + AGENTS.md 等多处）
- 配置变更：只列 `README.md`（不再是 README + docs/setup.md + AGENTS.md）
- 测试变更：去掉 `AGENTS.md 单元测试数量` 条目
