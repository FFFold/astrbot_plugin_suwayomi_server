# 指令结果卡片化（T2I 渲染）设计

> 日期：2026-08-16
> 状态：已评审通过，待实现
> 目标：通过 AstrBot 的 T2I（HTML→图片）服务，把插件的纯文本指令结果渲染为带漫画封面的精美卡片，提升手机端阅读体验。

## 背景与动机

当前 `main.py` 中大多数指令（搜索、订阅、我的订阅、批量订阅、更新通知、章节列表）结果均为纯文本。用户希望：
1. 展示漫画封面等视觉信息；
2. 文本与图片融为一体（卡片）；
3. 适配手机端阅读（窄卡、文字可读）。

### AstrBot T2I 机制约束（调研结论）

- `Star.html_render(tmpl, tmpldata, return_url, options)` 仅走网络：调用官方端点（`t2i.soulter.top`）或自建 `astrbot-t2i-service`，**无本地回退**，全部端点失败时抛 `RuntimeError`。
- 服务端渲染 HTML（Playwright 截图），**无法访问用户内网/localhost 的 Suwayomi，也无法携带认证头** → 封面必须本地下载（带认证）→ PIL 压缩 → **base64 data URL** 嵌入 HTML。
- 服务端原生支持 Jinja2（`tmpl` + `tmpldata`），且支持 `options.viewport_width`（默认 800px）。
- 渲染产物生命周期：`return_url=False` 时返回本地文件，发送后由 `schedule_cleanup` 清理（避免依赖远端图片 24h 生命周期）。

## 范围

以下命令/通知的结果卡片化（开关关闭或渲染失败时保持现有纯文本行为）：

| 卡片类型 | 来源命令/场景 |
| --- | --- |
| 搜索卡 | `/漫画 搜索` |
| 订阅确认卡 | `/漫画 订阅` |
| 批量订阅卡 | `/漫画 批量订阅`（汇总） |
| 我的订阅卡 | `/漫画 我的订阅` |
| 更新通知卡（单部/多部） | `check_updates` 推送 + `/漫画 更新` 汇总 |
| 章节卡（分块多图） | `/漫画 章节` |

**不卡片化**：`帮助`、`源`、`推送 开/关/状态`（纯信息、无封面数据）、`阅读`/`下载` 的加载中提示与正文（正文本身就是图片/文件）。

## 已确认决策

1. **范围**：上表 6 类全部卡片化。
2. **失败降级**：T2I 渲染失败/超时 → 回退现有纯文本（零回归）。
3. **配置**：全局开关（`result_cards_enabled`，默认 true）。
4. **视觉**（见下节）：浅色主题、列表行/左封面右信息/中等封面行堆叠/状态徽章行/分块三列。
5. **封面策略**：全部并发下载（复用 `download_concurrency`），失败/缺失显示占位块。
6. **卡片宽度 440px**（`options.viewport_width=440`）：手机端（~350-400px 显示）文字保持可读；布局结构不变，组件比例等比缩小。

## 视觉规格（440px 窄卡）

统一基础：宽度 440px、浅色背景 `#f8f9fb`、白色卡片块 + `box-shadow`、圆角 8-12px、字体 `"PingFang SC", "Microsoft YaHei", sans-serif`、章节行 `Consolas, monospace`。渲染选项 `{"type": "jpeg", "quality": 85}`（q40 对文本过糊）。

