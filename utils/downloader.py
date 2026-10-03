from __future__ import annotations

import asyncio
import ipaddress
import re
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import aiohttp
from yarl import URL

from astrbot.api import logger

from ..suwayomi.config import get_config_value

if TYPE_CHECKING:
    from ..suwayomi.client import SuwayomiClient

from ..suwayomi import PLUGIN_NAME

_PLUGIN_NAME = PLUGIN_NAME

# 文件打包路径（下载/AI 发送/自动推送 file 模式）的整章页数默认上限：
# 正常章节远低于此值，仅用于挡住恶意源宣告的超大页列表；整卷/合集
# 章节可合法超过默认值，用户可通过 file_delivery_max_pages 配置调大
FILE_DELIVERY_MAX_PAGES = 300


def get_file_delivery_max_pages(config: dict | None) -> int:
    """文件打包路径的整章页数上限（配置缺省/非法时回落 300）。"""
    try:
        value = int(
            get_config_value(
                config or {}, "file_delivery_max_pages", FILE_DELIVERY_MAX_PAGES
            )
        )
    except (TypeError, ValueError):
        return FILE_DELIVERY_MAX_PAGES
    return max(1, value)

# 单张图片响应的字节上限（防恶意源用超大响应打满内存/磁盘）
_MAX_IMAGE_BYTES = 64 * 1024 * 1024

# 手动跟随重定向的最大跳数
_MAX_REDIRECTS = 4

_REDIRECT_STATUSES = (301, 302, 303, 307, 308)


