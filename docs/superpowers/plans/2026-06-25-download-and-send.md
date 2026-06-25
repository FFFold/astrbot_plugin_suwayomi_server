# 下载打包发送功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `/漫画 下载` 命令改为：服务器下载完成后自动打包为 ZIP/PDF/CBZ 并发送给用户。同时抽取阅读/下载的共享逻辑为公共方法。

**Architecture:** 抽取 `_resolve_chapter` 和 `_fetch_pages_local` 两个公共方法供阅读和下载命令复用。下载命令新增轮询服务器下载状态 + 打包逻辑。ZIP 用标准库，PDF 用 img2pdf。

**Tech Stack:** Python 3.12+, aiohttp, img2pdf, zipfile (stdlib)

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `requirements.txt` | 修改 | 新增 `img2pdf>=0.5.0` |
| `_conf_schema.json` | 修改 | 新增 3 个配置项 |
| `main.py` | 修改 | 抽取公共方法，重写 `download_chapter`，新增打包方法 |
| `tests/test_pack.py` | 新增 | 打包功能单元测试 |

---

### Task 1: 添加依赖和配置

**Files:**
- Modify: `requirements.txt`
- Modify: `_conf_schema.json`

- [ ] **Step 1: 更新 requirements.txt**

在 `requirements.txt` 中添加 `img2pdf`：

```
aiohttp>=3.9.0
img2pdf>=0.5.0
```

- [ ] **Step 2: 更新 _conf_schema.json**

在 `chapter_cache_hours` 配置项之后添加 3 个新配置项：

```json
"download_format": {
    "description": "默认下载打包格式",
    "type": "string",
    "default": "zip",
    "options": ["zip", "pdf", "cbz"],
    "labels": ["ZIP 压缩包", "PDF 文档", "CBZ 漫画"]
},
"download_poll_interval": {
    "description": "下载状态轮询间隔（秒）",
    "type": "int",
    "default": 3,
    "hint": "检查服务器下载完成状态的间隔"
},
"download_timeout": {
    "description": "下载超时时间（秒）",
    "type": "int",
    "default": 300,
    "hint": "超过此时间未完成则提示超时"
}
```

- [ ] **Step 3: 安装依赖并验证**

```bash
cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server
pip install img2pdf>=0.5.0
python -c "import img2pdf; print('img2pdf OK')"
```

Expected: `img2pdf OK`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt _conf_schema.json
git commit -m "feat: add download format config and img2pdf dependency"
```

---

### Task 2: 抽取公共方法 `_resolve_chapter`

**Files:**
- Modify: `main.py`（在 `_find_chapter_by_id` 方法之后，约 537 行）

阅读和下载命令有 ~20 行重复的章节解析逻辑（判断 `id:xxx` 语法 → 按 ID 查找 → 按编号查找 → 多个匹配时提示）。抽取为公共方法。

- [ ] **Step 1: 实现 `_resolve_chapter` 方法**

在 `main.py` 的 `_find_chapter_by_id` 方法之后（约 537 行）添加：

```python
def _resolve_chapter(
    self, chapters: list[Chapter], chapter_num: str, manga_name_or_id: str, cmd: str
) -> tuple[Chapter | None, str | None]:
    """Resolve chapter by ID or number string.

    Args:
        chapters: List of chapters.
        chapter_num: User input like "1", "38.5", or "id:123".
        manga_name_or_id: Original manga arg (for disambiguation hint).
        cmd: Command name for hint text ("阅读" or "下载").

    Returns:
        (Chapter, None) on success, (None, error_msg) on failure.
    """
    if chapter_num.lower().startswith("id:"):
        try:
            cid = int(chapter_num[3:])
            target = self._find_chapter_by_id(chapters, cid)
            if target:
                return target, None
        except ValueError:
            pass
        return None, f"未找到 ID 为 {chapter_num[3:]} 的章节。"

    try:
        chapter_num_f = float(chapter_num)
    except ValueError:
        return None, "章节号格式不正确。"

    matches = self._find_chapters_by_num(chapters, chapter_num_f)
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        lines = [f"找到多个第 {_fmt_chapter_num(chapter_num_f)} 话，请使用 ID 指定:"]
        for ch in matches:
            lines.append(f"  ID:{ch.id} - {ch.name}")
        lines.append(f"\n发送「漫画 {cmd} {manga_name_or_id} ID:<ID>」选择")
        return None, "\n".join(lines)
    return None, None  # Not found, caller shows generic "未找到" message
