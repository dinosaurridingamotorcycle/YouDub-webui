# 01 - 项目总览

## TL;DR

YouDub WebUI 是一个**本地运行**的视频本地化配音流水线工具，核心场景是将 YouTube/Bilibili 英语视频转换为中文配音版。前后端分离的本地单体应用，通过浏览器访问 WebUI 操作。

## 项目定位

| 维度 | 说明 |
|---|---|
| 核心能力 | 视频 → 目标语言配音版（含字幕烧录） |
| 典型场景 | 英→中配音，也支持中→英 |
| 输入来源 | YouTube URL / Bilibili URL / 本地视频文件（可选附带 SRT 字幕） |
| 输出产物 | 带目标语言配音和字幕的最终视频（`video_final.mp4`） |
| 运行方式 | 本地部署，浏览器访问 WebUI |
| 执行模式 | auto（自动连续执行全部阶段）/ manual（逐步执行，可单独重做阶段） |

## 技术栈

### 后端

| 技术 | 用途 |
|---|---|
| Python + FastAPI | REST API 服务 |
| SQLite | 任务/阶段/设置持久化 |
| 单线程 worker | FIFO 任务队列，串行执行 |
| yt-dlp | 视频下载 |
| Demucs (htdemucs_ft) | 人声/BGM 分离 |
| OpenAI Whisper (large-v3-turbo) | 语音识别 |
| OpenAI 兼容 API | LLM 翻译 |
| VoxCPM2 (ModelScope) | TTS 语音合成 |
| librosa / audiostretchy | 音频切分/合并/变速对齐 |
| FFmpeg / ffprobe | 视频转码/字幕烧录/最终合成 |
| Fernet | API 密钥加解密 |

### 前端

| 技术 | 用途 |
|---|---|
| Next.js 16 (App Router) | Web 框架 |
| React 19 | UI 运行时 |
| TypeScript (strict) | 类型安全 |
| shadcn/ui (base-nova) + Tailwind CSS v4 | UI 组件与样式 |
| lucide-react | 图标 |
| 原生 fetch | HTTP 请求（无 axios） |
| React Context + localStorage | 自建 i18n（中/英） |

### 子模块

| 模块 | 路径 | 用途 |
|---|---|---|
| Demucs | `submodule/` | 源码引入的人声分离模型 |

## 目录结构

```
myyoudub/
├── backend/                    # 后端
│   ├── app/
│   │   ├── main.py             # FastAPI 入口 + 20 个 API 路由
│   │   ├── pipeline.py         # 流水线编排引擎（9 阶段）
│   │   ├── stages.py           # 阶段静态定义
│   │   ├── worker.py           # 单线程任务队列
│   │   ├── database.py         # SQLite 持久化
│   │   ├── config.py           # 全局路径与环境配置
│   │   ├── sources.py          # URL 来源识别
│   │   ├── stage_reset.py      # 阶段产物清理
│   │   ├── devices.py          # GPU/CPU 设备解析
│   │   ├── youtube.py          # URL 解析
│   │   ├── sanitize.py         # 文件名安全化
│   │   ├── secrets.py          # 密钥加解密
│   │   ├── runtime_checks.py   # 运行时校验
│   │   └── adapters/           # 13 个适配器文件
│   └── tests/                  # 测试
├── apps/
│   └── web/                    # 前端
│       └── src/
│           ├── app/            # Next.js App Router 页面
│           ├── components/     # 业务组件 + shadcn/ui
│           └── lib/            # API 客户端/i18n/工具
├── submodule/                  # Demucs 源码子模块
├── scripts/                    # 辅助脚本
├── requirements.txt            # Python 依赖（无版本锁定）
├── requirements-pytorch-cu128.txt  # PyTorch CUDA 12.8 依赖
├── env.txt.example             # 环境变量示例
└── package.json                # 前端 monorepo 配置
```

## 核心数据流（一句话版）

用户在 WebUI 提交视频 URL → 后端创建任务入队 → worker 串行执行 9 阶段流水线 → 各阶段调用对应适配器 → 产物落盘到 session 目录 → 前端 2 秒轮询展示进度 → 完成后可预览/下载最终视频。

> 详细架构与数据流见 [02-architecture.md](02-architecture.md)
> 流水线 9 阶段详解见 [03-pipeline.md](03-pipeline.md)

## 关键设计决策

1. **单线程串行执行**：worker 是单线程 FIFO 队列，任务一个接一个执行，避免 GPU 资源竞争
2. **产物落盘 + 缓存恢复**：每个阶段产物都写入 session 目录，失败后可从已成功阶段恢复（断点续跑）
3. **适配器模式**：每个外部能力独立一个适配器文件，可独立替换（换 ASR/TTS/翻译后端不影响其他阶段）
4. **双执行模式**：auto 全自动，manual 可逐步执行 + 单阶段重做，便于调试和局部修正
5. **无 WebSocket**：前端用 2 秒轮询获取状态，实现简单但有效
