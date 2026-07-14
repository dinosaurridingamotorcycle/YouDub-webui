# BB - 自包含视频下载模块

这是一个从 YouDub-webui 项目中独立剥离出来的**纯净自包含视频下载模块**。它专门用于高效地从 YouTube 或 哔哩哔哩（Bilibili）下载视频，并且支持保留独立的音视频轨道与字幕文件。

---

## 🌟 核心特性

- **完全自包含**：整个目录无任何外部本项目的依赖，拥有自己的独立 Python 虚拟环境，支持被移动、剪切到任意地方使用。
- **开箱即用默认值 (内聚在 bb 目录内部)**：
  - **`output_dir`**：默认创建并使用 `bb` 目录内的 **`bb/download/`** 目录。
  - **`cookie`**：默认创建并使用 `bb` 目录内的 **`bb/cookie/`** 目录。
- **专属子目录管理**：
  - 下载器会自动在输出根目录下为每一个视频创建形式为 **`{安全清洗后的视频标题}__{视频ID}`** 的专属隔离子目录。
  - **所有相关资源（音视频、字幕、元数据等）均全归集在该专属子目录下**，杜绝多视频下载时文件混杂。
- **专属目录产出内容**：
  - 合并后的完整高清视频：`video_source.mp4`
  - 独立的纯视频（无声）文件：`video_only.<ext>`
  - 独立的纯音频文件：`audio_only.<ext>`
  - 自动保留各语言原版字幕文件：`video_source.<lang_code>.vtt` 
  - 完整元数据：`ytdlp_info.json`
- **Bilibili 高清视频下载支持**：支持提供登录后的 B站 Cookie 凭证（导出为 Netscape 格式，存放在默认 `bb/cookie` 目录或通过参数指定），解锁 1080p、4K 等最高画质下载。
- **鲁棒的匿名降级**：未提供 Cookie 时，自动在 `bb/cookie` 目录下生成 `bilibili_cookie.txt` 匿名 Cookie 进行降级下载，确保下载绝对成功。

---

## 📦 依赖与环境准备

在使用本模块之前，请确保系统已安装 **FFmpeg**（yt-dlp 合并和处理音视频的必需系统级依赖）。

### 本地独立 Python 环境
本目录内置了独立的 Python `venv` 虚拟环境，保障了全局环境的纯净性，免受其他库的干扰。

#### 激活虚拟环境
- **Windows (PowerShell)**:
  ```powershell
  .\bb\venv\Scripts\Activate.ps1
  ```
- **macOS / Linux**:
  ```bash
  source bb/venv/bin/activate
  ```

---

## 💻 命令行 (CLI) 执行指南

支持**先进入 `bb` 目录内**，随后直接通过极其简洁的脚本执行下载，**无需指定 `bb` 模块参数**。对由于已经在包内部执行报错 `No module named bb` 进行了完美的兼容优化！

### 1. 切换到 `bb` 目录下并激活虚拟环境：
```bash
cd bb
.\venv\Scripts\Activate.ps1
```

### 2. 使用极简命令行启动下载：
直接使用默认配置进行下载（下载的视频子目录、自动生成的 Cookie 文件会完全内聚保存在 `bb/download` 和 `bb/cookie` 内部）：
```bash
python main.py "https://www.bilibili.com/video/BV1GJ411x7H7"
```
或者执行：
```bash
python cli.py "https://www.bilibili.com/video/BV1GJ411x7H7"
```

### 3. 自定义参数命令示例：

由于不同操作系统的命令行换行符存在差异，请选择适合您当前终端的输入格式：

- **单行直接执行（全平台通用，最不易出错，推荐）**：
  ```bash
  python main.py "视频链接" -o "./my_custom_downloads" -p "7890" -c "./my_cookie_file.txt"
  ```
- **Windows (PowerShell) 多行续行（使用反引号 `` ` `` 作为换行符）**：
  ```powershell
  python main.py "视频链接" `
      -o "./my_custom_downloads" `
      -p "7890" `
      -c "./my_cookie_file.txt"
  ```
- **Linux / macOS (Bash) 多行续行（使用反斜杠 `\` 作为换行符）**：
  ```bash
  python main.py "视频链接" \
      -o "./my_custom_downloads" \
      -p "7890" \
      -c "./my_cookie_file.txt"
  ```

### 4. CLI 所有支持选项帮助：
```bash
python main.py --help
```

---

## 🚀 Python API 快速上手

模块依然完美支持作为第三方包在项目根目录下或外部项目中作为 API 引用：

### 1. 基础极简下载
```python
from bb import download_video

# 零配置下载 (自动下载并内聚在 bb/download 下的视频子目录中)
download_dir, info = download_video(
    url="https://www.bilibili.com/video/BV1GJ411x7H7"
)

print(f"视频标题: {info.get('title')}")
print(f"产出物路径: {download_dir.resolve()}")
```

### 2. 高级参数下载
```python
from bb import download_video

# 传入 B站 真实 Cookie（放入 bb/cookie/bilibili.txt 中即可自动寻找）下载 1080p
download_dir, info = download_video(
    url="https://www.bilibili.com/video/BV1GJ411x7H7",
    output_dir="./HD_downloads",
    proxy_port="7890",
    cookie_path="./bb/cookie/bilibili_cookies_real.txt",
    keep_intermediate=True,
    download_subtitles=True
)
```
---

## 🛠️ Python API 参数详解

`download_video` 接受以下参数：

| 参数名 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| **`url`** | `str` | *必填* | 支持的 YouTube 或 Bilibili 单视频链接。 |
| **`output_dir`** | `str \| Path \| None` | `None` | 指定基础下载根目录。若为 `None`，默认使用 `bb` 目录内部下的 `download` 目录。 |
| **`proxy_port`** | `str` | `""` | 可选的本地代理端口（例如 `"7890"`）。 |
| **`cookie_path`** | `str \| Path \| None` | `None` | 可选的 Cookie 文本路径。若为 `None`，默认在 `bb` 目录内部下的 `cookie` 目录中自动寻找或初始化。 |
| **`use_proxy`** | `bool \| None` | `None` | 是否启用代理。`None` 表示：YouTube 自动使用，Bilibili 自动禁用。 |
| **`keep_intermediate`** | `bool` | `True` | 是否保留独立的无声视频 `video_only` 和纯音频 `audio_only` 文件。 |
| **`download_subtitles`** | `bool` | `True` | 是否在专属子目录下下载原视频所有的独立字幕。 |