```

- [ ] **Step 2: 重构 `read_chapter` 使用 `_resolve_chapter`**

在 `read_chapter` 方法中，将以下代码块（约 556-578 行）：

```python
            # Support "id:123" syntax to select chapter by ID
            target = None
            if chapter_num.lower().startswith("id:"):
                try:
                    cid = int(chapter_num[3:])
                    target = self._find_chapter_by_id(chapters, cid)
                except ValueError:
                    pass
            else:
                chapter_num_f = float(chapter_num)
                matches = self._find_chapters_by_num(chapters, chapter_num_f)
                if len(matches) == 1:
                    target = matches[0]
                elif len(matches) > 1:
                    lines = [f"找到多个第 {_fmt_chapter_num(chapter_num_f)} 话，请使用 ID 指定:"]
                    for ch in matches:
                        lines.append(f"  ID:{ch.id} - {ch.name}")
                    lines.append(f"\n发送「漫画 阅读 {manga_name_or_id} ID:<ID>」选择")
                    yield event.plain_result("\n".join(lines))
                    return

            if target is None:
                yield event.plain_result(f"未找到「{manga.title}」指定的章节。")
                return
```

替换为：

```python
            target, err_msg = self._resolve_chapter(chapters, chapter_num, manga_name_or_id, "阅读")
            if err_msg:
                yield event.plain_result(err_msg)
                return
            if target is None:
                yield event.plain_result(f"未找到「{manga.title}」指定的章节。")
                return
```

- [ ] **Step 3: 语法检查**

```bash
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: 运行现有测试确保不破坏**

```bash
cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server
python -m pytest tests/test_models.py tests/test_client.py tests/test_subscription.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "refactor: extract _resolve_chapter shared helper"
```

---

### Task 3: 抽取公共方法 `_fetch_pages_local`

**Files:**
- Modify: `main.py`（在 `_resolve_chapter` 之后）

阅读和下载都需要：获取章节页面 URL → 构建完整 URL → 下载图片到本地。抽取为公共方法。

- [ ] **Step 1: 实现 `_fetch_pages_local` 方法**

在 `_resolve_chapter` 方法之后添加：

```python
async def _fetch_pages_local(
    self, chapter_id: int, max_pages: int = 0
) -> tuple[list[str], list[str]]:
    """Fetch chapter pages and download images to local temp dir.

    Args:
        chapter_id: The chapter ID.
        max_pages: Max pages to fetch (0 = all).

    Returns:
        (page_urls, local_paths) — local_paths has empty strings for failed downloads.
    """
    pages = await self.client.fetch_chapter_pages(chapter_id)
    if not pages:
        return [], []
    if max_pages > 0:
        pages = pages[:max_pages]
    page_urls = [self.client.build_image_url(p) for p in pages]
    local_paths = await self._download_images(page_urls)
    return page_urls, local_paths
```

- [ ] **Step 2: 重构 `read_chapter` 使用 `_fetch_pages_local`**

将 `read_chapter` 中以下代码（约 584-597 行）：

```python
            pages = await self.client.fetch_chapter_pages(target.id)
            if not pages:
                yield event.plain_result(f"第 {_fmt_chapter_num(target.chapter_number)} 话暂无可用页面。")
                return

            max_pages = self.config.get("max_pages", 30)
            send_mode = self.config.get("send_mode", "image")
            fetch_mode = self.config.get("image_fetch_mode", "url")

            page_urls = [self.client.build_image_url(p) for p in pages[:max_pages]]
            local_paths: list[str] = []

            if fetch_mode == "download":
                local_paths = await self._download_images(page_urls)
```

替换为：

```python
            max_pages = self.config.get("max_pages", 30)
            send_mode = self.config.get("send_mode", "image")
            fetch_mode = self.config.get("image_fetch_mode", "url")

            if fetch_mode == "download":
                page_urls, local_paths = await self._fetch_pages_local(target.id, max_pages)
            else:
                pages = await self.client.fetch_chapter_pages(target.id)
                if not pages:
                    yield event.plain_result(f"第 {_fmt_chapter_num(target.chapter_number)} 话暂无可用页面。")
                    return
                page_urls = [self.client.build_image_url(p) for p in pages[:max_pages]]
                local_paths = []

            if not page_urls:
                yield event.plain_result(f"第 {_fmt_chapter_num(target.chapter_number)} 话暂无可用页面。")
                return
```

