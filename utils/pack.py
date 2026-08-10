"""Pack images into ZIP, CBZ, or PDF files."""
from __future__ import annotations

import zipfile
from pathlib import Path


def pack_zip(image_paths: list[str], output: Path):
    """将图片打包为 ZIP 文件。"""
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, path in enumerate(image_paths):
            if not path:
                continue
            ext = Path(path).suffix or ".jpg"
            zf.write(path, f"{i:04d}{ext}")


def pack_cbz(image_paths: list[str], output: Path):
    """将图片打包为 CBZ 文件（本质是 ZIP）。"""
    pack_zip(image_paths, output)


def pack_pdf(image_paths: list[str], output: Path):
    """将图片打包为 PDF 文件。"""
    import img2pdf
    valid = [p for p in image_paths if p and Path(p).exists()]
    if not valid:
        raise ValueError("No valid images to pack")
    with open(output, "wb") as f:
        f.write(img2pdf.convert(valid))


def sanitize_filename(name: str, max_len: int = 50) -> str:
    """Sanitize a name for safe use in filenames."""
    cleaned = "".join(c for c in str(name) if c not in r'<>:"/\|?*').strip()
    return cleaned[:max_len] or "untitled"


def normalize_pack_format(fmt: str) -> str:
    return fmt if fmt in ("pdf", "cbz", "zip") else "zip"


def build_chapter_output_path(directory: Path, title: str, label: str, fmt: str) -> Path:
    return directory / f"{sanitize_filename(title)}_{sanitize_filename(label)}.{fmt}"


def pack_images(image_paths: list[str], output: Path, fmt: str):
    if fmt == "pdf":
        pack_pdf(image_paths, output)
    elif fmt == "cbz":
        pack_cbz(image_paths, output)
    else:
        pack_zip(image_paths, output)


def parse_download_args(raw_message: str, default_fmt: str = "pdf") -> tuple[str, str, str]:
    """Parse download command arguments from raw message.

    Args:
        raw_message: The full message string, e.g. "/漫画 下载 151 ID:2531 zip".
        default_fmt: Default format if not specified.

    Returns:
        (manga_name_or_id, chapter_num, fmt)
    """
    tokens = raw_message.strip().split()
    try:
        cmd_idx = tokens.index("下载")
        args = tokens[cmd_idx + 1:]
    except ValueError:
        return "", "", default_fmt

    fmt = default_fmt
    if len(args) >= 3 and args[-1].lower() in ("zip", "pdf", "cbz"):
        fmt = args[-1].lower()
        manga = args[0]
        chapter = " ".join(args[1:-1])
    elif len(args) >= 2:
        manga = args[0]
        chapter = " ".join(args[1:])
    else:
        manga = args[0] if args else ""
        chapter = ""
    return manga, chapter, fmt
