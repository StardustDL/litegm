# API 参考（v1）

基础地址：`http://127.0.0.1:8080/v1`（以配置 `server.public_base_url` 为准）。
鉴权：`Authorization: Bearer <master_key>`。

## POST /v1/images/generations

JSON 请求体，字段对齐 OpenAI：

| 字段 | 说明 |
|------|------|
| `prompt` | 必填 |
| `model` | 配置中的别名，缺省用该任务配置的第一个别名 |
| `n` | 1..`n_max`（见模型能力） |
| `size` | `auto` 或 `WIDTHxHEIGHT`；会吸附到模型允许的步长/范围 |
| `quality` | `auto/low/medium/high/...`（透传，v1 不改变采样参数） |
| `output_format` | 仅 `png`（当前模板输出 PNG） |
| `background` | `opaque` / `auto` |
| `response_format` | `b64_json`（默认）或 `url`（网关签名链接） |
| `seed` | 扩展字段，缺省随机 |
| `stream` | `true` 时返回 SSE |

响应：`{"created", "data":[{"b64_json"|"url"}], "size", "quality", "output_format", "background"}`。

## POST /v1/images/edits

`multipart/form-data`：`image`（1–16 张）、`prompt`、`model`，以及上述可选字段。
`mask` 不支持（400 `unsupported_parameter`）。`image` 的第一张是编辑目标，后续为参考图，
prompt 中用 `<image1>`、`<image2>`… 指代。

## POST /v1/images（统一入口）

同一个端点同时支持文生图与图生图，按请求是否携带图片自动路由：

* **JSON 请求体**（同 `/v1/images/generations` 字段）→ 文生图；
* **multipart/form-data** 携带 `image` 文件（同 `/v1/images/edits` 字段）→ 图像编辑。

路由由配置 `routing.unified_image_models` 决定：配置为通用模型的别名（示例配置中是
`qwen-image-2.1-turbo`）在带图时走编辑变体、不带图时走文生图变体；未配置为通用模型的别名行为不变。

响应与 OpenAI `ImagesResponse` 一致。

## POST /v1/models

返回配置中的别名及能力。通用模型只出现一次，并带有：

```json
{"capabilities": {"task": ["image.generate", "image.edit"], "unified": true,
 "endpoints": ["/v1/images", "/v1/images/generations", "/v1/images/edits"],
 "routing": "images present -> edit; no images -> generate", "accepts_images": true, ...}}
```

## 视频生成（OpenAI 原生异步协议）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/videos` | multipart：`prompt`、`model`、`seconds`、`size`，可选 `input_reference`（图生视频）或多张 `reference_images`（参考生视频） |
| GET | `/v1/videos/{id}` | 轮询：`status`（queued/in_progress/completed/failed）、`progress`、`error` |
| GET | `/v1/videos/{id}/content` | 下载 mp4 |
| GET | `/v1/videos` | 任务列表 |
| DELETE | `/v1/videos/{id}` | 删除任务与产物 |

模型别名：`minimax-h3-t2v`、`minimax-h3-i2v`、`minimax-h3-r2v`。时长会吸附到 H3 的 17 帧网格（24fps），上限 15s，默认 2s。

也可使用**视频族名** `minimax-h3` 作为 `model`，网关按实际提供的输入字段路由：

| 提供的输入 | 路由到 |
|-----------|--------|
| 不带图 | `minimax-h3-t2v` |
| `input_reference` / `first_frame`（单图） | `minimax-h3-i2v` |
| `reference_images[]`（litegm 扩展，可重复） | `minimax-h3-r2v` |

同时提供 `input_reference` 与 `reference_images` 会返回 400；也可直接写具体别名强制路由。
响应中 `model` 为实际执行的变体，`requested_model` 为调用方传入值（例如族名）。

## 音频生成（自定义扩展，异步任务协议）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/audio/generations` | `input`（音乐描述 caption）、`lyrics`、`seconds`、`model`、`seed` |
| GET | `/v1/audio/{id}` | 轮询状态与进度 |
| GET | `/v1/audio/{id}/content` | 下载 FLAC |
| GET | `/v1/audio` | 任务列表 |
| DELETE | `/v1/audio/{id}` | 删除任务与产物 |

模型别名：`minimax-music3`。时长范围 5–300s，默认 30s。

## GET /v1/health

无需鉴权。返回网关版本、任务计数、各后端 `/system_stats` 与队列深度。

## 运维端点（v3）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health/live` | 存活探针：进程在即 200，不检查后端 |
| GET | `/health/ready` | 就绪探针：后端可用且配置已加载才 200 |
| GET | `/metrics` | Prometheus 文本格式（自实现，无额外依赖）：请求计数/耗时、任务计数/耗时、队列、磁盘用量 |

`/metrics` 与 `/health/*` 均无需鉴权，便于容器编排与监控直接抓取。

## 管理台 API（`/admin/api/*`，v3）

