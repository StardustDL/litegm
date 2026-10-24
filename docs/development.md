# litegm 开发者指南

面向需要阅读、修改或扩展 litegm 的开发者。用户文档见仓库根目录
[README](../README.md)，接口契约见 [API 参考](api.md)，设计依据见
[设计方案](design.md)。

---

## 1. 环境与工具链

| 用途 | 方式 |
|---|---|
| Python 运行时 | pixi 环境 `default`（Python 3.15，conda-forge 依赖，含 `ffmpeg`/`ffprobe`，见 `pixi.lock`） |
| 开发与测试 | pixi 环境 `dev`（pytest、openai SDK、Node.js 22、playwright） |
| 前端构建 | pixi 环境 `web`（Node.js 22）或仓库内 `web/node_modules` |
| 配置校验 | `pixi run check` |
| 单元测试 | `pixi run -e dev test-unit`（不需要 ComfyUI） |
| 集成测试 | `pixi run -e dev test-integration`（连接真实 ComfyUI，标记 `integration`） |
| 本地启动 | `pixi run serve` |
| 前端构建 | `pixi run -e web web-build`（产物 `web/dist`，由网关在 `/admin` 托管） |

工作区平台为 `win-64`、`linux-64` 与 `linux-aarch64`：`pixi.lock` 对三者都完整求解，
因此在 ARM64 Linux 主机（如 Apple Silicon 或 arm64 服务器）上可直接 `pixi install`，
不需要额外配置 `platforms`。注意本机只安装当前平台的包，跨平台条目只用于 lock 完整性
与容器构建。

注意：

- `pixi` 的任务（`pixi run ...`）已经处理了 PATH；若要直接调用环境内的可执行文件，
  可用 `& .pixi\envs\dev\python.exe -m pytest ...` 这类相对仓库根目录的路径。
- 测试临时目录使用工作区内的 `.test-work/`（`conftest.py` 的 `workdir` fixture），
  pytest 的 `tmpdir` 插件已禁用。
- 密钥通过环境变量提供：`$env:LITEGM_MASTER_KEY = "..."`。
- 本地调试/截图可设 `$env:LITEGM_AUTH_DISABLED = "1"` 关闭鉴权（勿用于共享环境）。

---

## 2. 项目结构

```
litegm/
├── pyproject.toml          # 项目元数据、pixi 环境与任务定义
├── pixi.lock               # 锁定的依赖（勿手改）
├── Dockerfile              # 两阶段镜像：web 构建 + pixi 运行时
├── docker-compose.yml      # 生产编排（端口、挂载、健康检查）
├── config/
│   ├── litegm.yaml         # 示例配置（提交到 git）：后端、路由、任务、存储、鉴权
│   └── workflows/          # 示例 workflow 模板（ComfyUI API 格式 JSON，提交到 git）
├── .config/                # 真实配置（.gitignore 忽略；本地/生产从这里读取）
│   ├── litegm.yaml
│   └── workflows/          # 可选：自定义模板
├── src/litegm/             # 网关服务端（见 §3）
├── web/                    # 管理控制台（React + TS + Tailwind，见 §4）
├── tests/                  # 单元测试与集成测试（见 §5）
├── scripts/                # 运维/验证脚本（截图、编码修复、模型校验）
├── docs/                   # 用户与开发者文档、变更记录
├── LICENSE                 # Apache License 2.0
└── AGENTS.md               # 面向 AI agent 的速查与规范
```

配置分两份：`config/` 是随仓库发布的示例；`.config/` 是本机/生产的真实配置，不入库。
`pixi run serve` / `pixi run check` 默认读 `.config/litegm.yaml`，单元测试读示例
`config/litegm.yaml`。配置里的 `config/workflows/...` 在 `.config/` 下找不到时会回退到仓库
自带的示例模板；`.config/workflows/...` 只解析到 `.config/` 下的本地模板（Z-Image 系这类
不入库的模板就走这条路）。

运行时数据默认写入 `data/`（SQLite 任务库、`artifacts/`、`uploads/`、`.thumbs/`），
已被 `.gitignore` 忽略。

---

## 3. 服务端模块索引（`src/litegm/`）

