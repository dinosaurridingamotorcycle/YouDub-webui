# 06 - 变更指南

> 常见迭代修改场景 → 该动哪里 → 注意事项。用于修改代码前快速定位影响范围，避免引入未知 bug。

## 修改前必读

**每次修改 `backend/app/` 或 `apps/web/src/` 代码前，先查阅 [05-code-map.md](05-code-map.md) 定位文件和函数，确认影响范围。**

修改完成后，同步更新对应的文档：
- 修改流水线逻辑 → 更新 `03-pipeline.md`
- 修改/新增适配器 → 更新 `04-adapters.md`
- 新增/删除文件 → 更新 `05-code-map.md` 和 `INDEX.md` 速查表

---

## 场景速查

| 场景 | 主要修改文件 | 影响范围 |
|---|---|---|
| 换 ASR 后端 | `adapters/whisper_asr.py` | 阶段 `asr` + 下游 `asr_fix`/`translate` |
| 换 TTS 后端 | `adapters/voxcpm.py` | 阶段 `tts` + 下游 `merge_audio` |
| 换翻译后端 | `adapters/openai_translate.py` | 阶段 `translate` + 下游 `split_audio`/`tts`/`merge_video` |
| 换下载后端 | `adapters/ytdlp.py` | 阶段 `download` |
| 加新视频源 | `sources.py` + `youtube.py` + `adapters/` | 阶段 `download` + `main.py` 创建逻辑 |
| 改翻译并发 | `adapters/openai_translate.py` | 阶段 `translate` |
| 调字幕样式 | `adapters/ffmpeg.py` | 阶段 `merge_video` |
| 新增流水线阶段 | `stages.py` + `pipeline.py` + `stage_reset.py` | 全局 |
| 新增 API 端点 | `main.py` + `lib/api.ts` + 前端页面 | 前后端 |
| 改前端轮询间隔 | `app/page.tsx` / `app/tasks/[id]/page.tsx` | 前端 |
| 改设备/GPU 配置 | `devices.py` + `config.py` | 全局 |
| 改密钥加密方式 | `secrets.py` + `database.py` | 设置相关 |

---

## 详细指引

### 1. 换 ASR 后端（Whisper → 其他）

**修改文件**：`adapters/whisper_asr.py`

**必须保持**：
- 函数签名：`recognize_speech(vocals_file, session, language)`
- 产物格式：`metadata/asr.json`（含 `utterances` + word timestamps）
- 产物路径：`session/metadata/asr.json`

**风险点**：
- `asr.json` 格式被 `asr_sentence_fixer.py` 和 `openai_translate.py` 依赖，格式不兼容会导致后续阶段失败
- 设备处理参考 `devices.py` 的 `resolve_device`，Whisper 在 MPS 下强制 CPU

**验证**：修改后跑一个短视频，检查 `asr.json` 格式是否与原版一致。

### 2. 换 TTS 后端（VoxCPM → 其他）

**修改文件**：`adapters/voxcpm.py`

**必须保持**：
- 函数签名：`generate_tts(translation_file, vocals_dir, session, progress_callback)`
- 产物：`segments/tts/*.wav`（每句一个文件，文件名需与 translation.json 条目对应）

**风险点**：
- `audio.merge_tts_audio` 按顺序读取 tts 目录文件合并，文件命名约定需一致
- TTS 片段时长影响 `merge_audio` 的变速对齐逻辑

### 3. 换翻译后端（OpenAI → 其他 LLM）

**修改文件**：`adapters/openai_translate.py`（可能还需 `openai_client.py`、`_translate_prompts.py`）

**必须保持**：
- 函数签名：`translate_asr(asr_file, session, settings, source)`
- 产物格式：`metadata/translation.{lang}.json`
- 产物路径：`session/metadata/translation.{lang}.json`

**风险点**：
- 翻译有断点续译逻辑，替换时需保留或重新实现
- `translation.json` 格式被 `split_audio`、`tts`、`ffmpeg`（字幕）依赖
- 翻译方向（`en-zh` / `zh-en`）由 `task.local_direction` 决定

### 4. 加新视频源（如新增其他平台）

