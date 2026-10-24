# litegm v2 规划（草案，待 review）

> 基于 2026-10-23 的 v1/v1.5/v1.6 实现现状与代码审阅整理。
> 目标：明确 v2 的范围、优先级与需要你拍板的决策点。

## 1. 现状盘点（已交付）

| 版本 | 内容 |
|------|------|
| v1 | OpenAI 兼容图像 API（generations/edits）、鉴权、workflow 编译与提交前校验、任务库、回退链、管理台、集成测试 |
| v1.5 | 通过配置接入 6 个额外 workflow（Qwen 2.1 base t2i/edit、MOSS、Z-Image×2、zib-image；Z-Image 系现为仅本地使用，不随仓库发布） |
| v1.6 | 通用图像模型（同一别名文生图/编辑自动路由）、管理台展示上传输入图 |

## 2. 代码审阅发现的真实缺口（v1 遗留，需要先修）

这些是"已实现但行为不完整"的问题，属于 bug 而非新功能，建议作为 v2 的前置修复：

| # | 问题 | 证据 | 影响 |
|---|------|------|------|
| G1 | **`n` 参数无效** | `validate_request` 只校验 1..n_max，引擎从不按 `n` 出多张（实测 `n=2` 只返回 1 张） | 违反 OpenAI 契约；调用方以为拿到多张 |
| G2 | **`quality` 只是透传** | 参数被校验但不映射到 steps/cfg/sigmas | `quality=high/low` 对结果无影响 |
| G3 | **`output_format` 仅支持 png** | 模板输出 PNG；`webp/jpeg` 被配置禁止 | 与 OpenAI 默认行为有差异 |
| G4 | **后端并发上限未真正生效** | `BackendConfig.concurrency` 只用于上传/提交信号量；`count_active_by_backend()` 未被调度使用；任务提交后直接轮询，不排队 | 多任务同时打后端，ComfyUI 队列堆积、显存/热控风险 |
| G5 | **无速率/队列上限** | `QueueFullError` 只在 ComfyUI 返回 Queue full 时触发 | 网关侧无背压 |
| G6 | **配置需重启** | 启动时加载，无热载 | 增删模型要重启（v1.5 的"只改配置"体验打折） |
| G7 | **产物保留策略仅按时间** | 只按 `artifact_ttl_days` 清理，无磁盘上限 | 长期运行磁盘可能撑满 |
| G8 | **管理台无审计/搜索增强** | 无按 prompt 搜索、无导出 | 排障效率有限 |

## 3. v2 候选范围（按优先级）

### P0：协议与正确性（必须先做）

1. **修复 G1–G3**：`n` 真正生成多张（同 workflow 多次提交不同 seed，或 batch_size 支持时用 batch）；`quality` 映射到每模型的 steps/cfg 档位（配置声明 `quality_map`）；`output_format` 支持 webp/jpeg（SaveImageAdvanced 已支持 png/exr/avif，webp 需确认或改用 SaveImage + 后处理）。
2. **修复 G4–G5**：网关侧队列（按 `backends[].concurrency` 与 `queue_max` 限流），任务状态增加 `queued`→`submitting` 的真实排队；429 与 `Retry-After`。
3. **视频接口（OpenAI 原生异步协议）**：`POST /v1/videos`（multipart，`prompt`、`input_reference`、`model`、`seconds`、`size`）→ `{id, object:"video", status, progress, ...}`；`GET /v1/videos/{id}`；`GET /v1/videos/{id}/content?variant=video|thumbnail`；`GET /v1/videos` 列表；`DELETE /v1/videos/{id}`。
   - 接入 MiniMax H3 的 T2V/I2V/R2V 三个 workflow（导出 API 格式模板放入 `config/workflows/video_minimax_h3_*_api.json`，并配置注入点）。
   - 产物为 mp4/webm，`CreateVideo`/`SaveVideo` 输出在 `images` 键下（已知）。
   - 时长/分辨率约束：H3 需要 17 帧网格、≤15s（建议默认 ≤10s，可配置）。
