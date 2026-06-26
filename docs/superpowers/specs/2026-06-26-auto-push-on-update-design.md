# Auto-Push on Update Design

**Date**: 2026-06-26
**Status**: Approved

## Overview

When the background update loop discovers new chapters for subscribed manga, automatically push the manga content (images or packaged file) to the subscriber's conversation. This extends the current behavior which only sends a text notification.

## Requirements

- **Push modes**: Two configurable modes — `image` (inline images, like the read command) and `file` (packaged ZIP/PDF/CBZ, like the download command)
- **Push scope**: All new chapters discovered in a single update check
- **Configuration**: Global `auto_push_mode` setting in plugin config; file mode reuses existing `download_format`
- **Per-umo toggle**: Default OFF; each conversation (umo) can enable/disable via command
- **Image mode**: Reuses read command logic, respects `max_pages` limit
- **File mode**: Reuses download command logic, respects `download_format` config
- **Text notification preserved**: The existing text notification is always sent regardless of auto-push toggle

## Data Structure Changes

### Subscription Data (KV: `suwayomi_subscriptions`)

Add optional `auto_push` field to each manga entry:

```json
{
  "12345": {
    "title": "一拳超人",
    "source_id": 524579092615598717,
    "latest_chapter_id": 9876,
    "subscribers": ["aiocqhttp:group:123456", "aiocqhttp:private:789"],
    "auto_push": {
      "aiocqhttp:group:123456": {"enabled": true},
      "aiocqhttp:private:789": {"enabled": false}
    }
  }
}
```

**Backward compatibility**: `auto_push` is optional. Missing field or missing umo entry = disabled (default off).

### SubscriptionManager New Methods

| Method | Description |
|--------|-------------|
| `set_auto_push(manga_id, umo, enabled)` | Set auto-push state for a umo on a manga |
| `get_auto_push(manga_id, umo)` | Query auto-push state (returns bool) |
| `get_auto_push_subscribers(manga_id)` | Get list of umo strings with auto-push enabled |

## New Configuration

### `_conf_schema.json` Addition

```json
"auto_push_mode": {
  "description": "自动推送模式",
  "type": "string",
  "options": ["image", "file"],
  "labels": ["图片（复用阅读）", "文件（复用下载）"],
  "default": "image"
}
```

File mode reuses existing `download_format` config (zip/pdf/cbz). No additional format config needed.

## New Commands

Command group: `漫画 推送`

| Command | Behavior |
|---------|----------|
| `漫画 推送 开` | Enable auto-push for all subscribed manga in current conversation |
| `漫画 推送 关` | Disable auto-push for all subscribed manga in current conversation |
| `漫画 推送 状态` | Show current conversation's auto-push status per manga |

- `开` iterates user's subscriptions and calls `set_auto_push(manga_id, umo, True)` for each
- `关` iterates and calls `set_auto_push(manga_id, umo, False)` for each
- `状态` iterates user's subscriptions, shows which have auto-push enabled

## Auto-Push Logic in `_check_updates`

After the existing text notification loop, add auto-push logic:

```
for each manga with new chapters:
    push_subscribers = sub_mgr.get_auto_push_subscribers(manga_id)
    for umo in push_subscribers:
        for chapter in new_chapters:
            if auto_push_mode == "image":
                push_chapter_images(umo, manga, chapter)
            else:
                push_chapter_file(umo, manga, chapter)
```

### `push_chapter_images(umo, manga, chapter)`

Reuses the read command flow:

1. `_fetch_pages_local(chapter.id, max_pages)` — get page URLs and download images
2. Build image chain (same logic as `read_chapter`):
   - `url` mode: `Comp.Image.fromURL(page_urls[i])`
   - `download` mode: `Comp.Image.fromFileSystem(local_paths[i])`
3. Prepend text header: `"📖「{title}」第 {num} 话"`
4. Send via `context.send_message(umo, chain)`
5. Schedule temp cleanup

### `push_chapter_file(umo, manga, chapter)`

Reuses the download command flow:

1. `_fetch_pages_local(chapter.id, no limit)` — download all pages
2. Pack using existing `pack_zip`/`pack_cbz`/`pack_pdf` based on `download_format`
3. Build file chain with `Comp.File`
4. Send via `context.send_message(umo, chain)`
5. Schedule temp cleanup

### Error Handling

- Each chapter push is wrapped in try/except
- Failure logs error and continues to next chapter
- Does not affect text notification (already sent)
- Does not affect other chapters or other umo's pushes

## Execution Order in `_check_updates`

1. Send text notifications (existing behavior, unchanged)
2. For each manga with new chapters:
   a. Get auto-push enabled umo list
   b. For each umo, for each new chapter: push content
3. Log summary of auto-push results

## Files Changed

| File | Changes |
|------|---------|
| `utils/subscription.py` | Add `set_auto_push`, `get_auto_push`, `get_auto_push_subscribers` |
| `main.py` | Add `push_chapter_images`, `push_chapter_file`; extend `_check_updates`; add `推送` command group |
| `_conf_schema.json` | Add `auto_push_mode` config |
| `tests/test_subscription.py` | Add tests for new SubscriptionManager methods |

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Large number of new chapters floods chat | Each chapter sent as separate message with small delay between sends |
| Image mode with many pages is bandwidth-heavy | Respect `max_pages` limit; users can switch to file mode |
| File mode temp storage grows | Reuse existing cleanup scheduling (120s delay) |
| Slow push blocks update loop | Push runs after text notification; failures are caught and logged |
