from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# 将当前文件所在目录加入 sys.path 以支持在 bb 目录内部作为直接脚本运行时能同级导入
current_dir = Path(__file__).parent.resolve()
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

import yt_dlp

from utils import extract_video_id, is_bilibili_url, is_youtube_url, sanitize_text

# 默认目录定义 (指向当前 bb 目录内部的子目录，保证彻底内聚和干净)
DEFAULT_DOWNLOAD_DIR = Path(__file__).parent / "download"
DEFAULT_COOKIE_DIR = Path(__file__).parent / "cookie"

FORMAT_CANDIDATES = (
    "bestvideo[height<=1080]+bestaudio/best",
    "bestvideo+bestaudio/best",
    "bv*+ba/b",
    "best",
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _bootstrap_bilibili_cookie(cookie_path: Path) -> None:
    """通过访问 Bilibili 首页，自动生成并保存匿名 Cookie 凭证"""
    try:
        import requests
        response = requests.get(
            "https://www.bilibili.com/",
            headers={"User-Agent": DEFAULT_USER_AGENT, "Referer": "https://www.bilibili.com/"},
            timeout=10,
        )
        response.raise_for_status()
        expires = int(time.time()) + 3600 * 24 * 365
        lines = ["# Netscape HTTP Cookie File", ""]
        cookies = dict(response.cookies)
        cookies.setdefault("SESSDATA", "anonymous_for_webpage_playinfo")
        for name, value in cookies.items():
            lines.append("\t".join([".bilibili.com", "TRUE", "/", "FALSE", str(expires), name, value]))
        cookie_path.parent.mkdir(parents=True, exist_ok=True)
        cookie_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        # 仅作为打印提示，确保不影响后续即使没有匿名 Cookie 的下载尝试
        print(f"Warning: Failed to bootstrap bilibili anonymous cookie: {e}")


def _ydl_base(
    url: str,
    proxy_port: str = "",
    cookie_path: str | Path | None = None,
    use_proxy: bool | None = None,
    download_subtitles: bool = True,
) -> dict[str, Any]:
    """生成基础 of yt-dlp 配置字典"""
    opts: dict[str, Any] = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "js_runtimes": {"node": {}},
        "http_headers": {"User-Agent": DEFAULT_USER_AGENT},
    }

    is_bili = is_bilibili_url(url)
    is_yt = is_youtube_url(url)

    # 1. 确定 Cookie 路径
    resolved_cookie_path = None
    if cookie_path:
        resolved_cookie_path = Path(cookie_path)
    elif is_bili:
        DEFAULT_COOKIE_DIR.mkdir(parents=True, exist_ok=True)
        # 支持寻找已建立的 bilibili 登录/匿名 cookie 
        cookie_candidates = [
            DEFAULT_COOKIE_DIR / "bilibili.txt",
            DEFAULT_COOKIE_DIR / "bilibili_cookie.txt",
        ]
        for cand in cookie_candidates:
            if cand.exists() and cand.stat().st_size > 0:
                resolved_cookie_path = cand
                break
        else:
            # 均不存在，自动引导一个匿名 Cookie
            anon_cookie = DEFAULT_COOKIE_DIR / "bilibili_cookie.txt"
            _bootstrap_bilibili_cookie(anon_cookie)
            resolved_cookie_path = anon_cookie

    if resolved_cookie_path and resolved_cookie_path.exists():
        opts["cookiefile"] = str(resolved_cookie_path)

    # 2. 处理代理选项
    actual_use_proxy = False
    if use_proxy is not None:
        actual_use_proxy = use_proxy
    else:
        # 默认：YouTube 使用代理，Bilibili 不使用代理
        if is_yt:
            actual_use_proxy = True
        elif is_bili:
            actual_use_proxy = False

    if actual_use_proxy:
        proxy = ""
        if proxy_port.strip():
            proxy = f"http://127.0.0.1:{proxy_port.strip()}"
        else:
            proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy") or ""
        if proxy:
            opts["proxy"] = proxy
    else:
        opts["proxy"] = ""

    # 3. 字幕配置
    if download_subtitles:
        opts.update({
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["all"],
        })

    return opts


def _remove_partial_outputs(video_file: Path) -> None:
    """清理多余或破损的临时输出文件"""
    for candidate in video_file.parent.glob(f"{video_file.name}*"):
        if candidate == video_file:
            continue
        if candidate.is_file():
            candidate.unlink(missing_ok=True)


