# 章节选择解析与提示修复 Implementation Plan

> **执行后调整（2026-11-13）**：命令层按本计划落地；AI 侧最终**未**复用匹配核心 —— `selector` 收窄为 `latest`/`list`/章节号/`ID:数字`，Agent 按返回的 `chapter_id` 选择（Task 2 的共享方案被放弃）。现状以 `docs/superpowers/specs/2026-11-13-chapter-resolution-design.md` 为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `/漫画 阅读/下载` 与 AI 章节选择同时接受编号、`第X话/第X卷`、章节名和 `ID:数字`，并在无法唯一确定时列出带名字的候选而不是裸 ID。

**Architecture:** 在 `suwayomi/service.py` 增加纯匹配核心 `match_chapters()`（归一化键 + 单位判定 + 候选集），`resolve_chapter()` 只负责把匹配结果渲染成中文文案；`ai_service` 复用同一核心。所有匹配是纯函数，不触网。

**Tech Stack:** Python 3.12、pytest、opencc（t2s）、dataclass `Chapter`。

**Spec:** `docs/superpowers/specs/2026-11-13-chapter-resolution-design.md`

## Global Constraints

- 用户可见文案一律中文；命令写法用 `「漫画 阅读」` 空格格式；`/漫画 阅读 …` 用法行保持可复制。
- 第三方/用户文本进入消息前必须过 `sanitize_for_message`（标题限 80，输入限 40）。
- 编号命中多个且无法用名称唯一确定时，**必须让用户选**，禁止自动挑"正篇"（用户已拍板）。
- 名称归一化不得让不同数字相等：保留 `.`，并对比较双方做数字序列校验。
- 不联网的单元测试必须覆盖全部规则；`tests/test_live_api.py` 不属于本计划。

## Review Focus

- `第01话` / `第1话` / `第１话` / `第1話` 必须都命中同一章，不能因前导零、全角、繁体而落到歧义。
- `第3卷` 在只有 `第03话` 的书里不能静默读第 3 话，必须报"没有卷"并列出 `第03话`。
- `第05话` 与 `第05话后篇` 同号时，`第5话` 要选中 `第05话`，`5` 要列出两个。
- 名称输入（`番外`、`附录`、`单行本`）不能跨章误配；单字/空输入必须给出提示而不是抛异常。
- 源站 `chapterNumber=5` 但名字是 `第15话` 时，`第5话` 不能静默选中，必须提示名称冲突并用 ID 确认。

---

### Task 1: 匹配核心与 `resolve_chapter`

**Files:**
- Modify: `suwayomi/service.py:41-55`（后缀表）、`suwayomi/service.py:128-164`（匹配与文案）
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `Chapter`（`id: int`, `name: str`, `chapter_number: float`）、`sanitize_for_message()`、`normalize_zh()`、`fmt_chapter_num()`、`fmt_chapter_label()`。
- Produces:
  - `chapter_name_key(text: str) -> str`
  - `match_chapters(chapters: list[Chapter], text: str) -> tuple[list[Chapter], str]`，`kind ∈ {"matched","ambiguous","unit_mismatch","name_conflict","not_found"}`
  - `parse_chapter_number_text(text: str) -> float | None`（扩展后缀，签名不变）
  - `resolve_chapter(chapters, chapter_num, manga_name_or_id, cmd) -> tuple[Chapter | None, str | None]`（签名不变）

- [ ] **Step 1: 写失败测试（真实语料夹具 + 规则断言）**

在 `tests/test_service.py` 增加：

