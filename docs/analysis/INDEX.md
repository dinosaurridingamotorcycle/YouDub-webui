# YouDub 项目分析文档索引

> 本目录是 YouDub 项目的结构化知识库，用于迭代开发时快速检索流程逻辑、定位修改点、避免引入未知 bug。

## TL;DR

YouDub 是一个本地视频本地化配音流水线工具（YouTube/Bilibili → 目标语言配音版）。

- **后端**：FastAPI + SQLite + 单线程 worker，9 阶段流水线（下载→分离→ASR→修正→翻译→切分→TTS→混音→压制）
- **前端**：Next.js 16 App Router + shadcn/ui，2 秒轮询，支持 auto/manual 两种执行模式
- **适配器**：`backend/app/adapters/` 下 13 个文件，每个外部能力一个适配器，可独立替换

## 文档索引

| 文档 | 内容 | 何时查阅 |
|---|---|---|
| [01-overview.md](01-overview.md) | 项目定位、技术栈、目录结构 | 第一次了解项目 |
| [02-architecture.md](02-architecture.md) | 架构、数据流、任务生命周期、模块边界 | 理解整体设计 |
| [03-pipeline.md](03-pipeline.md) | 9 阶段流水线详解（输入/输出/产物/函数链） | 修改流水线逻辑 |
| [04-adapters.md](04-adapters.md) | 适配器职责表 + 替换接口与约定 | 替换 ASR/TTS/翻译后端 |
| [05-code-map.md](05-code-map.md) | 文件→职责→关键函数映射（含行号） | 定位代码位置 |
| [06-change-guide.md](06-change-guide.md) | 常见修改场景→该动哪里→注意事项 | 迭代开发防错 |

## 文件→职责速查表

### 后端核心 (`backend/app/`)

| 文件 | 职责 |
|---|---|
| `main.py` | FastAPI 入口，20 个 REST API 路由 |
| `pipeline.py` | 流水线编排引擎，9 阶段顺序驱动 |
| `stages.py` | 阶段静态定义（名称 + 显示标签） |
| `worker.py` | 单线程 FIFO 任务队列 |
| `database.py` | SQLite 持久化（tasks / task_stages / settings 三表） |
| `config.py` | 全局路径与环境配置 |
| `sources.py` | URL 来源识别（YouTube / Bilibili / local） |
| `stage_reset.py` | 阶段产物清理（手动模式重做支持） |
| `devices.py` | GPU/CPU 设备解析与验证 |
| `youtube.py` | URL 解析与类型判断 |
| `sanitize.py` | 文件名安全化 |
| `secrets.py` | API 密钥加解密（Fernet） |
| `runtime_checks.py` | 运行时设备校验 |
| `adapters/` | 13 个适配器文件，每个外部能力一个 |

### 前端核心 (`apps/web/src/`)

| 文件 | 职责 |
|---|---|
| `app/page.tsx` | 首页：任务创建表单 + 历史列表（2s 轮询） |
| `app/tasks/[id]/page.tsx` | 任务详情：阶段/日志/视频/操作（2s 轮询） |
| `app/layout.tsx` | 根布局，注入 LanguageProvider |
| `lib/api.ts` | API 客户端 + 全部 TypeScript 类型定义（19 个 API 函数） |
| `lib/i18n.tsx` | 自建国际化系统（中/英） |
| `lib/status.ts` | 状态徽章 CSS 映射 |
| `components/settings-dialog.tsx` | 运行设置弹窗（Cookie/代理/OpenAI） |
| `components/app-header.tsx` | 顶部导航栏 |
| `components/ui/` | shadcn/ui 基础组件（11 个） |

> 完整的函数级映射见 [05-code-map.md](05-code-map.md)

## 维护规则

1. **修改代码后同步更新文档**：修改 `backend/app/` 或 `apps/web/src/` 后，检查相关文档是否需要更新
2. **新增/删除文件**：更新 `05-code-map.md` 和本文件的速查表
3. **修改流水线逻辑**：更新 `03-pipeline.md`
4. **修改/新增适配器**：更新 `04-adapters.md`
5. **文档格式约定**：表格优先，行号引用（如 `pipeline.py:62-71`），单篇不超过 ~200 行