def _organize_intermediate_files(output_dir: Path, final_video: Path) -> None:
    """
    后处理规整：把 keepvideo 保留下来的带特定格式后缀的临时视频轨（无声）和音频轨文件，
    规范命名为 video_only.<ext> 和 audio_only.<ext>
    """
    audio_extensions = {".m4a", ".mp3", ".aac", ".wav", ".ogg", ".opus"}
    video_extensions = {".mp4", ".mkv", ".flv", ".avi"}

    # 查找所有以 video_source. 开头，但是排除最终合并文件、json、字幕等文件
    candidates: list[Path] = []
    for file in output_dir.glob("video_source.*"):
        if file.name == final_video.name:
            continue
        if file.suffix.lower() in {".json", ".vtt", ".srt", ".part", ".ytdlp_info"}:
            continue
        candidates.append(file)

    audio_files: list[Path] = []
    video_files: list[Path] = []
    webm_files: list[Path] = []

    for file in candidates:
        suffix = file.suffix.lower()
        if suffix in audio_extensions:
            audio_files.append(file)
        elif suffix in video_extensions:
            video_files.append(file)
        elif suffix == ".webm":
            webm_files.append(file)

    # 针对 webm 格式做精细分类（webm 既可能作为视频轨道，也可能作为音频轨道）
    if len(webm_files) > 1:
        # 存在多个 webm 时，根据文件大小排序：最小的大概率是音频轨，其余归视频轨
        webm_files_sorted = sorted(webm_files, key=lambda f: f.stat().st_size)
        audio_files.append(webm_files_sorted[0])
        video_files.extend(webm_files_sorted[1:])
    elif len(webm_files) == 1:
        # 单个 webm：如果有其他已确定的音频，则它是视频；若已有视频，它是音频
        if audio_files:
            video_files.append(webm_files[0])
        elif video_files:
            audio_files.append(webm_files[0])
        else:
            # 既没有确定音频也没有视频，根据文件大小做阈值估算（一般大于2MB估算为无声视频）
            if webm_files[0].stat().st_size > 2 * 1024 * 1024:
                video_files.append(webm_files[0])
            else:
                audio_files.append(webm_files[0])

    # 重命名为规范的文件名
    for audio_file in audio_files:
        target = output_dir / f"audio_only{audio_file.suffix}"
        if not target.exists() or target.stat().st_size == 0:
            try:
                # 尝试重命名，如果失败则说明文件可能被占用
                if audio_file.exists():
                    audio_file.rename(target)
            except Exception:
                pass

    for video_file in video_files:
        target = output_dir / f"video_only{video_file.suffix}"
        if not target.exists() or target.stat().st_size == 0:
            try:
                if video_file.exists():
                    video_file.rename(target)
            except Exception:
                pass


def download_video(
    url: str,
    output_dir: str | Path | None = None,
    proxy_port: str = "",
    cookie_path: str | Path | None = None,
    use_proxy: bool | None = None,
    keep_intermediate: bool = True,
    download_subtitles: bool = True,
) -> tuple[Path, dict[str, Any]]:
    """
    从 YouTube 或 Bilibili 下载视频，自动为其创建专属子目录存放所有资源。

    :param url: 视频 URL 
    :param output_dir: 本地保存视频的基础根目录。若为 None，默认当前 bb 目录下的 download 目录
    :param proxy_port: 可选的代理端口，例如 "7890"
    :param cookie_path: 可选的 Cookie 文本路径。若为 None，默认在当前 bb 目录下的 cookie 目录中寻找或自动初始化
    :param use_proxy: 是否强制使用代理 (None 代表默认 YouTube 开启, Bilibili 禁用)
    :param keep_intermediate: 是否保留独立的原始无声视频文件和音频文件（重命名为 video_only / audio_only）
    :param download_subtitles: 是否下载字幕文件
    :return: (包含专属视频下所有生成文件的 Path (即专属子目录), 视频元数据字典)
    """
    # 确定基础输出路径，默认为 DEFAULT_DOWNLOAD_DIR
    base_output_path = Path(output_dir) if output_dir is not None else DEFAULT_DOWNLOAD_DIR
    base_output_path.mkdir(parents=True, exist_ok=True)

    video_id = extract_video_id(url)

    # 1. 提取元数据 
    info_opts = _ydl_base(
        url,
        proxy_port=proxy_port,
        cookie_path=cookie_path,
        use_proxy=use_proxy,
        download_subtitles=False,  # 提取元数据阶段不需要下载字幕
    )

    with yt_dlp.YoutubeDL(info_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    # 2. 根据下载的文件名(经过安全清洗的视频标题)和视频ID创建专属子目录
    title = sanitize_text(str(info.get("title") or "untitled"))
    session_dir = base_output_path / f"{title}__{video_id}"
    session_dir.mkdir(parents=True, exist_ok=True)

    # 3. 保存清理后的元数据至专属子目录中
    metadata_file = session_dir / "ytdlp_info.json"
    metadata_file.write_text(
        json.dumps(ydl.sanitize_info(info), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 4. 规范最终合并后的视频输出路径
    video_file = session_dir / "video_source.mp4"

    # 如果已经存在且有大小，直接返回，避免重复下载
    if video_file.exists() and video_file.stat().st_size > 0:
        return session_dir, info

    # 5. 开始尝试各种清晰度格式下载
    last_error: Exception | None = None
    for format_selector in FORMAT_CANDIDATES:
        download_opts = {
            **_ydl_base(
                url,
                proxy_port=proxy_port,
                cookie_path=cookie_path,
                use_proxy=use_proxy,
                download_subtitles=download_subtitles,
            ),
            "format": format_selector,
            "merge_output_format": "mp4",
            "outtmpl": str(session_dir / "video_source.%(ext)s"),
            "retries": 10,
            "fragment_retries": 10,
        }

        # 核心：如果要求保留独立的视频和音频，启用 keepvideo 机制
        if keep_intermediate:
            download_opts["keepvideo"] = True

        try:
            with yt_dlp.YoutubeDL(download_opts) as ydl_downloader:
                ydl_downloader.download([url])
            break
        except Exception as exc:
            last_error = exc
            _remove_partial_outputs(video_file)
            if "Requested format is not available" not in str(exc):
                continue
    else:
        if last_error:
            raise last_error

    # 6. 后处理整理专属子目录下的中间音视频轨道
    if keep_intermediate:
        _organize_intermediate_files(session_dir, video_file)

    # 7. 最终验证
    if not video_file.exists() or video_file.stat().st_size == 0:
        raise RuntimeError("yt-dlp finished without producing video_source.mp4")

    return session_dir, info
