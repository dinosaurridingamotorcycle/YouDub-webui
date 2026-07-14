import argparse
import sys
from pathlib import Path

# 将当前文件所在目录加入 sys.path 以支持在 bb 目录内部作为直接脚本运行时能同级导入
current_dir = Path(__file__).parent.resolve()
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from downloader import download_video


def main():
    parser = argparse.ArgumentParser(
        description="BB - 纯净、独立的 YouTube 与 Bilibili 视频及音视频轨道下载工具 CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "url",
        type=str,
        help="视频的播放链接 (YouTube 或 Bilibili 单视频 URL)",
    )

    parser.add_argument(
        "-o",
        "--output-dir",
        type=str,
        default=None,
        help="保存视频的基础输出根目录，不传则默认保存在 bb 目录下的 download 目录",
    )

    parser.add_argument(
        "-p",
        "--proxy-port",
        type=str,
        default="",
        help="本地代理端口（例如 '7890'）",
    )

    parser.add_argument(
        "-c",
        "--cookie-path",
        type=str,
        default=None,
        help="特定的 Cookie 文件路径（如需在 B 站下载高清，建议提供登录后的 Cookie 文件）",
    )

    parser.add_argument(
        "--no-keep",
        action="store_true",
        help="不保留单独的音视频轨道文件（仅留存最终合并后的 video_source.mp4）",
    )

    parser.add_argument(
        "--no-subs",
        action="store_true",
        help="不自动下载原视频的独立字幕文件",
    )

    parser.add_argument(
        "--proxy-mode",
        choices=["auto", "on", "off"],
        default="auto",
        help="代理启用模式。auto: 自动决定（YouTube 启用，Bilibili 禁用）; on: 强制启用; off: 强制禁用",
    )

    args = parser.parse_args()

    # 处理代理模式选择
    use_proxy = None
    if args.proxy_mode == "on":
        use_proxy = True
    elif args.proxy_mode == "off":
        use_proxy = False

    try:
        print(f"[*] 正在运行下载任务: {args.url}")
        print("[*] 请稍候，正在获取视频信息...")

        download_dir, info = download_video(
            url=args.url,
            output_dir=args.output_dir,
            proxy_port=args.proxy_port,
            cookie_path=args.cookie_path,
            use_proxy=use_proxy,
            keep_intermediate=not args.no_keep,
            download_subtitles=not args.no_subs,
        )

        print("\n================== 下载完成 ==================")
        print(f"[+] 视频标题: {info.get('title')}")
        print(f"[+] 专属保存子目录: {download_dir.resolve()}")

        print("\n[+] 下载产生的文件列表:")
        files_found = list(download_dir.glob("*"))
        if not files_found:
            print("  (无文件)")
        for file in files_found:
            if file.is_file():
                size_mb = file.stat().st_size / (1024 * 1024)
                print(f"  |-- {file.name:<35} ({size_mb:.2f} MB)")
        return 0

    except Exception as e:
        print(f"\n[ERROR] 下载失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