| 卡片 | 结构 | 关键尺寸 |
| --- | --- | --- |
| 搜索卡 | 头部 `🔍 搜索结果（源 · N 条）` → 行组件：编号圆徽章(20px) / 封面 44×60 / 标题 15px + 副行 `📖 连载中 · 200 话`（状态并入副行） | 每行 padding 8×10 |
| 订阅确认卡 | 左封面 120×168 + 右：`✅ 订阅成功` / 标题 / `ID · 源` / 状态胶囊 / 底部提示 | |
| 单部更新卡 | 左封面 160×224 + 右：`📢 标题 更新了！` / 状态+源标签 / 章节胶囊 / 阅读提示 | |
| 多部更新卡 | 头部 `📢 N 部漫画更新了` → 每部一行：封面 72×100 + 标题+状态徽章 + 章节胶囊 + 阅读提示 | 垂直堆叠 |
| 批量订阅卡 | 头部 `📚 批量订阅完成（x 新增, y 已存在, z 失败）` → 行组件：✓绿/⏭黄/✕红徽章 + 封面 44×60 + 标题 + 结果说明 | |
| 章节卡 | 第 1 张：信息卡（封面 100×140 + 标题/源/总话数/本地数 + 状态胶囊 + `--刷新` 提示）+ 三列章节块；续卡：迷你头部（封面 36×50 + `章节续 (2/N)`）+ 三列 | 每列宽约 130px，章节行 12px/行高 1.8，长名截断 |

**章节行格式**：`#253 终局`（复用 `fmt_chapter_label` 的 `ID:xxx` 重复编号标注与 📥 下载标记）。

**分块算法**：`_MAX_CARD_HEIGHT_PX = 1400`、`_MAX_CHAPTER_CARDS = 4`（纯算术切块可单测）。440px 宽下每卡约 130 行（每列 ~43 行：1400 − 头部 ~230px 后，12px/行高 1.8 ≈ 21.6px/行），253 话 ≈ 2 张卡；超过 4 张卡的上限后，剩余行回退纯文本（与现状分块行为一致）。

## 架构

### 新模块 `suwayomi/cards.py`（纯函数 + 依赖注入，镜像 `service.py` 风格）

```
suwayomi/cards.py
  ├── HTML_TEMPLATE           # 单个 Jinja2 模板字符串（服务端原生渲染 jinja2）
  │                            #   内含 6 变体 {% if %} 分支 + 共享 CSS/宏
  ├── build_search_card(items)            -> (tmpldata, fallback_text)
  ├── build_subscriptions_card(items)     -> (tmpldata, fallback_text)
  ├── build_update_card(items)            -> (tmpldata, fallback_text)   # 单部/多部同构
  ├── build_batch_card(results)           -> (tmpldata, fallback_text)
  ├── build_subscribe_confirm_card(manga) -> (tmpldata, fallback_text)
  ├── build_chapter_cards(manga, lines)   -> (list[tmpldata], tail_lines)  # 分块
  ├── embed_covers(client, items)         # 并发下载→PIL 120px JPEG q80→base64 data URL
  │                                        #   失败→占位标记（纯函数内 mock 下载器可测）
  └── render_card(html_render_fn, tmpldata, options, timeout) -> str | None
```

- 数据准备函数均返回 `(tmpldata, fallback_text)`：文本内容始终生成，供回退使用（避免回退时重新拼装）。
- 标题/章节名等用户可控文本在准备阶段 `html.escape()`（不依赖服务端 autoescape）。
- `embed_covers`：复用 `utils/downloader.download_images`（带 `client.auth_headers`），PIL 压缩为宽 120px JPEG q80 → `data:image/jpeg;base64,...`；失败置 `cover_data_url=None` → 模板渲染灰色占位块。
- `render_card`：`asyncio.timeout`（`card_render_timeout_sec`）包裹 `html_render(..., return_url=False)`；成功返回本地路径，任何异常/超时返回 `None`。
- 渲染结果内存缓存：`(card_type, sha1(tmpldata)) -> (path, ts)`，TTL 10 分钟（与 `_search_cache` 同款模式）；缓存文件经 `schedule_cleanup` 延后清理。

### 命令接入（main.py 统一套路）

```
开关开 → embed_covers → render_card → 成功: yield 图片链（+ 必要文本尾部）
                                   → None: ↓
开关关 → 原有纯文本（不变）
```

