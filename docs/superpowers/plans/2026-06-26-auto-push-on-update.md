# Auto-Push on Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the background update loop discovers new chapters, automatically push manga content (images or packaged file) to subscribers who have enabled auto-push.

**Architecture:** Extend `SubscriptionManager` with per-umo auto-push preferences stored in the existing subscription data. Add two push helper methods (`_push_chapter_images`, `_push_chapter_file`) that reuse the read/download flows. Integrate into `_check_updates` after text notifications. Add a `漫画 推送` command group for toggle control.

**Tech Stack:** Python 3.12+, AstrBot plugin API, existing `aiohttp`/`img2pdf` deps

---

### Task 1: Add auto-push methods to SubscriptionManager

**Files:**
- Modify: `utils/subscription.py`

- [ ] **Step 1: Add `set_auto_push` method**

Add after `update_latest_chapter` (line 67):

```python
async def set_auto_push(self, manga_id: int, umo: str, enabled: bool):
    """Enable or disable auto-push for a umo on a manga."""
    data = await self._load()
    key = str(manga_id)
    if key not in data:
        return
    if "auto_push" not in data[key]:
        data[key]["auto_push"] = {}
    data[key]["auto_push"][umo] = {"enabled": enabled}
    await self._save(data)
```

- [ ] **Step 2: Add `get_auto_push` method**

```python
async def get_auto_push(self, manga_id: int, umo: str) -> bool:
    """Check if auto-push is enabled for a umo on a manga."""
    data = await self._load()
    key = str(manga_id)
    info = data.get(key, {})
    ap = info.get("auto_push", {})
    entry = ap.get(umo, {})
    return entry.get("enabled", False)
```

- [ ] **Step 3: Add `get_auto_push_subscribers` method**

```python
async def get_auto_push_subscribers(self, manga_id: int) -> list[str]:
    """Get list of umo strings that have auto-push enabled for a manga."""
    data = await self._load()
    key = str(manga_id)
    info = data.get(key, {})
    ap = info.get("auto_push", {})
    return [umo for umo, cfg in ap.items() if cfg.get("enabled", False)]
```

- [ ] **Step 4: Add `set_auto_push_all` convenience method**

```python
async def set_auto_push_all(self, umo: str, enabled: bool):
    """Enable or disable auto-push for a umo on ALL subscribed manga."""
    data = await self._load()
    for manga_id, info in data.items():
        if umo in info.get("subscribers", []):
            if "auto_push" not in info:
                info["auto_push"] = {}
            info["auto_push"][umo] = {"enabled": enabled}
    await self._save(data)
```

- [ ] **Step 5: Run syntax check**

Run: `python -c "import ast; ast.parse(open('utils/subscription.py', encoding='utf-8').read()); print('OK')"`
Expected: OK

---

### Task 2: Add tests for new SubscriptionManager methods

**Files:**
- Modify: `tests/test_subscription.py`

- [ ] **Step 1: Add test for `set_auto_push` and `get_auto_push`**

Append to `tests/test_subscription.py`:

```python
@pytest.mark.asyncio
async def test_set_auto_push(mgr):
    await mgr.subscribe(42, "One Piece", 100, "user1")
    assert await mgr.get_auto_push(42, "user1") is False
    await mgr.set_auto_push(42, "user1", True)
    assert await mgr.get_auto_push(42, "user1") is True


@pytest.mark.asyncio
async def test_set_auto_push_disable(mgr):
    await mgr.subscribe(42, "One Piece", 100, "user1")
    await mgr.set_auto_push(42, "user1", True)
    await mgr.set_auto_push(42, "user1", False)
    assert await mgr.get_auto_push(42, "user1") is False


@pytest.mark.asyncio
async def test_get_auto_push_nonexistent(mgr):
    assert await mgr.get_auto_push(999, "user1") is False


@pytest.mark.asyncio
async def test_get_auto_push_subscribers(mgr):
    await mgr.subscribe(42, "One Piece", 100, "user1")
    await mgr.subscribe(42, "One Piece", 100, "user2")
    await mgr.set_auto_push(42, "user1", True)
    subs = await mgr.get_auto_push_subscribers(42)
    assert subs == ["user1"]


@pytest.mark.asyncio
async def test_set_auto_push_all(mgr):
    await mgr.subscribe(1, "A", 10, "user1")
    await mgr.subscribe(2, "B", 20, "user1")
    await mgr.set_auto_push_all("user1", True)
    assert await mgr.get_auto_push(1, "user1") is True
    assert await mgr.get_auto_push(2, "user1") is True


@pytest.mark.asyncio
async def test_auto_push_backward_compat(mgr):
    """Old data without auto_push field should default to disabled."""
    await mgr.subscribe(42, "One Piece", 100, "user1")
    # Manually remove auto_push to simulate old data
    data = await mgr._load()
    if "auto_push" in data.get("42", {}):
        del data["42"]["auto_push"]
    await mgr._save(data)
    assert await mgr.get_auto_push(42, "user1") is False
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_subscription.py -v`
Expected: All tests pass (including existing ones)