def _origin_of(url: str) -> str | None:
    """URL 的 origin（scheme://netloc）；非 http(s) 或无主机返回 None。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    return f"{parsed.scheme}://{parsed.netloc.lower()}"


async def _open_without_ssrf_redirect(
    session: aiohttp.ClientSession,
    url: str,
    timeout: aiohttp.ClientTimeout,
    headers: dict[str, str] | None = None,
) -> aiohttp.ClientResponse | None:
    """逐跳打开 URL（禁用自动重定向），拒绝跳向第三方私网地址。

    aiohttp 默认自动跟随重定向，会绕过 resolve_image_url 的私网地址
    过滤（302 → 127.0.0.1 可被跟随）。以初始 URL 的 origin 为可信基准
    （初始地址已由上游按同服务器/私网规则过滤）：重定向目标仅允许
    同 origin 或公网地址，且跨 origin 跳转时丢弃认证头（对齐 aiohttp
    自动重定向剥离 Authorization 的语义，避免凭据泄露给第三方）。
    跨源跳转在连接建立后复核对端 IP，命中私网/环回即中止（堵 DNS
    rebinding 与非常规 IP 编码绕过）。被拒/超跳数/缺少 Location 返回
    None，调用方按下载失败降级。
    """
    current = url
    trusted_origin = _origin_of(url)
    hop_headers = dict(headers) if headers else None
    for _ in range(_MAX_REDIRECTS + 1):
        resp = await session.get(
            current, timeout=timeout, allow_redirects=False, headers=hop_headers
        )
        if (
            _origin_of(current) != trusted_origin
            and _is_private_host(_peer_host(resp))
        ):
            logger.warning(
                f"[{_PLUGIN_NAME}] 重定向目标实际连接到私网/环回地址，已中止: {current}"
            )
            resp.close()
            return None
        if resp.status not in _REDIRECT_STATUSES:
            return resp
        location = resp.headers.get("Location")
        await resp.release()
        if not location:
            return None
        target = str(URL(current).join(URL(location)))
        target_origin = _origin_of(target)
        if target_origin is None or (
            target_origin != trusted_origin
            and _is_private_host(urlparse(target).hostname)
        ):
            logger.warning(
                f"[{_PLUGIN_NAME}] 拒绝跟随重定向到不可信地址: {target}"
            )
            return None
        if target_origin != trusted_origin:
            # 跨 origin：丢弃认证头，避免泄露给第三方主机
            hop_headers = None
        current = target
    return None


async def download_one(
    session: aiohttp.ClientSession,
    url: str,
    dest: Path,
    retries: int = 3,
    headers: dict[str, str] | None = None,
) -> bool:
    for attempt in range(retries):
        try:
            resp = await _open_without_ssrf_redirect(
                session, url, aiohttp.ClientTimeout(total=30), headers
            )
            if resp is None:
                return False
            async with resp:
                if resp.status == 200:
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in resp.content.iter_chunked(1 << 16):
                        size += len(chunk)
                        if size > _MAX_IMAGE_BYTES:
                            logger.warning(
                                f"[{_PLUGIN_NAME}] 图片响应超过 "
                                f"{_MAX_IMAGE_BYTES // (1024 * 1024)}MB 上限，放弃: {url}"
                            )
                            return False
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    ext = ".jpg"
                    ct = resp.headers.get("Content-Type", "")
                    if "png" in ct:
                        ext = ".png"
                    elif "webp" in ct:
                        ext = ".webp"
                    dest = dest.with_suffix(ext)
                    dest.write_bytes(data)
                    return True
                elif resp.status < 500:
                    return False
                logger.debug(
                    f"[{_PLUGIN_NAME}] 图片下载 HTTP {resp.status}，"
                    f"重试 {attempt + 1}/{retries}: {url}"
                )
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.debug(
                f"[{_PLUGIN_NAME}] 图片下载超时/网络错误，"
                f"重试 {attempt + 1}/{retries}: {e}"
            )
        except Exception as e:
            logger.warning(f"[{_PLUGIN_NAME}] 图片下载异常: {e}")
            return False
        if attempt < retries - 1:
            await asyncio.sleep(0.5 * (2**attempt))
    return False


async def download_images(
    urls: list[str],
    concurrency: int = 6,
    custom_tmp: str = "",
    retries: int = 3,
    headers: dict[str, str] | None = None,
) -> tuple[list[str], Path]:
    if custom_tmp:
        Path(custom_tmp).mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="suwayomi_", dir=custom_tmp or None))
    try:
        connector = aiohttp.TCPConnector(limit=concurrency)
        # headers 逐请求传递（不设 session 级）：跨 origin 跳转由
        # _open_without_ssrf_redirect 丢弃，避免重定向时泄露认证头
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [
                download_one(session, url, tmp_dir / f"{i:04d}.jpg", retries, headers)
                for i, url in enumerate(urls)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        paths: list[str] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(
                    f"[{_PLUGIN_NAME}] 图片 {i + 1} 下载异常: {result}"
                )
                paths.append("")
            elif result:
                matches = sorted(tmp_dir.glob(f"{i:04d}.*"))
                paths.append(str(matches[-1]) if matches else "")
            else:
                paths.append("")
        ok_count = sum(1 for path in paths if path)
        if len(paths) > ok_count:
            logger.debug(
                f"[{_PLUGIN_NAME}] 图片批量下载: {ok_count}/{len(paths)} 张成功"
            )
        return paths, tmp_dir
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


_IPV4_PART_RE = re.compile(r"^(?:0[xX][0-9a-fA-F]+|[0-9]+)$")


def _parse_ipv4_part(part: str) -> int:
    """inet_aton 分段规则：0x 十六进制 / 前导 0 八进制 / 十进制。"""
    if part.lower().startswith("0x"):
        return int(part, 16)
    if len(part) > 1 and part.startswith("0"):
        return int(part, 8)
    return int(part, 10)


def _parse_loose_ipv4(host: str) -> ipaddress.IPv4Address | None:
    """解析 inet_aton 兼容写法（2130706433 / 0177.0.0.1 / 0x7f.1 / 127.1）。

    Linux 的 getaddrinfo/inet_aton 接受这些非规范字面量并把它们当作
    127.0.0.1，仅用 ipaddress 解析会漏判。返回 None 表示不是 IP 字面量。
    """
    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    if not all(_IPV4_PART_RE.match(part) for part in parts):
        return None
    try:
        nums = [_parse_ipv4_part(part) for part in parts]
    except ValueError:
        return None
    if len(nums) == 1:
        combined = nums[0]
    elif len(nums) == 2:
        if nums[0] > 0xFF or nums[1] > 0xFFFFFF:
            return None
        combined = (nums[0] << 24) | nums[1]
    elif len(nums) == 3:
        if nums[0] > 0xFF or nums[1] > 0xFF or nums[2] > 0xFFFF:
            return None
        combined = (nums[0] << 24) | (nums[1] << 16) | nums[2]
    else:
        if any(n > 0xFF for n in nums):
            return None
        combined = (nums[0] << 24) | (nums[1] << 16) | (nums[2] << 8) | nums[3]
    if combined > 0xFFFFFFFF:
        return None
    return ipaddress.IPv4Address(combined)


def _peer_host(resp) -> str | None:
    """已连接响应的实际对端 IP；连接信息不可得（测试替身/已关闭）返回 None。"""
    connection = getattr(resp, "connection", None)
    transport = getattr(connection, "transport", None)
    if transport is None:
        return None
    try:
        peer = transport.get_extra_info("peername")
    except (RuntimeError, OSError):
        return None
    if isinstance(peer, (tuple, list)) and peer:
        return str(peer[0])
    return None


def _is_private_host(hostname: str | None) -> bool:
    """绝对 URL 的主机是否指向私网/环回/链路本地等不可达外网的目标。

    识别字面 IP（含 inet_aton 兼容写法：十进制整数、八进制、十六进制、
    `127.1` 缩写）与 localhost（含尾点写法）。域名解析到内网（DNS
    rebinding 类）不在此函数内做 DNS；重定向跳转由下载路径的连接后
    对端复检兜底，初始 URL 的域名解析仍属已知限制。
    """
    host = (hostname or "").strip().strip("[]").rstrip(".").lower()
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = _parse_loose_ipv4(host)
    if ip is None:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


def resolve_image_url(
    client: SuwayomiClient,
    thumbnail_url: str | None,
    auth_headers: dict[str, str] | None,
) -> tuple[str | None, dict[str, str] | None]:
    """Resolve a thumbnail URL to a fetchable URL plus the auth headers to use.

    Suwayomi's GraphQL ``thumbnailUrl`` is normally a server-relative path
    like ``/api/v1/manga/{id}/thumbnail``. Relative paths always carry the
    given ``auth_headers``; absolute URLs only when they point at the same
    server (scheme + host + port), to avoid leaking Suwayomi credentials to
    third-party hosts. 源扩展可控的第三方绝对地址若指向私网/环回目标
    则拒绝请求（防 SSRF），调用方按「无封面」降级。Returns
    ``(None, None)`` for empty or rejected input.
    """
    if not thumbnail_url:
        return None, None

    if thumbnail_url.startswith(("http://", "https://")):
        url = thumbnail_url
        use_headers = None
        same_server = False
        if client.server_url:
            server = urlparse(client.server_url)
            target = urlparse(thumbnail_url)
            server_port = server.port or (443 if server.scheme == "https" else 80 if server.scheme == "http" else None)
            target_port = target.port or (443 if target.scheme == "https" else 80 if target.scheme == "http" else None)
            same_server = (
                server.scheme == target.scheme
                and server.hostname == target.hostname
                and server_port == target_port
            )
            if same_server:
                use_headers = auth_headers
        if not same_server and _is_private_host(urlparse(thumbnail_url).hostname):
            logger.warning(
                f"[{_PLUGIN_NAME}] 拒绝下载指向私网/环回地址的第三方封面: "
                f"{urlparse(thumbnail_url).hostname}"
            )
            return None, None
    else:
        url = client.build_image_url(thumbnail_url)
        use_headers = auth_headers

    return url, use_headers


async def download_cover(
    client: SuwayomiClient,
    thumbnail_url: str | None,
    custom_tmp: str = "",
    retries: int = 3,
    headers: dict[str, str] | None = None,
) -> tuple[str | None, Path | None]:
    """Download a single manga cover to a temporary directory.

    Returns ``(local_path, tmp_dir)`` on success, or ``(None, None)`` when the
    cover is unavailable or cannot be downloaded. On success the caller is
    responsible for cleaning ``tmp_dir`` (e.g. via ``schedule_cleanup``).

    URL/auth resolution is delegated to ``resolve_image_url`` (single source
    of truth shared with the card renderer).
    """
    url, use_headers = resolve_image_url(client, thumbnail_url, headers)
    if url is None:
        return None, None

    try:
        paths, tmp_dir = await download_images(
            [url], concurrency=1, custom_tmp=custom_tmp, retries=retries, headers=use_headers
        )
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        logger.warning(f"[{_PLUGIN_NAME}] 封面下载失败: {e}", exc_info=True)
        return None, None
    except Exception:
        logger.exception(f"[{_PLUGIN_NAME}] 封面下载出现未知异常")
        raise

    if not paths or not paths[0]:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None, None

    return paths[0], tmp_dir


async def fetch_pages_local(
    client: SuwayomiClient,
    chapter_id: int,
    max_pages: int = 0,
    concurrency: int = 6,
    custom_tmp: str = "",
    retries: int = 3,
    headers: dict[str, str] | None = None,
) -> tuple[int, list[str], list[str], Path | None]:
    pages = await client.fetch_chapter_pages(chapter_id)
    if not pages:
        return 0, [], [], None
    total_pages = len(pages)
    if max_pages > 0:
        pages = pages[:max_pages]
    page_urls = [client.build_image_url(p) for p in pages]
    local_paths, tmp_dir = await download_images(
        page_urls, concurrency, custom_tmp, retries, headers
    )
    return total_pages, page_urls, local_paths, tmp_dir
