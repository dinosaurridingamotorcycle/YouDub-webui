# 05 - 代码地图

> 文件→职责→关键函数映射表，含行号引用。用于快速定位代码位置。

## 后端 (`backend/app/`)

### 核心模块

| 文件 | 职责 | 关键函数/类 | 行号 |
|---|---|---|---|
| `main.py` | FastAPI 入口，20 个 REST API 路由 | `lifespan(app)` — 启动时初始化 DB/清理僵尸/启动 worker | `:97` |
| | | `create_task(payload)` — 创建 YouTube/Bilibili 任务 | `:166` |
| | | `upload_local_video(...)` — 上传本地视频+可选字幕 | `:237` |
| | | `redo_stage(task_id, stage_name)` — 手动模式重做阶段 | `:352` |
| | | `continue_task(task_id, payload)` — 手动模式继续 | `:377` |
| | | `resume_task(task_id)` — 恢复失败任务 | `:394` |
| `pipeline.py` | 流水线编排引擎 | `PipelineArtifacts` (dataclass) — 存储所有中间产物路径 | `:19-32` |
| | | `PipelineRunner.__init__(task_id)` — 构建阶段→处理函数映射 | `:57-71` |
| | | `PipelineRunner.run()` — 主入口：遍历 9 阶段 | `:73-135` |
| | | `_run_stage(stage)` — 执行单阶段 | `:194-216` |
| | | `_restore_cached_stage(stage, task)` — 从磁盘恢复产物 | `:218-261` |
| | | `_download` / `_separate` / `_asr` / `_asr_fix` / `_translate` / `_split_audio` / `_tts` / `_merge_audio` / `_merge_video` — 9 阶段处理函数 | `:263-436` |
| | | `run_task(task_id)` — 模块级便捷入口 | `:439-440` |
| `stages.py` | 阶段静态定义 | `StageSpec` (frozen dataclass) — 含 name + label | `:6-9` |
| | | `STAGES` — 9 阶段有序元组 | `:12-22` |
| | | `STAGE_NAMES` — 仅阶段名元组 | `:25` |
| `worker.py` | 单线程 FIFO 任务队列 | `enqueue(task_id)` — 入队 | `:17` |
| | | `_loop(runner)` — 守护线程主循环 | `:21` |
| | | `start(runner)` — 启动 worker，恢复 queued 任务 | `:28` |
| `database.py` | SQLite 持久化 | `init_db()` — 建表/迁移/默认设置 | `:29` |
| | | `create_task(url, task_id, execution_mode)` — 创建任务+初始化阶段 | `:144` |
| | | `get_task(task_id)` — 查询任务及阶段 | `:207` |
| | | `reset_stages_from(task_id, from_stage)` — 重置指定阶段起 | `:261` |
| | | `reset_failed_for_resume(task_id)` — 恢复失败阶段为 pending | `:290` |
| | | `set_setting(key, value)` / `get_setting(key)` — 通用 KV | `:330` / `:342` |
| | | `get_openai_settings()` / `save_openai_settings()` — OpenAI 配置（含加解密） | `:348` / `:363` |

### 支持模块

| 文件 | 职责 | 关键函数/类 | 行号 |
|---|---|---|---|
| `config.py` | 全局路径/环境配置 | `DB_PATH`, `WORKFOLDER`, `device()`, `openai_defaults()`, `ensure_runtime_dirs()` | — |
| `sources.py` | URL 来源识别 | `SourceConfig` (dataclass), `SOURCES` (youtube/local/bilibili), `detect_source(url)` | — |
| `stage_reset.py` | 阶段产物清理 | `STAGE_OWN_ARTIFACTS` — 各阶段产物路径映射, `remove_stage_artifacts(session, from_stage, source)` | — |
| `youtube.py` | URL 解析 | `extract_video_id(url)`, `is_youtube_url()`, `is_bilibili_url()`, `is_local_upload_url()`, `local_upload_direction()` | — |
| `sanitize.py` | 文件名安全化 | `sanitize_text(value, fallback)` — 保留中文/字母数字，截断 120 字符 | — |
| `secrets.py` | API 密钥加解密 | `encrypt_secret(plaintext)`, `decrypt_secret(token)` — Fernet，无 cryptography 时降级明文 | — |
| `runtime_checks.py` | 运行时设备校验 | `validate_runtime_device()` — 检查 demucs/whisper 设备可用性 | — |
| `devices.py` | GPU/CPU 设备解析 | `resolve_device(component)` → DeviceResolution, `validate_device_available()`, `device_plan_summary()` | — |

### 适配器 (`adapters/`)