**修改文件**：
1. `sources.py`：在 `SOURCES` 中新增 `SourceConfig`
2. `youtube.py`：新增 URL 识别函数（`is_xxx_url()`）
3. `adapters/`：新增下载适配器文件
4. `main.py:166 create_task`：可能需要调整来源判断逻辑

**风险点**：
- `detect_source(url)` 是来源路由的入口，新来源必须在此注册
- 下载适配器需返回 `(session, info)` 元组，info 需含 title

### 5. 改翻译并发/批量大小

**修改文件**：`adapters/openai_translate.py` 中的 `translate_batch` 逻辑

**风险点**：
- 并发过高可能触发 API 限流，适配器有指数退避重试
- 断点续译依赖已翻译条目的持久化

### 6. 调字幕样式

**修改文件**：`adapters/ffmpeg.py` 中的 `write_srt()` 和 `merge_video()` 的 FFmpeg 滤镜参数

**风险点**：
- 字幕烧录通过 FFmpeg `subtitles` 滤镜实现，样式参数在滤镜字符串中
- 修改后需确认 FFmpeg 版本支持对应滤镜参数

### 7. 新增流水线阶段

**修改文件（按顺序）**：
1. `stages.py:12-22`：在 `STAGES` 元组中新增 `StageSpec`
2. `pipeline.py:57-71`：在阶段→处理函数映射中新增
3. `pipeline.py:263-436`：新增 `_xxx` 阶段处理函数
4. `stage_reset.py`：在 `STAGE_OWN_ARTIFACTS` 中注册新阶段产物路径
5. `database.py:144 create_task`：初始化新阶段的 task_stages 记录（可能自动处理）
6. 前端 `lib/i18n.tsx:150-161`：新增阶段标签翻译

**风险点**：
- 阶段顺序固定在 `STAGES` 元组中，插入位置决定执行时机
- `STAGE_NAMES` 也需同步更新
- 新阶段产物路径需在 `stage_reset.py` 注册，否则手动重做时不会清理

### 8. 新增 API 端点

**修改文件**：
1. `main.py`：新增路由处理函数
2. `apps/web/src/lib/api.ts`：新增 API 函数 + 类型定义
3. 对应前端页面/组件中调用

**风险点**：
- 前端通过 Next.js rewrites 代理，端点路径需以 `/api/` 开头
- `lib/api.ts` 是前后端契约的唯一来源，类型定义需与后端 Pydantic 模型一致

### 9. 改前端轮询间隔

**修改文件**：
- `app/page.tsx:94`：`setInterval(loadTasks, 2000)` → 改数字
- `app/tasks/[id]/page.tsx:204`：`setInterval(load, 2000)` → 改数字

**风险点**：间隔过短增加后端负载，过长影响实时性。

### 10. 改设备/GPU 配置

**修改文件**：`devices.py` + `config.py`

**风险点**：
- Whisper 在 MPS 下强制 CPU（`devices.py` 中 `device_plan_summary`），因为 MPS 不支持 float64
- 5060Ti (Blackwell, sm_120) 需 PyTorch cu128 wheel，需验证 `torch.cuda.is_available()`
- Demucs 和 VoxCPM 也依赖设备配置

### 11. 改密钥加密方式

**修改文件**：`secrets.py` + `database.py:348/363`

**风险点**：
- 已存储的密钥用旧方式加密，改加密方式需迁移
- `secrets.py` 无 cryptography 包时降级为明文存储

---

## 修改检查清单

每次修改代码后，确认以下事项：

- [ ] 修改是否影响了产物格式？（下游阶段是否依赖）
- [ ] 修改是否影响了函数签名？（调用方是否需要同步改）
- [ ] 新增文件是否更新了 `05-code-map.md` 和 `INDEX.md`？
- [ ] 修改流水线是否更新了 `03-pipeline.md`？
- [ ] 修改适配器是否更新了 `04-adapters.md`？
- [ ] 新增阶段是否在 `stages.py` + `pipeline.py` + `stage_reset.py` 三处同步？
- [ ] 新增 API 是否在 `main.py` + `lib/api.ts` 两端同步？
- [ ] 是否有硬编码的路径/常量需要同步修改？

> 完整代码位置索引见 [05-code-map.md](05-code-map.md)
> 适配器接口约定见 [04-adapters.md](04-adapters.md)
