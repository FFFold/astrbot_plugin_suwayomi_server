"""Tests for suwayomi/service.py helpers (no network)."""

from suwayomi.models import Chapter
from suwayomi.service import (
    fmt_chapter_display,
    fmt_chapter_label,
    resolve_chapter,
)


def _ch(name: str, num: float) -> Chapter:
    return Chapter(id=1, url="", name=name, chapter_number=num,
                   source_order=1, upload_date=0)


class TestFmtChapterDisplay:

    def test_uses_name_when_available(self):
        ch = _ch("07卷附录", 7)
        assert fmt_chapter_display(ch) == "07卷附录"

    def test_uses_name_with_volume(self):
        ch = _ch("第8卷", 8)
        assert fmt_chapter_display(ch) == "第8卷"

    def test_uses_name_with_chapter(self):
        ch = _ch("第01话", 1)
        assert fmt_chapter_display(ch) == "第01话"

    def test_falls_back_to_number_with_话(self):
        ch = _ch("", 7)
        assert fmt_chapter_display(ch) == "第7话"

    def test_fallback_with_decimal(self):
        ch = _ch("", 38.5)
        assert fmt_chapter_display(ch) == "第38.5话"

    def test_fallback_with_nan(self):
        import math
        ch = _ch("", math.nan)
        assert fmt_chapter_display(ch) == "第?话"

    def test_handles_whitespace_name(self):
        ch = _ch("  ", 3)
        assert fmt_chapter_display(ch) == "第3话"

    def test_handles_extra_chapter_name(self):
        ch = _ch("07卷附录", 7)
        assert fmt_chapter_display(ch) == "07卷附录"

    def test_name_with_id_suffix_not_affected(self):
        ch = _ch("第5话后篇", 5)
        assert fmt_chapter_display(ch) == "第5话后篇"


class TestFmtChapterLabel:

    def test_uses_name_when_available(self):
        ch = _ch("第8卷", 8)
        assert fmt_chapter_label(ch, {}) == "#8 第8卷"

    def test_uses_name_with_dup_tag(self):
        ch = _ch("07卷附录", 7)
        assert fmt_chapter_label(ch, {7: 2}) == "#7 07卷附录 (ID:1)"


def _chapter(id: int, name: str, num: float) -> Chapter:
    return Chapter(id=id, url="", name=name, chapter_number=num,
                   source_order=1, upload_date=0)


class TestResolveChapter:

    def test_by_id_ascii_colon(self):
        chapters = [_chapter(100, "第1话", 1), _chapter(200, "第2话", 2)]
        target, err = resolve_chapter(chapters, "ID:200", "test", "阅读")
        assert err is None
        assert target is not None and target.id == 200

    def test_by_id_fullwidth_colon(self):
        chapters = [_chapter(100, "第1话", 1), _chapter(200, "第2话", 2)]
        target, err = resolve_chapter(chapters, "ID：200", "test", "阅读")
        assert err is None
        assert target is not None and target.id == 200

    def test_by_id_lowercase(self):
        chapters = [_chapter(100, "第1话", 1)]
        target, err = resolve_chapter(chapters, "id:100", "test", "阅读")
        assert err is None
        assert target is not None and target.id == 100

    def test_by_id_lowercase_fullwidth(self):
        chapters = [_chapter(100, "第1话", 1)]
        target, err = resolve_chapter(chapters, "id：100", "test", "阅读")
        assert err is None
        assert target is not None and target.id == 100

    def test_by_id_invalid_format(self):
        _, err = resolve_chapter([], "ID:abc", "test", "阅读")
        assert err is not None and "格式无效" in err

    def test_by_id_not_found(self):
        chapters = [_chapter(100, "第1话", 1)]
        _, err = resolve_chapter(chapters, "ID:999", "test", "阅读")
        assert err is not None and "未找到" in err

    def test_by_number(self):
        chapters = [_chapter(100, "第5话", 5)]
        target, err = resolve_chapter(chapters, "5", "test", "阅读")
        assert err is None
        assert target is not None and target.id == 100

    def test_invalid_number(self):
        _, err = resolve_chapter([], "abc", "test", "阅读")
        assert err is not None and "章节号无效" in err