整体调用链：`api.py` / `video.py` / `audio.py`（协议层）→ `requests.py`（规范化与校验）
→ `engine.py`（任务执行）→ `workflow.py`（模板编译与提交前校验）→ `comfy.py`
（ComfyUI 适配）→ `storage.py` / `store.py`（产物与任务持久化）。`admin.py` 提供
管理台 API，`observability.py` 提供日志与指标。

| 文件 | 行数 | 职责 | 关键符号 |
|---|---|---|---|
| `__init__.py` | 2 | 包版本 | `__version__` |
| `app.py` | 235 | FastAPI 组装、生命周期、异常处理、静态资源挂载、GZip 与缓存头 | `create_app`、`AppState`、`AdminUIAssets` |
| `cli.py` | 123 | 命令行入口（`serve`/`check`） | `main`、`_check` |
| `config.py` | 358 | YAML 配置模型与校验、`env:` 变量解析、对外 URL 拼接 | `Config`、`ServerConfig`、`AuthConfig`、`StorageConfig`、`BackendConfig`、`ModelVariant`、`ImageSlots`、`ModelConstraints`、`TaskConfig`、`RoutingConfig` |
| `api.py` | 602 | OpenAI 兼容图像接口与模型/健康端点、统一入口路由 | `/v1/images/generations`、`/v1/images`、`/v1/images/edits`、`/v1/models`、`/v1/health`、`/v1/tasks/{id}`、`/v1/files/{id}` |
| `video.py` | 256 | OpenAI 异步视频协议、任务族路由 | `/v1/videos`、`/v1/videos/{id}`、`/v1/videos/{id}/content` |
| `audio.py` | 169 | 音频生成异步扩展 | `/v1/audio/generations`、`/v1/audio/{id}`、`/v1/audio/{id}/content` |
| `requests.py` | 254 | 请求规范化、尺寸/时长吸附、参数合法性校验 | `GenerationRequest` |
| `engine.py` | 454 | 任务队列（按后端并发上限）、提交、轮询、回退链、取消、估算进度 | `Engine`、`_BackendQueue` |
| `workflow.py` | 455 | workflow 模板加载、静态覆盖、注入映射、图片槽位接线、对照 `/object_info` 的提交前校验 | `compile_workflow`、`validate_workflow`、`validate_against_backend`、`CompiledWorkflow` |
| `comfy.py` | 339 | ComfyUI HTTP 适配（提交、历史、下载、上传、中断、对象信息、系统状态） | `ComfyClient` |
| `backends.py` | 73 | 后端注册表，支持配置热载时原子替换 | `BackendRegistry` |
| `store.py` | 577 | SQLite 任务/产物/事件/输入图持久化（WAL） | `TaskStore`、`Task`、`Artifact`、`TaskRow`、`ArtifactRow`、`EventRow`、`InputImageRow` |
| `storage.py` | 226 | 产物落盘、元数据、保留策略与磁盘上限清理、签名下载 URL | `ArtifactStore` |
| `admin.py` | 742 | 管理台 API：会话、任务列表/详情/导出/取消/重试/删除、缩略图、存储、配置热载、健康、SSE | `router`、缩略图与预览辅助函数 |
| `auth.py` | 79 | Bearer 与 Basic 鉴权、签名会话 Cookie | `Authenticator` |
| `errors.py` | 74 | 错误层级与 OpenAI 错误形状映射 | `LiteGMError` 及各子类 |
| `observability.py` | 181 | 结构化访问日志（ASGI 中间件）、Prometheus `/metrics`、存活/就绪探针 | `RequestLoggingMiddleware`、`METRICS` |
| `docs_discovery.py` | — | 发现文档：按当前配置动态生成 `/llms.txt`、增强 `/openapi.json`、Swagger UI 页面 | `llms_txt`、`openapi_extras`、`swagger_html` |

### 3.1 关键机制与修改入口

