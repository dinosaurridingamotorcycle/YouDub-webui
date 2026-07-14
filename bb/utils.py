from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
BILIBILI_BV_RE = re.compile(r"BV[A-Za-z0-9]{10}")
BILIBILI_HOSTS = {"bilibili.com", "www.bilibili.com", "m.bilibili.com"}


def sanitize_text(value: str, fallback: str = "untitled") -> str:
    """清洗文本，作为安全的文件名"""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value.strip(), flags=re.UNICODE)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._")
    return cleaned[:120] or fallback


def _extract_youtube_id(parsed) -> str | None:
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")

    if host in {"youtu.be", "www.youtu.be"}:
        candidate = path.split("/")[0]
        if YOUTUBE_ID_RE.match(candidate):
            return candidate

    if "youtube.com" not in host:
        return None

    query_id = parse_qs(parsed.query).get("v", [""])[0]
    if YOUTUBE_ID_RE.match(query_id):
        return query_id

    parts = path.split("/")
    for prefix in ("shorts", "embed", "live"):
        if len(parts) >= 2 and parts[0] == prefix and YOUTUBE_ID_RE.match(parts[1]):
            return parts[1]
    return None


def _extract_bilibili_id(parsed) -> str | None:
    host = parsed.netloc.lower()
    if host not in BILIBILI_HOSTS:
        return None
    match = BILIBILI_BV_RE.search(parsed.path)
    if match:
        return match.group(0)
    return None


def extract_video_id(url: str) -> str:
    """从链接中提取 YouTube ID 或 Bilibili BV 号"""
    parsed = urlparse(url.strip())
    video_id = _extract_youtube_id(parsed) or _extract_bilibili_id(parsed)
    if video_id:
        return video_id
    raise ValueError("Only YouTube or Bilibili single-video URLs are supported.")


def is_youtube_url(url: str) -> bool:
    try:
        return _extract_youtube_id(urlparse(url.strip())) is not None
    except ValueError:
        return False


def is_bilibili_url(url: str) -> bool:
    return urlparse(url.strip()).netloc.lower() in BILIBILI_HOSTS
