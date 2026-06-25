# 03 - 流水线详解

## TL;DR

流水线由 `pipeline.py` 编排，9 个阶段顺序执行。每个阶段对应一个 `_xxx` 处理函数，调用对应适配器完成实际工作。产物落盘到 session 目录，支持断点续跑（跳过已成功阶段）。manual 模式下每阶段后暂停等待用户操作。

## 阶段定义

阶段定义在 `stages.py:12-22`，9 个阶段按固定顺序执行：

| 顺序 | 阶段名 | 显示标签 | 处理函数 | 调用的适配器 |
|---|---|---|---|---|
| 1 | `download` | Download | `_download` (`:263`) | `ytdlp.download_video` 或 `local_video.import_local_video` |
| 2 | `separate` | Demucs | `_separate` (`:280`) | `demucs.separate_audio` |
| 3 | `asr` | Whisper | `_asr` (`:292`) | `whisper_asr.recognize_speech` 或 `local_subtitles.write_uploaded_subtitle_artifacts` |
| 4 | `asr_fix` | Split sentences | `_asr_fix` (`:322`) | `asr_sentence_fixer.fix_asr_sentences` |
| 5 | `translate` | Translate | `_translate` (`:352`) | `openai_translate.translate_asr` |
| 6 | `split_audio` | Split audio | `_split_audio` (`:391`) | `audio.split_audio_by_translation` |
| 7 | `tts` | VoxCPM | `_tts` (`:400`) | `voxcpm.generate_tts` |
| 8 | `merge_audio` | Merge audio | `_merge_audio` (`:415`) | `audio.merge_tts_audio` |
| 9 | `merge_video` | Merge video | `_merge_video` (`:426`) | `ffmpeg.merge_video` |

## 各阶段详解

### 1. download — 视频下载/导入

| 项 | 内容 |
|---|---|
| 处理函数 | `_download(task)` (`pipeline.py:263-278`) |
| 输入 | `task.url`（YouTube/Bilibili URL 或 `local://` 本地路径） |
| 逻辑 | 通过 `sources.detect_source` 判断来源 → YouTube/Bilibili 调 `ytdlp.download_video`，本地调 `local_video.import_local_video` |
| 产物 | `media/video_source.mp4` |
| 特殊 | 本地视频会通过 FFmpeg 转码为 mp4 |

### 2. separate — 人声/BGM 分离

| 项 | 内容 |
|---|---|
| 处理函数 | `_separate(task)` (`pipeline.py:280-290`) |
| 输入 | `media/video_source.mp4` |
| 逻辑 | 调用 `demucs.separate_audio`，使用 htdemucs_ft 模型分离 |
| 产物 | `media/audio_vocals.wav`（人声）、`media/audio_bgm.wav`（背景音乐） |
| 资源 | GPU 加速（CUDA/MPS），退回 CPU |

### 3. asr — 语音识别

| 项 | 内容 |
|---|---|
| 处理函数 | `_asr(task)` (`pipeline.py:292-320`) |
| 输入 | `media/audio_vocals.wav` |
| 逻辑 | **若用户上传了 SRT 字幕**→ 调 `local_subtitles.write_uploaded_subtitle_artifacts` 直接生成 asr.json，跳过 Whisper；否则调 `whisper_asr.recognize_speech` |
| 产物 | `metadata/asr.json`（含 utterances + word timestamps） |
| 资源 | Whisper large-v3-turbo，GPU 加速；**Whisper 在 MPS 下强制 CPU**（`devices.py` 中 `device_plan_summary`） |

### 4. asr_fix — 句子切分修正

| 项 | 内容 |
|---|---|
| 处理函数 | `_asr_fix(task)` (`pipeline.py:322-350`) |
| 输入 | `metadata/asr.json` |
| 逻辑 | 调 `asr_sentence_fixer.fix_asr_sentences`，重新切分句子并做时间轴 padding（start_pad/end_pad） |
| 产物 | `metadata/asr_fixed.json` |
| 特殊 | 纯算法，无外部依赖 |

### 5. translate — LLM 翻译

| 项 | 内容 |
|---|---|
| 处理函数 | `_translate(task)` (`pipeline.py:352-389`) |
| 输入 | `metadata/asr_fixed.json` + OpenAI 设置 |
| 逻辑 | 调 `openai_translate.translate_asr`：先 `preprocess`（预处理），再 `translate_batch`（批量翻译），支持断点续译 |
| 产物 | `metadata/translation.{lang}.json` |
| 重试 | 适配器内部有指数退避重试机制 |
| 方向 | `en-zh` 或 `zh-en`，由 `task.local_direction` 决定 |

### 6. split_audio — 参考音频切分

| 项 | 内容 |
|---|---|
| 处理函数 | `_split_audio(task)` (`pipeline.py:391-398`) |
| 输入 | `media/audio_vocals.wav` + `metadata/translation.{lang}.json` |
| 逻辑 | 调 `audio.split_audio_by_translation`，按翻译时间轴切分人声为参考片段 |
| 产物 | `segments/vocals/*.wav`（每句一个片段） |