| 文件 | 职责 | 关键函数 | 行号 |
|---|---|---|---|
| `ytdlp.py` | 视频下载 | `download_video(url, workfolder, source, proxy_port)` → (session, info) | — |
| `local_video.py` | 本地视频导入 | `import_local_video(url, workfolder, source)` → (session, info) | — |
| `demucs.py` | 人声/BGM 分离 | `separate_audio(video_file, session, progress_callback)` → (vocals.wav, bgm.wav) | — |
| `whisper_asr.py` | 语音识别 | `recognize_speech(vocals_file, session, language)` → asr.json | — |
| `asr_sentence_fixer.py` | ASR 句子修正 | `fix_asr_sentences(asr_file, session, start_pad, end_pad, language)` → asr_fixed.json | — |
| `local_subtitles.py` | SRT 字幕解析 | `parse_srt(content)`, `write_uploaded_subtitle_artifacts()` | — |
| `openai_translate.py` | LLM 翻译 | `preprocess()`, `translate_batch()`, `translate_asr(asr_file, session, settings, source)` → translation.json | — |
| `openai_client.py` | base_url 规范化 | `normalize_openai_base_url(base_url)` | — |
| `_translate_prompts.py` | 翻译 prompt 模板 | `PREPROCESS_PROMPT`, `TRANSLATE_RULES` (zh/en) | — |
| `audio.py` | 音频切分/合并 | `split_audio_by_translation()`, `merge_tts_audio()` → (dubbing.wav, timings.json) | — |
| `voxcpm.py` | TTS 语音合成 | `generate_tts(translation_file, vocals_dir, session, progress_callback)` → tts 目录 | — |
| `ffmpeg.py` | FFmpeg 操作 | `write_srt()`, `probe_video_size()`, `merge_video()` → video_final.mp4 | — |
| `__init__.py` | 包标识 | — | 注释"重量级适配器由 pipeline 懒加载" |

## 前端 (`apps/web/src/`)

### 页面 (`app/`)

| 文件 | 职责 | 关键函数/组件 | 行号 |
|---|---|---|---|
| `app/layout.tsx` | 根布局，注入 LanguageProvider | `RootLayout` | `:21` |
| `app/page.tsx` | 首页：任务创建+历史列表 | `Home` | `:61` |
| | | `refreshTasks()` — 刷新任务列表 | `:76` |
| | | `submitTask()` — 提交任务 | `:111` |
| | | `setInterval(loadTasks, 2000)` — 2s 轮询 | `:94` |
| `app/tasks/[id]/page.tsx` | 任务详情：阶段/日志/视频/操作 | `TaskDetailPage` | `:86` |
| | | `handleDelete()` / `handleRerun()` / `handleResume()` / `handleContinue()` / `handleRedoStage()` | `:107` / `:119` / `:134` / `:147` / `:160` |
| | | `setInterval(load, 2000)` — 2s 轮询 | `:204` |
| | | `canRedoStage` — 手动模式可重做 | `:186` |

### 业务组件 (`components/`)

| 文件 | 职责 | 关键函数/组件 | 行号 |
|---|---|---|---|
| `components/app-header.tsx` | 顶部导航栏 + 返回按钮 | `AppHeader` — props: `backHref?` | `:10` |
| `components/settings-dialog.tsx` | 运行设置弹窗 | `SettingsDialog` | `:64` |
| | | `submit()` — 保存设置 | `:108` |
| | | `fetchModels()` — 拉取可用模型 | `:139` |
| | | `SAVED_API_KEY_MASK` / `SAVED_COOKIE_SENTINEL` — 哨兵常量 | `:46-47` |
| `components/ui/` | shadcn/ui 基础组件（11 个） | badge, button, card, dialog, input, label, progress, scroll-area, select, separator, textarea | — |

### 核心库 (`lib/`)

| 文件 | 职责 | 关键函数/类型 | 行号 |
|---|---|---|---|
| `lib/api.ts` | API 客户端 + 类型定义 | `configuredApiBase()` — API base 解析 | `:1-9` |
| | | `request<T>()` — 通用 fetch 封装 | `:68-85` |
| | | 类型：`StageStatus`, `TaskStatus`, `ExecutionMode`, `TaskStage`, `Task`, `TaskSummary`, `CookieInfo`, `OpenAISettings`, `YtdlpSettings`, `LocalDirection` | `:11-66` |
| | | `listTasks()` / `getTask()` / `createTask()` / `uploadLocalTask()` / `deleteTask()` / `rerunTask()` / `resumeTask()` / `continueTask()` / `redoStage()` / `getTaskLog()` | `:101-151` |
| | | `getCookieInfo()` / `saveCookie()` / `getOpenAISettings()` / `saveOpenAISettings()` / `getOpenAIModels()` / `getYtdlpSettings()` / `saveYtdlpSettings()` | `:177-219` |
| | | `finalVideoUrl()` / `finalVideoDownloadUrl()` | `:226` / `:230` |
| `lib/i18n.tsx` | 国际化（中/英） | `LanguageProvider` | `:315` |
| | | `useI18n` hook | `:359` |
| | | localStorage key `youdub-ui-language` | `:7` |
| | | 阶段标签定义（中/英） | `:150-161` / `:280-291` |
| `lib/status.ts` | 状态徽章 CSS | `statusBadgeClass(status?)` | `:1` |
| `lib/utils.ts` | className 合并 | `cn(...inputs)` | `:4` |

### 配置文件

| 文件 | 职责 | 关键内容 | 行号 |
|---|---|---|---|
| `next.config.ts` | Next.js 配置 + API 代理 | `apiProxyTarget()` — 读环境变量 | `:3` |
| | | rewrites 规则（`/api/:path*` → 后端） | `:13-20` |
| `components.json` | shadcn/ui 配置 | style: base-nova, 图标: lucide, RSC: true | — |
| `package.json` | 依赖与脚本 | next 16.2.4, react 19.2.4, shadcn ^4.3.1 | — |

> 适配器详情见 [04-adapters.md](04-adapters.md)
> 修改代码的指引见 [06-change-guide.md](06-change-guide.md)
