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
