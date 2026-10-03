"""Bangumi (bgm.tv) metadata resolution for search alias expansion.

生态先例：Tachiyomi/Mihon 扩展库的 BangumiScraper、Aidoku、KikoPlay 等
均以 api.bgm.tv 的模糊搜索做标题解析。本模块职责：
1. ``resolve_aliases(query, bases)`` — 搜索 → 取前若干条目（按搜索排名）→
   合并官方中文名/日文名/别名表；首轮无强命中时用日文字形变体重试一次
   （转天 → 転天——「転天」这类俗称缩写常被官方收录在别名表里）。
   支持端点回退链（bases，见 api_bases）。任何网络/解析失败返回 None，
   调用方静默跳过扩展。
2. ``build_probes(query, resolution)`` — 挑选要拿去源站重搜的探针：
   别名 + 长别名的首段（站点收录常自选译法，全名探针会漏），按与
   关键词的相关度降序，去重后有界。
3. ``alias_boost`` — 仲裁器增强证据：「关键词命中官方别名」本身即
   强证据（海贼王 搜出 航海王 也能拿 A 级）；探针溯源关联受门槛
   与封顶约束，防止泛探针噪声借溯源挤入 top-N。

实测校准（详见各函数注释）：条目池取搜索排名前 5（正解常在第 4-5
位，官方长名对"带错字关键词"打分低，按分挑反而漏）；探针归一化
长度 ≥4（3 字探针在严格源返回 200+ 条且目标可能不在第一页）。
"""
from __future__ import annotations

import asyncio
import re
import time
import urllib.parse
from dataclasses import dataclass, field

import aiohttp

from astrbot.api import logger

from . import PLUGIN_NAME
from .ranking import (
    STRONG_MATCH_THRESHOLD,
    jp_variant,
    normalize_for_rank,
    score_title,
)

_PLUGIN_NAME = PLUGIN_NAME

OFFICIAL_API_BASE = "https://api.bgm.tv"
# 社区公共镜像（bangumi.vip 为 Mirrox 全域镜像、anibt.net 为 nginx API 反代；
# 2026-09 实测可用。公共镜像存在域名轮换/下线风险，仅作受限网络的回退链）。
BUILTIN_MIRROR_BASES = ["https://api.bangumi.vip", "https://bgmapi.anibt.net"]

_SEARCH_PATH = "/search/subject/{kw}?type=1&max_results=8"
_SUBJECT_PATH = "/v0/subjects/{sid}"
_HEADERS = {
    "User-Agent": (
        "astrbot_plugin_suwayomi_server "
        "(https://github.com/FFFold/astrbot_plugin_suwayomi_server)"
    )
}
_REQUEST_TIMEOUT = 8.0

_HAN_RE = re.compile(r"[\u4e00-\u9fff]")


@dataclass
class Resolution:
    """Bangumi 解析结果：条目 → 别名集合，及关键词的置信判定。"""

    by_subject: dict[int, list[str]] = field(default_factory=dict)
    confident: bool = False
    best_alias_score: float = 0.0

    def all_aliases(self) -> list[str]:
        seen: list[str] = []
        for names in self.by_subject.values():
            for name in names:
                if name not in seen:
                    seen.append(name)
        return seen


def parse_search(raw: dict) -> list[int]:
    """从搜索响应提取条目 id 列表（保持排名顺序）。"""
    items = (raw or {}).get("list") or []
    ids: list[int] = []
    for item in items:
        try:
            sid = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if sid not in ids:
            ids.append(sid)
    return ids


def parse_subject(raw: dict) -> list[str]:
    """从条目详情提取名称集合：官方中文名、日文名、别名表。"""
    names: list[str] = []
    for key in ("name_cn", "name"):
        value = (raw or {}).get(key)
        if value and value not in names:
            names.append(value)
    for item in (raw or {}).get("infobox") or []:
        if item.get("key") != "别名":
            continue
        value = item.get("value")
        if not isinstance(value, list):
            continue
        for entry in value:
            text = entry.get("v") if isinstance(entry, dict) else str(entry)
            if text and text not in names:
                names.append(text)
    return names


def best_alias_score(query: str, resolution: Resolution) -> float:
    best = 0.0
    for names in resolution.by_subject.values():
        for alias in names:
            best = max(best, score_title(query, alias))
    return best


def confident_aliases(query: str, resolution: Resolution) -> list[str]:
    """得分达到强命中阈值的官方别名（提示行展示用）。"""
    out: list[str] = []
    for names in resolution.by_subject.values():
        for alias in names:
            if score_title(query, alias) >= STRONG_MATCH_THRESHOLD and alias not in out:
                out.append(alias)
    return out[:3]


def api_bases(mirror_enabled: bool, mirror_url: str) -> list[str]:
    """Bangumi API 端点优先级（回退链）。

    - 镜像开关关闭：仅官方 api.bgm.tv（网络受限时解析失败 → 扩展静默跳过）
    - 镜像开关开启且填了自定义地址：只用用户提供的镜像
    - 镜像开关开启且未填：内置公共镜像按序回退
    全部失败时 resolve_aliases 返回 None，等价于不使用 Bangumi。
    """
    if not mirror_enabled:
        return [OFFICIAL_API_BASE]
    custom = (mirror_url or "").strip().rstrip("/")
    if custom:
        return [custom]
    return list(BUILTIN_MIRROR_BASES)