| 想做的事 | 改动位置 |
|---|---|
| 新增模型别名或换 workflow | 只改 `.config/litegm.yaml`（真实）与模板，无需改代码；示例配置同步更新 |
| 新增任务类型（如 `image.upscale`） | `config.py` 的任务模型可扩展；`api.py` 增加协议入口；`requests.py` 增加规范化；复用 `engine.py`/`workflow.py` |
| 修改参数注入/图片槽位语义 | `workflow.py`（`inject_values`、`wire_images`）与配置中的 `inject`/`image_slots` |
| 调整回退链行为 | `engine.py` 的 `_fallback_chain` 与 `_run_variant` |
| 调整进度估算 | `engine.py` 的 `_advance_estimated_progress`（当前为按阶段耗时估算） |
| 调整存储保留/清理 | `storage.py`、`config.py` 的 `StorageConfig` |
| 管理台新增字段或接口 | `admin.py`（会话校验、`_task_dict` 等），并同步 `web/src/api.ts` |
| 前端界面 | `web/src/`（见 §4） |
| 新增协议端点或修改端点语义 | 同步更新 `docs/api.md` 与 `docs_discovery.py` 的 `llms_txt`（agent 读的就是它）；端点说明可加入 `_ENDPOINT_DOCS` |

### 3.2 约定

- 错误必须通过 `errors.py` 的类型抛出，以保持 OpenAI 错误形状与 HTTP 状态一致。
- 所有外部输入先经 `requests.py` 校验，再由 `workflow.py` 对照后端 `/object_info` 校验，
  避免无效请求占用 GPU。
- 任务执行过程必须写事件（`store.add_event`），审计信息不可省略。
- 配置热载只允许 `tasks`/`routing`/`backends`；`server`/`auth`/`storage` 变更需重启。
- 发现文档（`/llms.txt`、`/openapi.json`）必须从生效配置生成，不得写死模型别名；新增
  端点时同步扩展 `docs_discovery.py`，并在 `tests/test_docs_discovery.py` 中加断言。

---

## 4. 前端模块索引（`web/src/`）

技术栈：React 19 + TypeScript（strict）+ Vite + Tailwind 3。构建 `base` 为 `/admin/`，
产物由网关同源托管。

| 文件 | 行数 | 职责 |
|---|---|---|
| `main.tsx` | 9 | 入口挂载 |
| `App.tsx` | 136 | 会话检查、哈希路由（`#tasks`、`#studio`、`#system`、`#tasks/<id>`）、SSE 实时刷新 |
| `Shell.tsx` | 641 | 应用外壳：图标导航栏、顶栏、命令面板（Ctrl/Cmd+K）、快捷键、登录页、响应式 |
| `Overview.tsx` | 687 | 概览脉搏面板 |
| `TaskList.tsx` | 1031 | 任务库：画廊与表格、筛选、批量操作、导出、分页 |
| `TaskDetail.tsx` | 1020 | 任务详情：产物画廊与灯箱、输入输出对照、时间线、workflow JSON |
| `Playground.tsx` | 1339 | 创作台：按模型约束生成表单、参考图托盘、实时进度与结果 |
| `System.tsx` | 794 | 系统面板：后端健康、队列、存储、路由表、热载 |
| `ui.tsx` | 624 | UI 组件库：Toast、弹窗、灯箱、JSON 查看器、媒体缩略、进度 |
| `components.tsx` | 425 | 业务展示组件：状态标签、产物卡片、指标块、区块标题 |
| `charts.tsx` | 251 | 纯 SVG 图表：折线、环形、堆叠条、队列槽位 |
| `icons.tsx` | 393 | 线性图标集 |
| `format.ts` | 152 | 状态词表、格式化、媒体辅助 |
| `api.ts` | 210 | 管理 API 客户端与类型 |
| `contract.tsx` | 92 | 数据轮询 Hook 与布局原语 |
| `index.css` | — | 设计系统：表面、按钮、输入、标签、表格、印片框、动效 |

约定：

- 只使用 `tailwind.config.js` 中声明的色板 token（`ink`/`amber`/`jade`/`coral`/
  `azure`/`violet`/`fg`），不要引入 `slate`/`sky` 等原生色。
