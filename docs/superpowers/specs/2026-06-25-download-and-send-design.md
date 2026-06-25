# 下载打包发送功能设计

## 概述

将 `/漫画 下载` 命令从"仅在服务器端排队下载"改为"下载完成后自动打包发送给用户"。支持 ZIP、PDF、CBZ 三种格式。

## 用户交互

### 命令格式

```
/漫画 下载 <漫画名或ID> <章节号或ID:xxx> [格式]
```

- `格式` 可选：`zip` / `pdf` / `cbz`，不填用配置默认值
- 示例：
  - `/漫画 下载 一拳超人 1` → 使用默认格式
  - `/漫画 下载 一拳超人 1 pdf` → PDF 格式
  - `/漫画 下载 一拳超人 ID:123 cbz` → CBZ 格式

### 用户体验流程

```
用户发送: /漫画 下载 一拳超人 1
↓
插件回复: ⏳ 正在下载「一拳超人」第 1 话，请稍候...
↓
[服务器下载 + 轮询等待 + 打包]
↓
插件发送: ✅「一拳超人」第 1 话下载完成
         [附件: 一拳超人_第1话.zip]
```

## 技术设计

### 整体流程

```
1. 解析漫画和章节（复用现有 _resolve_manga + _find_chapter_by_num）
2. 发送"正在下载"提示
3. enqueue_download([chapter_id]) → 触发服务器端下载
4. 轮询 chapter.isDownloaded 直到为 True
   - 间隔: download_poll_interval 秒（默认 3）
   - 超时: download_timeout 秒（默认 300）
5. fetch_chapter_pages(chapter_id) → 获取页面 URL 列表
6. _download_images(urls) → 下载页面到临时目录（复用现有方法）
7. 打包为指定格式
8. 通过 Comp.File() 发送文件
9. 延迟清理临时文件
```

### SuwayomiClient 新增方法

```python
async def get_chapters_by_manga_id(self, manga_id: int) -> list[Chapter]:
    """查询漫画的所有章节（用于轮询 isDownloaded 状态）

    与 get_chapters() 相同，但单独命名以明确用途。
    实际复用 get_chapters() 即可，无需新增方法。
    """
```

**轮询策略**：调用已有的 `get_chapters(manga_id)` 获取章节列表，从中找到目标章节并检查 `isDownloaded` 字段。无需新增 API 方法。

> 备选方案：如果 Suwayomi 支持 `chapter(id)` 根查询，可新增 `get_chapter()` 方法以减少数据传输。需在实现时验证。

### 打包实现

#### ZIP（标准库）

```python
import zipfile

def pack_zip(image_paths: list[str], output: Path, name: str):
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, path in enumerate(image_paths):
            ext = Path(path).suffix
            zf.write(path, f"{i:04d}{ext}")
```

#### CBZ（同 ZIP，改扩展名）

```python
def pack_cbz(image_paths: list[str], output: Path, name: str):
    pack_zip(image_paths, output, name)  # 本质一样
```

#### PDF（img2pdf）

```python
import img2pdf

def pack_pdf(image_paths: list[str], output: Path, name: str):
    valid = [p for p in image_paths if p]
    with open(output, "wb") as f:
        f.write(img2pdf.convert(valid))
```

### 临时文件管理

- 下载目录：`tempfile.mkdtemp(prefix="suwayomi_dl_")`
- 打包输出：同目录下 `{manga_title}_第{num}话.{ext}`
- 清理：发送后 60 秒调用 `shutil.rmtree`（复用现有模式）

### 文件发送

```python
ext = {"zip": "zip", "pdf": "pdf", "cbz": "cbz"}[fmt]
filename = f"{manga_title}_第{num}话.{ext}"
chain = [Comp.File(file=str(output_path), name=filename)]
yield event.chain_result(chain)
```

## 配置变更

### 新增配置项（_conf_schema.json）

```json
{
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
}
```

### 依赖变更（requirements.txt）

```
aiohttp>=3.9.0
img2pdf>=0.5.0
```

## 错误处理

| 场景 | 处理 |
|------|------|
| 章节未找到 | 现有逻辑不变 |
| 服务器下载超时 | 提示"下载超时，请稍后重试或在 WebUI 查看" |
| 页面获取失败 | 提示"获取页面失败" |
| 图片下载失败 | 跳过失败图片，用已有图片打包，提示"部分页面缺失" |
| 打包失败 | 提示"打包失败" |
| 未知格式 | 回退到默认格式 |
| 平台不支持 Comp.File | 回退为发送文本提示 + 图片预览（前几页） |

## 代码变更清单

| 文件 | 变更 |
|------|------|
| `main.py` | 重写 `download_chapter` 方法，新增 `_poll_download`、`_pack_chapter` 方法 |
| `suwayomi/client.py` | 可能新增 `get_chapter()` 方法（需验证 API 支持），或复用 `get_chapters()` |
| `_conf_schema.json` | 新增 3 个配置项 |
| `requirements.txt` | 新增 `img2pdf>=0.5.0` |

## 不做的事

- 不支持批量章节下载（如 `1-5` 范围），后续可扩展
- 不支持下载后自动导入到阅读器
- 不做下载进度百分比（Suwayomi API 不提供细粒度进度）
