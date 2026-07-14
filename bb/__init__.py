import sys
from pathlib import Path

# 将当前文件夹目录加入 sys.path，让作为包外部导入或在内部运行时均能使用统一的绝对命名空间导入
current_dir = Path(__file__).parent.resolve()
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from downloader import download_video
from utils import extract_video_id, is_bilibili_url, is_youtube_url, sanitize_text

__all__ = [
    "download_video",
    "extract_video_id",
    "is_bilibili_url",
    "is_youtube_url",
    "sanitize_text",
]
export_version = "1.0.0"
