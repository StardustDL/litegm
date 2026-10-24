# litegm 设计方案

> 状态：v1 设计已定稿，待实现
> 最后更新：2026-10-23
> 适用范围：v1（image 生成/编辑全链路）。video / audio 为 v2 预留结构，本文档只在必要处标注。

## 1. 背景与目标

litegm 是一个把 **ComfyUI** 包装成 **OpenAI 兼容多媒体生成 API** 的网关。

**目标**

1. 对外提供 OpenAI 原生字段形状的生成接口（v1：`/v1/images/generations`、`/v1/images/edits`）。
2. **不耦合具体 ComfyUI 服务器**：服务器地址、workflow 模板、参数注入点全部由配置文件声明。
3. 每个生成任务可配置**一到多个 workflow 变体**，按 `model` 别名路由，并支持失败回退链。
4. 同时提供**管理前端**，用于查看历史任务、任务状态、产物与排障信息。
5. v1 只支持本地部署，但实现上不依赖本地环境（路径、端口、后端 URL 全部来自配置/环境变量），为后续 Docker 化留出空间。

**非目标（v1）**

- 多租户、计费、配额。
- OpenAI 之外的协议（Anthropic/Gemini 风格）。
- 图像后处理（放大、裁剪、转码）。
- 异步任务协议（见 §2 的说明，留给 v2 的视频阶段）。
- `mask` 局部重绘（明确不支持，见 §5.3）。

## 2. 关于 OpenAI 的"异步模式"（已核实，并据此定 v1 形态）

核实对象：OpenAI 官方 Python SDK 源码（`openai/resources/videos.py`、`types/images_response.py`、`types/image.py`、`types/image_edit_stream_event.py` 等）。

结论：

| 能力 | OpenAI 原生形态 | litegm v1 处理 |
|------|----------------|----------------|
| 图像生成/编辑 | **只有同步**：直接返回 `{created, data[], size, quality, output_format, background, usage}`，无任务对象、无轮询端点 | 同步实现，严格对齐响应体 |
| 图像流式 | `stream=true` 的 SSE：`image_edit.partial_image` → `image_edit.completed`（事件内带 `b64_json`） | v1 支持该字段形状；ComfyUI 无中间帧时，只在完成时发 `image_edit.completed` |
| 视频生成 | **原生异步**：`POST /v1/videos` → `{id, object:"video", status: queued|in_progress|completed|failed, progress, ...}` → `GET /v1/videos/{id}` → `GET /v1/videos/{id}/content` | v2 按此协议实现 |

因此 v1 的图像接口**不做异步任务协议**。网关内部仍然是"任务持久化 + 队列 + worker"，但对外表现为同步阻塞。

### 2.1 同步超时策略（已确认）

- 配置项 `server.sync_timeout_s`（默认 600s）。
- 超过该时间仍未完成：返回 **HTTP 504**，并带响应头 `X-Litegm-Task-Id: <task_id>`；**任务继续在网关侧执行并落库**，不会丢失。
- 调用方可通过非标扩展 `GET /v1/tasks/{id}` 取回结果（该端点不属于 OpenAI 契约，但可被任意 HTTP 客户端使用）。
- 错误体仍使用 OpenAI 错误形状（见 §5.4）。

## 3. 技术栈与工程约束（已确认）

| 项 | 方案 |
|----|------|
| Python | **3.15（最新稳定版）**；由 pixi 管理虚拟环境（`pixi.toml` + 提交 `pixi.lock`） |
| 依赖渠道 | conda-forge（fastapi、uvicorn、httpx、pydantic、sqlalchemy、alembic、pytest 等）；`pyproject.toml` 中声明项目元数据，pixi 环境安装可编辑包 |
| 服务端 | FastAPI + uvicorn；SQLite（WAL）持久化任务与产物元数据；`asyncio` worker（按后端并发上限分区） |
| 前端 | Vite + React + TypeScript + Tailwind；构建产物由网关同源托管在 `/admin`；开发期用 Vite dev server 反代 API |
| 可移植性 | 所有路径/端口/后端 URL 来自配置与环境变量；无 Windows 专有假设；数据目录可挂载；日志输出到 stdout；v2 可直接加 Dockerfile |

### 3.1 关于 Python 3.15 的落地说明