### 7. tts — TTS 语音合成

| 项 | 内容 |
|---|---|
| 处理函数 | `_tts(task)` (`pipeline.py:400-413`) |
| 输入 | `metadata/translation.{lang}.json` + `segments/vocals/*.wav`（参考音频） |
| 逻辑 | 调 `voxcpm.generate_tts`，使用 VoxCPM2 模型逐句生成配音 |
| 产物 | `segments/tts/*.wav`（每句一个配音片段） |
| 资源 | GPU 加速 |

### 8. merge_audio — 配音合并

| 项 | 内容 |
|---|---|
| 处理函数 | `_merge_audio(task)` (`pipeline.py:415-424`) |
| 输入 | `segments/tts/*.wav` |
| 逻辑 | 调 `audio.merge_tts_audio`，合并 TTS 片段为完整配音轨，生成时间轴对齐信息，必要时变速对齐（audiostretchy） |
| 产物 | `tmp/audio_dubbing.wav`、`metadata/timings.json` |

### 9. merge_video — 最终合成

| 项 | 内容 |
|---|---|
| 处理函数 | `_merge_video(task)` (`pipeline.py:426-436`) |
| 输入 | `media/video_source.mp4` + `tmp/audio_dubbing.wav` + `media/audio_bgm.wav` + `metadata/translation.{lang}.json`（字幕） |
| 逻辑 | 调 `ffmpeg.merge_video`：先 `write_srt` 生成字幕，再 `probe_video_size` 探测分辨率，最终 FFmpeg 合成 |
| 产物 | `media/video_final.mp4`（带配音 + BGM + 烧录字幕） |
| 完成后 | 写入 `tasks.final_video_path`，任务标记 `succeeded` |

## 阶段间数据传递

- **内存传递**：`PipelineArtifacts` dataclass（`pipeline.py:19-32`）存储所有中间产物路径
- **落盘恢复**：所有产物写入 session 目录约定路径，`_restore_cached_stage`（`:218-261`）从磁盘按约定路径重建 artifacts
- **无队列/消息传递**：阶段间直接通过 artifacts 对象传递路径引用

## 缓存恢复机制（断点续跑）

```
run() 启动
  → 遍历 STAGES
  → 对每个阶段检查 task_stages.status
  → 如果 succeeded → _restore_cached_stage（从磁盘恢复产物路径，跳过执行）
  → 如果非 succeeded → 执行该阶段及后续
```

- 关键逻辑：`pipeline.py:96-107`
- 恢复函数：`_restore_cached_stage`（`:218-261`）
- 适配器级别的文件缓存：多数适配器有 `if output_file.exists(): return output_file` 逻辑

## 错误处理

| 层级 | 机制 | 位置 |
|---|---|---|
| 流水线级 | try/except 包裹整个 run()，失败标记 `failed` + 写 error_message + traceback | `pipeline.py:116-135` |
| 阶段级 | `_run_stage` 标记当前阶段 `failed` | `pipeline.py:194-216` |
| 适配器级 | 翻译有指数退避重试；其他适配器有文件缓存 | `adapters/openai_translate.py` |
| **无流水线级自动重试** | 失败后需用户手动 resume/rerun | — |

## 进度上报

- 节流机制（`pipeline.py:144-155`）：2 秒内不重复上报，进度不回退
- 适配器通过 `progress_callback` 回调上报进度
- 前端 2 秒轮询读取 `task_stages.progress`

## 执行模式

| 模式 | 行为 | 暂停逻辑 |
|---|---|---|
| `auto` | 连续执行全部 9 阶段 | 不暂停 |
| `manual` | 每阶段成功后暂停 | `run()` 在 manual 模式下每阶段后 break，等待用户 `continue` |

- manual 模式支持**单阶段重做**：`redo_stage`（`main.py:352`）→ 清理该阶段及后续产物（`stage_reset.py`）→ 重跑
- manual 模式暂停时，前端提供"执行下一阶段"和"自动执行剩余阶段"两个操作

## 核心代码位置索引

| 功能 | 位置 |
|---|---|
| 阶段处理器映射表 | `pipeline.py:61-71` |
| 主循环（遍历 + 缓存跳过 + manual 暂停） | `pipeline.py:96-107` |
| 成功完成标记 | `pipeline.py:108-114` |
| 异常处理与失败标记 | `pipeline.py:116-135` |
| 进度上报节流 | `pipeline.py:144-155` |
| 缓存恢复 | `pipeline.py:218-261` |
| 各阶段处理函数 | `pipeline.py:263-436` |
| 模块级入口 `run_task` | `pipeline.py:439-440` |

> 适配器详情见 [04-adapters.md](04-adapters.md)
> 修改流水线的指引见 [06-change-guide.md](06-change-guide.md)