- 界面文案使用中文，代码注释使用英文。
- 图标只用 `icons.tsx`，不要用 emoji 充当 UI 图标。
- 修改 `web/src/api.ts` 的类型时，需与 `admin.py` 的响应字段保持一致。
- 写文件后务必确认是合法 UTF-8：`python scripts/fix_utf8.py web/src/*.tsx`
  （该脚本可检测并修复被截断的中文字符）。

---

## 5. 测试

| 文件 | 覆盖内容 |
|---|---|
| `tests/conftest.py` | 共享 fixture（配置、任务库、工作目录、master key） |
| `tests/test_requests.py` | 请求规范化与参数校验 |
| `tests/test_workflow.py` | 模板编译、注入、槽位接线、校验 |
| `tests/test_routing.py` | 统一图像模型与视频族路由 |
| `tests/test_video.py` | 视频协议与变体 |
| `tests/test_audio.py` | 音频协议 |
| `tests/test_storage.py` | 存储治理、保留与清理 |
| `tests/test_v3_ops.py` | 可观测性、热载、运维接口 |
| `tests/test_docs_discovery.py` | `/llms.txt` 结构、别名与约束来自配置、不泄露密钥；`/openapi.json` 增强与 Swagger 页面 |
| `tests/test_admin_ui_support.py` | 缩略图、列表预览字段、`duration_s`、GZip、静态缓存头 |
| `tests/test_integration.py` | 真实 ComfyUI 集成（标记 `integration`，默认跳过） |
| `tests/test_openai_sdk.py` | 官方 OpenAI SDK 调用验证 |

新增测试请优先复用 `workdir` fixture，避免依赖 pytest `tmpdir`。

---

## 6. 脚本

| 脚本 | 用途 |
|---|---|
| `scripts/ui_shot.py` | 用无头 Edge 通过 CDP 截取管理台（需关闭鉴权），支持 `overview`/`tasks`/`studio`/`system`/`detail` 与原始哈希 |
| `scripts/ui_shot_auth.py` | 登录后注入会话 Cookie 再截图，用于验证开启鉴权的部署 |
| `scripts/screenshot.py` | 早期截图辅助（Cookie 注入） |
| `scripts/fix_utf8.py` | 检测并修复被截断的 UTF-8 文本 |
| `scripts/check_doc_links.py` | 校验 Markdown 相对链接是否指向存在的文件 |
| `scripts/verify_aliases.py` / `verify_video.py` / `verify_audio.py` / `verify_r2v.py` | 对真实后端验证别名、视频、音频与参考生视频 |

---

## 7. 扩展指南

### 7.1 新增一个生成模型（不改代码）

1. 把 ComfyUI 导出的 API 格式 workflow 放入 `.config/workflows/`（若同时要发布示例，再放一份
   到 `config/workflows/`）。
2. 在 `.config/litegm.yaml` 对应任务类型下新增 `alias`，声明 `backend`、`template`、
   `inject`（节点 id + inputs 路径）、`static`、必要的 `image_slots` 与 `constraints`。
3. `pixi run check` 校验；通过后在系统面板热载或重启。

### 7.2 新增任务类型

1. `config.py` 中扩展任务类型的约束模型（如需新字段）。
2. `requests.py` 中新增该类型的规范化与校验。
3. 在 `api.py`（或新协议模块）中新增端点，复用 `engine.submit` / `engine.run`。
4. `admin.py` 与 `web/src/format.ts`、`web/src/api.ts` 中补充展示所需字段。
5. 增加单元测试与（如可行）集成测试。

### 7.3 接入真实步级进度

`comfy.py` 已保留 WebSocket 监听能力；在 `engine.py` 的 `_poll` 中接入
`/ws` 的 `progress`/`executing`/`execution_error`，替换
`_advance_estimated_progress` 的估算逻辑，并保证断线后可退回轮询。

---

## 8. 提交与记录约定

- 每个里程碑在 `docs/changelog/` 下写一份记录（范围、实现、验证结果、遗留项），并在
  `docs/changelog/README.md` 索引。
- 提交信息使用 `type(scope): summary` 形式（如 `feat(v4): …`、`chore(deploy): …`），
  正文说明动机、关键改动与验证方式。
- 密钥与本地部署配置不要入库：`.env` 已被忽略；配置中的密钥使用 `env:` 引用。