- 目标为 conda-forge 的 `python 3.15`（当前最新稳定版为 3.15.1）。
- 工作区现有 pixi 环境是 **Python 3.14.9**（脚手架阶段遗留），实现前会先把 `pyproject.toml` 的 `requires-python` 与环境锁定调整到 3.15。
- **风险与回退**：若个别依赖在 win-64 上没有 3.15 构建，按以下顺序处理并记录：① 优先换用 conda-forge 已提供 3.15 构建的等价依赖；② 若确有阻塞，则把该依赖以纯 Python 方式引入；③ 最后手段是在文档中登记并临时回退到 3.14（需你确认）。实现时会先做一次依赖解析验证再动代码。

## 4. 鉴权（已确认）

单配置文件中的 `username` + `master key` 做简单鉴权：

```yaml
auth:
  username: admin
  master_key: "env:LITEGM_MASTER_KEY"   # 支持从环境变量读取，避免明文入库
```

- **API 侧**：`Authorization: Bearer <master_key>`，与 OpenAI SDK 的 `api_key` 参数直接兼容。缺失或错误 → 401，OpenAI 错误形状（`code: invalid_api_key`）。
- **管理前端**：HTTP Basic（`username` + `master_key`）换取会话 cookie（HttpOnly、SameSite=Lax、短期签名 token）；`/admin/api/*` 全部校验会话。
- 比较使用 `hmac.compare_digest`；日志脱敏。

## 5. 对外 API（v1）

### 5.1 端点

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| POST | `/v1/images/generations` | Bearer | JSON 请求，字段对齐 OpenAI |
| POST | `/v1/images/edits` | Bearer | multipart：`image[]`(1–16)、`mask?`（v1 拒绝）、`prompt` |
| GET | `/v1/models` | Bearer | 按配置列出 model 别名与能力 |
| GET | `/v1/health` | 无 | 网关状态与各 ComfyUI 后端 `/system_stats` 健康 |
| GET | `/v1/tasks/{id}` | Bearer | 非标扩展：同步超时后的取回通道 |

### 5.2 请求字段（图像生成）

对齐 OpenAI（`gpt-image` 系）字段：`prompt`、`model`、`n`、`size`、`quality`、`output_format`(png/webp/jpeg)、`output_compression`、`background`、`moderation`、`safety_identifier`、`user`、`stream`、`response_format`。

- `size` 支持 `auto` 与 `WIDTHxHEIGHT`；网关按模型约束吸附到最近的合法尺寸（模板要求 32 的倍数）。
- `n` 上限由配置中每个 model 别名声明。
- 不支持的字段（如某些模型不支持 `background=transparent`）按 OpenAI 语义**显式报错**而不是静默忽略。

### 5.3 编辑接口与 mask

- `image[]` 映射到编辑 workflow 的图片槽位：`image_1` = 编辑目标（node 470），后续为参考图（node 475 + 动态插入的 `LoadImage`）。
- **`mask` 在 v1 明确不支持**：收到 `mask` 时返回 400，`code: unsupported_parameter`，消息说明"当前编辑 workflow 无局部重绘节点"。v2 引入 mask workflow 变体后再支持。

### 5.4 响应与错误

- 成功响应严格使用 OpenAI 形状：`{"created":…, "data":[{"b64_json"|"url":…}], "size":…, "quality":…, "output_format":…, "background":…, "usage":{…}}`。
- `response_format=url` 时返回网关签名下载链接（带过期时间）；默认 `b64_json`。
- 错误体：`{"error":{"type","code","message","param"}}`。
- 映射：ComfyUI `Queue full` → 429；节点错误/参数非法 → 422；后端不可达 → 503；同步超时 → 504（带 `X-Litegm-Task-Id`）；鉴权失败 → 401。

## 6. 内部架构

```
┌──────────── 管理前端 (React, /admin) ────────────┐
│ 任务列表/详情/产物/错误/后端健康（SSE 实时）        │
└───────────────▲───────────────────────────────────┘
                │ REST + SSE（Basic 登录会话）
┌───────────────┴──────────── litegm 网关 ──────────┐
│ API 层：鉴权 → 请求校验 → 模型别名路由 → 同步等待     │
│ 任务层：任务持久化(SQLite) → 队列(按后端并发上限)     │
│ workflow 编译：模板 + 注入映射 + 图片槽位 + 回退链    │
│ 提交前校验：/object_info 对照校验必填/combo/槽位      │
│ ComfyUI 适配器：/prompt /history /view /upload/image │
│                 /interrupt /object_info /system_stats│
│ 产物层：落盘 + 元数据 + 签名下载 + 全黑图自检          │
│ 审计：最终 workflow 快照、prompt_id、阶段耗时、错误原文 │
└───────────────┬───────────────────────────────────┘
         ComfyUI 后端（配置声明，可多台）
```

关键机制：