同时需要更新后面引用 `pages` 的地方（`len(pages) > max_pages` 检查），改为使用 `len(page_urls)` 并记录原始页数。在 fetch 之前记录：

```python
            total_pages = len(page_urls)  # After fetch, for the truncation check
```

并将两处 `if len(pages) > max_pages:` 改为 `if total_pages > max_pages:`。
以及提示中的 `len(pages) - max_pages` 改为 `total_pages - max_pages`。

- [ ] **Step 3: 语法检查**

```bash
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: 运行现有测试**

```bash
cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server
python -m pytest tests/test_models.py tests/test_client.py tests/test_subscription.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "refactor: extract _fetch_pages_local shared helper"
```

---

### Task 4: 实现打包方法和轮询

**Files:**
- Modify: `main.py`
- Create: `tests/test_pack.py`

- [ ] **Step 1: 编写打包功能的单元测试**

创建 `tests/test_pack.py`：

```python
"""Tests for chapter image packing (ZIP, PDF, CBZ)."""
import zipfile
from pathlib import Path

import pytest


def _create_test_images(tmp_dir: Path, count: int = 3) -> list[str]:
    """Create minimal test JPEG files."""
    paths = []
    for i in range(count):
        p = tmp_dir / f"{i:04d}.jpg"
        # Minimal valid JPEG: SOI + APP0 + EOI
        p.write_bytes(
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xd9"
        )
        paths.append(str(p))
    return paths


class TestPackZip:
    def test_creates_file(self, tmp_path):
        from main import SuwayomiPlugin
        images = _create_test_images(tmp_path)
        output = tmp_path / "test.zip"
        SuwayomiPlugin._pack_zip_static(images, output)
        assert output.exists()
        assert output.stat().st_size > 0

    def test_contains_all_images(self, tmp_path):
        from main import SuwayomiPlugin
        images = _create_test_images(tmp_path, 5)
        output = tmp_path / "test.zip"
        SuwayomiPlugin._pack_zip_static(images, output)
        with zipfile.ZipFile(output) as zf:
            names = zf.namelist()
            assert len(names) == 5
            assert all(n.endswith(".jpg") for n in names)

    def test_empty_images(self, tmp_path):
        from main import SuwayomiPlugin
        output = tmp_path / "test.zip"
        SuwayomiPlugin._pack_zip_static([], output)
        assert output.exists()

    def test_skips_empty_paths(self, tmp_path):
        from main import SuwayomiPlugin
        images = _create_test_images(tmp_path, 2)
        images.append("")
        output = tmp_path / "test.zip"
        SuwayomiPlugin._pack_zip_static(images, output)
        with zipfile.ZipFile(output) as zf:
            assert len(zf.namelist()) == 2


class TestPackCbz:
    def test_is_zip_format(self, tmp_path):
        from main import SuwayomiPlugin
        images = _create_test_images(tmp_path)
        output = tmp_path / "test.cbz"
        SuwayomiPlugin._pack_cbz_static(images, output)
        assert output.exists()
        with zipfile.ZipFile(output) as zf:
            assert len(zf.namelist()) == 3


class TestPackPdf:
    def test_creates_pdf(self, tmp_path):
        pytest.importorskip("img2pdf")
        from main import SuwayomiPlugin
        images = _create_test_images(tmp_path)
        output = tmp_path / "test.pdf"
        SuwayomiPlugin._pack_pdf_static(images, output)
        assert output.exists()
        with open(output, "rb") as f:
            assert f.read(4) == b"%PDF"

    def test_skips_empty_paths(self, tmp_path):
        pytest.importorskip("img2pdf")
        from main import SuwayomiPlugin
        images = _create_test_images(tmp_path, 2)
        images.append("")
        output = tmp_path / "test.pdf"
        SuwayomiPlugin._pack_pdf_static(images, output)
        assert output.exists()

    def test_no_valid_images_raises(self, tmp_path):
        pytest.importorskip("img2pdf")
        from main import SuwayomiPlugin
        output = tmp_path / "test.pdf"
        with pytest.raises(ValueError):
            SuwayomiPlugin._pack_pdf_static([], output)
        with pytest.raises(ValueError):
            SuwayomiPlugin._pack_pdf_static(["", ""], output)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server
python -m pytest tests/test_pack.py -v
```

Expected: FAIL（方法不存在）

- [ ] **Step 3: 在 main.py 中实现打包方法**

在 `SuwayomiPlugin` 类中（`_fetch_pages_local` 方法之后）添加：

```python
@staticmethod
def _pack_zip_static(image_paths: list[str], output: Path):
    """将图片打包为 ZIP 文件。"""
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, path in enumerate(image_paths):
            if not path:
                continue
            ext = Path(path).suffix or ".jpg"
            zf.write(path, f"{i:04d}{ext}")