---

### Task 3: Add `auto_push_mode` config

**Files:**
- Modify: `_conf_schema.json`

- [ ] **Step 1: Add config entry**

Add before the closing `}` in `_conf_schema.json`:

```json
  "auto_push_mode": {
    "description": "自动推送模式",
    "type": "string",
    "default": "image",
    "options": ["image", "file"],
    "labels": ["图片（复用阅读）", "文件（复用下载）"],
    "hint": "发现更新时自动推送的模式：图片直接发到聊天，文件发送 ZIP/PDF/CBZ 包"
  }
```

- [ ] **Step 2: Validate JSON**

Run: `python -c "import json; json.load(open('_conf_schema.json', encoding='utf-8')); print('OK')"`
Expected: OK

---

### Task 4: Add push helper methods to main.py

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add `_push_chapter_images` method**

Add after `_fetch_pages_local` (after line 623), before the `阅读` command:

```python
async def _push_chapter_images(self, umo: str, title: str, chapter: Chapter):
    """Push a chapter as inline images to a conversation (reuses read logic)."""
    num_label = _fmt_chapter_num(chapter.chapter_number)
    max_pages = self.config.get("max_pages", 30)
    fetch_mode = self.config.get("image_fetch_mode", "url")

    if fetch_mode == "download":
        total_pages, page_urls, local_paths = await self._fetch_pages_local(chapter.id, max_pages)
    else:
        pages = await self.client.fetch_chapter_pages(chapter.id)
        if not pages:
            return
        total_pages = len(pages)
        page_urls = [self.client.build_image_url(p) for p in pages[:max_pages]]
        local_paths = []

    if not page_urls:
        return

    def _img(idx: int) -> Comp.Image:
        if fetch_mode == "download" and idx < len(local_paths) and local_paths[idx]:
            return Comp.Image.fromFileSystem(local_paths[idx])
        return Comp.Image.fromURL(page_urls[idx])

    chain = [Comp.Plain(f"📖「{title}」第 {num_label} 话")]
    chain.extend(_img(i) for i in range(len(page_urls)))
    if total_pages > max_pages:
        chain.append(Comp.Plain(f"... 还有 {total_pages - max_pages} 页，请使用「漫画 阅读」查看"))

    await self.context.send_message(umo, MessageChain().chain(chain))

    if local_paths:
        valid_paths = [p for p in local_paths if p]
        if valid_paths:
            parent = Path(valid_paths[0]).parent
            async def _cleanup():
                await asyncio.sleep(60)
                try:
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: shutil.rmtree(parent, ignore_errors=True)
                    )
                except Exception:
                    pass
            asyncio.create_task(_cleanup())
```

- [ ] **Step 2: Add `_push_chapter_file` method**

Add after `_push_chapter_images`:

```python
async def _push_chapter_file(self, umo: str, title: str, chapter: Chapter):
    """Push a chapter as a packaged file to a conversation (reuses download logic)."""
    num_label = _fmt_chapter_num(chapter.chapter_number)
    fmt = self.config.get("download_format", "zip")

    _, page_urls, local_paths = await self._fetch_pages_local(chapter.id)
    if not page_urls:
        return

    valid_paths = [p for p in local_paths if p]
    if not valid_paths:
        return

    tmp_dir = Path(valid_paths[0]).parent
    safe_title = "".join(c for c in title if c not in r'<>:"/\|?*')[:50]
    safe_label = "".join(c for c in str(num_label) if c not in r'<>:"/\|?*')
    ext_map = {"zip": "zip", "pdf": "pdf", "cbz": "cbz"}
    file_ext = ext_map.get(fmt, "zip")
    output_path = tmp_dir / f"{safe_title}_第{safe_label}话.{file_ext}"

    try:
        loop = asyncio.get_running_loop()
        if fmt == "pdf":
            await loop.run_in_executor(None, pack_pdf, valid_paths, output_path)
        elif fmt == "cbz":
            await loop.run_in_executor(None, pack_cbz, valid_paths, output_path)
        else:
            await loop.run_in_executor(None, pack_zip, valid_paths, output_path)
    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] 自动推送打包失败: {e}")
        return

    filename = f"{safe_title}_第{safe_label}话.{file_ext}"
    chain = [Comp.File(file=str(output_path), name=filename)]
    try:
        await self.context.send_message(umo, MessageChain().chain(chain))
    except Exception:
        # Fallback to text hint if file send fails
        await self.context.send_message(umo, MessageChain().message(
            f"📖「{title}」第 {num_label} 话已更新，但文件发送失败，请使用「漫画 下载」获取"
        ))

    async def _cleanup():
        await asyncio.sleep(120)
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: shutil.rmtree(tmp_dir, ignore_errors=True)
            )
        except Exception:
            pass
    asyncio.create_task(_cleanup())
```