4. **音频接口（自定义扩展）**：`POST /v1/audio/generations`（Music3），字段 `model`、`input`(caption)、`lyrics`、`duration`、`response_format`；产物 flac/mp3。
   - 长曲（>1min）耗时极长，必须走异步或长同步超时，建议复用视频的任务协议（`object:"audio"`）。

### P1：可用性与运维

5. **配置热载**：`POST /admin/api/config/reload` + 校验失败回滚；新增 `litegm check --watch`。
6. **Docker 化**：Dockerfile（多阶段：web build → python 运行），`docker-compose.yml` 挂载 `data/` 与 `config/`，环境变量注入密钥；不改代码结构。
7. **存储治理**：磁盘上限（`storage.max_bytes`）+ LRU 清理，产物保留策略按任务状态区分（失败任务保留更久便于排障）。
8. **可观测性**：结构化访问日志（请求 id、任务 id、耗时、状态）、`/metrics`（Prometheus 文本格式：任务数/耗时直方图/后端队列深度）、健康检查分离 liveness/readiness。
9. **管理台增强**：按 prompt 关键词搜索、时间范围、CSV/JSON 导出、任务详情里的"同 prompt 重跑"、后端队列可视化。

### P2：扩展能力

10. **`mask` / 局部重绘**：新增 mask workflow 变体（`SetLatentNoiseMask` 或 Qwen 的 inpaint 节点），配置 `mask_policy: supported`；`/v1/images/edits` 接受 `mask`。
11. **更多编辑/控制**：图生图（img2img denoise）、放大（Upscale workflow）、透明背景（RGBA 已支持，需 `background=transparent` 的语义映射）。
12. **多后端调度**：按 `tags` 能力匹配、负载均衡、故障转移（当前回退链只在变体级别，未跨后端）。
13. **提示词模板**：H3 的官方三字段、Music3 的 caption 三段式，可在配置里做 prompt 预处理（`prompt_template`），避免调用方必须懂模型格式。

## 4. 需要你拍板的决策

| # | 决策点 | 建议 |
|---|--------|------|
| D1 | v2 范围：P0（修复+视频+音频）一次做完，还是先 P0 修复 + 视频，音频放 v2.5 | 建议先做 G1–G5 修复 + 视频，音频紧随其后 |
| D2 | 视频产物存储：落盘保留（默认 30 天）还是按需转存 | 落盘 + TTL，与图像一致 |
| D3 | 音频接口形状：自定义 `/v1/audio/generations`，还是复用 `/v1/videos` 的任务协议（`object:"audio"`） | 复用任务协议，前端与轮询逻辑统一 |
| D4 | 是否引入 Prometheus 依赖 | 轻量自实现 `/metrics` 文本格式，不引入客户端库 |
| D5 | Docker 基础镜像：Python 3.15 slim 是否可用（需验证 conda-forge 3.15 的 Docker 安装方式） | 用 conda-forge/micromamba 安装 pixi 环境 |
| D6 | 管理台是否需要登录以外的用户体系（v2 仍单用户） | 保持单用户 |
| D7 | G1 的 `n` 实现方式：重复提交（慢但稳）vs batch_size（快但模板需支持） | 重复提交 + 并发受限，后续再评估 batch |

## 5. 建议的实施顺序（若 D1 选"修复+视频优先"）

1. 前置修复 G1–G5（约 1 个里程碑），含单元测试与真实小尺寸验证。
2. 视频接口 + H3 三个 workflow（1 个里程碑），用真实短视频（2s、低分辨率）验证。
3. 音频接口 + Music3（1 个里程碑），用 30s 曲验证（避免 200s 长曲）。
4. P1 运维项（配置热载、Docker、存储治理、可观测性、管理台增强）。
5. P2 扩展（mask、img2img、放大、多后端、prompt 模板）。

## 6. 验收方式

- 每个里程碑写 changelog（与 v1 一致）。
- 集成验证用"小尺寸/短时长"样本，避免长时间 GPU 占用（沿用 v1.6 的 verify_aliases 思路）。
- 协议兼容性用官方 OpenAI SDK 实测（图像/视频）。