@staticmethod
def _pack_cbz_static(image_paths: list[str], output: Path):
    """将图片打包为 CBZ 文件（本质是 ZIP）。"""
    SuwayomiPlugin._pack_zip_static(image_paths, output)

@staticmethod
def _pack_pdf_static(image_paths: list[str], output: Path):
    """将图片打包为 PDF 文件。"""
    import img2pdf
    valid = [p for p in image_paths if p and Path(p).exists()]
    if not valid:
        raise ValueError("No valid images to pack")
    with open(output, "wb") as f:
        f.write(img2pdf.convert(valid))
```

- [ ] **Step 4: 实现 `_poll_download` 方法**

在打包方法之后添加：

```python
async def _poll_download(self, manga_id: int, chapter_id: int) -> bool:
    """轮询等待章节在服务器端下载完成。

    Returns:
        True if download completed, False if timed out.
    """
    interval = self.config.get("download_poll_interval", 3)
    timeout = self.config.get("download_timeout", 300)
    elapsed = 0.0

    while elapsed < timeout:
        await asyncio.sleep(interval)
        elapsed += interval
        try:
            chapters = await self.client.get_chapters(manga_id)
            for ch in chapters:
                if ch.id == chapter_id and ch.is_downloaded:
                    logger.info(f"[{PLUGIN_NAME}] 章节下载完成: manga={manga_id}, chapter={chapter_id}")
                    return True
        except Exception as e:
            logger.warning(f"[{PLUGIN_NAME}] 轮询下载状态失败: {e}")

    logger.warning(f"[{PLUGIN_NAME}] 下载超时: manga={manga_id}, chapter={chapter_id}, elapsed={elapsed}s")
    return False
```

- [ ] **Step 5: 运行打包测试**

```bash
cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server
python -m pytest tests/test_pack.py -v
```

Expected: 全部 PASS

- [ ] **Step 6: 语法检查**

```bash
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_pack.py
git commit -m "feat: add packing (ZIP/CBZ/PDF) and download polling"
```

---

### Task 5: 重写 `download_chapter` 命令

**Files:**
- Modify: `main.py`

- [ ] **Step 1: 更新帮助文本**

在 `help_cmd` 方法中，将：

```
  /漫画 下载 <漫画名或ID> <章节号>      — 下载章节
```

改为：

```
  /漫画 下载 <漫画名或ID> <章节号> [格式]  — 下载并打包发送（格式: zip/pdf/cbz）