- [ ] **Step 3: Run syntax check**

Run: `python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"`
Expected: OK

---

### Task 5: Integrate auto-push into `_check_updates`

**Files:**
- Modify: `main.py` — `_check_updates` method (lines 831-908)

- [ ] **Step 1: Extend `_check_updates` to store new_chapters in `updated_mangas`**

The current `updated_mangas` tuple is `(title, ch_info, last_ch, subscribers)`. Change it to `(title, ch_info, new_chapters, subscribers)` so we have access to the actual Chapter objects for pushing.

In the `_check_updates` method, change line 877 from:

```python
updated_mangas.append((title, ch_info, new_chapters[-1], subscribers))
```

to:

```python
updated_mangas.append((title, ch_info, new_chapters, subscribers))
```

- [ ] **Step 2: Update text notification to use `new_chapters[-1]`**

Change line 891 from:

```python
for title, ch_info, last_ch, subscribers in updated_mangas:
    latest_num = _fmt_chapter_num(last_ch.chapter_number)
```

to:

```python
for title, ch_info, new_chapters, subscribers in updated_mangas:
    latest_num = _fmt_chapter_num(new_chapters[-1].chapter_number)
```

- [ ] **Step 3: Update summary section**

Change line 906 from:

```python
for title, ch_info, _, _ in updated_mangas:
```

to:

```python
for title, ch_info, _, _ in updated_mangas:
```