- 搜索：`build_search_card` 一次渲染一张卡；文本尾行提示仍保留。
- 我的订阅：订阅记录无封面 URL → 先并行 `client.get_manga()` 拉取元数据（失败用存储标题 + 占位封面）。
- 章节：`build_chapter_cards` 分块 → 每块独立 `render_card` 串行渲染（保证 `(2/N)` 编号顺序）→ 图片链 + 尾部文本行；现有 `chapter_list_show_cover` 开关语义保持（开关 = 不用卡片化路径，直接走旧逻辑）。
- 订阅确认/批量订阅：替换对应 `plain_result` 分支。

### 更新通知接入（updater.py）

- `check_updates()` 注入可选 `render_update_card_fn`（main.py `_build_check_updates_fn` 预绑定）。
- 渲染成功 → 把对每个会话的文本通知替换为单张**多部更新卡**（含全部更新漫画行）。
- 渲染失败/未注入 → 维持现有文本消息；渲染耗时不影响 `update_lock` 流程。
- `_check_one_manga` 已 fetch `Manga`（含 `thumbnail_url`），透传给卡片数据。
- `/漫画 更新` 的 `summary` 返回文本同样可换为多部更新卡（调用侧回退文本）。

## 错误处理

- `render_card` 捕获一切异常（网络、端点、PIL、超时）→ `None` → 文本回退。**卡片是增量增强，绝不因 T2I 故障导致命令失败**。
- 封面部分失败 → 仅影响该行占位。
- 章节卡渲染 4 张后超出 → 尾部文本。
- 开关关闭/配置异常 → 文本。

## 性能

- 封面并发下载复用 `download_concurrency`（默认 6）与 `download_retries`。
- PIL 压缩 120px JPEG q80：单张 10-25KB，20 张 ≈ 400-500KB base64 请求体。
- 渲染结果 TTL 缓存避免同查询重复渲染（搜索类命令收益最大）。
- 章节卡串行渲染（顺序语义），每张独立超时。

## 配置新增（_conf_schema.json）

```jsonc
{
  "result_cards_enabled": { "type": "bool", "default": true,
    "description": "指令结果卡片渲染", "hint": "使用 T2I 服务把指令结果渲染为带封面的卡片；关闭或渲染失败时回退纯文本" },
  "card_render_timeout_sec": { "type": "int", "default": 30, "min": 5, "max": 120,
    "description": "卡片渲染超时（秒）" }
}
```

## 依赖

- `requirements.txt` 显式补充 `pillow`（AstrBot 核心已传递依赖，声明更规范；仅用于封面压缩）。

## 测试

**新增 `tests/test_cards.py`**（纯单测，mock 下载器与 `html_render`）：
- 数据准备：编号连续、状态映射、HTML 转义、章节行格式（`#N 名`、`ID:xxx`、📥）、长名截断。
- 分块算法：0 行/少行/253 行 → 正确分块与 `(2/N)` 编号；剩余行返回。
- `embed_covers`：mock 下载成功/失败/部分失败 → data URL 或占位，无异常泄漏。
- `render_card`：成功返回路径；异常/超时返回 `None`。
- 缓存：命中不重复渲染；TTL 过期重渲染。

**命令层回归**：
- `test_list_chapters.py`：开关关 → 旧行为；渲染失败 → 文本回退。
- `test_updater.py`：注入 mock 渲染成功 → 卡片消息；失败 → 文本；多部 → 单卡。
- AI 发送路径（`test_ai_service.py`/`test_push.py`）不加卡片，不受影响。

**手动验收**（实现计划内含步骤）：真实端点渲染搜索卡/章节卡/更新通知卡截图确认视觉效果。

## 不做的事（YAGNI）

- 本地 PIL 卡片渲染回退（本地渲染器不支持自定义 HTML；文本回退已足够）。
- 每命令独立开关、主题切换（暗色）、卡片模板用户自定义。
- 封面缓存（base64 已入渲染缓存）。
- `text_to_image`（Markdown 渲染）路线。
