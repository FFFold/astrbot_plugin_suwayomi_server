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
