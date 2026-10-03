"""Cross-source search result ranking (pure functions, stdlib + opencc only).

打分模型（从强到弱的证据等级，详见 docs 与设计讨论）：

- A  完全相等          归一化后一字不差                        1000
- B  正向包含          完整关键词是标题的子串                  900 − 额外长度×2 − 位置惩罚
- B  多词项包含        按 空格/'+' 切词后每个词都出现在标题里  895 − 额外长度×2
- B' 反向包含          标题是关键词的子串且覆盖关键词 ≥60%     880 − 缺失长度×3
- B'' 子序列(fzf 式)   关键词各字符按序出现、允许间隔          800 + 60×紧凑度
- C  部分重叠          字符覆盖率 + 序列相似度 + 词项命中率    ≤800

同分保持原顺序（稳定排序）：打分失误时行为退化为现状，不会更糟。

归一化链：NFKC → casefold → 日文新字体转繁体（opencc 自带
JPVariants.txt 动态构建）→ 繁转简(t2s) → 内置小表补漏 → 去空白/
'+'/连接符/标点。插件依赖 opencc-python-reimplemented 不带 jp2t
配置文件，故运行时直接解析其 dictionary/JPVariants.txt（繁→日变体，
逐行 `繁\\t日1 日2`）反向构建 日→繁 全量映射（365 对；多对一字形
如 辨/瓣/辯→弁 经 setdefault 塌缩取首个繁体，属已知取舍）；字典
缺失或解析失败时整体回落下方内置小映射表（优雅退化，未覆盖字符
原样保留）。
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
from importlib import resources

import opencc

STRONG_MATCH_THRESHOLD = 800.0

_t2s = opencc.OpenCC("t2s")


def _load_jp_variant_tables() -> tuple[dict[str, str], dict[str, str], opencc.OpenCC] | None:
    """解析 opencc 自带 JPVariants.txt，构建 日→繁 / 繁→日 映射与 s2t 转换器。

    返回 None 表示任一环节失败（包结构变化/字典缺失/s2t 配置缺失），
    调用方整体回落内置小映射表。
    """
    try:
        raw = (resources.files("opencc") / "dictionary" / "JPVariants.txt").read_text(
            encoding="utf-8"
        )
        jp_to_trad: dict[str, str] = {}
        trad_to_jp: dict[str, str] = {}
        for line in raw.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) != 2:
                continue
            trad = parts[0].strip()
            variants = parts[1].split()
            if not trad or not variants:
                continue
            jp_to_trad.setdefault(variants[0], trad)
            trad_to_jp.setdefault(trad, variants[0])
        if not jp_to_trad:
            return None
        return jp_to_trad, trad_to_jp, opencc.OpenCC("s2t")
    except Exception:
        return None


_JP_TABLES = _load_jp_variant_tables()
# 全量 日→繁 字符对（JPVariants 反向）；None = 回落内置小表
_JP_TO_TRAD_RAW: dict[str, str] | None = _JP_TABLES[0] if _JP_TABLES else None
# 繁→日 正向字符对（取首变体），仅用于构造 Bangumi 日文重试查询
_TRAD_TO_JP_RAW: dict[str, str] | None = _JP_TABLES[1] if _JP_TABLES else None
_s2t: opencc.OpenCC | None = _JP_TABLES[2] if _JP_TABLES else None
_JP_TO_TRAD = str.maketrans(_JP_TO_TRAD_RAW) if _JP_TO_TRAD_RAW is not None else None
_TRAD_TO_JP = str.maketrans(_TRAD_TO_JP_RAW) if _TRAD_TO_JP_RAW is not None else None

# 日文新字体 → 简体（仅收录与简体字形不同的常用字；繁体字由 t2s 处理）。
# JPVariants.txt 可用时仅作补漏（覆盖其未收录的键），不可用时整体回落
_JP_TO_CN_RAW = {
    "転": "转", "売": "卖", "対": "对", "変": "变", "実": "实", "経": "经",
    "楽": "乐", "価": "价", "満": "满", "関": "关", "説": "说", "読": "读",
    "続": "续", "勧": "劝", "弾": "弹", "撃": "击", "沢": "泽", "滝": "泷",
    "広": "广", "伝": "传", "両": "两", "剣": "剑", "気": "气", "竜": "龙",
    "帰": "归", "観": "观", "挙": "举", "録": "录", "鉄": "铁", "銭": "钱",
    "電": "电", "風": "风", "飛": "飞", "養": "养", "飯": "饭", "館": "馆",
    "長": "长", "開": "开", "間": "间", "遠": "远", "違": "违", "賀": "贺",
    "課": "课", "諸": "诸", "賓": "宾", "難": "难", "険": "险", "検": "检",
    "隠": "隐", "様": "样", "桜": "樱", "姫": "姬", "図": "图", "絵": "绘",
    "涙": "泪", "準": "准", "現": "现", "環": "环", "異": "异", "発": "发",
    "盤": "盘", "築": "筑", "結": "结", "終": "终", "統": "统", "継": "继",
    "編": "编", "織": "织", "義": "义", "習": "习", "聞": "闻", "舎": "舍",
    "艦": "舰", "覚": "觉", "覧": "览", "記": "记", "証": "证", "話": "话",
    "誇": "夸", "談": "谈", "請": "请", "諾": "诺", "講": "讲", "謝": "谢",
    "譜": "谱", "豊": "丰", "貝": "贝", "財": "财", "責": "责", "賢": "贤",
    "質": "质", "軍": "军", "軽": "轻", "軸": "轴", "辺": "边", "進": "进",
    "遅": "迟", "郷": "乡", "酔": "醉", "銀": "银", "鋭": "锐", "閃": "闪",
    "陽": "阳", "隊": "队", "霊": "灵", "響": "响", "領": "领", "頭": "头",
    "顔": "颜", "餓": "饿", "馬": "马", "駆": "驱", "騎": "骑", "黒": "黑",
    "黙": "默", "窓": "窗", "渋": "涩", "縁": "缘",
    "芸": "艺", "錬": "炼", "斎": "斋", "嶋": "岛", "嬢": "娘",
    "頬": "颊", "艶": "艳", "働": "动",
}
_JP_TO_CN = str.maketrans(_JP_TO_CN_RAW)
# JPVariants 已覆盖的键不再重复映射；未覆盖的键由小表补漏
_JP_EXTRA_TO_CN = str.maketrans(
    {k: v for k, v in _JP_TO_CN_RAW.items() if k not in (_JP_TO_TRAD_RAW or {})}
)
# 反向表（仅用于构造 Bangumi 日文重试查询；当前映射无重复目标字，若未来
# 加入碰撞对，此处 dict 推导会保留最后一个键——加键时需自行核对唯一性）
_CN_TO_JP = str.maketrans({v: k for k, v in _JP_TO_CN_RAW.items()})

_STRIP_RE = re.compile(
    r"[\s\.\。·・\-—_~～！？!?:：;；'‘’\"“”「」『』（）()【】\[\]《》<>×*+/\\|,，、]+"
)
_TRUNCATED_RE = re.compile(r"(?:\.{2,}|。{2,}|…)$")


@lru_cache(maxsize=1024)
def _normalize_cached(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    if _JP_TO_TRAD is not None:
        # JPVariants 全量：日文新字体 → 繁体，再统一繁转简
        text = _t2s.convert(text.translate(_JP_TO_TRAD))
        # 字典未收录的日文新字体由内置小表直转简体补漏
        text = text.translate(_JP_EXTRA_TO_CN)
    else:
        text = _t2s.convert(text)
        text = text.translate(_JP_TO_CN)
    return _STRIP_RE.sub("", text)


def normalize_for_rank(text: str) -> str:
    """归一化标题/关键词：消除繁简、全半角、大小写、日文字形与标点差异。"""
    return _normalize_cached(str(text or ""))


def jp_variant(text: str) -> str | None:
    """把简体关键词转成日文新字体写法（用于 Bangumi 重试）；无差异时返回 None。"""
    t = str(text or "")
    if _TRAD_TO_JP is not None and _s2t is not None:
        # 简 → 繁(s2t) → JPVariants 正向取日文首变体
        converted = _s2t.convert(t).translate(_TRAD_TO_JP)
    else:
        converted = _t2s.convert(t).translate(_CN_TO_JP)
    return converted or None


def split_tokens(text: str) -> list[str]:
    """按空白/'+' 切词并归一化（多词查询的词项命中率用）。"""
    raw = re.split(r"[\s+]+", str(text or "").strip())
    return [n for n in (normalize_for_rank(t) for t in raw) if n]


def looks_truncated(title: str) -> bool:
    """标题是否疑似被源站截断（以 .. / 。。 / … 结尾）。"""
    return bool(_TRUNCATED_RE.search(str(title or "").strip()))


def _subsequence_score(nq: str, nt: str) -> float | None:
    """fzf 式子序列打分：nq 各字符按序出现在 nt 中允许间隔。

    常量取自 fzf（src/algo/algo.go）：每命中字符 16 分，间隔 −3 起 −1 续，
    连续片段每处 +4，首字符在标题开头 +8；最终按理想分折算成 [800, 860]。
    """
    positions: list[int] = []
    cursor = 0
    for ch in nq:
        idx = nt.find(ch, cursor)
        if idx == -1:
            return None
        positions.append(idx)
        cursor = idx + 1
    score = 16.0 * len(nq)
    prev = positions[0]
    for cur in positions[1:]:
        gap = cur - prev - 1
        if gap:
            score -= 3.0 + (gap - 1)
        else:
            score += 4.0
        prev = cur
    if positions[0] == 0:
        score += 8.0
    ideal = 16.0 * len(nq) + 4.0 * (len(nq) - 1) + 8.0
    ratio = max(0.0, min(1.0, score / ideal)) if ideal > 0 else 0.0
    return 800.0 + 60.0 * ratio


def _partial_score(query: str, nq: str, nt: str) -> float:
    """C 级部分重叠：字符覆盖率(recall 优先) + 序列相似度 + 词项命中率，≤800。"""
    q_chars, t_chars = set(nq), set(nt)
    recall = len(q_chars & t_chars) / len(q_chars) if q_chars else 0.0
    ratio = SequenceMatcher(None, nq, nt).ratio()
    tokens = split_tokens(query)
    token_hit = 0.0
    if len(tokens) > 1:
        token_hit = sum(1 for t in tokens if t in nt) / len(tokens)
    return min(800.0, 400.0 * recall + 250.0 * ratio + 150.0 * token_hit)


def score_title(query: str, title: str) -> float:
    """关键词与标题的相关度分；分数越高越可能是用户想要的作品。"""
    nq = normalize_for_rank(query)
    nt = normalize_for_rank(title)
    if not nq or not nt:
        return 0.0
    if nq == nt:
        return 1000.0
    if nq in nt:
        extra = len(nt) - len(nq)
        return 900.0 - 2.0 * extra - min(nt.find(nq), 30)
    tokens = split_tokens(query)
    if len(tokens) > 1:
        token_len = sum(len(t) for t in tokens)
        if all(t in nt for t in tokens):
            return 895.0 - 2.0 * (len(nt) - token_len)
    if nt in nq and len(nt) >= 3 and len(nt) * 10 >= len(nq) * 6:
        return 880.0 - 3.0 * (len(nq) - len(nt))
    sub = _subsequence_score(nq, nt)
    if sub is not None:
        return sub
    return _partial_score(query, nq, nt)


def rank_items(query, items, title_of):
    """按相关度稳定降序排序；返回 (排序后items, 对应分数)。"""
    scored = [(score_title(query, title_of(it)), i, it) for i, it in enumerate(items)]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [it for _, _, it in scored], [s for s, _, _ in scored]