- **后端注册表**：`backends[]` 声明 `id/base_url/concurrency/timeout/tags`，不写死 URL。
- **workflow 变体**：每个任务类型下多个 `model_alias` → 模板路径 + 注入映射；编辑类额外声明图片槽位（目标图/参考图/BatchImages 同步）。
- **回退链**：变体内 `fallbacks[]`，提交失败或节点错误时按顺序尝试下一个，逐次记录尝试历史。
- **提交前校验**：对照 `/object_info` 校验必填输入、combo 取值、AUTOGROW 槽位；校验失败直接 422，不消耗 GPU。
- **产物发现**：基于 `/history` 的 `outputs`（`images` 键，含 `subfolder`/`type`/`metadata.width/height`），经 `/view` 下载。
- **质量自检**：对图片做像素统计，`mean < 3` 判定疑似全黑，标记 `suspicious` 并在管理台高亮。
- **断点恢复**：持久化 `comfy_prompt_id`，进程重启后重新接管轮询。

## 7. 配置草案（v1 仅含 turbo t2i + edit）

```yaml
server: { host: 0.0.0.0, port: 8080, public_base_url: "http://127.0.0.1:8080", sync_timeout_s: 600 }
auth: { username: admin, master_key: "env:LITEGM_MASTER_KEY" }
storage: { root: ./data, artifact_ttl_days: 30 }
backends:
  - { id: gpu-1, base_url: "http://127.0.0.1:8188", concurrency: 1, timeout_s: 1800, tags: [image] }
tasks:
  image.generate:
    models:
      - alias: qwen-image-2.1-turbo          # 别名通过配置管理
        backend: gpu-1
        template: config/workflows/image_qwen_image_2_1_turbo_t2i_api.json
        inject: { ... }                      # 节点 id + inputs 路径
        constraints: { sizes: [...], size_step: 32, n_max: 4 }
      - alias: qwen-image-2.1-turbo-pe       # 同模板，默认 refine_prompt=true + thinking
        fallbacks: [qwen-image-2.1-turbo]
  image.edit:
    models:
      - alias: qwen-image-2.1-turbo-edit
        image_slots: { target: {node: "470"}, reference: {start_node: 475, extra_node_base: 510}, batch: {node: "485"} }
        mask_policy: unsupported
```

v1 只上线 turbo 的 t2i 与 edit；moss / qwen21 base 等备选 workflow 后续按需追加，不需要改代码。

## 8. 管理前端（v1 范围）

- Basic 登录 → 任务列表（类型/模型/后端/状态/时间过滤，SSE 实时刷新）
- 任务详情：请求参数、**实际提交的 workflow JSON 快照**、`comfy_prompt_id`、阶段耗时、产物预览、错误原文、`suspicious` 标记
- 取消 / 重试 / 下载产物；后端健康面板；模型别名列表
- 配置编辑不在 v1 范围（只读展示）

## 9. 目录结构

```
litegm/
  pyproject.toml / pixi.toml / pixi.lock
  src/litegm/        # api/ auth/ config/ tasks/ workflow/ comfy/ storage/ admin/
  web/               # React 管理台
  config/litegm.yaml + config/workflows/*.json   # 示例配置与模板（随仓库发布）
  .config/litegm.yaml + .config/workflows/*.json # 真实配置与自定义模板（不入库）
  tests/             # 单元测试 + 集成测试（标记 integration，打真实 ComfyUI）
  docs/              # 本设计文档 + API 兼容性说明 + 配置参考
```

## 10. 实施顺序

1. 依赖与环境验证（Python 3.15 解析）、配置 schema、后端注册表、ComfyUI 适配器、任务库
2. workflow 编译与提交前校验（t2i 两个别名 + edit）
3. OpenAI 兼容 images API + 鉴权 + 错误映射 + `/v1/models`、`/v1/health`
4. 管理前端
5. 集成测试：每个别名在真实 ComfyUI 上跑通一次，并用 OpenAI SDK 直接调用验证（`client.images.generate(...)`）

## 11. 风险与对策

| 风险 | 对策 |
|------|------|
| Python 3.15 在 win-64 上个别依赖缺构建 | §3.1 的处理顺序；先做依赖解析验证 |
| 同步等待期间客户端断开 | 任务照常完成并落库，`X-Litegm-Task-Id` 可取回 |
| GPU 与其他服务共享显存/热控 | 后端并发上限、排队、任务级尺寸上限 |
| workflow 模板与服务器版本漂移 | 启动自检 + 提交前 `/object_info` 校验 + 快照存档 |
| 2K 出图耗时长 | 同步超时后 504 但任务保留，管理台可见 |