def _quote_keyword(keyword: str) -> str:
    # safe="" 防路径段注入（关键词含 / 时不再拼出多段路径，如
    # 「海贼王/航海王」这类输入曾导致请求落到错误路径而静默失败）；
    # '+' 是本插件多词连接符，bgm 侧按空格分词，先归一。
    return urllib.parse.quote(keyword.replace("+", " "), safe="")


async def _get_json(session: aiohttp.ClientSession, url: str) -> dict:
    # 不跟随重定向：bgm API 正常不重定向，端点被 302 到私网地址属
    # SSRF 面；3xx 按端点失败处理，由 resolve_aliases 走回退链
    async with session.get(url, headers=_HEADERS, allow_redirects=False) as resp:
        if 300 <= resp.status < 400:
            location = resp.headers.get("Location", "")
            raise aiohttp.ClientError(
                f"HTTP {resp.status} redirect to {location!r} refused (SSRF guard)"
            )
        resp.raise_for_status()
        return await resp.json(content_type=None)


async def resolve_aliases(
    query: str,
    max_subjects: int = 5,
    timeout: float = _REQUEST_TIMEOUT,
    bases: list[str] | None = None,
    deadline: float | None = None,
) -> Resolution | None:
    """解析关键词的官方条目与别名。失败返回 None（调用方静默跳过扩展）。

    逐个端点尝试（bases 由调用方按镜像配置生成），首个拿到条目的
    端点胜出；全部失败返回 None，等价于不使用 Bangumi。
    deadline 为整条回退链的共享预算（秒，墙钟）：按剩余端点数均分
    剩余时间，单个端点无论快败、慢滴还是 hang 都不能超出其切片
    （wait_for 强制），预算耗尽立即放弃后续端点。
    """
    query = str(query or "").strip()
    if not query:
        return None
    chain = list(bases or [OFFICIAL_API_BASE])
    start = time.monotonic()
    for index, base in enumerate(chain):
        if deadline is None:
            per_base = timeout
        else:
            remaining = deadline - (time.monotonic() - start)
            if remaining <= 0:
                logger.debug(
                    f"[{_PLUGIN_NAME}] Bangumi 解析预算耗尽，放弃剩余端点: {query!r}"
                )
                return None
            per_base = remaining / (len(chain) - index)
        try:
            resolution = await asyncio.wait_for(
                _resolve_via(base, query, max_subjects, per_base),
                timeout=per_base,
            )
        except asyncio.TimeoutError:
            logger.debug(
                f"[{_PLUGIN_NAME}] Bangumi 端点 {base} 超时（{per_base:.1f}s）"
            )
            continue
        if resolution is not None and resolution.by_subject:
            if index > 0:
                logger.debug(
                    f"[{_PLUGIN_NAME}] Bangumi 前序端点失败，回退到 {base} 成功"
                )
            return resolution
    logger.debug(
        f"[{_PLUGIN_NAME}] Bangumi 全部 {len(chain)} 个端点均失败，"
        f"跳过别名扩展: {query!r}"
    )
    return None


async def _resolve_via(
    base: str,
    query: str,
    max_subjects: int,
    timeout: float,
) -> Resolution | None:
    resolution = Resolution()
    # trust_env: 若容器配置了 HTTP(S)_PROXY 环境变量（如自建 clash）则自动走代理；
    # 部分网络环境下 api.bgm.tv 的线路被干扰，代理是恢复解析的通路之一。
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(timeout=timeout_cfg, trust_env=True) as session:

            async def _collect(keyword: str) -> None:
                raw = await _get_json(
                    session, base + _SEARCH_PATH.format(kw=_quote_keyword(keyword))
                )
                sids = parse_search(raw)[:max_subjects]

                async def _fetch(sid: int) -> None:
                    try:
                        subject = await _get_json(
                            session, base + _SUBJECT_PATH.format(sid=sid)
                        )
                    except Exception as exc:
                        # 单个条目失败跳过不阻塞，调试日志留痕
                        logger.debug(
                            f"[{_PLUGIN_NAME}] Bangumi 条目 {sid} 详情解析失败: {exc}"
                        )
                        return
                    names = parse_subject(subject)
                    if names:
                        resolution.by_subject[sid] = names

                # 条目详情并发拉取，单个失败跳过不阻塞
                await asyncio.gather(*(_fetch(sid) for sid in sids))

            await _collect(query)
            if best_alias_score(query, resolution) < STRONG_MATCH_THRESHOLD:
                jp = jp_variant(query)
                if jp and jp != query:
                    logger.debug(
                        f"[{_PLUGIN_NAME}] Bangumi 首轮无强命中，"
                        f"使用日文字形变体重试: {jp!r}"
                    )
                    await _collect(jp)
    except Exception as exc:
        logger.debug(f"[{_PLUGIN_NAME}] Bangumi 端点 {base} 解析失败: {exc}")
        return None

    resolution.best_alias_score = best_alias_score(query, resolution)
    resolution.confident = resolution.best_alias_score >= STRONG_MATCH_THRESHOLD
    return resolution


