"""Tests for chapter image packing (ZIP, PDF, CBZ)."""
import zipfile
from pathlib import Path

import pytest

from utils.pack import pack_zip, pack_cbz, pack_pdf


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