```python
REAL_CHAPTERS = [
    _chapter(2531, "第01话", 1), _chapter(2532, "番外篇1", 1),
    _chapter(2539, "单行本：第01卷", 1), _chapter(2538, "单行本：第02卷", 2),
    _chapter(2527, "第05话", 5), _chapter(2526, "第05话后篇", 5),
    _chapter(2477, "07卷附录", 7), _chapter(2524, "第07话", 7),
    _chapter(2488, "第38.2话", 38.2), _chapter(2522, "第09话", 9),
    _chapter(8485, "番外篇2", 2),
]

@pytest.mark.parametrize("text", ["第1话", "第01话", "第１话", "第1話", "第１話"])
def test_name_key_ignores_leading_zero_width_and_traditional(text):
    target, err = resolve_chapter(REAL_CHAPTERS, text, "安达与岛村", "阅读")
    assert err is None and target is not None and target.id == 2531

@pytest.mark.parametrize("text", ["第1卷", "第01卷", "01卷", "第2卷"])
def test_volume_unit_selects_volume(text):
    target, _ = resolve_chapter(REAL_CHAPTERS, text, "安达与岛村", "阅读")
    assert target is not None and target.id in {2539, 2538}

def test_unit_mismatch_never_silently_picks_other_unit():
    target, err = resolve_chapter(REAL_CHAPTERS, "第3卷", "安达与岛村", "阅读")
    assert target is None and "卷" in err and "ID:2529" in err

def test_ambiguous_message_lists_names_and_one_usage_line():
    target, err = resolve_chapter(REAL_CHAPTERS, "1", "安达与岛村", "阅读")
    assert target is None
    assert "第01话" in err and "番外篇1" in err and "单行本：第01卷" in err
    assert err.count("用法:") == 1 and "ID:2531" in err
    assert "第 1 话" not in err  # 旧模板重复"第/话"

def test_ambiguous_suffix_input_does_not_duplicate_di_prefix():
    _, err = resolve_chapter(REAL_CHAPTERS, "第01话", "安达与岛村", "阅读")
    assert err is None  # 名称精确命中，不再进歧义分支

def test_five_selects_plain_chapter_not_afterword():
    target, err = resolve_chapter(REAL_CHAPTERS, "第5话", "安达与岛村", "阅读")
    assert err is None and target.id == 2527

def test_bare_number_five_is_ambiguous_between_both():
    target, err = resolve_chapter(REAL_CHAPTERS, "5", "安达与岛村", "阅读")
    assert target is None and "第05话" in err and "第05话后篇" in err

@pytest.mark.parametrize("text,expected", [("番外篇1", 2532), ("附录", 2477), ("单行本：第01卷", 2539)])
def test_name_inputs_resolve(text, expected):
    target, err = resolve_chapter(REAL_CHAPTERS, text, "安达与岛村", "阅读")
    assert err is None and target.id == expected

def test_partial_name_stays_ambiguous():
    target, err = resolve_chapter(REAL_CHAPTERS, "番外", "安达与岛村", "阅读")
    assert target is None and "番外篇1" in err and "番外篇2" in err

def test_single_char_and_empty_input_are_not_matched():
    for text in ("卷", "", "   "):
        target, err = resolve_chapter(REAL_CHAPTERS, text, "安达与岛村", "阅读")
        assert target is None and "ID:123" in err

def test_name_conflict_is_reported_not_selected():
    chapters = [_chapter(2, "第15话", 5)]
    target, err = resolve_chapter(chapters, "第5话", "测试漫画", "阅读")
    assert target is None and "ID:2" in err and "第15话" in err
    target, err = resolve_chapter(chapters, "5", "测试漫画", "阅读")
    assert err is None and target.id == 2

def test_duplicate_names_stay_ambiguous():
    chapters = [_chapter(1, "第1话", 1), _chapter(3, "第1话", 1)]
    target, err = resolve_chapter(chapters, "第1话", "测试漫画", "阅读")
    assert target is None and "ID:1" in err and "ID:3" in err

def test_normalization_does_not_merge_different_numbers():
    chapters = [_chapter(1, "第1-2话", 12), _chapter(2, "第12话", 12)]
    target, err = resolve_chapter(chapters, "第12话", "测试漫画", "阅读")
    assert err is None and target.id == 2
```

- [ ] **Step 2: 运行新测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_service.py -v`
Expected: FAIL（`第1卷` 报"章节号无效"、歧义消息只有裸 ID 等）。

- [ ] **Step 3: 实现归一化与匹配核心**

在 `suwayomi/service.py`：

```python
_CHAPTER_UNIT_MARKS = "话話章回集"
_VOLUME_UNIT_MARKS = "卷冊册"
_ALL_UNIT_MARKS = _CHAPTER_UNIT_MARKS + _VOLUME_UNIT_MARKS
_CHAPTER_NUM_SUFFIX_RE = re.compile(r"[话話章回集卷冊册]$")  # 替换原 (?:话|話|章)$
_SEPARATOR_RE = re.compile(r"[\s:：·・、,，。~()\[\]【】{}!?！？\"'“”‘’#*_]+")
_LEADING_ZERO_RE = re.compile(r"(?<!\d)0+(?=\d)")
_DIGIT_RUN_RE = re.compile(r"\d+(?:\.\d+)?")

