import sys
from pathlib import Path

# 将父目录加入搜索路径，以支持在 bb 目录下直接运行
sys.path.append(str(Path(__file__).parent.parent))

from bb import download_video


def main():
    # 测试 Bilibili 链接
    url = "https://www.bilibili.com/video/BV1GJ411x7H7"

    print(f"[*] 开始测试下载视频: {url}")
    print("[*] 正在使用默认输出根目录 (bb 目录内部下的 download/)\n")

    try:
        # output_dir=None 代表采用项目默认的 bb/download 路径
        download_dir, info = download_video(
            url=url,
            output_dir=None,
            keep_intermediate=True,
            download_subtitles=True,
        )
        print("\n=== 下载验证成功! ===")
        print(f"视频标题: {info.get('title')}")
        print(f"视频专属子目录: {download_dir.resolve()}")

        print("\n专属子目录内已下载的文件及大小:")
        files_found = list(download_dir.glob("*"))
        if not files_found:
            print(" (未找到任何文件)")
        for file in files_found:
            if file.is_file():
                size_mb = file.stat().st_size / (1024 * 1024)
                print(f"  |-- {file.name:<30} ({size_mb:.2f} MB)")

    except Exception as e:
        print(f"\n下载测试中发生错误: {e}")


if __name__ == "__main__":
    main()