# 探针首段切分用的连接词（取别名第一段做 4 字头，如「转生王女与…」→「转生王女」）
_CONJ_RE = re.compile(r"[与和及跟之的×·、，,：:／/＋+]+")


def _probe_candidates(names: list[str]) -> list[str]:
    """单个条目贡献的探针候选：全部别名 + 长别名的首段。

    站点收录常自选译法（实测 311s.com 收录「转生王女和天才千金…」
    用「和」而非「与」，全名探针会漏），长别名首段（4 字头）作为
    兜底探针。
    """
    out: list[str] = []
    for name in names:
        out.append(name)
        normalized = normalize_for_rank(name)
        if len(normalized) > 6:
            first_seg = _CONJ_RE.split(str(name).strip())[0].strip()
            if first_seg and first_seg != name and first_seg not in out:
                out.append(first_seg)
    return out


def build_probes(
    query: str,
    resolution: Resolution,
    max_probes: int = 3,
) -> list[tuple[str, int]]:
    """挑选拿去源站重搜的 (探针, 来源条目id)，按与关键词的相关度降序。

    过滤：归一化长度 ≥4（实测 3 字探针在严格源返回 200+ 条且目标
    可能不在第一页）、与关键词归一化相同者（第一轮已搜过）、汉字
    占比过低者（英文名对中文源站无意义）。
    """
    query_norm = normalize_for_rank(query)
    seen = {query_norm}
    candidates: list[tuple[float, str, int]] = []
    for sid, names in resolution.by_subject.items():
        for candidate in _probe_candidates(names):
            normalized = normalize_for_rank(candidate)
            if len(normalized) < 4 or normalized in seen:
                continue
            # 汉字占比过低（英文名对中文源站无意义）则跳过
            han_count = len(_HAN_RE.findall(normalized))
            if han_count < max(2, 0.5 * len(normalized)):
                continue
            seen.add(normalized)
            candidates.append((score_title(query, candidate), candidate, sid))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [(name, sid) for _, name, sid in candidates[:max_probes]]


# 别名增强的保守校准。bgm.tv 的别名是社区 wiki（注册用户可编辑），
# 高频短字（如单字「王」）一旦被追加进条目别名，任何标题含该字的
# 结果都会命中子串关联——故两条路径都设门槛：
# ① 结果标题包含条目某别名（归一化子串）→ 别名须 ≥ _ALIAS_MIN_LEN 字
#    （防短字投毒），继承分封顶 _ALIAS_BOOST_CAP（略低于完全相等）；
# ② 仅溯源关联（探针捞回）→ 结果自身对 query 的分数需 ≥
#    _PROVENANCE_BASE_FLOOR，且增强分封顶 _PROVENANCE_BOOST_CAP
#    （低于强命中线，噪声无法独自过线）。
_ALIAS_MIN_LEN = 3
_ALIAS_BOOST_CAP = 949.0
_PROVENANCE_BASE_FLOOR = 650.0
_PROVENANCE_BOOST_CAP = 849.0


def alias_boost(
    query: str,
    title: str,
    provenance_sid: int | None,
    resolution: Resolution | None,
    base_score: float | None = None,
) -> float:
    """结果的别名增强分（0 表示无增强）。

    「结果 ↔ 条目」关联判定：① 结果标题包含该条目某别名的归一化形式
    （标题「航海王」包含别名「航海王」→ 继承「query 命中官方别名」的分）；
    ② 第二轮探测携带的溯源条目 provenance（受 base_score 门槛与封顶约束）。
    仅在解析置信时生效，防止错误解析抬高错误结果。
    """
    if not resolution or not resolution.confident:
        return 0.0
    title_norm = normalize_for_rank(title)
    if not title_norm:
        return 0.0
    best = 0.0
    for sid, names in resolution.by_subject.items():
        # 只认可信长度的别名做子串关联（防社区别名表投毒高频短字）
        long_aliases = [
            a for a in names
            if len(normalize_for_rank(a)) >= _ALIAS_MIN_LEN
        ]
        alias_linked = any(
            (alias_norm := normalize_for_rank(alias)) and alias_norm in title_norm
            for alias in long_aliases
        )
        from_probe = provenance_sid == sid
        if not alias_linked and not from_probe:
            continue
        if from_probe and not alias_linked:
            # 溯源-only：结果自身须与 query 有基础相关度，且不继承满分
            if base_score is not None and base_score < _PROVENANCE_BASE_FLOOR:
                continue
            best = max(
                best,
                min(
                    max(score_title(query, alias) for alias in names),
                    _PROVENANCE_BOOST_CAP,
                ),
            )
        else:
            # 子串关联：继承分封顶（防「query==别名」1000 分直接置顶）
            best = max(
                best,
                min(
                    max(score_title(query, alias) for alias in names),
                    _ALIAS_BOOST_CAP,
                ),
            )
    return best