def chapter_name_key(text: str) -> str: ...
def _digit_runs(key: str) -> tuple[str, ...]: ...
def _unit_after_number(key: str, num: float) -> str | None: ...
def _name_unit(chapter: Chapter, num: float) -> str | None: ...
def _name_has_other_number(chapter: Chapter, num: float, unit: str) -> bool: ...
def match_chapters(chapters: list[Chapter], text: str) -> tuple[list[Chapter], str]: ...
```

规则（照 spec 实现，勿扩展）：
- `parse_chapter_number_text` 先 NFKC、剥 `#`/`#`/`第`、再剥单位后缀；解析失败返回 `None`。
- 数字分支：容差 `abs(num - n) < 0.01`；有单位先按 `(?<!\d)<num>[单位]` 过滤，过滤为空但候选带另一种单位 → `unit_mismatch`；候选名 key 与输入 key 相等 + 数字序列相等且唯一 → `matched`；候选唯一时若 `_name_has_other_number()` 为真 → `name_conflict`，否则 `matched`；多个 → `ambiguous`。
- 非数字分支：名称 key 精确（数字序列校验）唯一 → `matched`；否则 key 长度 ≥ 2 时做包含匹配（输入首/尾是数字时加 `(?<!\d)` / `(?!\d)`），唯一 → `matched`，多个 → `ambiguous`；否则 `not_found`。
- `_unit_after_number` 只认紧邻编号的单位字符；`_name_has_other_number` 只在"同单位、不同编号"时返回真。

- [ ] **Step 4: 重写 `resolve_chapter` 文案**

保留 `ID:` 分支不动；其余按 kind 渲染：

```python
def _chapter_choices_lines(chapters, limit=10) -> list[str]:  # "#1 名字 (ID:2531)"
```

- `ambiguous`：`「{input}」匹配到 N 个章节，请用 ID 指定：` + 行 + `用法: /漫画 {cmd} {manga} ID:{第一个候选id}` + 超出提示 `… 共 N 个`。
- `unit_mismatch`：`「{input}」未匹配到{卷/话}，编号 {num} 只有：` + 行 + 用法（指向第一个候选 ID）。
- `name_conflict`：`编号 {num} 的章节名是「{name}」，与输入「{input}」不一致：` + 行 + `用法: /漫画 {cmd} {manga} {num}  或  ID:{id}`。
- `not_found`：`未找到「{input}」对应的章节。可用：1、38.5、第5话、第1卷、章节名，或 ID:123；也可先 /漫画 {cmd === "阅读" ? "章节" : "章节"} {manga} 查看列表。`（实际写成统一一句，`/漫画 章节`）。

所有插入的输入/名字/漫画名走 `sanitize_for_message`；`N` 为候选总数。

- [ ] **Step 5: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_service.py -v`
Expected: PASS（含原有 47 项）。

- [ ] **Step 6: 提交**

```bash
git add suwayomi/service.py tests/test_service.py
git commit -m "feat(chapter): 支持卷/名称匹配并让歧义提示带章节名"
```

---

### Task 2: AI 章节选择复用匹配核心

**Files:**
- Modify: `suwayomi/ai_service.py:259-288`
- Test: `tests/test_ai_service.py`

**Interfaces:**
- Consumes: `match_chapters(chapters, text) -> (candidates, kind)` from Task 1。
- Produces: `_select_chapter_candidates(chapters, selector) -> tuple[Chapter | None, list[Chapter], str | None]`（签名不变）。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_ai_service.py`：

```python
def test_selector_accepts_chapter_name_and_volume():
    from suwayomi.ai_service import _select_chapter_candidates
    chapters = [
        _chapter_with_name(2531, "第01话", 1),
        _chapter_with_name(2539, "单行本：第01卷", 1),
    ]
    selected, _, err = _select_chapter_candidates(chapters, "第1卷")
    assert err is None and selected.id == 2539
    selected, _, err = _select_chapter_candidates(chapters, "第01话")
    assert err is None and selected.id == 2531

def test_selector_unit_mismatch_returns_candidates_not_wrong_chapter():
    from suwayomi.ai_service import _select_chapter_candidates
    chapters = [_chapter_with_name(2529, "第03话", 3)]
    selected, candidates, err = _select_chapter_candidates(chapters, "第3卷")
    assert selected is None and [c.id for c in candidates] == [2529] and err
```