```

- [ ] **Step 2: 重写 `download_chapter` 方法**

替换整个 `download_chapter` 方法（约 644-689 行）：

```python
@manga_group.command("下载")
async def download_chapter(self, event: AstrMessageEvent, manga_name_or_id: str, chapter_num: str = ""):
    '''下载漫画章节并打包发送。用法: /漫画 下载 <漫画名或ID> <章节号或ID:数字> [zip/pdf/cbz]'''
    if not chapter_num:
        yield event.plain_result(
            "用法: /漫画 下载 <漫画名或ID> <章节号> [格式]\n"
            "示例: /漫画 下载 一拳超人 1\n"
            "指定格式: /漫画 下载 一拳超人 1 pdf\n"
            "指定章节 ID: /漫画 下载 一拳超人 ID:123"
        )
        return

    # Parse optional format argument
    fmt = self.config.get("download_format", "zip")
    parts = chapter_num.strip().split()
    if parts and parts[-1].lower() in ("zip", "pdf", "cbz"):
        fmt = parts[-1].lower()
        chapter_num = " ".join(parts[:-1]) if len(parts) > 1 else ""
        if not chapter_num:
            yield event.plain_result("请指定章节号。")
            return

    try:
        manga, err = await self._resolve_manga(event, manga_name_or_id)
        if err or manga is None:
            yield event.plain_result(err or "未找到该漫画。")
            return

        chapters = await self._get_or_fetch_chapters(manga.id)

        target, err_msg = self._resolve_chapter(chapters, chapter_num, manga_name_or_id, "下载")
        if err_msg:
            yield event.plain_result(err_msg)
            return
        if target is None:
            yield event.plain_result(f"未找到「{manga.title}」指定的章节。")
            return

        num_label = _fmt_chapter_num(target.chapter_number)
        await event.send(event.plain_result(
            f"⏳ 正在下载「{manga.title}」第 {num_label} 话，请稍候..."
        ))

        # Step 1: Enqueue download on server
        await self.client.enqueue_download([target.id])

        # Step 2: Poll for completion (skip if already downloaded)
        if not target.is_downloaded:
            downloaded = await self._poll_download(manga.id, target.id)
            if not downloaded:
                yield event.plain_result(
                    f"⏰ 服务器下载超时，请稍后重试或在 WebUI 查看进度。\n"
                    f"发送「漫画 下载 {manga_name_or_id} {chapter_num}」重试"
                )
                return

        # Step 3: Fetch page URLs and download images locally
        await event.send(event.plain_result(f"📦 正在打包，请稍候..."))
        page_urls, local_paths = await self._fetch_pages_local(target.id)

        if not page_urls:
            yield event.plain_result(f"第 {num_label} 话暂无可用页面。")
            return

        valid_paths = [p for p in local_paths if p]
        if not valid_paths:
            yield event.plain_result("所有页面下载失败，无法打包。")
            return

        if len(valid_paths) < len(page_urls):
            logger.warning(f"[{PLUGIN_NAME}] {len(page_urls) - len(valid_paths)} 页下载失败，将用已有页面打包")

        # Step 4: Pack
        tmp_dir = Path(valid_paths[0]).parent
        safe_title = "".join(c for c in manga.title if c not in r'<>:"/\|?*')[:50]
        ext_map = {"zip": "zip", "pdf": "pdf", "cbz": "cbz"}
        file_ext = ext_map.get(fmt, "zip")
        output_path = tmp_dir / f"{safe_title}_第{num_label}话.{file_ext}"

        try:
            if fmt == "pdf":
                self._pack_pdf_static(valid_paths, output_path)
            elif fmt == "cbz":
                self._pack_cbz_static(valid_paths, output_path)
            else:
                self._pack_zip_static(valid_paths, output_path)
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 打包失败: {e}")
            yield event.plain_result(f"打包失败: {e}")
            return

        # Step 5: Send file
        filename = f"{safe_title}_第{num_label}话.{file_ext}"
        try:
            chain = [Comp.File(file=str(output_path), name=filename)]
            yield event.chain_result(chain)
        except Exception as e:
            logger.warning(f"[{PLUGIN_NAME}] 发送文件失败，回退为图片预览: {e}")
            preview_count = min(3, len(valid_paths))
            chain = [Comp.Plain(f"📄 {filename}（{len(valid_paths)} 页，文件发送不支持，以下为预览）")]
            for i in range(preview_count):
                chain.append(Comp.Image.fromFileSystem(valid_paths[i]))
            yield event.chain_result(chain)

        # Step 6: Cleanup after delay
        asyncio.get_event_loop().call_later(
            120, lambda d=str(tmp_dir): shutil.rmtree(d, ignore_errors=True)
        )

    except SuwayomiError as e:
        yield event.plain_result(f"下载失败: {e}")
    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] download error: {e}")
        yield event.plain_result("下载失败。")
```

- [ ] **Step 3: 语法检查**

```bash
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: 运行全部测试**

```bash
cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server
python -m pytest tests/test_pack.py tests/test_models.py tests/test_client.py tests/test_subscription.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: rewrite download command with pack and send"
```

---

### Task 6: 集成验证

**Files:** 无文件变更

- [ ] **Step 1: 完整语法检查**

```bash
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 2: 运行全部测试**

```bash
cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server
python -m pytest tests/ -v --ignore=tests/test_live_api.py
```

Expected: 全部 PASS

- [ ] **Step 3: 配置 schema 验证**

```bash
python -c "import json; json.load(open('_conf_schema.json', encoding='utf-8')); print('JSON OK')"
```

Expected: `JSON OK`

- [ ] **Step 4: 确认阅读命令未被破坏**

检查 `read_chapter` 方法中对 `_resolve_chapter` 和 `_fetch_pages_local` 的调用是否正确。

- [ ] **Step 5: （可选）集成测试**

如果有 Suwayomi-Server 运行，测试实际命令：
- `/漫画 阅读 <漫画> <章节>` — 确认阅读功能正常
- `/漫画 下载 <漫画> <章节>` — 确认下载打包发送正常

- [ ] **Step 6: Final Commit**

```bash
git add -A
git commit -m "feat: download command now packs and sends files (ZIP/PDF/CBZ)"
```
