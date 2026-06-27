# 批量订阅功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `「漫画 批量订阅」` 命令，支持用户一次性提供多个漫画名称，自动搜索并批量订阅。

**Architecture:** 在 `main.py` 中新增 `batch_subscribe` 命令方法和 `_search_best_match` 辅助方法。复用现有 `search_manga` 和 `subscribe` 逻辑，顺序处理每个名称，逐个反馈进度，最后汇总结果。

**Tech Stack:** Python 3.12+, aiohttp, AstrBot plugin framework

---

## 文件结构

仅修改一个文件：
- Modify: `main.py` — 新增 `batch_subscribe` 命令方法 + `_search_best_match` 辅助方法

## 关键参考

- `main.py:56-64` — `STATUS_EMOJI` 常量
- `main.py:270-341` — `search_manga` 命令（源匹配逻辑）
- `main.py:345-368` — `subscribe_manga` 命令（订阅逻辑）
- `utils/subscription.py:21-33` — `SubscriptionManager.subscribe()`
- `suwayomi/models.py:26-53` — `Manga` 数据类

---

### Task 1: 添加 `_search_best_match` 辅助方法

**Files:**
- Modify: `main.py` (在 `search_manga` 方法之前，约 line 268)

- [ ] **Step 1: 在 `SuwayomiPlugin` 类中添加辅助方法**

在 `# ── 漫画搜索 ──────────────────────────────────────────────────` 注释之前，添加：

```python
    async def _search_best_match(self, name: str, source_filter: Source | None = None) -> tuple[Manga | None, str | None]:
        """搜索漫画名称，返回最佳匹配结果。返回 (manga, error_msg)。"""
        sources = await self.client.get_sources()
        if not sources:
            return None, "未找到已安装的漫画源"

        if source_filter:
            target_sources = [source_filter]
        else:
            default_sid = self.config.get("default_source_id", 0)
            if default_sid:
                target_sources = [s for s in sources if s.id == default_sid]
                if not target_sources:
                    target_sources = sources[:3]
            else:
                target_sources = sources[:3]

        for src in target_sources:
            try:
                result = await self.client.search_manga(src.id, name)
                if result.mangas:
                    return result.mangas[0], None
            except Exception as e:
                logger.warning(f"[{PLUGIN_NAME}] 批量订阅搜索源 {src.name} 失败: {e}")

        return None, "未找到匹配结果"
```

- [ ] **Step 2: 验证语法**

```bash
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add _search_best_match helper for batch subscribe"
```

---

### Task 2: 添加 `batch_subscribe` 命令方法

**Files:**
- Modify: `main.py` (在 `subscribe_manga` 方法之后，约 line 368)

- [ ] **Step 1: 添加批量订阅命令**

在 `subscribe_manga` 方法结束后，添加：

```python
    @manga_group.command("批量订阅")
    async def batch_subscribe(self, event: AstrMessageEvent):
        '''批量订阅漫画。用法: /漫画 批量订阅 <名称1>, <名称2>, ... [源名]'''
        try:
            raw = event.message_str.strip()
            prefix = "漫画 批量订阅"
            if not raw.startswith(prefix):
                yield event.plain_result("用法: 漫画 批量订阅 <名称1>, <名称2>, ... [源名]")
                return
            args_str = raw[len(prefix):].strip()
            if not args_str:
                yield event.plain_result("用法: 漫画 批量订阅 <名称1>, <名称2>, ... [源名]\n名称用逗号分隔，如: 漫画 批量订阅 咒术回战, 鬼灭之刃")
                return

            sources = await self.client.get_sources()
            source_filter = None
            search_str = args_str

            last_space = args_str.rfind(" ")
            if last_space > 0:
                potential_source = args_str[last_space + 1:].lower()
                for src in sources:
                    if potential_source in (src.name.lower(), src.display_name.lower(), src.lang.lower()):
                        source_filter = src
                        search_str = args_str[:last_space]
                        break

            raw_names = [n.strip() for n in re.split(r'[,，;；]', search_str) if n.strip()]
            if not raw_names:
                yield event.plain_result("请提供漫画名称，用逗号分隔。")
                return

            if len(raw_names) > 20:
                yield event.plain_result("一次最多批量订阅 20 部漫画。")
                return

            await event.send(event.plain_result(f"📚 开始批量订阅 {len(raw_names)} 部漫画..."))

            umo = event.unified_msg_origin
            existing_subs = await self.sub_mgr.get_subscriptions(umo)
            existing_ids = {s["manga_id"] for s in existing_subs}

            results: list[tuple[str, str, str]] = []
            for i, name in enumerate(raw_names, 1):
                await event.send(event.plain_result(f"正在处理 [{i}/{len(raw_names)}] {name}..."))

                manga, error = await self._search_best_match(name, source_filter)
                if error or manga is None:
                    results.append((name, "fail", error or "未找到匹配结果"))
                    continue

                if manga.id in existing_ids:
                    status_text = STATUS_EMOJI.get(manga.status, "未知")
                    source_name = ""
                    for src in sources:
                        if src.id == manga.source_id:
                            source_name = src.display_name
                            break
                    results.append((name, "exists", f"{manga.title} - {status_text} - {source_name}"))
                    continue

                await self.sub_mgr.subscribe(manga.id, manga.title, manga.source_id, umo)
                existing_ids.add(manga.id)
                try:
                    chapters = await self._get_or_fetch_chapters(manga.id)
                    if chapters:
                        max_id = max(ch.id for ch in chapters)
                        await self.sub_mgr.update_latest_chapter(manga.id, max_id)
                except Exception as e:
                    logger.warning(f"[{PLUGIN_NAME}] 批量订阅拉取「{manga.title}」章节失败: {e}")

                status_text = STATUS_EMOJI.get(manga.status, "未知")
                source_name = ""
                for src in sources:
                    if src.id == manga.source_id:
                        source_name = src.display_name
                        break
                results.append((name, "ok", f"{manga.title} - {status_text} - {source_name}"))

            ok_count = sum(1 for _, s, _ in results if s == "ok")
            exist_count = sum(1 for _, s, _ in results if s == "exists")
            fail_count = sum(1 for _, s, _ in results if s == "fail")

            lines = [f"📚 批量订阅完成 ({ok_count} 新增, {exist_count} 已存在, {fail_count} 失败):"]
            for name, status, info in results:
                if status == "ok":
                    lines.append(f"  ✅ {info}")
                elif status == "exists":
                    lines.append(f"  ⏭ {info} (已订阅)")
                else:
                    lines.append(f"  ❌ {name} - {info}")

            yield event.plain_result("\n".join(lines))

        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] batch_subscribe error: {e}")
            yield event.plain_result("批量订阅失败，请稍后重试。")
```