（若现有测试辅助函数 `_chapter` 不带 `name`，新增 `_chapter_with_name`，或在原 helper 上加 `name` 默认参数。）

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ai_service.py -v`
Expected: FAIL（`第1卷` 走 `parse_chapter_number_text` 失败）。

- [ ] **Step 3: 替换数字匹配段**

`_select_chapter_candidates` 中，`latest/list/ID` 分支保持；把 `parse_chapter_number_text(...)+严格相等` 一段替换为：

```python
candidates, kind = match_chapters(chapters, normalized)
if kind == "not_found":
    return None, [], f"未找到「{selector}」对应的章节"
if kind == "matched" and len(candidates) == 1:
    return candidates[0], candidates, None
return None, candidates, "同一章节号存在多个结果，需要使用 chapter_id 明确选择"
```

- [ ] **Step 4: 运行测试**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ai_service.py tests/test_ai_tools.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add suwayomi/ai_service.py tests/test_ai_service.py
git commit -m "refactor(ai): 章节选择复用统一匹配核心"
```

---

### Task 3: 帮助、用法与工具描述

**Files:**
- Modify: `main.py:847-856`（帮助）、`main.py:1715-1720`（阅读用法）、`main.py:1776-1787`（下载用法）
- Modify: `suwayomi/ai_tools.py:96`
- Test: `tests/test_service.py` 已有文案断言；本任务补 `tests/test_help.py`（新建，直接断言帮助字符串）

**Interfaces:**
- Consumes: 无（纯文案）。
- Produces: 帮助与用法文本包含 `第5话`、`第01卷`、`章节名`、`ID:123` 四种写法。

- [ ] **Step 1: 写失败测试**

`tests/test_help.py`：

```python
from pathlib import Path

def test_help_mentions_all_selector_forms():
    text = Path("main.py").read_text(encoding="utf-8")
    assert "第5话" in text and "第01卷" in text and "章节名" in text
    assert "列表里重号会标注 ID" in text

def test_ai_tool_selector_description_mentions_volume_and_name():
    text = Path("suwayomi/ai_tools.py").read_text(encoding="utf-8")
    assert "第5话" in text and "第01卷" in text and "章节名" in text
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_help.py -v`
Expected: FAIL。

- [ ] **Step 3: 更新文案**

- 帮助「📚 阅读与下载」：`<章节号|第X话|第X卷|章节名|ID:数字>`，补一行示例 `例: /漫画 阅读 一拳超人 1 / 第5话 / 第01卷 / ID:123` 与 `列表里重号会标注 ID`。
- `read_chapter` 用法提示与 docstring 同步：缺参数时说明四种写法并给 `章节名` 示例。
- `download_chapter` 用法与 docstring 同步。
- `ai_tools.py` 的 `selector` 描述：`list、latest、章节号（1 / 38.5）、第5话 / 第01卷、章节名或 ID:数字`。

- [ ] **Step 4: 运行测试**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_help.py tests/test_service.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add main.py suwayomi/ai_tools.py tests/test_help.py
git commit -m "docs(help): 说明章节号/卷/名称/ID 四种选择方式"
```

---

### Task 4: 开发文档与变更日志

**Files:**
- Modify: `docs/dev/development.md:158`
- Modify: `README.md:78-79`、`README.md:92`
- Modify: `CHANGELOG.md`（顶部未发布段）

**Interfaces:** 无代码接口。

- [ ] **Step 1: 更新 `docs/dev/development.md` 关键函数说明**

写明 `resolve_chapter` 委托 `match_chapters`，支持 `5`、`第5话`、`第01卷`、章节名、`ID:123`，并说明三种拒绝情形（ambiguous / unit_mismatch / name_conflict）。

- [ ] **Step 2: 更新 README 命令表与 AI 工具表**

阅读/下载行改为 `<章节号|第X话|第X卷|章节名|ID:数字>`；AI `selector` 行同步。

- [ ] **Step 3: 更新 CHANGELOG**

在顶部未发布段新增两条：命令支持卷/章节名选择；歧义提示列出章节名与可复制用法。

- [ ] **Step 4: 全量测试**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 全绿（live 测试自动跳过）。

- [ ] **Step 5: 提交**

```bash
git add docs/dev/development.md README.md CHANGELOG.md
git commit -m "docs: 同步章节选择能力"
```

---

## 自查记录

- Spec 覆盖：归一化/单位/冲突/文案/帮助/AI/测试/文档均有对应任务。
- 类型一致：`match_chapters` 返回 `(list[Chapter], str)`，Task 2 按该签名使用。
- 未新增非数字名称的"反向包含"匹配，避免过度匹配。