会话 cookie（`POST /admin/api/login`，Basic 认证）鉴权。`auth.enabled: false`
（或 `LITEGM_AUTH_DISABLED=1`）时跳过鉴权，供本地开发/截图使用。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/api/tasks` | 列表，支持 `status`/`task_type`/`model_alias`/`backend_id`/`since`/`until`/`search` |
| GET | `/admin/api/tasks/export` | 导出 `format=json\|csv`，支持同样的过滤与 `search` |
| GET | `/admin/api/tasks/{id}` | 详情（请求、workflow 快照、输入图、产物、事件） |
| POST | `/admin/api/tasks/{id}/cancel` | 取消 |
| POST | `/admin/api/tasks/{id}/retry` | 同参数重跑（重新上传原输入图） |
| DELETE | `/admin/api/tasks/{id}` | 硬删产物与输入文件，软删记录（保留审计） |
| GET | `/admin/api/storage` | 磁盘用量与保留策略 |
| POST | `/admin/api/storage/sweep` | 立即执行清理（TTL + 磁盘上限 LRU） |
| GET | `/admin/api/config` | 当前生效配置（脱敏） |
| POST | `/admin/api/config/reload` | 热载 `tasks`/`routing`/`backends`；`server`/`auth`/`storage` 变更需重启（响应列出） |
| GET | `/admin/api/health` | 运行状态、后端健康、队列 |
| GET | `/admin/api/events` | SSE 任务事件流 |
| GET | `/admin/api/artifacts/{id}/thumb?size=64..1024` | 产物缩略图（JPEG，磁盘缓存，ETag） |
| GET | `/admin/api/tasks/{id}/inputs/{idx}/thumb?size=…` | 上传输入图的缩略图 |

任务列表项自 v4 起额外返回 `preview` 与 `input_preview`（首个产物/输入图的缩略图描述，
可为 `null`），详情额外返回 `duration_s`、`artifact_previews`、`input_previews`；
原有字段不变。响应体 ≥1 KB 时按 `Accept-Encoding` 压缩，`/admin/assets/*` 的哈希文件名
返回 `immutable` 缓存头，`index.html` 为 `no-cache`。

## 发现与文档端点（v4.6）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/llms.txt` | 面向 AI agent 的接入说明（Markdown，llmstxt.org 布局），**由当前生效配置动态生成** |
| GET | `/swagger-ui`（别名 `/docs`） | Swagger UI 交互式文档页，可 Authorize 填入 master key 直接试调用 |
| GET | `/openapi.json` | OpenAPI 3 文档：servers、bearer securityScheme、关键端点说明与请求示例 |

这三个端点**无需 Bearer**：它们只描述 API，不执行调用；响应中也不会出现 master key
（`llms.txt` 里只有 `<master_key>` 占位符）。`llms.txt` 与 `openapi.json` 按请求实时生成，
因此热载配置或重启后内容立即反映当前别名与约束。

`/llms.txt` 的章节结构：

| 章节 | 内容 |
|------|------|
| Start here | Swagger UI、OpenAPI、`/v1/models`、`/v1/health`、本文件的绝对链接 |
| Authentication | Bearer master key；鉴权关闭时的行为 |
| Quick start | curl 文生图/图生图、OpenAI SDK（Python/JS）示例 |
| Models | 当前部署每个别名的 task、尺寸/时长约束、可接受图片数、回退链；视频族路由表 |
| Image / Video / Audio API | 端点清单与关键语义（同步超时、签名链接、异步轮询） |
| Async tasks and polling | `GET /v1/tasks/{id}`、`GET /v1/files/{id}`、推荐轮询节奏与保留期 |
| Errors | HTTP 状态与错误码对照（与下方错误码表一致） |
| Operational endpoints | `/health/live`、`/health/ready`、`/metrics`、管理台 |

### 给 agent 的最小接入流程

1. `GET /llms.txt` —— 读取本部署的别名、约束与调用示例（无需鉴权）。
2. `GET /v1/models`（带 Bearer）—— 拿到实际可用的 `id` 与 `capabilities`；**不要猜测模型名**。
3. 按任务类型选端点：图像走 `/v1/images*`（同步），视频 `/v1/videos`、音频
   `/v1/audio/generations`（异步）。
4. 图像调用若返回 504，用响应头 `X-Litegm-Task-Id` 轮询 `GET /v1/tasks/{id}`；
   异步任务按 2–5 秒退避轮询，完成后下载 `/content`。
5. 需要机器可读 schema 时用 `/openapi.json`（可直接生成工具定义或客户端）。

## GET /v1/tasks/{id}

非标扩展：同步超时后取回任务状态与产物链接。

## GET /v1/files/{artifact_id}?expires=…&sig=…

签名下载链接（`response_format=url` 返回），无需 Bearer。

## 错误格式

```json
{"error": {"type": "...", "code": "...", "message": "...", "param": "..."}}
```

| 场景 | HTTP | code |
|------|------|------|
| 鉴权失败 | 401 | `invalid_api_key` |
| 未知模型 | 404 | `model_not_found` |
| 参数非法 / 不支持 | 400 | `invalid_value` / `unsupported_parameter` |
| ComfyUI 队列满 | 429 | `rate_limit_exceeded` |
| 节点/执行错误 | 422 | `comfy_execution_error` / `node_errors` |
| 后端不可达 | 503 | `backend_unavailable` |
| 同步等待超时 | 504（+`X-Litegm-Task-Id`） | `sync_timeout` |