- [ ] **Step 2: 确保导入完整**

检查 `main.py` 顶部：
- 需要添加 `import re`
- 需要修改 `from .suwayomi.models import Chapter, Manga, SearchResult` 为 `from .suwayomi.models import Chapter, Manga, SearchResult, Source`

- [ ] **Step 3: 验证语法**

```bash
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: add batch subscribe command"
```

---

### Task 3: 添加单元测试

**Files:**
- Create: `tests/test_batch_subscribe.py`

- [ ] **Step 1: 编写批量参数解析测试**

```python
import re


def parse_batch_args(args_str, sources=None):
    """从 batch_subscribe 提取的参数解析逻辑，用于独立测试。"""
    source_filter = None
    search_str = args_str

    if sources:
        last_space = args_str.rfind(" ")
        if last_space > 0:
            potential_source = args_str[last_space + 1:].lower()
            for src in sources:
                if potential_source in (src.name.lower(), src.display_name.lower(), src.lang.lower()):
                    source_filter = src
                    search_str = args_str[:last_space]
                    break

    raw_names = [n.strip() for n in re.split(r'[,，;；]', search_str) if n.strip()]
    return raw_names, source_filter


class MockSource:
    def __init__(self, name, display_name, lang, id):
        self.name = name
        self.display_name = display_name
        self.lang = lang
        self.id = id


def test_parse_simple_names():
    names, sf = parse_batch_args("咒术回战, 鬼灭之刃, 电锯人")
    assert names == ["咒术回战", "鬼灭之刃", "电锯人"]
    assert sf is None


def test_parse_chinese_comma():
    names, sf = parse_batch_args("咒术回战，鬼灭之刃，电锯人")
    assert names == ["咒术回战", "鬼灭之刃", "电锯人"]


def test_parse_semicolon():
    names, sf = parse_batch_args("咒术回战; 鬼灭之刃; 电锯人")
    assert names == ["咒术回战", "鬼灭之刃", "电锯人"]


def test_parse_mixed_separators():
    names, sf = parse_batch_args("咒术回战, 鬼灭之刃；电锯人")
    assert names == ["咒术回战", "鬼灭之刃", "电锯人"]


def test_parse_with_source_filter():
    sources = [MockSource("jm", "禁漫天堂", "zh", "123")]
    names, sf = parse_batch_args("咒术回战, 鬼灭之刃 jm", sources)
    assert names == ["咒术回战", "鬼灭之刃"]
    assert sf is not None
    assert sf.name == "jm"


def test_parse_no_match_treated_as_name():
    sources = [MockSource("jm", "禁漫天堂", "zh", "123")]
    names, sf = parse_batch_args("咒术回战, 鬼灭之刃", sources)
    assert names == ["咒术回战", "鬼灭之刃"]
    assert sf is None


def test_parse_source_by_display_name():
    sources = [MockSource("mangabox", "拷贝漫画", "zh", "456")]
    names, sf = parse_batch_args("咒术回战, 鬼灭之刃 拷贝漫画", sources)
    assert names == ["咒术回战", "鬼灭之刃"]
    assert sf is not None
    assert sf.display_name == "拷贝漫画"


def test_parse_source_by_lang():
    sources = [MockSource("mangabox", "MangaBox", "en", "789")]
    names, sf = parse_batch_args("one piece, naruto en", sources)
    assert names == ["one piece", "naruto"]
    assert sf is not None
    assert sf.lang == "en"


def test_parse_empty():
    names, sf = parse_batch_args("")
    assert names == []


def test_parse_single_name():
    names, sf = parse_batch_args("咒术回战")
    assert names == ["咒术回战"]


def test_parse_whitespace_handling():
    names, sf = parse_batch_args("  咒术回战 ,  鬼灭之刃  , 电锯人 ")
    assert names == ["咒术回战", "鬼灭之刃", "电锯人"]
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/test_batch_subscribe.py -v
```

Expected: All 10 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_batch_subscribe.py
git commit -m "test: add batch subscribe argument parsing tests"
```

---

### Task 4: 运行全部测试确认无回归

- [ ] **Step 1: 运行完整测试套件**

```bash
uv run pytest tests/test_pack.py tests/test_models.py tests/test_client.py tests/test_subscription.py tests/test_web_api.py tests/test_batch_subscribe.py -v
```

Expected: All tests PASS

- [ ] **Step 2: 语法检查**

```bash
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Final commit (if needed)**

如有修复，提交修复。否则跳过。
