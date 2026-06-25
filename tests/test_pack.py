"""Tests for chapter image packing (ZIP, PDF, CBZ)."""
import zipfile
from pathlib import Path

import pytest

from utils.pack import pack_zip, pack_cbz, pack_pdf, parse_download_args


def _create_test_images(tmp_dir: Path, count: int = 3) -> list[str]:
    """Create minimal test JPEG files using PIL."""
    from PIL import Image
    paths = []
    for i in range(count):
        p = tmp_dir / f"{i:04d}.jpg"
        img = Image.new("RGB", (10, 10), color=(i * 50, 100, 150))
        img.save(str(p), "JPEG")
        paths.append(str(p))
    return paths


class TestPackZip:
    def test_creates_file(self, tmp_path):
        images = _create_test_images(tmp_path)
        output = tmp_path / "test.zip"
        pack_zip(images, output)
        assert output.exists()
        assert output.stat().st_size > 0

    def test_contains_all_images(self, tmp_path):
        images = _create_test_images(tmp_path, 5)
        output = tmp_path / "test.zip"
        pack_zip(images, output)
        with zipfile.ZipFile(output) as zf:
            names = zf.namelist()
            assert len(names) == 5
            assert all(n.endswith(".jpg") for n in names)

    def test_empty_images(self, tmp_path):
        output = tmp_path / "test.zip"
        pack_zip([], output)
        assert output.exists()

    def test_skips_empty_paths(self, tmp_path):
        images = _create_test_images(tmp_path, 2)
        images.append("")
        output = tmp_path / "test.zip"
        pack_zip(images, output)
        with zipfile.ZipFile(output) as zf:
            assert len(zf.namelist()) == 2


class TestPackCbz:
    def test_is_zip_format(self, tmp_path):
        images = _create_test_images(tmp_path)
        output = tmp_path / "test.cbz"
        pack_cbz(images, output)
        assert output.exists()
        with zipfile.ZipFile(output) as zf:
            assert len(zf.namelist()) == 3


class TestPackPdf:
    def test_creates_pdf(self, tmp_path):
        pytest.importorskip("img2pdf")
        images = _create_test_images(tmp_path)
        output = tmp_path / "test.pdf"
        pack_pdf(images, output)
        assert output.exists()
        with open(output, "rb") as f:
            assert f.read(4) == b"%PDF"

    def test_skips_empty_paths(self, tmp_path):
        pytest.importorskip("img2pdf")
        images = _create_test_images(tmp_path, 2)
        images.append("")
        output = tmp_path / "test.pdf"
        pack_pdf(images, output)
        assert output.exists()

    def test_no_valid_images_raises(self, tmp_path):
        pytest.importorskip("img2pdf")
        output = tmp_path / "test.pdf"
        with pytest.raises(ValueError):
            pack_pdf([], output)
        with pytest.raises(ValueError):
            pack_pdf(["", ""], output)


class TestParseDownloadArgs:
    """Tests for parse_download_args function."""

    def _parse(self, msg, default_fmt="zip"):
        return parse_download_args(msg, default_fmt)

    def test_basic(self):
        manga, chapter, fmt = self._parse("/漫画 下载 一拳超人 1")
        assert manga == "一拳超人"
        assert chapter == "1"
        assert fmt == "zip"

    def test_with_format_zip(self):
        manga, chapter, fmt = self._parse("/漫画 下载 一拳超人 1 zip")
        assert manga == "一拳超人"
        assert chapter == "1"
        assert fmt == "zip"

    def test_with_format_pdf(self):
        manga, chapter, fmt = self._parse("/漫画 下载 一拳超人 1 pdf")
        assert manga == "一拳超人"
        assert chapter == "1"
        assert fmt == "pdf"

    def test_with_format_cbz(self):
        manga, chapter, fmt = self._parse("/漫画 下载 一拳超人 1 cbz")
        assert manga == "一拳超人"
        assert chapter == "1"
        assert fmt == "cbz"

    def test_id_syntax_with_format(self):
        manga, chapter, fmt = self._parse("/漫画 下载 151 ID:2531 zip")
        assert manga == "151"
        assert chapter == "ID:2531"
        assert fmt == "zip"

    def test_id_syntax_without_format(self):
        manga, chapter, fmt = self._parse("/漫画 下载 151 ID:2531")
        assert manga == "151"
        assert chapter == "ID:2531"
        assert fmt == "zip"

    def test_default_fmt_used(self):
        manga, chapter, fmt = self._parse("/漫画 下载 一拳超人 1", default_fmt="pdf")
        assert fmt == "pdf"

    def test_explicit_overrides_default(self):
        manga, chapter, fmt = self._parse("/漫画 下载 一拳超人 1 cbz", default_fmt="pdf")
        assert fmt == "cbz"

    def test_no_chapter(self):
        manga, chapter, fmt = self._parse("/漫画 下载 一拳超人")
        assert manga == "一拳超人"
        assert chapter == ""
        assert fmt == "zip"

    def test_format_keyword_not_confused_with_chapter_name(self):
        """Chapter name containing 'zip' as substring should not be stripped."""
        manga, chapter, fmt = self._parse("/漫画 下载 漫画名 1.5 zip")
        assert manga == "漫画名"
        assert chapter == "1.5"
        assert fmt == "zip"

    def test_decimal_chapter(self):
        manga, chapter, fmt = self._parse("/漫画 下载 海贼王 38.5 pdf")
        assert manga == "海贼王"
        assert chapter == "38.5"
        assert fmt == "pdf"