(This line doesn't need changes since it uses `_` for unused fields.)

- [ ] **Step 4: Add auto-push loop after text notification**

After the text notification loop (after line 901), add:

```python
# Auto-push content for enabled subscribers
auto_push_mode = self.config.get("auto_push_mode", "image")
for title, ch_info, new_chapters, subscribers in updated_mangas:
    for umo in subscribers:
        try:
            if not await self.sub_mgr.get_auto_push(
                int(next(k for k, v in all_subs.items() if umo in v.get("subscribers", []))),
                umo,
            ):
                continue
        except Exception:
            continue

        for ch in new_chapters:
            try:
                if auto_push_mode == "file":
                    await self._push_chapter_file(umo, title, ch)
                else:
                    await self._push_chapter_images(umo, title, ch)
            except Exception as e:
                logger.warning(f"[{PLUGIN_NAME}] 自动推送「{title}」第{_fmt_chapter_num(ch.chapter_number)}话到{umo}失败: {e}")
```

**Note:** The `int(next(...))` lookup is needed because we iterate `updated_mangas` (which has title, not manga_id). To avoid this, change the `updated_mangas` tuple to also include `manga_id`.

- [ ] **Step 5: Refactor to include `manga_id` in `updated_mangas`**

Change the append at line 877 to:

```python
updated_mangas.append((manga_id, title, ch_info, new_chapters, subscribers))
```

Update text notification loop (line 890):

```python
for manga_id, title, ch_info, new_chapters, subscribers in updated_mangas:
```

Update summary loop (line 906):

```python
for _, title, ch_info, _, _ in updated_mangas:
```

Update auto-push loop:

```python
for manga_id, title, ch_info, new_chapters, subscribers in updated_mangas:
    for umo in subscribers:
        if not await self.sub_mgr.get_auto_push(manga_id, umo):
            continue
        for ch in new_chapters:
            try:
                if auto_push_mode == "file":
                    await self._push_chapter_file(umo, title, ch)
                else:
                    await self._push_chapter_images(umo, title, ch)
            except Exception as e:
                logger.warning(f"[{PLUGIN_NAME}] 自动推送「{title}」第{_fmt_chapter_num(ch.chapter_number)}话到{umo}失败: {e}")
```

- [ ] **Step 6: Run syntax check**

Run: `python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"`
Expected: OK

---

### Task 6: Add `推送` command group

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add command group and `开` command**

Add after the `我的订阅` command (after line 369), before the `_resolve_manga` section:

```python
# ── 自动推送 ──────────────────────────────────────────────────

@manga_group.group("推送")
def push_group(self):
    pass

@push_group.command("开")
async def push_enable(self, event: AstrMessageEvent):
    '''开启当前会话的漫画自动推送'''
    try:
        umo = event.unified_msg_origin
        subs = await self.sub_mgr.get_subscriptions(umo)
        if not subs:
            yield event.plain_result("📭 你还没有订阅任何漫画，请先使用「漫画 搜索」订阅。")
            return
        await self.sub_mgr.set_auto_push_all(umo, True)
        yield event.plain_result(f"✅ 已开启自动推送，共 {len(subs)} 部漫画。有更新时将自动推送内容。")
    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] push_enable error: {e}")
        yield event.plain_result("开启自动推送失败。")

@push_group.command("关")
async def push_disable(self, event: AstrMessageEvent):
    '''关闭当前会话的漫画自动推送'''
    try:
        umo = event.unified_msg_origin
        subs = await self.sub_mgr.get_subscriptions(umo)
        if not subs:
            yield event.plain_result("📭 你还没有订阅任何漫画。")
            return
        await self.sub_mgr.set_auto_push_all(umo, False)
        yield event.plain_result("✅ 已关闭自动推送。有更新时将只发送文本通知。")
    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] push_disable error: {e}")
        yield event.plain_result("关闭自动推送失败。")

@push_group.command("状态")
async def push_status(self, event: AstrMessageEvent):
    '''查看当前会话的自动推送状态'''
    try:
        umo = event.unified_msg_origin
        subs = await self.sub_mgr.get_subscriptions(umo)
        if not subs:
            yield event.plain_result("📭 你还没有订阅任何漫画。")
            return
        lines = ["📡 自动推送状态:"]
        for s in subs:
            enabled = await self.sub_mgr.get_auto_push(s["manga_id"], umo)
            status = "✅ 开启" if enabled else "❌ 关闭"
            lines.append(f"  • {s['title']} — {status}")
        yield event.plain_result("\n".join(lines))
    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] push_status error: {e}")
        yield event.plain_result("获取推送状态失败。")
```

- [ ] **Step 2: Run syntax check**

Run: `python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"`
Expected: OK

---

### Task 7: Update help text

**Files:**
- Modify: `main.py` — `help_cmd` method (line 183)

- [ ] **Step 1: Add push section to help text**

Change the help text (lines 183-207) to include the new commands. Add after the `更新` section:

```python
text = """📖 Suwayomi 漫画助手

🔍 搜索与订阅
  /漫画 搜索 <关键词> [源名]  — 搜索漫画
  /漫画 订阅 <编号>            — 订阅搜索结果
  /漫画 取消订阅 <ID或名称>    — 取消订阅
  /漫画 我的订阅               — 查看订阅列表

📚 阅读与下载
  /漫画 章节 <漫画名或ID>               — 查看章节列表
  /漫画 阅读 <漫画名或ID> <章节号>      — 阅读章节
  /漫画 下载 <漫画名或ID> <章节号> [格式]  — 下载并打包发送（格式: zip/pdf/cbz）

  添加 --刷新 强制从源更新章节数据：
  /漫画 章节 <漫画名> --刷新

  重复编号章节可用 ID: 指定：
  /漫画 阅读 <漫画名> ID:123

🔄 更新
  /漫画 更新  — 手动检查更新（自动推送默认每小时一次）

📡 自动推送
  /漫画 推送 开    — 开启自动推送（有更新时自动发送漫画内容）
  /漫画 推送 关    — 关闭自动推送
  /漫画 推送 状态  — 查看推送状态

📋 其他
  /漫画 源    — 查看已安装的漫画源
  /漫画 帮助  — 显示本帮助"""
```

- [ ] **Step 2: Run syntax check**

Run: `python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"`
Expected: OK

---

### Task 8: Run all tests and verify

- [ ] **Step 1: Run unit tests**

Run: `uv run pytest tests/test_pack.py tests/test_models.py tests/test_subscription.py -v`
Expected: All tests pass

- [ ] **Step 2: Run full syntax check**

Run: `python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); ast.parse(open('utils/subscription.py', encoding='utf-8').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Verify config JSON is valid**

Run: `python -c "import json; json.load(open('_conf_schema.json', encoding='utf-8')); print('OK')"`
Expected: OK
